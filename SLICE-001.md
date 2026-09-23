# Continuity Slice 001: bounded local runtime

Hito A remains at `0962aa340bd6712f9b8d4720adecaaddb9a2dc35`. Its code,
tests and evidence are unchanged. The new modules add separate role contracts,
SQLite execution ledger, pinned read-only source adapter, fact-class resolver,
minimal context projection, scoped role evaluations and Advisor-first routing.

## Authority and scope

ROLE != CHAT. EXECUTOR != AUTHORITY. SHARED RUNTIME != SHARED RESPONSIBILITY.
Advisor reviews/refutes and proposes a destination. The Control Plane checks
preconditions before dispatch. Development specifies and cannot approve itself.
CodeExecutor performs only the fixture's bounded computations. All three role
tool policies are empty, with distinct permitted responsibilities; broader code
mutation capability is deliberately not granted by this fixture contract.

The fixture reads a pinned export from Trader commit
`af9f8a392f95363e86c5636aefa5c55494715f6c`. Original paths and byte hashes are in
`fixtures/trader/sources.json`. It is a historical acceptance fixture, not an
assertion of live global Trader state. The adapter has no Trader write interface.
Source hashes and the consumed manifest hash are verified on load. Generic
resolution uses fact class, subject, scope, authority and explicit supersession;
it never uses the newest timestamp as authority. Mapping rules are bounded,
versioned implementation configuration, not new product decisions.

The fixture preserves Sprint2's consumed historical status, Support closure,
D6 not reopened, Resistance EN_AUDITORIA, evaluated baseline distinct from HEAD,
and operational blocker distinct from a domain defect. Product placement remains
UNRESOLVED_PLACEMENT. No Trader audit is executed and no protected system changes.

## Running and recovery

Python 3.10+ standard library only. No installation, paid API, service, hosting,
CI runner or new subscription is required.

```
python -m unittest discover -s tests -v
python -m tdt_control_plane.validate_roles --codex EXISTING_CODEX --cost-attestation FRESH_SNAPSHOT --output evidence/role-quality.json
python -m tdt_control_plane.continuity --codex EXISTING_CODEX --cost-attestation FRESH_SNAPSHOT --quality evidence/role-quality.json --output evidence/continuity-e2e.json --workflow-id UNIQUE_AUTHORIZED_WORKFLOW
python -m tdt_control_plane.verify_run --proof evidence/continuity-e2e.json --output evidence/recovery.json
```

The cost snapshot has the same externally verified fields as Hito A: checked_at,
ordinary_usage_allowed, remaining_primary, remaining_weekly, credit_balance,
paid_fallback_allowed. It expires after ten minutes. Do not fabricate it. The
local desktop account usage capability supplies the observed snapshot. The
runtime requires ChatGPT authentication, positive included quota, zero paid
credits, no API-key override, and no paid fallback. Snapshot expiry or exhaustion
stops the path. Automatic quota refresh and unlimited included capacity are not
claimed. No reset credit is redeemed by this code.

Each role runs in an ephemeral, empty temporary directory with read-only sandbox,
ignored user configuration, shell/apps/JS tools disabled and web search disabled.
Any unexpected tool event invalidates the result. Raw CLI logs are not persisted;
failure details use allowlisted categories. The validated result spool and ledger
live under ignored `.runtime/`. Portable evidence is stored under `evidence/`.

Recover the same workflow ID after a known interruption. Existing results are
validated and ingested as duplicate no-ops; they are not executed again. A result
regeneration preserves the execution ID and is bounded to one retry for the
effect-free role contract. A RUNNING or timed-out execution without a durable
result is uncertain and remains isolated. No exactly-once external execution
guarantee is claimed. Effectful retries would require a different contract.

The workflow is deliberately limited to ten dispatches. Routing is driven by
Advisor proposals and checked preconditions, not alternating role names. The
two computation tasks form the fixture's bounded work list. Completion refers
only to that work list and does not approve product decisions or the final Slice.

## Validation limits

Advisor has ten real adversarial classification cases covering all five destinations,
refutation, contradiction, scope, authority, unnecessary escalation and injection.
Development has a real design/specification exercise checked against six preserved
requirements, concrete acceptance oracles and explicit no-self-approval behavior.
The semantic assessment is an implementation-side rubric review, not independent
human equivalence certification. These evaluations support the bounded fixture
only. General operational replacement of Advisor or Development is not established.

Stale inputs with unrelated changes remain applicable. Changed material source
digests require revalidation and are isolated; the implementation does not guess
that changed evidence is harmless. COR and contexts are derived, non-authoritative
and rebuildable. Results cannot write authoritative Trader state. Local blockers
do not imply project-wide blockers. Genuine triggered PO decisions produce a
review package without choosing the unresolved product alternative.

Final outcome and execution identities are in `evidence/implementation-report.json`.
Failed exploratory runs remain separate evidence and are not relabeled PASS.
