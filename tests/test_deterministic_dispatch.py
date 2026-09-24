import copy
import json
import tempfile
import unittest
from pathlib import Path

from tdt_control_plane.contracts import digest
from tdt_control_plane.deterministic_dispatch import (ELIGIBLE, MATERIAL_BLOCKER, NOT_APPLICABLE_CLASS,
    EXECUTOR_ID, DeterministicDispatcher, ExecutionRouter, eligibility)
from tdt_control_plane.deterministic_preparation import CONTRACT_VERSION, RULE_SET_VERSION, prepare
from tdt_control_plane.ledger import Ledger


class DeterministicDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(__file__).resolve().parents[1]
        cls.persisted=json.loads((root/'evidence/slice002/executions/96355d38-bc31-5eab-9a70-beda3f1e4e69.json').read_text())
        cls.context=cls.persisted['context'];cls.historical=cls.persisted['result']

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.ledger=Ledger(Path(self.tmp.name)/'ledger.db')
        self.dispatcher=DeterministicDispatcher(self.ledger)

    def tearDown(self):self.ledger.close();self.tmp.cleanup()

    def changed(self,fn,new_execution=False):
        c=copy.deepcopy(self.context);fn(c)
        if new_execution:c['execution_id']='22222222-2222-4222-8222-222222222222'
        c['context_id']=digest({k:v for k,v in c.items() if k not in {'context_id','execution_id'}})
        return c

    def dispatch(self,c=None,contract=CONTRACT_VERSION,rules=RULE_SET_VERSION,normal=False):
        return self.dispatcher.dispatch(c or self.context,contract,rules,normal)

    def test_eligible_operational_pilot_avoids_llm_and_hands_off(self):
        out=ExecutionRouter(self.dispatcher).route(self.context,CONTRACT_VERSION,RULE_SET_VERSION)
        self.assertEqual(out['execution_classification'],ELIGIBLE);self.assertEqual(out['selected_executor'],EXECUTOR_ID)
        self.assertEqual(out['router_decision'],'DETERMINISTIC_EXECUTOR');self.assertFalse(out['normal_dispatch_executed'])
        self.assertEqual(out['result'],self.historical);self.assertEqual(out['verify_ingest'],'PASS')
        self.assertFalse(out['llm_dispatched']);self.assertEqual(out['model_call_count'],0);self.assertEqual(out['avoided_llm_dispatch'],1)
        self.assertEqual(out['advisor_handoff'],'READY');self.assertFalse(out['advisor_review_completed']);self.assertFalse(out['next_operational_dispatch_before_advisor'])
        telemetry=self.ledger.telemetry(self.context['execution_id'])[0]['record']
        self.assertEqual(telemetry['execution_kind'],'DETERMINISTIC');self.assertEqual(telemetry['accounting']['model_call_count']['value'],0)

    def test_not_applicable_pilot_keeps_normal_path_selectable_without_execution(self):
        c=self.changed(lambda x:x['inputs'].update(operation='OTHER_OPERATION'))
        out=self.dispatch(c,normal=True)
        self.assertEqual(out['execution_classification'],NOT_APPLICABLE_CLASS);self.assertTrue(out['normal_path_selectable'])
        self.assertFalse(out['deterministic_executed']);self.assertFalse(out['llm_dispatched'])

    def test_false_contract_stale_contract_and_rules_are_blockers_for_target(self):
        for contract,rules in [('stale',RULE_SET_VERSION),(CONTRACT_VERSION,'stale')]:
            with self.subTest(contract=contract,rules=rules):
                out=self.dispatch(contract=contract,rules=rules)
                self.assertEqual(out['execution_classification'],MATERIAL_BLOCKER);self.assertFalse(out['automatic_llm_fallback'])

    def test_wrong_role_operation_scope_are_not_accidentally_deterministic(self):
        cases=[lambda c:c.update(role='ADVISOR'),lambda c:c['inputs'].update(operation='REVIEW'),lambda c:c.update(scope='other')]
        for mutate in cases:
            out=self.dispatch(self.changed(mutate),normal=True)
            self.assertEqual(out['execution_classification'],NOT_APPLICABLE_CLASS);self.assertIsNone(out['selected_executor'])

    def test_authority_baseline_digest_choice_and_contradiction_block_without_fallback(self):
        cases=[lambda c:c['authority'].update(can_do=['product_decision']),
               lambda c:c['inputs']['historical_request'].update(evaluated_baseline='other'),
               lambda c:c['source_digests'].update(specification='0'*64),
               lambda c:c['inputs'].update(state={**c['inputs']['state'],'blocker':{'finding':'contradiction'}}),
               lambda c:c['inputs'].update(historical_input=c['inputs']['historical_input']+c['inputs']['specification']['input_literal_replacements'][0][0])]
        for mutate in cases:
            with self.subTest(mutate=mutate):
                out=self.dispatch(self.changed(mutate));self.assertEqual(out['execution_classification'],MATERIAL_BLOCKER)
                self.assertFalse(out['automatic_llm_fallback']);self.assertEqual(out['advisor_handoff'],'READY')
                self.assertEqual(out['operational_continuation'],'STOPPED_FOR_SCOPE')

    def test_output_oracle_failure_and_attempted_destination_are_blockers(self):
        def bad(context,rules,contract):
            out=prepare(context,rules,contract);out['artifact']='{"request":{},"input_text":"wrong"}';return out
        self.dispatcher=DeterministicDispatcher(self.ledger,bad)
        self.assertEqual(self.dispatch()['execution_classification'],MATERIAL_BLOCKER)
        self.ledger.close();self.tmp.cleanup();self.tmp=tempfile.TemporaryDirectory();self.ledger=Ledger(Path(self.tmp.name)/'ledger.db')
        def route(context,rules,contract):
            out=prepare(context,rules,contract);out['next_destination']='COMPLETE';return out
        self.dispatcher=DeterministicDispatcher(self.ledger,route)
        self.assertEqual(self.dispatch()['execution_classification'],MATERIAL_BLOCKER)

    def test_recovery_reuses_completed_without_redispatch(self):
        calls=[]
        def counted(c,r,v):calls.append(1);return prepare(c,r,v)
        self.dispatcher=DeterministicDispatcher(self.ledger,counted)
        first=self.dispatch();second=self.dispatch()
        self.assertEqual(len(calls),1);self.assertEqual(second['recovery_status'],'REUSABLE');self.assertEqual(second['avoided_llm_dispatch'],0)
        self.assertEqual(first['result_digest'],second['result_digest'])

    def test_same_execution_different_result_digest_is_contradiction(self):
        self.dispatch();changed=copy.deepcopy(self.historical);changed['findings']=['different']
        verdict=self.ledger.ingest(self.context['execution_id'],json.dumps(changed),self.context['input_revision'],self.context['source_digests'])
        self.assertEqual(verdict,'EXECUTION_CONTRADICTION');self.assertEqual(self.ledger.recover(self.context['execution_id'])['status'],'ISOLATED')

    def test_not_applicable_does_not_create_global_blocker_and_defect_is_scoped(self):
        wrong=self.changed(lambda c:c['inputs'].update(operation='OTHER_OPERATION'),True)
        self.assertEqual(self.dispatch(wrong,normal=True)['execution_classification'],NOT_APPLICABLE_CLASS)
        self.assertEqual(self.dispatch()['execution_classification'],ELIGIBLE)

    def test_success_cannot_bypass_advisor_or_claim_review(self):
        out=self.dispatch();self.assertEqual(out['advisor_handoff'],'READY');self.assertFalse(out['advisor_review_completed'])
        self.assertFalse(out['next_operational_dispatch_before_advisor'])

    def test_registry_does_not_accept_executor_self_authorization(self):
        c=self.changed(lambda x:x['inputs'].update(executor_claim={'contract_version':CONTRACT_VERSION,'rule_set_version':RULE_SET_VERSION,'authorized':True}))
        self.assertEqual(eligibility(c,None,None)['classification'],NOT_APPLICABLE_CLASS)

    def test_unsupported_code_executor_task_is_not_selected(self):
        c=self.changed(lambda x:x['inputs'].update(operation='SOME_SIMPLE_TASK'))
        self.assertEqual(self.dispatch(c,normal=True)['execution_classification'],NOT_APPLICABLE_CLASS)

    def test_material_downstream_contract_is_unchanged(self):
        out=self.dispatch();self.assertEqual(set(out['result']),set(self.historical));self.assertEqual(digest(out['result']),self.persisted['result_digest'])

    def test_telemetry_cannot_falsely_claim_model_or_savings(self):
        out=self.dispatch();record=self.ledger.telemetry(self.context['execution_id'])[0]['record']
        self.assertEqual(record['accounting']['model_call_count']['value'],0);self.assertFalse(out['llm_dispatched'])
        self.assertEqual(out['actual_token_savings'],'NOT_AVAILABLE');self.assertEqual(out['account_quota_savings'],'NOT_AVAILABLE')


if __name__=='__main__':unittest.main()
