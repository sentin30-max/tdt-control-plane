import copy
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from tdt_control_plane.contracts import digest
from tdt_control_plane.resolution import load_fixture, resolve, next_action, TraderSourceAdapter, derive_claims
from tdt_control_plane.projection import project
from tdt_control_plane.roles import strict_json

ROOT = Path(__file__).resolve().parents[1] / 'fixtures/trader'


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        self.r = load_fixture(ROOT)

    def test_real_pinned_fixture(self):
        r = self.r['resolved']
        for key, value in [('support_closed','CERRADO'),('d6_preserved',False),('sprint2_not_reaudited',False),('support_consumed','CONSUMADO'),('resistance_audit','EN_AUDITORIA'),('blocker','EXECUTION_BLOCKER_NOT_AUDIT_RESULT')]:
            self.assertEqual(r[key]['value'], value)
        self.assertIn('HISTORICAL', r['sprint2_historical']['value'])
        self.assertNotEqual(r['evaluated']['value'], self.r['source_revision'])
        self.assertIn('NOT_DETERMINABLE',r['domain_not_determined']['value'])
        self.assertEqual(r['resistance_audit']['historical'], ['resistance_open'])

    def test_rebuild_without_cache_is_identical(self):
        self.assertEqual(self.r, load_fixture(ROOT))
        self.assertFalse(self.r['authoritative'])

    def test_contradiction_not_latest_wins_and_authority_scoped(self):
        m, docs = TraderSourceAdapter(ROOT).load()
        conf = strict_json((ROOT.parent/'mapping.json').read_text())
        claims = derive_claims(m, docs, conf['mapping'])
        c = next(c for c in claims if c['id']=='support_closed')
        bad = {**c, 'id':'conflict', 'value':'APROBADO'}
        self.assertEqual(resolve(claims+[bad], conf['authority_catalog'],'Support','lifecycle','Support')['status'],'UNRESOLVED')
        bad['authority']='planning'
        self.assertEqual(resolve(claims+[bad], conf['authority_catalog'],'Support','lifecycle','Support')['value'],'CERRADO')

    def test_tampered_bytes_rejected(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(ROOT, Path(tmp)/'trader')
            (Path(tmp)/'trader/support_close.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'HASH_MISMATCH'):
                TraderSourceAdapter(Path(tmp)/'trader').load()

    def test_local_blocker_does_not_block_independent_scope(self):
        actions=[dict(scope='independent',authorized=True,preconditions_met=True)]
        blockers=[dict(affected_scopes=['audit'],type='OPERATIONAL')]
        self.assertEqual(next_action('independent',actions,blockers,[])['status'],'DERIVABLE')
        self.assertEqual(next_action('audit',actions,blockers,[])['status'],'BLOCKED')

    def test_deferred_placement_preserved_until_trigger(self):
        decisions=self.r['open_decisions']
        self.assertEqual(decisions[0]['placement'],'UNRESOLVED_PLACEMENT')
        self.assertEqual(next_action('control-plane-fixture',[],[],decisions)['status'],'NONE')
        reached=[{**decisions[0],'review_trigger_reached':True}]
        self.assertEqual(next_action('product-placement',[],[],reached)['status'],'PO_DECISION_REQUIRED')

    def test_projection_role_isolation_and_minimum_context(self):
        task=dict(task_id=str(uuid4()),required_claims=['resistance_audit'],requirements=['preserve'],work='inspect',relevant_scopes=[],objective='bounded',review_target={'result':'proposal'},permitted_destinations=['DEVELOPMENT'],implementation_specification={'bounded':True})
        contexts=[project(self.r,task,role,str(uuid4())) for role in ('ADVISOR','DEVELOPMENT','CODE_EXECUTOR')]
        self.assertIn('review_target',contexts[0]['inputs'])
        self.assertNotIn('review_target',contexts[1]['inputs'])
        self.assertNotIn('implementation_specification',contexts[0]['inputs'])
        self.assertEqual(set(contexts[0]['inputs']['claims']),{'resistance_audit'})
        self.assertNotIn('support_close',contexts[0]['source_digests'])
        self.assertEqual(len({digest(c['authority']) for c in contexts}),3)

    def test_unresolved_claim_blocks_projection(self):
        self.r['resolved']['resistance_audit']['status']='UNRESOLVED'
        with self.assertRaisesRegex(ValueError,'UNRESOLVED_DEPENDENCY'):
            project(self.r,dict(required_claims=['resistance_audit']),'ADVISOR',str(uuid4()))
