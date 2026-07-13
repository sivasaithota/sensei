# Research Examiner Foundation

## Objective

Create the first governed research path from a versioned, source-derived hypothesis to immutable evidence. The module must make experiments reproducible and must be incapable of promoting a strategy, modifying the active Playbook, or reaching execution.

The public seam is:

```python
ResearchExaminer.examine(ExaminationRequest) -> EvidenceDossier
```

## Inputs

An `ExaminationRequest` contains:

- one immutable Hypothesis Version, including its source-backed `RuleSpec`;
- one immutable Market Data Snapshot identity and its captured frames;
- one versioned Examination Protocol with common chronological folds, costs, evidence thresholds, and minimum coverage.

Changing any hypothesis, rule, source-claim identity, data value, universe, as-of date, protocol field, or examiner version must change the experiment identity.

## Output

An `EvidenceDossier` contains:

- a deterministic content-addressed experiment identifier;
- hypothesis, snapshot, protocol, and examiner identities;
- data-quality findings;
- evidence for every chronological fold and the aggregate;
- warnings and explicit reasons;
- a recommendation limited to `REJECT`, `NEEDS_MORE_EVIDENCE`, or `ELIGIBLE_FOR_SHADOW`;
- a fixed `QUARANTINED` status.

There is deliberately no `adopted`, `active`, `promote`, order, broker, or capital field.

## Safety invariants

1. Examination never reads or writes `data/playbook/current.json`.
2. Examination never writes `data/studied_rules.json`, pending orders, paper state, or execution configuration.
3. Examination imports no paper or broker execution module.
4. Invalid or insufficient market data fails closed as `NEEDS_MORE_EVIDENCE` with reasons.
5. A strategy-name collision is reported and remains quarantined; identity is never inferred from a name alone.
6. The same request is idempotent. An existing experiment artifact may be reused only when its canonical content matches exactly.
7. A failed write must not leave a valid-looking partial dossier.
8. Holdout and promotion authority remain outside this foundation.

## Initial evidence policy

- All folds use fixed calendar boundaries shared by every symbol.
- Signals may use earlier bars for indicator warm-up, but entries must occur inside the fold. A position that cannot reach a genuine stop, target, or full time exit before the fold ends is censored rather than force-closed.
- Costs are fixed by the protocol and recorded in the dossier.
- Evidence is aggregated across symbols for this foundation; chronological portfolio construction, capacity, dependence-aware uncertainty, multiple-testing controls, and locked-holdout access are subsequent slices and are required before paper promotion.
- Passing the initial thresholds means only `ELIGIBLE_FOR_SHADOW`.

## Acceptance criteria

1. A valid synthetic request produces a quarantined dossier and a deterministic experiment ID.
2. Repeating the same request produces the same canonical dossier and, when evidence persistence is configured, one immutable artifact.
3. Changing hypothesis, snapshot, or protocol content changes the experiment ID.
4. Fold evidence uses common calendar dates and contains no entries from outside a fold.
5. Invalid OHLCV, bars after the as-of date, missing coverage, or too few trades cannot yield shadow eligibility.
6. Threshold failure yields `REJECT`; inadequate coverage yields `NEEDS_MORE_EVIDENCE`; only complete passing evidence yields `ELIGIBLE_FOR_SHADOW`.
7. Examination cannot mutate current Playbook or studied-rule files, even when evidence passes.
8. Focused tests, the complete test suite, and an independent standards/spec review pass.

## Out of scope for this slice

- Source ingestion, embeddings, RAG, Obsidian, or Hermes.
- Strategy promotion or lifecycle transitions.
- Portfolio simulation, parameter search, multiple-testing correction, or opening a locked holdout.
- Broker connectivity, paper orders, risk reservations, or live execution.
- Intraday data or strategies.
