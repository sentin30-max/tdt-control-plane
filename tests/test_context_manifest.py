import copy
import json
import tempfile
import unittest
from pathlib import Path

from tdt_control_plane.context_manifest import (_duplicates, applicable, build_manifest,
    derivability_candidate, reference_candidate, validate_dependencies)
from tdt_control_plane.contracts import digest
from tdt_control_plane.resistance_pilot import route
from tdt_control_plane.runtime import build_role_prompt
from tdt_control_plane.tc02_shadow import generate
from test_ledger import context, result


class ContextManifestTests(unittest.TestCase):
    def test_reproducible_digest_and_exact_byte_partition(self):
        c=context('ADVISOR');c['inputs']['applicable_destinations']=['CODE_EXECUTOR']
        first=build_manifest(c);second=build_manifest(copy.deepcopy(c))
        self.assertEqual(first,second)
        self.assertEqual(first['manifest_digest'],second['manifest_digest'])
        self.assertEqual(sum(x['byte_size'] for x in first['context_units']),len(json.dumps(c).encode()))

    def test_revision_or_source_change_invalidates_manifest(self):
        c=context();m=build_manifest(c);self.assertTrue(applicable(m,c))
        changed=copy.deepcopy(c);changed['input_revision']=digest('new')
        self.assertFalse(applicable(m,changed))
        changed=copy.deepcopy(c);changed['source_digests']['source']=digest('changed')
        self.assertFalse(applicable(m,changed))

    def test_structural_duplicate_detected_but_different_authority_not_collapsed(self):
        value={'adverse':'preserve','limit':'no execution'}
        units=[{'unit_id':'a','_value':value,'authority_class':'EVIDENCE','kind':'VALUE','transport_form':'INLINE_REQUIRED','duplicates':[],
                'confidence_basis':'x','reason_code':'x'},
               {'unit_id':'b','_value':json.dumps(value),'authority_class':'EVIDENCE','kind':'VALUE','transport_form':'INLINE_REQUIRED','duplicates':[],
                'confidence_basis':'x','reason_code':'x'},
               {'unit_id':'c','_value':value,'authority_class':'AUTHORITY','kind':'VALUE','transport_form':'INLINE_REQUIRED','duplicates':[],
                'confidence_basis':'x','reason_code':'x'}]
        _duplicates(units)
        self.assertEqual(units[1]['transport_form'],'DUPLICATED')
        self.assertEqual(units[2]['transport_form'],'INLINE_REQUIRED')

    def test_derivable_requires_version_inputs_rule_and_equality_oracle(self):
        self.assertFalse(derivability_candidate()['eligible'])
        self.assertFalse(derivability_candidate({'a':1},'v1',lambda x:2,3)['eligible'])
        self.assertTrue(derivability_candidate({'a':1},'v1',lambda x:x['a']+1,2)['eligible'])

    def test_reference_requires_digest_access_fetch_and_same_scope(self):
        args=('id','v1','a'*64,'READ_AUTHORIZED','resolver','scope','scope')
        self.assertTrue(reference_candidate(*args)['eligible'])
        self.assertFalse(reference_candidate('id','v1','a'*64,'DENIED','resolver','scope','scope')['eligible'])
        self.assertFalse(reference_candidate('id','v1','a'*64,'READ_AUTHORIZED','resolver','scope','other')['eligible'])

    def test_unknown_stays_unknown_and_protective_missing_is_material(self):
        c=context();c['inputs']['mystery']={'small_prohibition':'never mutate'}
        m=build_manifest(c)
        mystery=next(x for x in m['context_units'] if x['selector']=='/inputs/mystery')
        self.assertEqual(mystery['semantic_necessity'],'UNKNOWN')
        del c['protected'];m=build_manifest(c)
        self.assertEqual(m['protective_coverage']['status'],'MATERIAL_FINDING')
        self.assertIn('protected_baselines',m['protective_coverage']['missing'])

    def test_small_zero_cost_and_old_adverse_finding_are_preserved(self):
        c=context('ADVISOR');c['inputs'].update(applicable_destinations=['PO_REQUIRED'],
            po_authority='ZERO_COST_ONLY. Never pay.',
            previous_material_result={'result':{'findings':['old adverse finding still applies']}})
        m=build_manifest(c)
        self.assertIn('zero_cost_only',m['protective_coverage']['represented'])
        self.assertIn('adverse_findings',m['protective_coverage']['represented'])

    def test_digest_valid_wrong_scope_and_inaccessible_ref_fail_closed(self):
        for permission,scope in [('DENIED','right'),('READ_AUTHORIZED','wrong')]:
            with self.subTest(permission=permission,scope=scope):
                self.assertEqual(reference_candidate('id','v','b'*64,permission,'fetch','right',scope)['classification'],'NEEDS_CONTRACT_EVIDENCE')

    def test_missing_and_circular_dependency_fail_closed(self):
        units=[{'unit_id':'a','derived_from':['b']},{'unit_id':'b','derived_from':['a']}]
        with self.assertRaisesRegex(ValueError,'CIRCULAR_DEPENDENCY'):validate_dependencies(units)
        # A missing edge never becomes a derivation proof.
        self.assertFalse(derivability_candidate({'source':'missing'},'v1',None,'value')['eligible'])

    def test_shadow_does_not_change_prompt_routing_or_result(self):
        project=Path(__file__).resolve().parents[1]
        pilot=json.loads((project/'evidence/slice002/pilot-run.json').read_text())
        first=pilot['executions'][0];persisted=json.loads((project/'evidence/slice002/executions'/(first['execution_id']+'.json')).read_text())
        c=persisted['context'];r=persisted['result'];prompt=build_role_prompt(c);state=c['inputs']['state']
        with tempfile.TemporaryDirectory() as tmp:report=generate(project,Path(tmp))
        self.assertEqual(build_role_prompt(c),prompt)
        self.assertEqual(digest(r),first['result_digest'])
        self.assertEqual(route(r,state),pilot['routing'][0]['proposed'])
        self.assertEqual(report['new_llm_calls_for_tc02'],0)
        self.assertFalse(report['material_context_change'])

    def test_slice002_four_manifests_and_tc01_semantics(self):
        project=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:report=generate(project,Path(tmp))
        self.assertEqual(report['status'],'PASS');self.assertEqual(len(report['manifests']),4)
        baseline=report['tc01_baseline']
        self.assertEqual((baseline['llm_sessions'],baseline['deterministic_executions']), (4,1))
        self.assertEqual((baseline['estimated_input_tokens'],baseline['estimated_output_tokens'],baseline['estimated_combined_tokens']),(28397,4928,33325))
        self.assertIsNone(baseline['actual_runtime_tokens']);self.assertIsNone(baseline['account_quota_attribution'])


if __name__=='__main__':unittest.main()
