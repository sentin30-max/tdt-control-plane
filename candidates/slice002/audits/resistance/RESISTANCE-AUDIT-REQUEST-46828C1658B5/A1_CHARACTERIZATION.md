# Resistance A1 — Characterization

- Audit target: `Resistance`.
- Evaluated code baseline: `46828c1658b5328f65fd23ad2e350a19e54039ae`.
- Nature: deterministic domain substrate that derives immutable Resistance birth,
  episode and event history from authorized structural references and official
  closed Candle inputs. It also exposes recomputable geometry, separate derived
  context and a non-authoritative read composition.
- Exposure: public domain API consumed by later context/rule layers. It neither
  executes orders nor emits entries, exits, stops, targets, sizing or risk actions.
- Causality: reference causal availability and ascending closed-input semantic order
  constrain every constitutive decision. Late knowledge cannot backfill history.
- Identity: reference, Resistance, episode and event identities are deterministic
  functions of contractual material. Same-price references remain distinct when
  provenance differs.
- History: facts are immutable, append-only and totally ordered. Retries are
  idempotent; divergent futures cannot rewrite a shared prefix.
- Fact/context boundary: `ResistanceEvent` is the only fact-store payload.
  `ResistanceDerivedContext` is non-causal, non-constitutive, non-operational and
  cannot be cast or appended as a fact.
- Read boundary: `ResistanceSnapshot` composes canonical sources and projections;
  it is not a source of truth. Current geometry remains recomputable from exact
  price/scale plus an official closed Candle.
- Persistence: this delivery adds no productive persistence, database, broker,
  queue, scheduler or network dependency. The in-memory event store is a tested
  append-only boundary, not productive storage infrastructure.
- Reversibility/impact: audit documentation and lifecycle metadata are reversible;
  the evaluated code baseline is frozen and is not modified by this dossier.

## Sensitive property families and limits

| Family | Sensitive invariant | Evidence scope | Known limit |
|---|---|---|---|
| P01 | NO_LOOK_AHEAD | availability, birth, episode, reentry and prefix scenarios | scenario/subdomain evidence, not a universal proof over future consumers |
| P02 | NO_REPAINT | immutable facts and divergent-prefix tests | downstream consumers are outside this audit target |
| P03 | REPLAY_DETERMINISM | reducers, coordinator, store and replay evidence | fixed public contract and tested canonical inputs |
| P04 | IDEMPOTENCY | birth, inputs, events and break consumption | tested boundaries only |
| P05 | REFERENCE_INDEPENDENCE | isolated/joint multi-reference scenarios | authorized reference model only |
| P06 | EVENT_ORDER_TOTALITY | contractual five-level sort and chain ordering | Resistance facts only |
| P07 | IDENTITY_DETERMINISM | canonical identity material and replay | no claim beyond governed serializers/material |
| P08 | NO_BACKFILL | causal availability and late-reference scenarios | governed closed-input path |
| P09 | FACT_CONTEXT_SEPARATION | type, store, representation and snapshot boundaries | Resistance derived-context subtype only |
| P10 | EXACT_PRICE_SCALE_COHERENCE | identity, brackets and geometry | configured exact-price scale contexts |
| P11 | SINGLE_BIRTH_PER_REFERENCE_LINEAGE | BORN closure and retry | one governed lineage per stable reference |
| P12 | SINGLE_CONSUMPTION_PER_BREAK_CHAIN | supersession, pairing, retry | Resistance break/reentry chain |

Consumers must treat these as bounded claims to evaluate, not as globally proven
properties of unrelated modules.
