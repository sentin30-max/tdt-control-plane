TASK=A3_EVALUACION_EVIDENCIA_RESISTANCE
REQUEST_ID=RESISTANCE-AUDIT-REQUEST-46828C1658B5
INSTANCE_ID=RESISTANCE-A3-INSTANCE-46828C1658B5
EVALUATED_CODE_BASELINE=46828c1658b5328f65fd23ad2e350a19e54039ae
ADDITIONAL_INDEPENDENCE_REQUIRED=NO

CONTRACT:
Evaluate relevance, sufficiency, unresolved contradictions and stated coverage limits
for each claim. States: DEMOSTRADA, REFUTADA, CONTRADICHA, INSUFICIENTE,
SIN_EVIDENCIA, NO_EVALUABLE. Global SATISFACTORIA requires every claim DEMOSTRADA;
any REFUTADA/CONTRADICHA is DEFECTUOSA; otherwise missing sufficiency is
INSUFICIENTE. A3 does not decide A4 independence.

FROZEN CLAIMS:
C1 no look-ahead; C2 no repaint; C3 deterministic replay; C4 deterministic
identity; C5 reference independence; C6 total event order; C7 no backfill; C8
fact/derived-context separation; C9 exact price/scale; C10 single birth lineage;
C11 break/reentry single consumption; C12 snapshot non-authoritative; C13 reference
binding immutable; C14 AT-002 traceability covers RT-RES-001..095.

FROZEN EVIDENCE:
- AF-RESISTANCE-006 and AT-RESISTANCE-001 define the public/technical contract.
- AT-RESISTANCE-002 publishes 95 acceptance oracles and P01-P12.
- IMP-RESISTANCE-012-TRACEABILITY maps all 95 oracles to consumed test evidence and
  identifies bounded property-family scope.
- Consumed execution at the evaluated baseline: Resistance 149 PASS; global 638
  PASS; no missing AT-002 oracle.
- A1_CHARACTERIZATION.md states exposure and limits; A2_CONTROL_REQUIREMENTS.md
  states required audit intensity and independence.
- EVIDENCE_MANIFEST.json fixes artifact paths and SHA-256 values.

QUESTIONS:
For C1-C14, is the cited evidence pertinent and sufficient for its bounded claim?
Is any evidence internally contradictory? Does any claim exceed its stated scope?
Do not infer global proof from scenario coverage and do not treat test count alone
as proof.

BOUNDARY:
Do not redesign Resistance, rerun tests, add product semantics, reuse Support audit
conclusions, or turn absent unrelated evidence into an adverse market claim.

OUTPUT JSON:
{"stage":"A3","global_state":"SATISFACTORIA|DEFECTUOSA|INSUFICIENTE","claims":[{"id":"C1","state":"DEMOSTRADA|REFUTADA|CONTRADICHA|INSUFICIENTE|SIN_EVIDENCIA|NO_EVALUABLE","basis":"...","contradiction":"...|NONE","scope_limit":"..."}],"material_adverse_findings":[],"pending_evidence":[],"scope_respected":true}
