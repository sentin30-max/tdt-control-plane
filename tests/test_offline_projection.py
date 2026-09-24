import copy
import json
import tempfile
import unittest
from pathlib import Path

from tdt_control_plane.context_manifest import build_manifest
from tdt_control_plane.offline_projection import build_projection, evaluate_gates, reconstruct
from tdt_control_plane.tc03_offline import generate
from test_ledger import context


class OfflineProjectionTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parents[1]

    def _projection(self, execution_id="96355d38-bc31-5eab-9a70-beda3f1e4e69"):
        record=json.loads((self.root/'evidence/slice002/executions'/(execution_id+'.json')).read_text())
        manifest=json.loads((self.root/'evidence/tc02'/(execution_id+'.manifest.json')).read_text())
        return record['context'],manifest,build_projection(record['context'],manifest)

    def test_four_offline_projections_are_non_authoritative_and_recover_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            report=generate(self.root,Path(tmp))
            self.assertEqual(len(report['slice002_results']),4)
            self.assertEqual(report['new_llm_calls_for_tc03'],0)
            for result in report['slice002_results']:
                p=json.loads((Path(tmp)/(result['execution_id']+'.projection.json')).read_text())
                self.assertFalse(p['authoritative']);self.assertFalse(p['operational']);self.assertFalse(p['dispatchable'])
                self.assertEqual(p['projection_acceptance'],'ACCEPTED')
                self.assertTrue(all(x['status']=='PASS' for x in p['equivalence_gates'].values()))

    def test_exact_duplicate_has_ledger_and_exact_recovery(self):
        original,manifest,p=self._projection('2142e6da-c067-55c8-8912-cff46e335f64')
        accepted=[x for x in p['transformation_ledger'] if x['status']=='ACCEPTED']
        self.assertTrue(accepted);self.assertEqual(accepted[0]['transformation_type'],'EXACT_DUPLICATE_ELISION')
        self.assertEqual(reconstruct(p['projected_context'],p['transformation_ledger'],manifest['context_units']),original)

    def test_different_authority_duplicate_is_kept(self):
        c=context('ADVISOR');v={'rule':'never mutate'}
        c['inputs']['po_authority']=v;c['inputs']['one']=copy.deepcopy(v)
        p=build_projection(c,build_manifest(c))
        self.assertIn('one',p['projected_context']['inputs']);self.assertIn('po_authority',p['projected_context']['inputs'])

    def test_prohibition_and_adverse_finding_in_duplicate_looking_material_stay(self):
        c=context('ADVISOR');finding=['never execute while unresolved']
        c['inputs']['previous_material_result']={'result':{'findings':finding}}
        c['inputs'].setdefault('state',{})['blocker']={'finding':finding}
        p=build_projection(c,build_manifest(c))
        self.assertEqual(p['projected_context']['inputs']['state']['blocker']['finding'],finding)
        self.assertEqual(p['projected_context']['inputs']['previous_material_result']['result']['findings'],finding)

    def test_wrong_scope_or_revision_invalidates_manifest(self):
        c=context();m=build_manifest(c)
        for field,value in [('scope','wrong'),('input_revision','0'*64)]:
            changed=copy.deepcopy(c);changed[field]=value
            with self.assertRaisesRegex(ValueError,'MANIFEST_NOT_APPLICABLE'):build_projection(changed,m)

    def test_missing_ledger_changed_blocker_destination_and_silent_correction_fail(self):
        original,manifest,p=self._projection('2142e6da-c067-55c8-8912-cff46e335f64')
        accepted=[x for x in p['transformation_ledger'] if x['status']=='ACCEPTED']
        self.assertTrue(accepted)
        self.assertEqual(evaluate_gates(original,p['projected_context'],[],manifest['context_units'])['EG-10']['status'],'FAIL')
        for selector,value,gate in [('/inputs/state/blocker',{'new':'blocker'},'EG-08'),
                                    ('/inputs/applicable_destinations',['PO_REQUIRED'],'EG-09')]:
            changed=copy.deepcopy(p['projected_context'])
            parts=selector.strip('/').split('/');node=changed
            for part in parts[:-1]:node=node.setdefault(part,{})
            node[parts[-1]]=value
            self.assertEqual(evaluate_gates(original,changed,p['transformation_ledger'],manifest['context_units'])[gate]['status'],'FAIL')

    def test_derivation_reference_unknown_conditional_and_superseded_material_fail_closed(self):
        original,manifest,p=self._projection('2142e6da-c067-55c8-8912-cff46e335f64')
        c=copy.deepcopy(original);c['inputs'].update(mystery='UNKNOWN must remain',conditional_requirement='active',superseded_decision='retain provenance')
        p=build_projection(c,build_manifest(c))
        for key in ('mystery','conditional_requirement','superseded_decision'):
            self.assertIn(key,p['projected_context']['inputs'])
        self.assertTrue(all(key in p['projected_context']['inputs'] for key in ('mystery','conditional_requirement','superseded_decision')))

    def test_wrong_derivation_rule_or_missing_input_and_inaccessible_ref_are_not_proofs(self):
        from tdt_control_plane.context_manifest import derivability_candidate, reference_candidate
        self.assertFalse(derivability_candidate(None,'v1',lambda x:x,'x')['eligible'])
        self.assertFalse(derivability_candidate({'x':1},'wrong',lambda x:2,1)['eligible'])
        self.assertFalse(reference_candidate('id','v1','a'*64,'DENIED','resolver','scope','scope')['eligible'])

    def test_changed_stale_finding_and_contradiction_are_detected(self):
        c=context('ADVISOR');c['inputs']['previous_material_result']={'result':{'findings':['contradiction unresolved']}}
        m=build_manifest(c);p=build_projection(c,m);changed=copy.deepcopy(p['projected_context'])
        changed['inputs']['previous_material_result']['result']['findings']=[]
        gates=evaluate_gates(c,changed,p['transformation_ledger'],m['context_units'])
        self.assertEqual(gates['EG-04']['status'],'FAIL');self.assertEqual(gates['EG-12']['status'],'FAIL')

    def test_metadata_overhead_is_reported_separately_and_can_exceed_saving(self):
        _,_,p=self._projection()
        self.assertGreater(p['shadow_metadata_bytes'],p['byte_accounting']['removed_bytes'])
        self.assertEqual(p['byte_accounting']['future_executor_context_bytes'],p['byte_accounting']['projected_bytes'])

    def test_final_unknown_does_not_look_resolved(self):
        _,_,p=self._projection('be889d75-1dd5-50bb-8835-ebd70bea693f')
        resolutions=p['needs_contract_evidence_resolution']
        self.assertEqual((len(resolutions),sum(x['bytes'] for x in resolutions)),(5,15057))
        self.assertTrue(all(x['resolution']=='UNRESOLVED_KEEP_INLINE' for x in resolutions))


if __name__=='__main__':unittest.main()
