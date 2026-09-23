import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from tdt_control_plane.ledger import Ledger
from tdt_control_plane.runtime import CodexRoleExecutor
from test_ledger import context, result


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.l=Ledger(self.root/'ledger.db')
        self.c=context()
        self.cost=dict(checked_at=time.time(),ordinary_usage_allowed=True,remaining_primary=50,remaining_weekly=50,credit_balance=0,paid_fallback_allowed=False)
        self.runtime=CodexRoleExecutor('codex',self.l,self.root/'spool',self.cost)

    def tearDown(self):
        self.l.close()
        self.tmp.cleanup()

    def run_fake(self,args,**kw):
        if args[1:]==['login','status']:
            return subprocess.CompletedProcess(args,0,'Logged in using ChatGPT','')
        self.assertIn('features.shell_tool=false',args)
        self.assertIn('--ignore-user-config',args)
        self.assertIn('read-only',args)
        self.assertNotEqual(Path(kw['cwd']),self.root)
        Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(result(self.c)),encoding='utf-8')
        events=[{'type':'thread.started','thread_id':str(uuid4())},{'type':'turn.completed'}]
        return subprocess.CompletedProcess(args,0,'\n'.join(json.dumps(e) for e in events),'')

    @patch.dict('os.environ',{},clear=True)
    def test_lost_response_recovered_without_second_execution(self):
        with patch('subprocess.run',side_effect=self.run_fake) as runner:
            first=self.runtime.submit(self.c)
            second=self.runtime.submit(self.c)
        self.assertEqual(first,second)
        self.assertEqual(runner.call_count,2) # auth + one execution
        self.assertEqual(self.l.recover(self.c['execution_id'])['attempts'],1)

    @patch.dict('os.environ',{},clear=True)
    def test_cost_exhaustion_isolated_without_launch(self):
        self.cost['remaining_weekly']=0
        with patch('subprocess.run') as runner, self.assertRaisesRegex(ValueError,'COST_GUARD'):
            self.runtime.submit(self.c)
        runner.assert_not_called()

    @patch.dict('os.environ',{},clear=True)
    def test_tool_call_invalidates_result(self):
        def run(args,**kw):
            p=self.run_fake(args,**kw)
            if 'exec' in args:
                p.stdout+='\n'+json.dumps({'type':'item.completed','item':{'type':'command_execution'}})
            return p
        with patch('subprocess.run',side_effect=run),self.assertRaises(ValueError):
            self.runtime.submit(self.c)
        self.assertIsNone(self.runtime.recover(self.c))

    @patch.dict('os.environ',{},clear=True)
    def test_executor_failure_preserves_identity_without_domain_failure(self):
        def run(args,**kw):
            if 'exec' in args:
                return subprocess.CompletedProcess(args,1,'','synthetic error')
            return self.run_fake(args,**kw)
        with patch('subprocess.run',side_effect=run),self.assertRaises(ValueError):
            self.runtime.submit(self.c)
        row=self.l.recover(self.c['execution_id'])
        self.assertEqual(row['status'],'ISOLATED')
        self.assertIsNone(row['result'])
