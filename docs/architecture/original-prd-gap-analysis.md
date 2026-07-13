# Original PRD Gap Analysis

Status: accepted historical baseline with amendments, reviewed 2026-07-13. The
implemented foundation and its current limits are documented in
`trading-platform-foundations.md`.

The July 2026 PRD correctly describes the desired product: a deliberate trading organization that researches, debates, executes, and learns. The current repository is a useful P0/P1 paper prototype, but it compresses several independent responsibilities into mutable JSON workflows. This document distinguishes what should be preserved from what must be deepened before live trading.

## Preserve

- Constrained `RuleSpec` data compiled by deterministic code; agents do not emit executable Python.
- Structured Trade Theses and an ordered veto chain.
- Hard risk rails outside agent control.
- Paper trading, post-mortems, owner reporting, and a kill control.
- The PRD learning sequence: source or outcome → hypothesis → historical examination → paper evidence → limited-capital evidence → adoption or rejection.

## Current implementation versus PRD

| Capability | Current state | Required depth |
|---|---|---|
| Historian | Daily Yahoo data, current Nifty constituents, per-symbol 70/30 split, pooled thresholds | Point-in-time universes, corporate actions and delistings, validated snapshots, common chronological folds, locked holdout, uncertainty, regime and portfolio evidence |
| Literature learning | Text/stdin truncated to 30,000 characters, free-text source, immediate rule persistence | Immutable artifacts, citations, claim lineage, faithful Strategy Plans, registered hypotheses, bounded retrieval |
| Experiment governance | Rule name is identity; dated Playbooks can overwrite; backtest passage writes `current.json` | Content-addressed hypotheses, snapshots, protocols and dossiers; immutable registry; separate staged promotion and rollback |
| Learning from trades | One LLM post-mortem can append a global prompt rule | Complete Trade Episodes; observations; recurrence and counterfactual analysis; a new hypothesis that must pass the same examination path |
| Agent hierarchy | Fixed Python calls; several LLM verdicts | Agents propose, challenge, summarize and explain; deterministic modules own evidence gates, risk, promotion and execution authority |
| Execution | Paper workflow plus an unused broker adapter | Durable order lifecycle, idempotency, partial fills, broker reconciliation, protection invariant, safe halt/resume |
| Persistence | Mutable JSON and JSONL files | Transactional/event records as authority; vector and note views are rebuildable projections |
| Intraday | Not implemented; current semantics are daily swing/CNC | Separate session-aware data, research, risk and execution specification after swing is dependable |

## Amendments to the original PRD

1. Safety and compliance are constraints, not optimization targets. Learning velocity may be maximized only inside simulation, paper, and explicitly capped canary budgets.
2. Agent plurality is not control independence. Agents using correlated models and evidence cannot authorize risk or bypass deterministic gates.
3. The Orchestrator may vary research tactics but may not rewrite its own authority, validation protocol, promotion thresholds, risk rails, or capital limits.
4. Backtest passage means at most “eligible for shadow.” It never means active Playbook adoption.
5. A trade outcome creates an Observation, not a global mistake rule. Only validated Mistake Hypotheses can alter a guard or Strategy Plan.
6. Remove the target of at least one strategy change per month; it rewards churn and repeated testing. Track evidence quality, false discoveries, calibration, live-versus-simulated drift, and rollback instead.
7. A vector index is a retrieval projection, never the authoritative Playbook, Mistake Ledger, approval record, or trade record.
8. A kill action must protect known fills first, then cancel only broker-confirmed working entry remainders. Blindly cancelling every order can create naked positions, while inventing cancellation for an order never confirmed by the broker creates false operational truth.
9. Swing and intraday are distinct products. Build and validate swing first; do not stretch daily-bar semantics into intraday trading.
10. Lifecycle stage `paper` makes a plan eligible for a trial but does not approve a trade. Every governed paper intent needs the exact unanimous L1 risk, L2 challenge, L3 compliance, and L4 orchestration verdict chain bound to its Trade Thesis.

## Build order

1. Research Examiner and immutable experiment identity.
2. Point-in-time Market Data Snapshots and quality gates.
3. Source-faithful Strategy Plans and research/live conformance tests.
4. Strategy Lifecycle with shadow, paper, canary, active, quarantine, retirement, and rollback.
5. Trade Episodes and validated outcome-learning.
6. Provenance Corpus and evaluated retrieval; add vector search only when metadata/full-text retrieval is insufficient.
7. Broker-sourced portfolio risk and capital reservations.
8. Durable trading kernel, reconciliation, protection invariant, and operational controls before micro-live.
9. Intraday as a separate research and execution track.

RAG, Obsidian, and Hermes are excluded from the implemented foundation. They are
not required for governed research or paper admission and cannot substitute for
the immutable Provenance Corpus, precise citations, deterministic evidence gates,
or the per-trade committee. Any future retrieval or note-taking integration must
remain a rebuildable research projection with no trading authority.
