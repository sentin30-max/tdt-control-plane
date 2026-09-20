import hashlib
import json
from dataclasses import asdict, dataclass
from uuid import UUID


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class ExecutionContext:
    context_id: str
    execution_id: str
    nonce: str
    operands: tuple[int, int]

    def __post_init__(self):
        for value in (self.context_id, self.execution_id, self.nonce):
            if not isinstance(value, str) or str(UUID(value)) != value:
                raise ValueError("Invalid identity")
        if type(self.operands) is not tuple or len(self.operands) != 2 or any(type(v) is not int or abs(v) > 1000 for v in self.operands):
            raise ValueError("Invalid bounded task")

    def document(self):
        return {**asdict(self), "operands": list(self.operands), "task": "add_integers", "authoritative": False}


WIRE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        **{k: {"type": "string"} for k in ("context_id", "execution_id", "nonce", "context_digest")},
        "status": {"type": "string", "enum": ["SUCCEEDED"]},
        "executor": {"type": "string", "enum": ["CodexCodeExecutor"]},
        "payload": {"type": "object", "properties": {"sum": {"type": "integer"}}, "required": ["sum"], "additionalProperties": False},
        "failure": {"type": "null"},
    },
    "required": ["context_id", "execution_id", "nonce", "context_digest", "status", "executor", "payload", "failure"],
}


def parse_wire(raw, context):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=unique)
    expected = {
        "context_id": context.context_id, "execution_id": context.execution_id,
        "nonce": context.nonce, "context_digest": digest(context.document()),
        "status": "SUCCEEDED", "executor": "CodexCodeExecutor",
        "payload": {"sum": sum(context.operands)}, "failure": None,
    }
    if type(value) is not dict or value != expected or type(value.get("payload", {}).get("sum")) is not int:
        raise ValueError("Invalid result or correlation")
    return value


@dataclass(frozen=True)
class ExecutionResult:
    context_id: str
    execution_id: str
    context_digest: str
    status: str
    executor: str
    payload: dict | None
    evidence: dict
    failure: str | None

    def __post_init__(self):
        for value in (self.context_id, self.execution_id):
            if str(UUID(value)) != value:
                raise ValueError("Invalid result identity")
        if self.executor != "CodexCodeExecutor" or self.status not in ("SUCCEEDED", "FAILED"):
            raise ValueError("Invalid result status/executor")
        if len(self.context_digest) != 64 or any(c not in "0123456789abcdef" for c in self.context_digest):
            raise ValueError("Invalid context digest")
        if self.status == "SUCCEEDED":
            if type(self.payload) is not dict or set(self.payload) != {"sum"} or type(self.payload["sum"]) is not int or self.failure is not None:
                raise ValueError("Invalid success")
            if set(self.evidence) != {"thread_id", "exit_code", "wire_digest", "tool_calls"} or str(UUID(self.evidence["thread_id"])) != self.evidence["thread_id"] or self.evidence["exit_code"] != 0 or self.evidence["tool_calls"] != 0:
                raise ValueError("Invalid execution evidence")
        elif self.payload is not None or self.failure not in {"AUTH_UNAVAILABLE", "COST_GUARD", "EXECUTION_FAILED", "TIMEOUT", "INVALID_RESULT"} or self.evidence:
            raise ValueError("Invalid failure")

    def document(self):
        return asdict(self)
