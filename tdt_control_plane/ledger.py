"""Transactional local ledger; accepted results do not mutate source authority."""
import json
import sqlite3

from .contracts import digest
from .roles import strict_json, validate_context, validate_result


class Ledger:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS executions (
          id TEXT PRIMARY KEY, context TEXT NOT NULL, status TEXT NOT NULL,
          attempts INTEGER NOT NULL DEFAULT 0, result TEXT, digest TEXT, classification TEXT);
        CREATE TABLE IF NOT EXISTS events (
          seq INTEGER PRIMARY KEY, execution_id TEXT, kind TEXT, detail TEXT);
        ''')

    def close(self):
        self.db.close()

    def _event(self, eid, kind, detail=""):
        self.db.execute("INSERT INTO events(execution_id,kind,detail) VALUES(?,?,?)", (eid, kind, detail))

    def register(self, context):
        validate_context(context)
        raw = json.dumps(context, sort_keys=True)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT context FROM executions WHERE id=?", (context["execution_id"],)).fetchone()
            if row and row[0] != raw:
                raise ValueError("EXECUTION_ID_REBOUND")
            if not row:
                self.db.execute("INSERT INTO executions(id,context,status) VALUES(?,?,'REGISTERED')", (context["execution_id"], raw))
                self._event(context["execution_id"], "REGISTERED", digest(context))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def recover(self, eid):
        row = self.db.execute("SELECT context,status,attempts,result,digest,classification FROM executions WHERE id=?", (eid,)).fetchone()
        if not row:
            raise ValueError("UNKNOWN_EXECUTION")
        return dict(context=json.loads(row[0]), status=row[1], attempts=row[2], result=json.loads(row[3]) if row[3] else None, result_digest=row[4], classification=row[5])

    def claim(self, eid):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.recover(eid)
            # RUNNING after a crash is uncertain: recover output; never blindly execute twice.
            if row["status"] not in {"REGISTERED", "RETRYABLE"} or row["attempts"] >= 2:
                raise ValueError("RECOVER_BEFORE_RETRY")
            self.db.execute("UPDATE executions SET status='RUNNING', attempts=attempts+1 WHERE id=?", (eid,))
            self._event(eid, "DISPATCHED")
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def fail(self, eid, code, definitely_not_executed=False):
        allowed = {"COST_GUARD", "AUTH_UNAVAILABLE", "TRANSPORT_FAILURE", "EXECUTOR_FAILURE", "INVALID_RESULT", "TIMEOUT", "DEPENDENCY_FAILURE"}
        if code not in allowed:
            raise ValueError("FAILURE_CODE")
        row = self.recover(eid)
        if row["result"] is not None:
            raise ValueError("RESULT_ALREADY_RECEIVED")
        status = "RETRYABLE" if definitely_not_executed and row["attempts"] < 2 else "ISOLATED"
        with self.db:
            self.db.execute("UPDATE executions SET status=?,classification=? WHERE id=?", (status, code, eid))
            self._event(eid, code)

    def ingest(self, eid, raw, current_revision, current_sources):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.recover(eid)
            try:
                result = validate_result(strict_json(raw), row["context"])
            except (ValueError, TypeError, KeyError):
                self._event(eid, "REJECTED_INVALID")
                self.db.execute("COMMIT")
                return "REJECTED_INVALID"
            result_digest = digest(result)
            if row["result_digest"]:
                verdict = "DUPLICATE_NOOP" if row["result_digest"] == result_digest else "EXECUTION_CONTRADICTION"
                if verdict == "EXECUTION_CONTRADICTION":
                    self.db.execute("UPDATE executions SET status='ISOLATED',classification=? WHERE id=?", (verdict, eid))
                self._event(eid, verdict, result_digest)
                self.db.execute("COMMIT")
                return verdict
            c = row["context"]
            changed = any(current_sources.get(k) != v for k, v in c["source_digests"].items())
            if changed:
                verdict = "REQUIRES_REVALIDATION"
            elif current_revision != c["input_revision"]:
                verdict = "STILL_APPLICABLE"
            else:
                verdict = "ACCEPTED"
            status = "ISOLATED" if changed else "INGESTED"
            self.db.execute("UPDATE executions SET status=?,result=?,digest=?,classification=? WHERE id=?", (status, json.dumps(result, sort_keys=True), result_digest, verdict, eid))
            self._event(eid, verdict, result_digest)
            self.db.execute("COMMIT")
            return verdict
        except Exception:
            self.db.execute("ROLLBACK")
            raise
