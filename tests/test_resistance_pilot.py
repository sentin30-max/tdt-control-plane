import copy
import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from tdt_control_plane.contracts import digest
from tdt_control_plane.ledger import Ledger
from tdt_control_plane.resistance_candidate import expected_candidate, validate_candidate
from tdt_control_plane.resistance_pilot import applicable, route
from tdt_control_plane.resistance_sources import REVISION, sha, verify_export
from tdt_control_plane.roles import make_context

ROOT=Path(__file__).resolve().parents[1]


class ResistancePilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources=json.loads((ROOT/'evidence/slice002/source-documents.json').read_text(encoding='utf-8'))

    def test_candidate_preserves_real_claims_surfaces_and_only_authorized_request_changes(self):
        from tdt_control_plane.resistance_candidate import REQUEST_UPDATES
        artifact=expected_candidate(self.sources)
        original=json.loads(self.sources['texts']['historical_request'])
        for key,value in original.items():
            if key not in REQUEST_UPDATES:self.assertEqual(artifact['request'][key],value)
        self.assertEqual(artifact['request']['claims'],['C'+str(i) for i in range(1,15)])
        self.assertEqual(artifact['request']['permitted_stages'],['A4'])
        old=self.sources['texts']['historical_input']
        preserved=lambda s:s.split('MANDATORY ATTACK SURFACES:')[1].split('OUTPUT AUTHORITY:')[0]
        self.assertEqual(preserved(artifact['input_text']),preserved(old))
        self.assertNotIn('refutation_valid boolean',artifact['input_text'])
        self.assertTrue(validate_candidate(artifact,self.sources))

    def test_candidate_rejects_silent_reduction_provider_budget_and_authority_changes(self):
        for field,value in [('claims',['C1']),('provider','paid'),('max_output_tokens_per_stage',10),('permitted_stages',['A4','A5'])]:
            candidate=expected_candidate(self.sources)
            candidate['request'][field]=value
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'CANDIDATE_CONTRACT_MISMATCH'):
                validate_candidate(candidate,self.sources)
        candidate=expected_candidate(self.sources);candidate['input_text']=candidate['input_text'][:100]
        with self.assertRaises(ValueError):validate_candidate(candidate,self.sources)

    def test_routes_follow_need_not_coverage(self):
        ready={'specification_gap':None,'candidate':None,'verification':None}
        self.assertEqual(applicable(ready),{'ADVISOR','CODE_EXECUTOR'})
        needs_design={**ready,'specification_gap':'Missing material requirement'}
        self.assertEqual(applicable(needs_design),{'ADVISOR','DEVELOPMENT'})
        self.assertNotIn('COMPLETE',applicable({**ready,'candidate':{'id':'new'}}))
        self.assertIn('COMPLETE',applicable({**ready,'candidate':{'id':'new'},'verification':{'local_validation':'PASS','preflight':'PASS'}}))

    def test_unresolved_and_preflight_blockers_cannot_redispatch_or_complete(self):
        for code in ['UNRESOLVED_CONTRADICTION','UNRESOLVED_NORMATIVE_AMBIGUITY','PREFLIGHT_FAILED']:
            state={'blocker':{'code':code},'candidate':{'id':'new'}}
            self.assertEqual(applicable(state),{'ADVISOR','PO_REQUIRED'})
            for target in ['CODE_EXECUTOR','DEVELOPMENT','COMPLETE']:
                with self.subTest(code=code,target=target),self.assertRaises(ValueError):
                    route({'role':'ADVISOR','next_destination':target,'outcome':'SUCCEEDED'},state)

    def test_executor_and_failed_advisor_cannot_authorize_completion(self):
        state={'candidate':{'id':'new'},'verification':{'local_validation':'PASS','preflight':'PASS'}}
        for role,outcome in [('CODE_EXECUTOR','SUCCEEDED'),('ADVISOR','REFUTED'),('ADVISOR','BLOCKED')]:
            with self.assertRaises(ValueError):
                route({'role':role,'outcome':outcome,'next_destination':'COMPLETE'},state)

    def test_export_change_or_escape_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'source').write_bytes(b'original')
            manifest={'revision':REVISION,'files':{'source':sha(b'original')}}
            self.assertTrue(verify_export(root,manifest))
            (root/'source').write_bytes(b'changed')
            with self.assertRaises(ValueError):verify_export(root,manifest)
            manifest['files']={'../outside':'0'*64}
            with self.assertRaises(ValueError):verify_export(root,manifest)

    def test_real_source_bound_result_duplicate_contradiction_and_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Ledger(Path(tmp)/'ledger.sqlite')
            sources=self.sources['hashes']
            def context():
                return make_context(str(uuid4()),str(uuid4()),digest({'revision':REVISION}),
                    'CODE_EXECUTOR','Slice002','Prepare only',{},sources,['Trader','TEF','Governance'])
            def result(c):
                r={k:c[k] for k in ['execution_id','task_id','context_id','input_revision','role']}
                r.update(context_digest=digest(c),outcome='SUCCEEDED',next_destination='NONE',
                         rationale='Preparation only',artifact='{}',findings=[],evidence_refs=['historical_request'],
                         proposals=[],effects=[],protected_scope_touched=[])
                return r
            c=context();r=result(c);ledger.register(c)
            self.assertEqual(ledger.ingest(c['execution_id'],json.dumps(r),c['input_revision'],sources),'ACCEPTED')
            self.assertEqual(ledger.ingest(c['execution_id'],json.dumps(r),c['input_revision'],sources),'DUPLICATE_NOOP')
            mutated=copy.deepcopy(r);mutated['artifact']='{"different":true}'
            self.assertEqual(ledger.ingest(c['execution_id'],json.dumps(mutated),c['input_revision'],sources),'EXECUTION_CONTRADICTION')
            self.assertEqual(ledger.recover(c['execution_id'])['result_digest'],digest(r))
            c=context();ledger.register(c)
            self.assertEqual(ledger.ingest(c['execution_id'],json.dumps(result(c)),c['input_revision'],{**sources,'historical_request':'0'*64}),'REQUIRES_REVALIDATION')
            self.assertEqual(ledger.recover(c['execution_id'])['status'],'ISOLATED')
            ledger.close()


if __name__=='__main__':unittest.main()
