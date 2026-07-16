# Governed Decision Memory Foundation

## Purpose

Sensei's Operational Journal remains the sole durable authority for trading,
governance, risk and learning facts. Decision Memory is a deterministic,
read-only projection that gives each desk role relevant prior context without
creating a second mutable memory database.

This foundation does not yet inject memory into live Desk cycles. That
integration must record a `MemoryContextPackAssembled` event and bind its ID to
the consuming cycle before memory can influence an agent judgment.

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

## Required follow-up

1. Pass the coordinator's already cycle-bound packs into each concrete role
   adapter and include their audit IDs in the Desk cycle manifest.
2. Add bounded context sizing and retrieval-quality evaluation datasets.
3. Measure calibration, false vetoes and trade-frequency collapse against a
   no-memory baseline.
4. Add contradiction/staleness lifecycle for derived interpretations.
5. Add PostgreSQL migrations, concurrency tests, backup/restore and encryption
   for remote deployment.
