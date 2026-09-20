# TDT Control Plane — Hito A

Minimal Python standard-library transport: ExecutionContext -> CodeExecutorAdapter
-> CodexCodeExecutor -> authenticated `codex exec` -> validated ExecutionResult.
The bounded task adds two integers. No domain resolver or authority transition exists.

Run tests with Python 3.10+: `python -m unittest discover -s tests -v`.

Run the real proof from this repository:

```text
python -m tdt_control_plane --codex PATH_TO_EXISTING_CODEX --cost-attestation PATH_TO_FRESH_ATTESTATION --output PATH_TO_NEW_EVIDENCE
```

The cost attestation is an externally verified, non-secret snapshot of current
included usage (checked_at Unix seconds, ordinary_usage_allowed, remaining_primary,
remaining_weekly, credit_balance, paid_fallback_allowed). It expires after ten minutes.
It is not a billing API or a guarantee about future quota. The runner requires positive
included quota, zero paid credit balance, no paid fallback and ChatGPT login.
Do not fabricate this snapshot. Refresh it from the existing account usage capability.

The CLI runs with user configuration ignored, read-only sandbox, ephemeral session,
strict output schema and stdin context. No auth file is read by this package. Raw CLI
logs and errors are never persisted; only validated results and allowlisted evidence
are returned. Temporary result files are removed automatically. There are no retries,
new services, credentials in the repository, or changes to Trader.

Adapter handles are synchronous and process-local. Restart recovery, ingest,
idempotency, scheduling and B–F are deliberately outside Hito A. Real execution
requires the existing authenticated desktop user's environment, network access,
and installed CLI. The offline sandbox account alone cannot resolve that user's home.

Hito A evidence is a derived, non-authoritative observation, pending Advisor review.
