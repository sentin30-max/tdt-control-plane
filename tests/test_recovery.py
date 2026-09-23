import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tdt_control_plane.contracts import digest
from tdt_control_plane.ledger import Ledger
from tdt_control_plane.recovery import review_package, verify_recovery
from tdt_control_plane.resolution import load_fixture
from tdt_control_plane.runtime import CodexRoleExecutor, atomic_json
from test_ledger import context,result


class RecoveryTests(unittest.TestCase):
    def test_genuine_po_package_preserves_unresolved_no_effects(self):
        r=load_fixture(Path(__file__).resolve().parents[1]/'fixtures/trader')
        d=r['open_decisions'][0]
        with self.assertRaises(ValueError):review_package(r,d)
        p=review_package(r,{**d,'review_trigger_reached':True})
        self.assertEqual(p['unresolved'],'UNRESOLVED_PLACEMENT')
        self.assertFalse(p['authoritative'])
        self.assertEqual(p['effects_applied'],[])

    def test_restart_recovery_without_executor_and_stale_dependency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            c=context();r=result(c)
            record={'context':c,'context_digest':digest(c),'result':r,'result_digest':digest(r)}
            ledger=Ledger(root/'ledger.db');ledger.register(c);ledger.claim(c['execution_id'])
            atomic_json(root/(c['execution_id']+'.json'),record)
            ledger.close() # simulate lost response/process restart before ingest
            ledger=Ledger(root/'ledger.db')
            runtime=CodexRoleExecutor('codex',ledger,root,{})
            with patch('subprocess.run') as process:
                recovered=runtime.submit(c)
                self.assertEqual(ledger.ingest(c['execution_id'],json.dumps(recovered['result']),c['input_revision'],c['source_digests']),'ACCEPTED')
                report=verify_recovery(runtime,{'records':[record]},{'revision':c['input_revision'],'source_digests':c['source_digests']})
                self.assertEqual(report['new_external_executions'],0)
                process.assert_not_called()
            ledger.close()

    def test_recovery_rejects_corrupt_spool(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ledger=Ledger(root/'ledger.db');c=context();r=result(c)
            atomic_json(root/(c['execution_id']+'.json'),{'result':r,'context_digest':digest(c),'result_digest':digest('wrong')})
            runtime=CodexRoleExecutor('codex',ledger,root,{})
            with self.assertRaisesRegex(ValueError,'RECOVERY_HASH_MISMATCH'):runtime.recover(c)
            ledger.close()
