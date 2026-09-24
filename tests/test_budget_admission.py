import copy
import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from tdt_control_plane.budget_admission import (AdmissionGate,BudgetPolicy,GovernedLLMExecutor,
    POLICY_VERSION,material_fingerprint)
from tdt_control_plane.contracts import digest
from tdt_control_plane.deterministic_dispatch import DeterministicDispatcher
from tdt_control_plane.deterministic_preparation import CONTRACT_VERSION,RULE_SET_VERSION
from tdt_control_plane.ledger import Ledger
from tdt_control_plane.roles import make_context
from tdt_control_plane.telemetry import serialized_json_bytes


class BudgetAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(__file__).resolve().parents[1]
        cls.deterministic=json.loads((root/'evidence/slice002/executions/96355d38-bc31-5eab-9a70-beda3f1e4e69.json').read_text())['context']

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.ledger=Ledger(Path(self.tmp.name)/'ledger.db')
        self.gate=AdmissionGate(self.ledger,DeterministicDispatcher(self.ledger))

    def tearDown(self):self.ledger.close();self.tmp.cleanup()

    def context(self,role='DEVELOPMENT',execution_id=None,blocker=None,authority_marker='v1'):
        task='11111111-1111-4111-8111-111111111111';revision='a'*64
        return make_context(execution_id or str(uuid4()),task,revision,role,'budget-fixture','Produce bounded material output',
            {'state':{'value':1,'blocker':blocker},'authority_marker':authority_marker}, {'fixture':'b'*64}, ['protected baseline'])

    def configure(self,c,calls=4,tokens=20000,review_calls=1,review_tokens=2000,role_calls=3,role_tokens=16000):
        allocations={'DEVELOPMENT':{'max_model_calls':role_calls,'estimated_token_ceiling':role_tokens},
                     'ADVISOR':{'max_model_calls':calls-role_calls,'estimated_token_ceiling':tokens-role_tokens}}
        p=BudgetPolicy(c['task_id'],calls,tokens,review_calls,review_tokens,allocations);self.gate.configure(p);return p

    def evaluate(self,c,**kwargs):
        values={'why_llm_required':'GENERATIVE_SYNTHESIS_REQUIRED','execution_purpose':'create specification',
                'expected_material_output':'validated structured specification','output_token_budget':1000}
        values.update(kwargs);return self.gate.evaluate(c,**values)

    def test_hierarchy_arithmetic_and_overallocation_rejected(self):
        c=self.context();self.configure(c)
        with self.assertRaisesRegex(ValueError,'OVERALLOCATION'):
            BudgetPolicy(c['task_id'],2,1000,1,100,{'DEVELOPMENT':{'max_model_calls':3,'estimated_token_ceiling':1000}}).validate()

    def test_admit_creates_atomic_non_double_counted_reservation(self):
        c=self.context();self.configure(c);out=self.evaluate(c)
        self.assertEqual(out['decision'],'ADMIT');self.assertEqual(out['reservation_status'],'RESERVED');self.assertFalse(out['llm_dispatched'])
        estimate=out['resource_estimate'];self.assertEqual(estimate['total_tokens']['value'],estimate['context_tokens']['value']+estimate['output_tokens']['value'])
        usage=self.gate.telemetry(c['task_id'])['usage'];self.assertEqual(usage['model_calls'],1);self.assertEqual(usage['estimated_tokens'],estimate['total_tokens']['value'])

    def test_duplicate_reservation_is_atomic_and_rejected(self):
        c=self.context();self.configure(c);first=self.evaluate(c);second=self.evaluate(c)
        self.assertEqual(first['decision'],'ADMIT');self.assertEqual(second['decision'],'BLOCK');self.assertEqual(second['reason'],'DUPLICATE_RESERVATION')
        self.assertEqual(self.gate.telemetry(c['task_id'])['usage']['reserved'],1)

    def test_reservation_lifecycle_measured_estimated_and_release(self):
        c=self.context();self.configure(c);out=self.evaluate(c);rid=out['reservation_id']
        self.gate.transition(rid,'CONSUMED',777);usage=self.gate.telemetry(c['task_id'])['usage']
        self.assertEqual((usage['consumed'],usage['measured_tokens']),(1,777))
        c2=self.context();out2=self.evaluate(c2);self.gate.transition(out2['reservation_id'],'RELEASED')
        usage=self.gate.telemetry(c['task_id'])['usage'];self.assertEqual(usage['released'],1);self.assertEqual(usage['model_calls'],1)

    def test_uncertain_never_becomes_zero_or_automatic_retry(self):
        c=self.context();self.configure(c);out=self.evaluate(c);self.gate.transition(out['reservation_id'],'UNCERTAIN')
        retry=self.evaluate(c);self.assertEqual(retry['decision'],'DEFER');self.assertEqual(retry['reason'],'UNCERTAIN_NO_AUTOMATIC_RETRY')
        usage=self.gate.telemetry(c['task_id'])['usage'];self.assertEqual(usage['uncertain'],1);self.assertEqual(usage['model_calls'],1)

    def test_reuse_precedes_reservation_and_material_deltas_change_fingerprint(self):
        c=self.context();self.configure(c);fp=self.gate.remember_reusable(c,'c'*64)
        reuse=self.evaluate(c);self.assertEqual(reuse['route'],'REUSE');self.assertIsNone(reuse['reservation'])
        for changed in (self.context(blocker='new'),self.context(authority_marker='v2')):
            self.assertNotEqual(fp,material_fingerprint(changed))

    def test_deterministic_precedes_budget_and_creates_no_llm_reservation(self):
        out=self.gate.evaluate(self.deterministic,contract_version=CONTRACT_VERSION,rule_set_version=RULE_SET_VERSION)
        self.assertEqual(out['route'],'DETERMINISTIC');self.assertIsNone(out['reservation']);self.assertEqual(out['deterministic_result']['model_call_count'],0)

    def test_review_reserve_protected_without_context_or_output_degradation(self):
        c=self.context();tokens=(serialized_json_bytes(c)+3)//4+1000
        self.configure(c,calls=2,tokens=tokens+1999,review_calls=1,review_tokens=2000,role_calls=1,role_tokens=tokens)
        out=self.evaluate(c);self.assertEqual(out['decision'],'REVIEW_REQUIRED');self.assertEqual(out['reason'],'ADVISOR_REVIEW_RESERVE_PROTECTED')
        self.assertFalse(out['silent_context_degradation']);self.assertFalse(out['silent_output_degradation'])

    def test_task_budget_exhaustion_defers_and_does_not_reduce_output(self):
        c=self.context();tokens=(serialized_json_bytes(c)+3)//4+999
        self.configure(c,calls=4,tokens=tokens,review_calls=0,review_tokens=0,role_calls=3,role_tokens=tokens)
        out=self.evaluate(c,output_token_budget=1000);self.assertEqual(out['decision'],'DEFER');self.assertEqual(out['reason'],'TASK_BUDGET_EXHAUSTED')
        self.assertFalse(out['llm_dispatched']);self.assertFalse(out['silent_output_degradation'])

    def test_independent_review_exception_does_not_reuse(self):
        c=self.context('ADVISOR');
        p=BudgetPolicy(c['task_id'],2,10000,1,2000,{'ADVISOR':{'max_model_calls':2,'estimated_token_ceiling':10000}});self.gate.configure(p)
        self.gate.remember_reusable(c,'d'*64)
        out=self.gate.evaluate(c,why_llm_required='INDEPENDENT_REVIEW_REQUIRED',execution_purpose='independent review',
                               expected_material_output='independent findings',output_token_budget=1000,independent_review=True)
        self.assertEqual(out['decision'],'ADMIT');self.assertTrue(out['independent_review'])

    def test_llm_necessity_is_not_role_and_value_justification_required(self):
        c=self.context();self.configure(c)
        self.assertEqual(self.gate.evaluate(c,why_llm_required='ROLE_IS_DEVELOPMENT',execution_purpose='x',expected_material_output='y',output_token_budget=1)['decision'],'BLOCK')
        self.assertEqual(self.gate.evaluate(c,why_llm_required='OPEN_ENDED_ANALYSIS',output_token_budget=1)['decision'],'REVIEW_REQUIRED')

    def test_not_available_propagates_and_is_neither_zero_nor_infinite(self):
        c=self.context();self.configure(c);out=self.evaluate(c)
        self.assertEqual(out['account_quota'],{'status':'NOT_AVAILABLE','value':None,'source':'NOT_CONNECTED'})
        self.assertEqual(out['resource_estimate']['context_tokens']['status'],'ESTIMATED');self.assertEqual(out['resource_estimate']['context_bytes']['status'],'MEASURED')

    def test_executor_cannot_bypass_gate_or_self_authorize_budget(self):
        c=self.context();self.configure(c)
        class Delegate:
            def submit(self,context):return 'called'
        governed=GovernedLLMExecutor(self.gate,Delegate())
        with self.assertRaisesRegex(ValueError,'PRE_LLM_ADMISSION_REQUIRED'):governed.submit(c)
        c['inputs']['claimed_extra_budget']=999999;c['context_id']=digest({k:v for k,v in c.items() if k not in {'context_id','execution_id'}})
        out=self.evaluate(c);self.assertEqual(out['decision'],'ADMIT');self.assertLess(out['resource_estimate']['total_tokens']['value'],999999)

    def test_permit_requires_real_active_reservation(self):
        c=self.context();self.configure(c);out=self.evaluate(c);permit=self.gate.permit(out['reservation_id'],c['execution_id'])
        self.assertEqual(permit['policy_version'],POLICY_VERSION)
        self.gate.transition(out['reservation_id'],'UNCERTAIN')
        with self.assertRaisesRegex(ValueError,'PRE_LLM_ADMISSION_REQUIRED'):self.gate.permit(out['reservation_id'],c['execution_id'])

    def test_deterministic_material_blocker_never_falls_through_to_llm(self):
        c=copy.deepcopy(self.deterministic);c['source_digests']['specification']='0'*64
        c['context_id']=digest({k:v for k,v in c.items() if k not in {'context_id','execution_id'}})
        out=self.gate.evaluate(c,contract_version=CONTRACT_VERSION,rule_set_version=RULE_SET_VERSION,
            why_llm_required='OPEN_ENDED_ANALYSIS',execution_purpose='bypass',expected_material_output='x',output_token_budget=1000)
        self.assertEqual(out['decision'],'BLOCK');self.assertIn('DETERMINISTIC_MATERIAL_BLOCKER',out['reason']);self.assertFalse(out['llm_dispatch_authorized'])


if __name__=='__main__':unittest.main()
