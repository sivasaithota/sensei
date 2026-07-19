# Governed Decision Memory Foundation

## Purpose

Sensei's Operational Journal remains the sole durable authority for trading,
governance, risk and learning facts. Decision Memory is a deterministic,
read-only projection that gives each desk role relevant prior context without
creating a second mutable memory database.

The live Desk prepares one role-scoped context pack for all nine roles, passes
the exact pack into each role adapter, binds pack and audit IDs to the durable
cycle start, and records one evaluation-only invocation fact for every completed
or skipped role. Completed-cycle replay reuses that evidence and never invokes
the roles or rebuilds memory.

Advisory judgment consumes the bounded context explicitly: the Analyst receives
it in `AnalystBrief` and cites the highest-priority prior summaries in its
narrative; the Committee receives the same role-scoped prior context in its
regime/sign-off input. Canonical and safety roles (Historian, Reporter, Crowd
Reader, Trader and Secretary) validate and materialize their packs but do not
allow remembered interpretations to override current market, risk, governance,
broker or journal truth. The Coach continues to learn from those journal facts
through `OutcomeLearner` rather than treating retrieved prose as policy.

## Public boundary

`DecisionMemoryService.query(MemoryQuery)` reconstructs knowledge available to
one of the nine roles at `as_of`. An event is eligible only when both its
business occurrence and durable recording are no later than `as_of`; this
prevents a backdated reflection from leaking into a historical replay.

`DecisionMemoryService.build_context_pack(MemoryQuery)` produces a deterministic,
content-addressed `MemoryContextPack`. Its identity covers the query, projected
items, provenance and explicit non-authority flags.

`ContextPackAuditTrail.record(...)` may append an idempotent audit fact. It does
not grant the memory service a strategy, risk, lifecycle, committee or broker
mutation method.

`DeskMemoryCoordinator.prepare_cycle_contexts(...)` creates and audits exactly
one role-scoped pack for every Desk role. Consumer identity includes the cycle
and role, so repeated preparation is idempotent while two cycles may consume
the same deterministic pack independently.

`MemoryBudget` caps both item count and canonical encoded bytes. Selection keeps
counter-evidence-first ordering; an oversized item is omitted rather than
truncated into an unauditable summary.

## Memory classes

- `episode`: decisions, intents, orders and protection facts;
- `outcome`: fills, costs, reconciliation and episode closure;
- `counter_evidence`: halts, skipped roles, quarantines and safety failures;
- `knowledge`: provenance-backed source artifacts and claims;
- `learning`: observations, hypotheses and research results;
- `governance`: immutable plans, dossiers, lifecycle and preregistered policy;
- `risk`: reservations, releases, Committee facts and safety controls;
- `market_context`: point-in-time data, health and drift observations;
- `operations`: explicitly allowlisted scheduler and supervisor facts.

Unknown event types fail closed. Adding a future event to memory requires an
explicit classification and role-access decision.

## Retrieval rules

1. Verify the journal before every projection.
2. Filter by exact structured scope before ranking: instrument, plan version,
   lineage, regime and timeframe.
3. Rank abstentions and negative outcomes before positive and neutral examples.
4. Include the source journal event itself and every referenced evidence event.
5. Enforce per-role allowlists. In particular, the Trader cannot retrieve
   research/learning memory.
6. Preserve immutable facts as canonical JSON; summaries are deterministic and
   never LLM-authored.

## Authority and integration

Memory is advisory context. It cannot:

- change a Strategy Plan or risk limit;
- promote a strategy;
- approve a Trade Thesis or create a Trade Intent;
- call a broker gateway;
- convert a Coach reflection into production policy.

The Coach may use memory to propose a research-only hypothesis. Adoption still
requires the Research Backtest Lab, preregistered evidence and the existing
Strategy Lifecycle.

## Deployment path

The projection consumes ordered `JournalEvent` records rather than owning a
separate memory truth. A deployed system may initially use the existing SQLite
journal with backup/restore. A future PostgreSQL event source must preserve
global order, immutable event identity, occurrence time, recording time and
integrity verification before it can implement the same boundary. MCP, RAG,
Hermes or Obsidian may be adapters or interfaces; none becomes an authority.

Graph-derived retrieval follows the same rule. `DerivedMemoryIndex` is a narrow
candidate-ID seam and `ShadowRetrievalComparator` is evaluation-only. A future
Graphiti adapter may implement that seam, but unknown or role-invisible IDs are
rejected and no index result enters a live context pack directly.

Probabilistic interpretations use `DerivedMemoryRegistry` and the states
`candidate`, `corroborated`, `contradicted`, `stale`, and `retired`. Every
interpretation and transition requires immutable journal evidence and retains
`RESEARCH_ONLY` authority.

## Required follow-up

1. Populate representative production retrieval datasets; the versioned runner
   and explicit no-memory/structured-memory baselines are implemented.
2. Connect the counterfactual producer to the future deterministic Market Twin;
   it already scans eligible invocations but cannot invent replay P&L.
3. Accumulate champion/challenger and future Graphiti shadow evidence until
   calibration, false-veto, latency, cost and trade-frequency gates pass.
4. Add PostgreSQL migrations, concurrency tests, backup/restore and encryption
   for remote deployment.
