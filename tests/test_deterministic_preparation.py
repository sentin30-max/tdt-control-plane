import copy
import json
import unittest
from pathlib import Path

from tdt_control_plane.contracts import digest
from tdt_control_plane.deterministic_preparation import (CONTRACT_VERSION, RULE_SET_VERSION,
    MATERIAL_OUTPUT_FIELDS, NOT_APPLICABLE, PreparationError, ShadowRecovery, prepare,
    rule_coverage, timed_prepare, validate_output)


class DeterministicPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(__file__).resolve().parents[1]
        cls.persisted=json.loads((root/'evidence/slice002/executions/96355d38-bc31-5eab-9a70-beda3f1e4e69.json').read_text())
        cls.context=cls.persisted['context'];cls.historical=cls.persisted['result']

    def changed(self,mutator):
        c=copy.deepcopy(self.context);mutator(c)
        c['context_id']=digest({k:v for k,v in c.items() if k not in {'context_id','execution_id'}})
        return c

    def assert_closed(self,context=None,rule=RULE_SET_VERSION,contract=CONTRACT_VERSION):
        with self.assertRaisesRegex(PreparationError,NOT_APPLICABLE):prepare(context or self.context,rule,contract)

    def test_historical_replay_is_byte_exact_structural_and_material(self):
        output=prepare(self.context)
        self.assertEqual(output,self.historical)
        self.assertEqual(json.dumps(output),json.dumps(self.historical))
        self.assertTrue(validate_output(self.context,output))

    def test_all_material_fields_have_declared_rules(self):
        coverage=rule_coverage()
        self.assertEqual(set(coverage),set(MATERIAL_OUTPUT_FIELDS))
        self.assertTrue(all(coverage.values()))

    def test_valid_candidate_identity_change_propagates_without_memorization(self):
        def mutate(c):
            c['inputs']['specification']['request_updates']['request_id']='RESISTANCE-AUDIT-REQUEST-NEW-A4-TWO-STAGE-V1-01'
            c['source_digests']['specification']=digest(c['inputs']['specification'])
        c=self.changed(mutate);out=prepare(c);artifact=json.loads(out['artifact'])
        self.assertEqual(artifact['request']['request_id'],'RESISTANCE-AUDIT-REQUEST-NEW-A4-TWO-STAGE-V1-01')
        self.assertNotEqual(out,self.historical)

    def test_valid_context_revision_change_propagates(self):
        c=self.changed(lambda x:x.update(input_revision='a'*64));out=prepare(c)
        self.assertEqual(out['input_revision'],'a'*64);self.assertNotEqual(out['context_digest'],self.historical['context_digest'])

    def test_valid_literal_and_hash_change_propagates(self):
        def mutate(c):
            spec=c['inputs']['specification'];old,new=spec['input_literal_replacements'][0]
            spec['input_literal_replacements'][0]=[old,new+'-changed'];c['source_digests']['specification']=digest(spec)
        out=prepare(self.changed(mutate));self.assertIn('two-stage-v1-changed',json.loads(out['artifact'])['input_text'])

    def test_missing_input_revision_contract_and_rule_fail_closed(self):
        c=copy.deepcopy(self.context);del c['inputs']['historical_input'];self.assert_closed(c)
        self.assert_closed(self.changed(lambda x:x.update(input_revision='short')))
        self.assert_closed(rule='unknown');self.assert_closed(contract='unknown')

    def test_protected_baseline_and_authority_changes_fail_closed(self):
        self.assert_closed(self.changed(lambda c:c['inputs']['historical_request'].update(evaluated_baseline='other')))
        self.assert_closed(self.changed(lambda c:c['authority'].update(can_do=['product_decision'])))

    def test_extra_field_malformed_and_contradiction_fail_closed(self):
        self.assert_closed(self.changed(lambda c:c['inputs']['historical_request'].update(extra_relevant='x')))
        self.assert_closed(self.changed(lambda c:c['inputs'].update(historical_input={'bad':True})))
        self.assert_closed(self.changed(lambda c:c['inputs']['state'].update(blocker={'finding':'contradiction'})))

    def test_unresolved_choice_and_candidate_collision_fail_closed(self):
        def duplicate(c):
            old=c['inputs']['specification']['input_literal_replacements'][0][0]
            c['inputs']['historical_input']+=old;c['source_digests']['specification']=digest(c['inputs']['specification'])
        self.assert_closed(self.changed(duplicate))
        def collision(c):
            s=c['inputs']['specification'];s['request_updates']['request_id']=c['inputs']['historical_request']['request_id'];c['source_digests']['specification']=digest(s)
        self.assert_closed(self.changed(collision))

    def test_syntactically_valid_but_materially_wrong_output_is_rejected(self):
        out=prepare(self.context);artifact=json.loads(out['artifact']);artifact['request']['unit']='Support'
        out['artifact']=json.dumps(artifact,separators=(',',':'))
        with self.assertRaisesRegex(PreparationError,'REQUEST_TRANSFORMATION_ORACLE_FAILED'):validate_output(self.context,out)

    def test_builder_does_not_assume_advisor_or_routing_authority(self):
        out=prepare(self.context)
        self.assertEqual(out['next_destination'],'NONE');self.assertEqual(out['effects'],[]);self.assertEqual(out['proposals'],[])

    def test_idempotency_order_insensitivity_and_material_delta(self):
        first,telemetry=timed_prepare(self.context,20);second=prepare(copy.deepcopy(self.context))
        self.assertEqual(first,second);self.assertEqual(digest(first),digest(second));self.assertEqual(telemetry['iterations'],20)
        # JSON mapping insertion order is irrelevant because artifact follows the historical request's canonical order.
        c=copy.deepcopy(self.context);c['inputs']['specification']['request_updates']=dict(reversed(list(c['inputs']['specification']['request_updates'].items())))
        c['source_digests']['specification']=digest(c['inputs']['specification']);c['context_id']=digest({k:v for k,v in c.items() if k not in {'context_id','execution_id'}})
        self.assertEqual(json.loads(prepare(c)['artifact']),json.loads(first['artifact']))

    def test_shadow_recovery_duplicate_is_no_effect_and_conflict_fails(self):
        result=prepare(self.context);recovery=ShadowRecovery();identity='shadow:'+self.context['context_id']
        self.assertEqual(recovery.persist(identity,result)['status'],'PERSISTED_SHADOW')
        self.assertEqual(recovery.persist(identity,result)['status'],'NO_NEW_EFFECT')
        changed=copy.deepcopy(result);changed['findings'].append('different')
        with self.assertRaisesRegex(PreparationError,'RECOVERY_DIGEST_CONTRADICTION'):recovery.persist(identity,changed)

    def test_historical_result_was_not_used_as_builder_input(self):
        out=prepare(self.context)
        self.assertNotIn('historical_result',self.context['inputs'])
        self.assertEqual(digest(out),self.persisted['result_digest'])


if __name__=='__main__':unittest.main()
