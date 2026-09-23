import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from tdt_control_plane.contracts import digest
from tdt_control_plane.roles import make_context
from tdt_control_plane.ledger import Ledger


def context(role="DEVELOPMENT"):
    return make_context(str(uuid4()), str(uuid4()), digest("revision"), role, "fixture", "bounded task", {}, {"source": digest("source")}, ["Trader", "TEF", "Governance"])


def result(c):
    return {**{k: c[k] for k in ("execution_id", "task_id", "context_id", "input_revision", "role")},
            "context_digest": digest(c), "outcome": "SUCCEEDED", "next_destination": "CODE_EXECUTOR" if c["role"] == "ADVISOR" else "NONE",
            "rationale": "Source supports bounded task", "artifact": "bounded specification",
            "findings": [], "evidence_refs": ["source"], "proposals": [], "effects": [], "protected_scope_touched": []}


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "ledger.db")
        self.l = Ledger(self.path)
        self.c = context()
        self.eid = self.c["execution_id"]
        self.l.register(self.c)
        self.r = result(self.c)

    def tearDown(self):
        self.l.close()
        self.tmp.cleanup()

    def ingest(self, r=None, revision=None, sources=None):
        return self.l.ingest(self.eid, json.dumps(r or self.r), revision or self.c["input_revision"], self.c["source_digests"] if sources is None else sources)

    def test_duplicate_callback_and_restart_recovery(self):
        self.assertEqual(self.ingest(), "ACCEPTED")
        self.l.close()
        self.l = Ledger(self.path)
        self.assertEqual(self.ingest(), "DUPLICATE_NOOP")
        self.assertEqual(self.l.recover(self.eid)["result_digest"], digest(self.r))

    def test_conflicting_result_isolates_and_preserves_original(self):
        self.ingest()
        self.assertEqual(self.ingest({**self.r, "artifact": "different"}), "EXECUTION_CONTRADICTION")
        self.assertEqual(self.l.recover(self.eid)["result"], self.r)
        self.assertEqual(self.l.recover(self.eid)["status"], "ISOLATED")

    def test_correlation_authority_and_malformed(self):
        for key, value in [("task_id", str(uuid4())), ("context_digest", digest("bad")), ("effects", ["approve"]), ("protected_scope_touched", ["Trader"]), ("next_destination", "COMPLETE"), ("evidence_refs", ["invented"]), ("extra", True), ("findings", "wrong")]:
            with self.subTest(key=key):
                self.assertEqual(self.ingest({**self.r, key: value}), "REJECTED_INVALID")
        self.assertIsNone(self.l.recover(self.eid)["result"])

    def test_duplicate_json_key_rejected(self):
        raw = json.dumps(self.r)[:-1] + ',"role":"DEVELOPMENT"}'
        self.assertEqual(self.l.ingest(self.eid, raw, self.c["input_revision"], self.c["source_digests"]), "REJECTED_INVALID")

    def test_stale_unrelated_change_still_applicable(self):
        self.assertEqual(self.ingest(revision=digest("new")), "STILL_APPLICABLE")

    def test_stale_material_change_isolated(self):
        self.assertEqual(self.ingest(sources={"source": digest("changed")}), "REQUIRES_REVALIDATION")
        self.assertEqual(self.l.recover(self.eid)["status"], "ISOLATED")

    def test_retry_keeps_identity_and_budget(self):
        self.l.claim(self.eid)
        self.l.fail(self.eid, "TRANSPORT_FAILURE", definitely_not_executed=True)
        self.l.claim(self.eid)
        self.l.fail(self.eid, "TRANSPORT_FAILURE", definitely_not_executed=True)
        with self.assertRaises(ValueError):
            self.l.claim(self.eid)
        self.assertEqual(self.l.recover(self.eid)["attempts"], 2)

    def test_uncertain_execution_cannot_blind_retry(self):
        self.l.claim(self.eid)
        with self.assertRaises(ValueError):
            self.l.claim(self.eid)

    def test_read_only_regeneration_same_identity_once(self):
        self.l.claim(self.eid)
        self.l.fail(self.eid,'INVALID_RESULT')
        self.l.regenerate_read_only_result(self.eid)
        self.l.claim(self.eid)
        self.l.fail(self.eid,'INVALID_RESULT')
        with self.assertRaisesRegex(ValueError,'REGENERATION_NOT_SAFE'):
            self.l.regenerate_read_only_result(self.eid)
        self.assertEqual(self.l.recover(self.eid)['attempts'],2)

    def test_running_timeout_and_tool_violation_cannot_regenerate(self):
        self.l.claim(self.eid)
        with self.assertRaises(ValueError):self.l.regenerate_read_only_result(self.eid)
        self.l.fail(self.eid,'TIMEOUT')
        with self.assertRaises(ValueError):self.l.regenerate_read_only_result(self.eid)
        self.l.fail(self.eid,'DEPENDENCY_FAILURE')
        with self.assertRaises(ValueError):self.l.regenerate_read_only_result(self.eid)
        self.l.fail(self.eid, "TIMEOUT")
        with self.assertRaises(ValueError):
            self.l.claim(self.eid)

    def test_identity_cannot_be_rebound(self):
        other = context()
        other["execution_id"] = self.eid
        with self.assertRaises(ValueError):
            self.l.register(other)

    def test_concurrent_callbacks_apply_once(self):
        def callback(_):
            ledger = Ledger(self.path)
            try:
                return ledger.ingest(self.eid, json.dumps(self.r), self.c["input_revision"], self.c["source_digests"])
            finally:
                ledger.close()
        with ThreadPoolExecutor(max_workers=4) as pool:
            answers = list(pool.map(callback, range(8)))
        self.assertEqual(answers.count("ACCEPTED"), 1)
        self.assertEqual(answers.count("DUPLICATE_NOOP"), 7)


if __name__ == "__main__":
    unittest.main()
