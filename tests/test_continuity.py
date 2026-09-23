import json
import tempfile
import unittest
from pathlib import Path

from tdt_control_plane.continuity import run, authorize_destination, expected_artifact
from tdt_control_plane.contracts import digest
from tdt_control_plane.ledger import Ledger
from tdt_control_plane.resolution import load_fixture
from test_ledger import result

ROOT=Path(__file__).resolve().parents[1]
QUALITY={'evaluations':[{'role':'ADVISOR','passed':True},{'role':'DEVELOPMENT','passed':True}], 'semantic_review':{'passed':True}}


class ScriptedRuntime:
    def __init__(self,ledger,resolution,destinations):
        self.ledger=ledger
        self.resolution=resolution
        self.destinations=iter(destinations)
        self.roles=[]

    def submit(self,c):
        self.ledger.register(c)
        self.ledger.claim(c['execution_id'])
        self.roles.append(c['role'])
        r=result(c)
        r['evidence_refs']=list(c['source_digests'])
        if c['role']=='ADVISOR':
            r['next_destination']=next(self.destinations)
            r['artifact']='{}'
        elif c['role']=='CODE_EXECUTOR':
            r['artifact']=json.dumps(expected_artifact(self.resolution,c['inputs']['work']['current_operation']))
        else:
            r['artifact']=json.dumps(dict(requirements=['preserve'],steps=['compute'],acceptance=['exact match'],prohibitions=['protected writes'],open_questions=[]))
        return {'context':c,'result':r,'result_digest':digest(r),'authoritative':False}


class ContinuityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.ledger=Ledger(self.root/'ledger.db')
        self.resolution=load_fixture(ROOT/'fixtures/trader')

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def execute(self,destinations):
        runtime=ScriptedRuntime(self.ledger,self.resolution,destinations)
        proof=run(runtime,self.resolution,QUALITY,self.root/'proof.json','test')
        return runtime,proof

    def test_consecutive_code_destinations_and_advisor_first(self):
        runtime,proof=self.execute(['CODE_EXECUTOR','CODE_EXECUTOR','COMPLETE'])
        self.assertEqual(runtime.roles,['ADVISOR','CODE_EXECUTOR','ADVISOR','CODE_EXECUTOR','ADVISOR'])
        self.assertEqual(proof['executions_verified'],2)

    def test_dynamic_development_and_repeat_advisor(self):
        runtime,proof=self.execute(['DEVELOPMENT','ADVISOR','CODE_EXECUTOR','CODE_EXECUTOR','COMPLETE'])
        self.assertEqual(runtime.roles[:4],['ADVISOR','DEVELOPMENT','ADVISOR','ADVISOR'])
        self.assertEqual(proof['status'],'PASS')

    def test_premature_complete_stops(self):
        with self.assertRaisesRegex(ValueError,'PREMATURE_COMPLETION'):
            self.execute(['COMPLETE'])

    def test_missing_quality_gate(self):
        runtime=ScriptedRuntime(self.ledger,self.resolution,[])
        with self.assertRaisesRegex(ValueError,'ROLE_QUALITY_NOT_VALIDATED'):
            run(runtime,self.resolution,{'evaluations':[]},self.root/'proof.json','test')
        self.assertEqual(runtime.roles,[])

    def test_authority_guards_and_real_po(self):
        with self.assertRaisesRegex(ValueError,'EXECUTION_PRECONDITIONS'):
            authorize_destination('CODE_EXECUTOR',specification_ready=False,completed=False)
        with self.assertRaisesRegex(ValueError,'UNJUSTIFIED_PO'):
            authorize_destination('PO_REQUIRED',specification_ready=True,completed=False)
        self.assertEqual(authorize_destination('PO_REQUIRED',specification_ready=False,completed=False,decision_required=True),'PO_REQUIRED')

    def test_infinite_advisor_loop_is_bounded(self):
        with self.assertRaisesRegex(ValueError,'DISPATCH_BUDGET_EXHAUSTED'):
            self.execute(['ADVISOR']*10)

    def test_source_change_stops_before_dispatch(self):
        runtime=ScriptedRuntime(self.ledger,self.resolution,[])
        with self.assertRaisesRegex(ValueError,'SOURCE_CHANGED'):
            run(runtime,self.resolution,QUALITY,self.root/'proof.json','test',refresh=lambda:{'revision':digest('changed')})
        self.assertEqual(runtime.roles,[])

    def test_terminal_review_has_no_phantom_operation(self):
        runtime,proof=self.execute(['CODE_EXECUTOR','CODE_EXECUTOR','COMPLETE'])
        work=proof['records'][-1]['context']['inputs']['work']
        self.assertIsNone(work['current_operation'])
        self.assertEqual(work['completed_operation_count'],2)
        self.assertEqual(work['contract']['operation_indices'],[0,1])
        verified=[r for r in work['verification_history'] if r['independent_verification']]
        self.assertEqual(len(verified),2)

    def test_refuted_review_cannot_dispatch_code(self):
        runtime=ScriptedRuntime(self.ledger,self.resolution,['CODE_EXECUTOR'])
        submit=runtime.submit
        def refuted(c):
            record=submit(c)
            record['result']['outcome']='REFUTED'
            record['result_digest']=digest(record['result'])
            return record
        runtime.submit=refuted
        with self.assertRaisesRegex(ValueError,'UNRESOLVED_REVIEW_FINDINGS'):
            run(runtime,self.resolution,QUALITY,self.root/'proof.json','test')
