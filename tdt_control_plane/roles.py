"""Strict role contracts. Results are observations/proposals, never authority."""
import json
from uuid import UUID

from .contracts import digest

ROLES = {"ADVISOR", "DEVELOPMENT", "CODE_EXECUTOR"}
DESTINATIONS = ROLES | {"PO_REQUIRED", "COMPLETE"}
POLICIES = {
    "ADVISOR": {"can_do": ["review", "refute", "classify", "propose_destination"], "tools": []},
    "DEVELOPMENT": {"can_do": ["design", "specify"], "tools": []},
    "CODE_EXECUTOR": {"can_do": ["bounded_computation"], "tools": []},
}
PROHIBITIONS = ["product_decision", "self_approval", "mutate_authority", "modify_protected", "spend"]


def strict_json(raw):
    def pairs(items):
        value = {}
        for k, v in items:
            if k in value:
                raise ValueError("DUPLICATE_KEY")
            value[k] = v
        return value
    def invalid(_):
        raise ValueError("NON_FINITE")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def identity(value):
    if type(value) is not str or str(UUID(value)) != value:
        raise ValueError("IDENTITY")


def hash_value(value):
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("DIGEST")


def validate_context(c):
    fields = {"schema_version", "execution_id", "task_id", "context_id", "input_revision", "role", "scope", "authority", "protected", "objective", "inputs", "source_digests", "done_when", "after_completion", "authoritative"}
    if type(c) is not dict or set(c) != fields or c["schema_version"] != 1 or type(c["schema_version"]) is not int or c["authoritative"] is not False:
        raise ValueError("CONTEXT_SCHEMA")
    for k in ("execution_id", "task_id"):
        identity(c[k])
    for k in ("context_id", "input_revision"):
        hash_value(c[k])
    if c["role"] not in ROLES or c["authority"] != {**POLICIES[c["role"]], "cannot_do": PROHIBITIONS}:
        raise ValueError("ROLE_AUTHORITY")
    if any(type(c[k]) is not str or not c[k] for k in ("scope", "objective", "after_completion")):
        raise ValueError("CONTEXT_TEXT")
    if type(c["inputs"]) is not dict or type(c["source_digests"]) is not dict:
        raise ValueError("CONTEXT_INPUTS")
    for v in c["source_digests"].values():
        hash_value(v)
    for k in ("protected", "done_when"):
        if type(c[k]) is not list or not c[k] or any(type(x) is not str for x in c[k]):
            raise ValueError("CONTEXT_LIST")
    body = {k: v for k, v in c.items() if k not in {"context_id", "execution_id"}}
    if digest(body) != c["context_id"]:
        raise ValueError("CONTEXT_DIGEST")
    return c


def make_context(execution_id, task_id, revision, role, scope, objective, inputs, sources, protected):
    c = dict(schema_version=1, execution_id=execution_id, task_id=task_id,
             input_revision=revision, role=role, scope=scope,
             authority={**POLICIES[role], "cannot_do": PROHIBITIONS}, protected=protected,
             objective=objective, inputs=inputs, source_digests=sources,
             done_when=["Return evidenced structured result within role authority"],
             after_completion="CONTROL_PLANE_VERIFY_THEN_ADVISOR_REVIEW", authoritative=False)
    c["context_id"] = digest({k: v for k, v in c.items() if k != "execution_id"})
    return validate_context(c)


RESULT_SCHEMA = {"type": "object", "additionalProperties": False, "properties": {
    **{k: {"type": "string"} for k in ("execution_id", "task_id", "context_id", "input_revision", "context_digest", "rationale", "artifact")},
    "role": {"type": "string", "enum": sorted(ROLES)},
    "outcome": {"type": "string", "enum": ["SUCCEEDED", "BLOCKED", "REFUTED"]},
    "next_destination": {"type": "string", "enum": sorted(DESTINATIONS | {"NONE"})},
    **{k: {"type": "array", "items": {"type": "string"}} for k in ("findings", "evidence_refs", "proposals", "effects", "protected_scope_touched")},
}}
RESULT_SCHEMA["required"] = list(RESULT_SCHEMA["properties"])


def validate_result(r, c):
    if type(r) is not dict or set(r) != set(RESULT_SCHEMA["required"]):
        raise ValueError("RESULT_SCHEMA")
    for k, schema in RESULT_SCHEMA["properties"].items():
        if schema["type"] == "array":
            if type(r[k]) is not list or any(type(x) is not str for x in r[k]):
                raise ValueError("RESULT_TYPE")
        elif type(r[k]) is not str:
            raise ValueError("RESULT_TYPE")
        if "enum" in schema and r[k] not in schema["enum"]:
            raise ValueError("RESULT_ENUM")
    for k in ("execution_id", "task_id", "context_id", "input_revision", "role"):
        if r[k] != c[k]:
            raise ValueError("CORRELATION")
    if r["context_digest"] != digest(c):
        raise ValueError("CORRELATION")
    if r["effects"] or r["protected_scope_touched"]:
        raise ValueError("UNAUTHORIZED_EFFECT")
    if c["role"] != "ADVISOR" and r["next_destination"] != "NONE":
        raise ValueError("ROLE_AUTHORITY")
    if c["role"] == "ADVISOR" and r["next_destination"] == "NONE":
        raise ValueError("DESTINATION_REQUIRED")
    if not r["rationale"] or not r["evidence_refs"] or not set(r["evidence_refs"]) <= set(c["source_digests"]):
        raise ValueError("EVIDENCE")
    return r
