# Slice 002 — informe consolidado de STOP

**Resultado: PARTIAL. El segmento completo no está demostrado.**

El candidato fue preparado y validado. El preflight nativo calculó **5.604 + 1.600 + 800 = 8.004**, que no cumple el límite estricto **< 8.000**. Se preservaron candidato, evidencia y finding adverso sin compactar ni reintentar.

Ruta real: `ADVISOR → CODE_EXECUTOR → ADVISOR → CODE_EXECUTOR → ADVISOR → PO_REQUIRED`.

Recuperación en un proceso nuevo: mismos cinco resultados, todos duplicate/no-op, cero nuevos dispatches. Las pruebas de contradicción y stale utilizaron ledgers separados.

No se ejecutaron Groq/A4/A5 ni se modificó Trader, TEF, Governance o históricos. La preparación permanece inactiva en Control Plane. Development no fue necesario ni se forzó.

51 pruebas de Control Plane; 135 de tooling publicado, incluidas 35 del resolver. La calidad del Advisor observada es limitada a este segmento; el informe conserva las limitaciones de contexto declaradas por el rol.

## Campos del gate

| Campo | Resultado |
|---|---|
| SLICE_002_REAL_RESISTANCE_PILOT | PARTIAL |
| SEGMENT_COMPLETED | false |
| RESISTANCE_SOURCE_REVISION | af9f8a392f95363e86c5636aefa5c55494715f6c |
| EVALUATED_BASELINE | 46828c1658b5328f65fd23ad2e350a19e54039ae |
| RESISTANCE_FORMAL_LIFECYCLE | EN_AUDITORIA |
| RECOVERED_OPERATIONAL_POINT | A4_TWO_STAGE_PUBLICATION_COMPLETED; prepare new request/input; local validation and preflight only |
| A4_TWO_STAGE_PUBLICATION | VERIFIED |
| REQUEST_PREPARATION | BLOCKED |
| CANDIDATE_PREPARATION | PREPARED; LOCAL_VALIDATION_PASS; INACTIVE; PRESERVED |
| REQUEST_PATH | candidates/slice002/audits/resistance/RESISTANCE-AUDIT-REQUEST-46828C1658B5/A4_TWO_STAGE_REQUEST_V1.json |
| INPUT_PATH | candidates/slice002/audits/resistance/RESISTANCE-AUDIT-REQUEST-46828C1658B5/A4_TWO_STAGE_INPUT_V1.md |
| PERMITTED_STAGES | ["A4"] |
| A3 | SKIPPED |
| A5 | NOT_AUTHORIZED |
| LLM_EMITS_REFUTATION_VALID | NO |
| LLM_EMITS_REFUTATION_VALIDITY | NO |
| LLM_EMITS_GLOBAL_STATE | NO |
| LLM_FIELDS_CLAIM_BOUNDARY | Enforced by candidate input and published evidence-only schema; negative probes rejected all three fields. No actual auditor run occurred. |
| REFUTATION_VALIDITY_VERSION | 1 |
| A4_RESOLVER_VERSION | 1 |
| CLAIMS_PRESERVED | SI |
| ATTACK_SURFACES_PRESERVED | SI |
| EVIDENCE_SET_PRESERVED | SI |
| INDEPENDENCE_REQUIREMENT_PRESERVED | SI |
| LOCAL_VALIDATION | PASS |
| A4_TWO_STAGE_PREFLIGHT | FAIL |
| PREFLIGHT_BUDGET | {"estimated_prompt_tokens": 5604, "fits": false, "max_output_tokens": 1600, "prompt_bytes": 22414, "provider_tpm_limit": 8000, "requested_budget": 8004, "safety_margin_tokens": 800} |
| ADVISOR_FIRST | PASS |
| MATERIAL_RESULTS_RETURNED_TO_ADVISOR | PASS |
| DYNAMIC_ROUTING | PASS |
| ACTUAL_ROUTE | ["ADVISOR", "CODE_EXECUTOR", "ADVISOR", "CODE_EXECUTOR", "ADVISOR", "PO_REQUIRED"] |
| ROUTING_CLAIM_BOUNDARY | Observed state-based route to preparation, local preflight and STOP; Development route was not exercised. |
| PO_MANUAL_TRANSPORT_DURING_SEGMENT | NONE |
| RECOVERY | PASS |
| IDEMPOTENCY | PASS |
| PROTECTED_SURFACES_MODIFIED | NO |
| PROTECTION_EVIDENCE | All 238 pinned exported source files retain manifest hashes; actual source reads use git show. Candidate/support files are separate Control Plane copies. Original/corrective/V2/hybrid outputs were never reprocessed. |
| GROQ_EXECUTED | NO |
| A4_EXECUTED | NO |
| A5_EXECUTED | NO |
| PAID_CAPACITY_USED | NO |
| COST_POLICY | ZERO_COST_ONLY |
| COST_EVIDENCE | Four isolated Codex sessions used included ChatGPT capacity, tools disabled, no API-key overrides or paid fallback. One deterministic local CodeExecutor. Zero-credit guard enforced before each model dispatch. No Actions or hosting launched. |
| MATERIAL_BLOCKERS | ["Native preflight total 8004 is not strictly below 8000. No compaction, evidence reduction, budget reduction, re-dispatch or auditor call performed."] |
| UNRESOLVED_AUTHORITY_DEPENDENCIES | ["PO disposition needed for a subsequent bounded response to the preserved preflight failure. No constraint change has been selected or authorized."] |
| DEVELOPMENT_ROLE_COVERAGE | NOT_REQUIRED |
| DEVELOPMENT_ROUTE_DEMONSTRATED | false |
| CODE_EXECUTOR_ROLE_COVERAGE | DEMONSTRATED |
| ADVISOR_ROLE_QUALITY | BOUNDED_OBSERVED: reviewed real inputs/candidate, distinguished successful diagnostics from failed readiness, rejected completion and escalated the preserved preflight blocker. Not general human equivalence. |
| ADVISOR_CONTEXT_LIMITATION | Middle Advisor review received complete generated candidate. Final review received verification and candidate hashes, not full candidate contents; its explicit limitation is preserved in the result. |
| NEXT_ACTION | Advisor/PO review of preserved preflight STOP; any subsequent adjustment or Groq execution requires separate explicit authorization. |
| NEXT_DESTINATION | PO_REQUIRED |
| PRODUCT_OWNER_DECISION_REQUIRED | YES |
| TASK_ID | 42176b41-3abb-59a7-b28c-44a6ec3e8fc9 |
| CANDIDATE_DIGEST | e0111607b7167e7c0cad0d20388e2b1f08d587096cf9c6557b4d19378174adf6 |
| TESTS | {"control_plane": 51, "publication_tooling": 135, "resolver_subset": 35, "recovery": "PASS"} |
| SCOPE_LIMITATIONS | ["No real external audit", "No production readiness claim", "No Trader code modification", "No autonomous closure of Resistance", "No exactly-once external effects claim"] |
| SLICE_001 | Preserved and consumed as accepted bounded dependency; no reopening, merge or authority expansion. |
| HITO_A_COMMIT | 0962aa340bd6712f9b8d4720adecaaddb9a2dc35 |
| SLICE_001_COMMIT | 97950ef55a6a2cc5a54752d1ec54243de327a646 |
| authoritative | false |

