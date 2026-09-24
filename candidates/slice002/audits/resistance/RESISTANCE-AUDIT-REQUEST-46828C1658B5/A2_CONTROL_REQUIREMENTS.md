# Resistance A2 — Control requirements

Evaluated baseline: `46828c1658b5328f65fd23ad2e350a19e54039ae`.

## Classification

- Sensitivity: **HIGH**.
- Breadth: **MEDIUM**.
- Uncertainty: **MEDIUM**.
- Reversibility exposure in this delivery: **LOW**.
- Audit intensity: **REINFORCED**.

The reinforced increment applies to causality, deterministic identity, immutable
history, no-look-ahead/no-repaint, replay, fact/derived-context separation and
reference lineage. It does not add product semantics or an arbitrary numeric test
threshold.

## Required controls

1. A3 must separately evaluate relevance, sufficiency, contradictions and limits
   for every frozen claim C1-C14. Missing evidence cannot yield conformity.
2. A3 separation is required, but additional/external independence is **not**
   required. TEF-03 assigns evidence evaluation to A3 and independence judgment to
   A4; this A2 does not elevate A3 beyond that floor.
3. A4 must execute a genuine falsification attempt with predeclared discriminating
   oracles, cognitive/procedural/traceable separation and **additional independent
   execution** because sensitivity is HIGH.
4. A4 must use the dedicated Resistance request and instance. Support inputs,
   results and conclusions are inadmissible as Resistance evidence.
5. Negative findings must be preserved verbatim. A3 cannot override A4, passing
   counts cannot compensate an adverse finding, and the producer cannot redefine
   an oracle after observing a result.
6. A5 is non-compensable: it may be composed only after A3 and A4 results exist.
   Any insufficient/defective/adverse required component prevents conformity.
7. Scope is the frozen evaluated baseline and published Resistance contracts.
   Auditors must not introduce Tendencias, order execution, persistence or other
   future semantics.

## Independence assignment

- A3 additional independence required: **NO**.
- A4 additional independence required: **YES**.
- Independent execution capacity: existing zero-cost Groq runner,
  `GROQ_FREE/openai/gpt-oss-120b`, with a Resistance-specific frozen request,
  distinct instance binding, separate A3/A4 calls, input hashes and preserved raw
  adverse output.
