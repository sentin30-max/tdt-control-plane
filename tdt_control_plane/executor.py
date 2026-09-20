import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Protocol

from .contracts import ExecutionContext, ExecutionResult, WIRE_SCHEMA, digest, parse_wire


class CodeExecutorAdapter(Protocol):
    def submit(self, context: ExecutionContext) -> str: ...
    def status(self, execution: str) -> str: ...
    def result(self, execution: str) -> ExecutionResult: ...


class CodexCodeExecutor:
    """Synchronous Hito A adapter. Handles live only in the calling process."""

    def __init__(self, executable, workspace, cost_attestation):
        self.executable = str(Path(executable).resolve())
        self.workspace = Path(workspace).resolve()
        self.cost = cost_attestation
        self._results = {}

    def _run(self, args, **kwargs):
        return subprocess.run([self.executable, *args], cwd=self.workspace, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, **kwargs)

    def _guard(self):
        c = self.cost
        return (set(c) == {"checked_at", "ordinary_usage_allowed", "remaining_primary", "remaining_weekly", "credit_balance", "paid_fallback_allowed"}
                and type(c["checked_at"]) in (int, float) and 0 <= time.time() - c["checked_at"] < 600
                and c["ordinary_usage_allowed"] is True and c["paid_fallback_allowed"] is False
                and type(c["credit_balance"]) is int and c["credit_balance"] == 0
                and all(type(c[k]) in (int, float) and 0 < c[k] <= 100 for k in ("remaining_primary", "remaining_weekly"))
                and not any(os.environ.get(k) for k in ("CODEX_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "CODEX_ACCESS_TOKEN", "OPENAI_FEDERATION_RULE_ID")))

    def submit(self, context):
        if context.execution_id in self._results:
            raise ValueError("Execution already submitted; no implicit retry")
        failure = "COST_GUARD"
        try:
            if not self._guard():
                raise ValueError("guard")
            failure = "AUTH_UNAVAILABLE"
            auth = self._run(["login", "status"])
            if auth.returncode != 0 or "Logged in using ChatGPT" not in auth.stdout + auth.stderr:
                raise ValueError("auth")
            failure = "EXECUTION_FAILED"
            with tempfile.TemporaryDirectory(prefix="tdt-hito-a-") as tmp:
                schema = Path(tmp) / "schema.json"
                output = Path(tmp) / "result.json"
                schema.write_text(json.dumps(WIRE_SCHEMA), encoding="utf-8")
                document = context.document()
                prompt = ("You are the bounded Code Executor for a transport test. Do not use tools, read files, modify files, or call services. "
                          "Add the two context operands. Return only the required JSON, echoing context_id, execution_id, nonce and context_digest exactly. "
                          "Use status SUCCEEDED, executor CodexCodeExecutor, payload {sum: computed integer}, failure null.\n"
                          + json.dumps({"context": document, "context_digest": digest(document)}))
                process = self._run(["exec", "--ignore-user-config", "--ephemeral", "--sandbox", "read-only", "--json", "--output-schema", str(schema), "--output-last-message", str(output), "-"], input=prompt)
                if process.returncode != 0:
                    raise ValueError("process")
                failure = "INVALID_RESULT"
                events = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
                threads = [e["thread_id"] for e in events if e.get("type") == "thread.started"]
                completed = sum(e.get("type") == "turn.completed" for e in events)
                if len(threads) != 1 or completed != 1 or any(e.get("type") in ("error", "turn.failed") for e in events):
                    raise ValueError("lifecycle")
                if any(e.get("item", {}).get("type") not in (None, "agent_message", "reasoning") for e in events):
                    raise ValueError("unexpected tool")
                raw = output.read_text(encoding="utf-8")
                wire = parse_wire(raw, context)
                result = ExecutionResult(context.context_id, context.execution_id, digest(document), "SUCCEEDED", "CodexCodeExecutor", wire["payload"], {"thread_id": threads[0], "exit_code": 0, "wire_digest": digest(wire), "tool_calls": 0}, None)
        except subprocess.TimeoutExpired:
            result = self._failed(context, "TIMEOUT")
        except (ValueError, OSError, KeyError, TypeError):
            result = self._failed(context, failure)
        self._results[context.execution_id] = result
        return context.execution_id

    def _failed(self, context, code):
        return ExecutionResult(context.context_id, context.execution_id, digest(context.document()), "FAILED", "CodexCodeExecutor", None, {}, code)

    def status(self, execution):
        return self._results[execution].status

    def result(self, execution):
        return self._results[execution]