## Identidades de ejecución

| Rol / backend | Execution ID | Result digest |
|---|---|---|
| ADVISOR / CodexRoleExecutor | 2142e6da-c067-55c8-8912-cff46e335f64 | b3330f9c42ba285b4511d3281c0e3ec35c073420cd88f4086c31d67959670e21 |
| CODE_EXECUTOR / CodexRoleExecutor | 96355d38-bc31-5eab-9a70-beda3f1e4e69 | 110e7ba80f9667fd7cfc0c2457866b03caba0542bd227ae79cdf3601854a9bed |
| ADVISOR / CodexRoleExecutor | 8b8c775c-8b7d-56bc-b31b-b91173b3edc1 | 1739579bb72f758237dd25be45663fa2272c2a9705166501e4858c7b36088ac8 |
| CODE_EXECUTOR / PublishedLocalValidationExecutor | e254b74e-dfe5-5663-9486-fff9cc5ced62 | 460459e9c4cfac8c2a248b3eacdd1d10eb982d70f0ca83f9bab246afdd306998 |
| ADVISOR / CodexRoleExecutor | be889d75-1dd5-50bb-8835-ebd70bea693f | ec8f610c528e127a7b91cb650a03a6b11b18910bcf6bcd3ff9fb1a8fbdefcf47 |

Cada contexto/digest, resultado y finding del Advisor está en `executions/`; `ledger-export.json` conserva ingest y eventos. `candidate.json` conserva hashes de todos los archivos. `local-verification.json` conserva el presupuesto nativo y los hashes de evidencia.

**Siguiente destino: PO_REQUIRED.** Corresponde revisar el STOP y autorizar, si procede, un nuevo tramo acotado. Este informe no selecciona una reducción de presupuesto, cambio de evidencia o proveedor, ni autoriza Groq.
