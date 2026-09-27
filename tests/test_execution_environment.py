import copy
import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from tdt_control_plane.budget_admission import material_fingerprint
from tdt_control_plane.continuity import expected_artifact,run
from tdt_control_plane.contracts import digest
from tdt_control_plane.execution_environment import POLICY,verify_workspace
from tdt_control_plane.ledger import Ledger
from tdt_control_plane.resolution import load_fixture
from tdt_control_plane.roles import make_context
from tdt_control_plane.runtime import CodexRoleExecutor

ROOT=Path(__file__).resolve().parents[1]
QUALITY={'evaluations':[{'role':'ADVISOR','passed':True},{'role':'DEVELOPMENT','passed':True}],
         'semantic_review':{'passed':True}}


class ExecutionEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.repo=self.base/'checkout';self.repo.mkdir()
        self.git('init','-b','main');self.git('config','user.email','fixture@example.invalid');self.git('config','user.name','Fixture')
        (self.repo/'tracked.txt').write_text('baseline\n',encoding='utf-8');self.git('add','tracked.txt');self.git('commit','-m','baseline')
        self.git('remote','add','origin','https://github.com/sentin30-max/tdt-control-plane.git')
        self.head=self.git('rev-parse','HEAD').stdout.strip()
        self.binding={'repository_identity':'sentin30-max/tdt-control-plane','required_commit':self.head,
                      'branch_hint':'main','workspace_policy':dict(POLICY)}
        self.ledger=Ledger(self.base/'ledger.db')

    def tearDown(self):self.ledger.close();self.tmp.cleanup()

    def git(self,*args):
        return subprocess.run(['git','-C',str(self.repo),*args],check=True,capture_output=True,text=True)

    def context(self,binding=None,execution_id=None):
        return make_context(execution_id or str(uuid4()),str(uuid4()),'a'*64,'DEVELOPMENT','environment-fixture',
            'Produce bounded output',{'state':'verified'},{'source':'b'*64},['Trader AI','TEF','Governance'],
            self.binding if binding is None else binding)

    def result(self,c):
        return {'execution_id':c['execution_id'],'task_id':c['task_id'],'context_id':c['context_id'],
            'input_revision':c['input_revision'],'context_digest':digest(c),'role':c['role'],'outcome':'SUCCEEDED',
            'next_destination':'NONE','rationale':'bounded fixture','artifact':'{}','findings':[],
            'evidence_refs':['source'],'proposals':[],'effects':[],'protected_scope_touched':[]}

    def cost(self):
        return {'checked_at':time.time(),'ordinary_usage_allowed':True,'remaining_primary':50,'remaining_weekly':50,
                'credit_balance':0,'paid_fallback_allowed':False}

    def fake_codex(self,c,cwds):
        def run_command(args,**kwargs):
            if args[1:]==['login','status']:return subprocess.CompletedProcess(args,0,'Logged in using ChatGPT','')
            cwds.append(Path(kwargs['cwd']).resolve())
            Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(self.result(c)),encoding='utf-8')
            events=[{'type':'thread.started','thread_id':str(uuid4())},{'type':'turn.completed'}]
            return subprocess.CompletedProcess(args,0,'\n'.join(json.dumps(e) for e in events),'')
        return run_command

    def test_01_binding_is_in_execution_context(self):
        self.assertEqual(self.context()['execution_environment'],self.binding)

    def test_02_binding_is_covered_by_context_digest(self):
        c=self.context();body={k:v for k,v in c.items() if k not in {'context_id','execution_id'}}
        self.assertEqual(c['context_id'],digest(body))

    def test_03_binding_is_persisted_and_recovered_by_ledger(self):
        c=self.context();self.ledger.register(c)
        self.assertEqual(self.ledger.recover(c['execution_id'])['context']['execution_environment'],self.binding)

    def test_04_correct_repository_commit_and_policy_allow_dispatch_in_exact_workspace(self):
        c=self.context();runtime=CodexRoleExecutor('codex',self.ledger,self.base/'spool',self.cost(),self.repo);cwds=[]
        proof=verify_workspace(self.binding,self.repo)
        with patch('tdt_control_plane.runtime.verify_workspace',return_value=proof) as verifier, \
             patch('tdt_control_plane.runtime.subprocess.run',side_effect=self.fake_codex(c,cwds)):
            record=runtime.submit(c)
        self.assertEqual(record['result']['outcome'],'SUCCEEDED');self.assertEqual(cwds,[self.repo.resolve()]);self.assertEqual(verifier.call_count,2)

    def test_05_wrong_repository_is_blocked(self):
        bad={**self.binding,'repository_identity':'sentin30-max/other'}
        with self.assertRaisesRegex(ValueError,'EXECUTION_ENVIRONMENT_MISMATCH'):verify_workspace(bad,self.repo)

    def test_06_wrong_commit_is_blocked(self):
        bad={**self.binding,'required_commit':'0'*40}
        with self.assertRaisesRegex(ValueError,'EXECUTION_ENVIRONMENT_MISMATCH'):verify_workspace(bad,self.repo)

    def test_07_workspace_incompatible_with_clean_policy_is_blocked(self):
        (self.repo/'untracked.txt').write_text('dirty',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'EXECUTION_ENVIRONMENT_MISMATCH'):verify_workspace(self.binding,self.repo)

    def test_08_executor_is_not_invoked_when_verification_fails(self):
        c=self.context({**self.binding,'required_commit':'0'*40});runtime=CodexRoleExecutor('codex',self.ledger,self.base/'spool',self.cost(),self.repo)
        with patch('tdt_control_plane.runtime.verify_workspace',side_effect=ValueError('EXECUTION_ENVIRONMENT_MISMATCH')), \
             patch('tdt_control_plane.runtime.subprocess.run') as executor, self.assertRaisesRegex(ValueError,'EXECUTION_ENVIRONMENT_MISMATCH'):
            runtime.submit(c)
        executor.assert_not_called();self.assertEqual(self.ledger.recover(c['execution_id'])['classification'],'DEPENDENCY_FAILURE')

    def test_09_branch_hint_does_not_replace_exact_commit(self):
        proof=verify_workspace({**self.binding,'branch_hint':'definitely-not-current'},self.repo)
        self.assertEqual(proof['required_commit'],self.head);self.assertEqual(proof['branch_hint'],'definitely-not-current')

    def test_10_material_binding_change_changes_context_and_reasoning_digests(self):
        c=self.context();changed=copy.deepcopy(c);changed['execution_environment']['required_commit']='0'*40
        changed['context_id']=digest({k:v for k,v in changed.items() if k not in {'context_id','execution_id'}})
        self.assertNotEqual(c['context_id'],changed['context_id']);self.assertNotEqual(material_fingerprint(c),material_fingerprint(changed))

    def test_11_recovery_preserves_binding_without_environment_rediscovery(self):
        c=self.context();self.ledger.register(c);first=self.ledger.recover(c['execution_id']);second=self.ledger.recover(c['execution_id'])
        self.assertEqual(first['context'],second['context']);self.assertEqual(second['context']['execution_environment'],self.binding)

    def test_12_advisor_routing_inherits_binding_without_mutation(self):
        resolution=load_fixture(ROOT/'fixtures/trader');submitted=[];destinations=iter(['CODE_EXECUTOR','CODE_EXECUTOR','COMPLETE'])
        outer=self
        class Runtime:
            ledger=outer.ledger
            def submit(self,c):
                self.ledger.register(c);self.ledger.claim(c['execution_id']);submitted.append(c)
                r=outer.result(c);r['evidence_refs']=list(c['source_digests'])
                if c['role']=='ADVISOR':r['next_destination']=next(destinations);r['artifact']='{}'
                elif c['role']=='CODE_EXECUTOR':r['artifact']=json.dumps(expected_artifact(resolution,c['inputs']['work']['current_operation']))
                return {'context':c,'result':r,'result_digest':digest(r),'authoritative':False}
        proof=run(Runtime(),resolution,QUALITY,self.base/'proof.json','environment-routing',execution_environment=self.binding)
        self.assertEqual(proof['status'],'PASS');self.assertTrue(all(c['execution_environment']==self.binding for c in submitted))

    def test_13_legacy_unbound_context_remains_valid_for_historical_recovery(self):
        c=make_context(str(uuid4()),str(uuid4()),'a'*64,'DEVELOPMENT','legacy','Recover historical result',{},
            {'source':'b'*64},['protected'])
        self.ledger.register(c);self.assertNotIn('execution_environment',self.ledger.recover(c['execution_id'])['context'])

    def test_14_zero_cost_guard_remains_effective_after_environment_verification(self):
        c=self.context();cost=self.cost();cost['remaining_weekly']=0
        runtime=CodexRoleExecutor('codex',self.ledger,self.base/'spool',cost,self.repo)
        proof=verify_workspace(self.binding,self.repo)
        with patch('tdt_control_plane.runtime.verify_workspace',return_value=proof), \
             patch('tdt_control_plane.runtime.subprocess.run') as executor, self.assertRaisesRegex(ValueError,'COST_GUARD'):
            runtime.submit(c)
        executor.assert_not_called()


if __name__=='__main__':unittest.main()
