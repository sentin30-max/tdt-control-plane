import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from tdt_control_plane.budget_admission import AdmissionGate,BudgetPolicy
from tdt_control_plane.deterministic_dispatch import DeterministicDispatcher
from tdt_control_plane.ledger import Ledger
from tdt_control_plane.roles import make_context


class BudgetAmendmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.ledger=Ledger(Path(self.tmp.name)/'ledger.db')
        self.gate=AdmissionGate(self.ledger,DeterministicDispatcher(self.ledger))

    def tearDown(self):self.ledger.close();self.tmp.cleanup()

    def context(self,execution_id=None,role='DEVELOPMENT'):
        return make_context(execution_id or str(uuid4()),'22222222-2222-4222-8222-222222222222','a'*64,role,
            'tc06-b-fixture','Produce required bounded output',{'state':{'open':True}},
            {'fixture':'b'*64},['Trader AI','TEF','Governance'])

    def policy(self,c,calls=1,tokens=5000,review_calls=0,review_tokens=0,revision=1,amendment_digest=None):
        allocations={'DEVELOPMENT':{'max_model_calls':calls,'estimated_token_ceiling':tokens}}
        return BudgetPolicy(c['task_id'],calls,tokens,review_calls,review_tokens,allocations,
            revision=revision,amendment_digest=amendment_digest)

    def evaluate(self,c):
        return self.gate.evaluate(c,why_llm_required='GENERATIVE_SYNTHESIS_REQUIRED',
            execution_purpose='complete authorized material work',expected_material_output='bounded result',output_token_budget=1000)

    def exhausted(self,*,with_old_reservation=False):
        first=self.context();policy=self.policy(first);self.gate.configure(policy)
        old=self.evaluate(first) if with_old_reservation else None
        if not with_old_reservation:
            # A ceiling below the internally computed estimate establishes insufficiency without a reservation.
            tiny=self.policy(first,tokens=1);self.ledger.db.execute('UPDATE budget_policies SET policy=? WHERE task_id=?',
                (json.dumps(tiny.__dict__,sort_keys=True),first['task_id']))
        target=self.context();decision=self.evaluate(target)
        self.assertEqual(decision['reason'],'TASK_BUDGET_EXHAUSTED')
        return first,target,old

    def request(self,target,delta='validated underestimate'):
        return self.gate.request_expansion(target,material_need='finish the already authorized result',
            material_delta=delta,revised_estimate={'max_model_calls':2,'estimated_token_ceiling':10000},
            review_reserve_impact={'preserved':True})

    def approve(self,target,request):
        reviewed=self.gate.review_expansion(request['request_digest'],reviewer_role='ADVISOR',recommend=True)
        self.assertEqual(reviewed['decision'],'PO_REQUIRED')
        amended=self.gate.apply_amendment(request['request_digest'],self.policy(target,calls=2,tokens=10000,revision=2),
            approving_authority='PO')
        return amended

    def test_01_internal_budget_insufficiency_opens_amendment_instead_of_terminal_block(self):
        _,target,_=self.exhausted();out=self.request(target)
        self.assertEqual((out['decision'],out['reason']),('REVIEW_REQUIRED','ADVISOR_RECOMMENDATION_REQUIRED'))
        self.assertFalse(out['new_llm_dispatch'])

    def test_02_hard_constraint_cannot_be_amended(self):
        _,target,_=self.exhausted();out=self.gate.request_expansion(target,material_need='needed',material_delta='new evidence',
            revised_estimate={'max_model_calls':2},review_reserve_impact={},hard_constraints=['ZERO_COST_ONLY'])
        self.assertEqual(out['reason'],'HARD_CONSTRAINT_NOT_AMENDABLE');self.assertFalse(out['new_reservation'])

    def test_03_executor_can_request_but_cannot_approve(self):
        _,target,_=self.exhausted();request=self.request(target)
        with self.assertRaisesRegex(ValueError,'ADVISOR_REVIEW_REQUIRED'):
            self.gate.review_expansion(request['request_digest'],reviewer_role='DEVELOPMENT',recommend=True)
        with self.assertRaisesRegex(ValueError,'PO_AMENDMENT_AUTHORITY_REQUIRED'):
            self.gate.apply_amendment(request['request_digest'],self.policy(target,calls=2,tokens=10000,revision=2),
                approving_authority='DEVELOPMENT')
        second=self.request(target,delta='different evidence reviewed as insufficient')
        rejected=self.gate.review_expansion(second['request_digest'],reviewer_role='ADVISOR',recommend=False)
        self.assertEqual(rejected['decision'],'EXPANSION_NOT_JUSTIFIED')

    def test_04_valid_recommendation_requires_po(self):
        _,target,_=self.exhausted();request=self.request(target)
        out=self.gate.review_expansion(request['request_digest'],reviewer_role='ADVISOR',recommend=True)
        self.assertEqual((out['decision'],out['approval_authority']),('PO_REQUIRED','PO'))

    def test_05_new_policy_revision_preserves_prior_policy(self):
        _,target,_=self.exhausted();request=self.request(target);amended=self.approve(target,request)
        rows=self.ledger.db.execute('SELECT revision,policy FROM budget_policy_history WHERE task_id=? ORDER BY revision',(target['task_id'],)).fetchall()
        self.assertEqual([row[0] for row in rows],[1,2]);self.assertNotEqual(rows[0][1],rows[1][1])
        self.assertEqual(amended['previous_policy_revision'],1)

    def test_06_cumulative_consumption_is_monotonic(self):
        _,target,old=self.exhausted(with_old_reservation=True);before=self.gate.telemetry(target['task_id'])['usage']
        request=self.request(target);amended=self.approve(target,request);after=amended['cumulative_usage']
        self.assertEqual(old['decision'],'ADMIT');self.assertGreaterEqual(after['model_calls'],before['model_calls'])
        self.assertGreaterEqual(after['estimated_tokens'],before['estimated_tokens'])

    def test_07_review_reserve_cannot_be_reduced(self):
        c=self.context();base=BudgetPolicy(c['task_id'],2,3000,1,2000,
            {'DEVELOPMENT':{'max_model_calls':1,'estimated_token_ceiling':2000},'ADVISOR':{'max_model_calls':1,'estimated_token_ceiling':1000}})
        self.gate.configure(base);decision=self.evaluate(c);self.assertEqual(decision['reason'],'ADVISOR_REVIEW_RESERVE_PROTECTED')
        request=self.request(c);self.gate.review_expansion(request['request_digest'],reviewer_role='ADVISOR',recommend=True)
        lowered=BudgetPolicy(c['task_id'],2,10000,0,0,
            {'DEVELOPMENT':{'max_model_calls':1,'estimated_token_ceiling':7000},'ADVISOR':{'max_model_calls':1,'estimated_token_ceiling':3000}},revision=2)
        with self.assertRaisesRegex(ValueError,'REVIEW_RESERVE_MUST_BE_PRESERVED'):
            self.gate.apply_amendment(request['request_digest'],lowered,approving_authority='PO')

    def test_08_uncertain_reservation_is_preserved_and_equivalent_retry_cannot_expand(self):
        c=self.context();self.gate.configure(self.policy(c,calls=2,tokens=10000));admit=self.evaluate(c)
        self.gate.transition(admit['reservation_id'],'UNCERTAIN');retry=self.evaluate(c)
        self.assertEqual(retry['reason'],'UNCERTAIN_NO_AUTOMATIC_RETRY')
        with self.assertRaisesRegex(ValueError,'BUDGET_INSUFFICIENCY_NOT_ESTABLISHED'):
            self.request(c)
        self.assertEqual(self.gate.telemetry(c['task_id'])['usage']['uncertain'],1)

    def test_09_duplicate_request_without_material_delta_is_no_op(self):
        _,target,_=self.exhausted();first=self.request(target);second=self.request(target)
        self.assertEqual(second['decision'],'NO_OP');self.assertEqual(second['request_digest'],first['request_digest'])
        self.assertFalse(second['new_review']);self.assertFalse(second['new_reservation']);self.assertFalse(second['new_llm_dispatch'])

    def test_10_amendment_is_followed_by_normal_tc06_reevaluation(self):
        _,target,_=self.exhausted();request=self.request(target);amended=self.approve(target,request)
        self.assertFalse(amended['approval_is_admission']);admission=self.evaluate(target)
        self.assertEqual(admission['decision'],'ADMIT');self.assertEqual(admission['reservation_status'],'RESERVED')

    def test_11_approval_does_not_dispatch_or_create_reservation(self):
        _,target,_=self.exhausted();before=self.gate.telemetry(target['task_id'])['usage']
        amended=self.approve(target,self.request(target));after=self.gate.telemetry(target['task_id'])['usage']
        self.assertFalse(amended['new_reservation']);self.assertFalse(amended['new_llm_dispatch']);self.assertEqual(before,after)

    def test_12_old_permit_is_invalid_and_reevaluation_creates_new_reservation(self):
        _,target,old=self.exhausted(with_old_reservation=True);permit=self.gate.permit(old['reservation_id'],old['execution_id'])
        self.approve(target,self.request(target))
        with self.assertRaisesRegex(ValueError,'STALE_POLICY_PERMIT'):self.gate.permit(old['reservation_id'],old['execution_id'])
        fresh=self.evaluate(target);self.assertNotEqual(fresh['reservation_id'],old['reservation_id'])
        with self.assertRaisesRegex(ValueError,'DISPATCH_RIGHT_NOT_AVAILABLE'):
            self.gate.claim_dispatch(permit,old['execution_id'])

    def test_13_zero_cost_authority_scope_and_protected_baselines_remain_unchanged(self):
        _,target,_=self.exhausted();request=self.request(target)
        stored=json.loads(self.ledger.db.execute('SELECT request FROM expansion_requests WHERE request_digest=?',(request['request_digest'],)).fetchone()[0])
        self.assertEqual(stored['scope_digest'],__import__('tdt_control_plane.contracts',fromlist=['digest']).digest(target['scope']))
        self.assertEqual(stored['authority_digest'],__import__('tdt_control_plane.contracts',fromlist=['digest']).digest(target['authority']))
        self.assertEqual(target['protected'],['Trader AI','TEF','Governance'])
        self.gate.review_expansion(request['request_digest'],reviewer_role='ADVISOR',recommend=True)
        invalid=replace(self.policy(target,calls=2,tokens=10000,revision=2),zero_cost_only=False)
        with self.assertRaisesRegex(ValueError,'ZERO_COST_ONLY_NOT_AMENDABLE'):
            self.gate.apply_amendment(request['request_digest'],invalid,approving_authority='PO')

    def test_14_flow_uses_no_delegate_provider_or_real_llm(self):
        _,target,_=self.exhausted();request=self.request(target);self.approve(target,request);out=self.evaluate(target)
        self.assertEqual(out['decision'],'ADMIT');self.assertFalse(out['llm_dispatched'])
        self.assertEqual(self.ledger.db.execute("SELECT count(*) FROM reservations WHERE status='CONSUMED'").fetchone()[0],0)


if __name__=='__main__':unittest.main()
