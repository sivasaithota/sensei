# Graphiti assessment for Sensei decision memory

Date: 2026-07-17

Reviewed revision: [`getzep/graphiti@5e2be0f`](https://github.com/getzep/graphiti/tree/5e2be0faf7038a5b40e700d757b2c337e96b3a05) (`graphiti-core` 0.29.0)

## Bottom line

Graphiti is strong prior art—and a plausible future **derived retrieval index**—but it should not replace Sensei's governed journal, point-in-time decision projection, context-pack audit trail, or evaluation ledger. Its temporal graph, episode provenance, typed ontology, and hybrid search could improve associative recall across strategies, regimes, instruments, events, theses, and outcomes. However, its mutable extracted edges do not by themselves preserve the exact “known at decision time” state required for trading audit and leakage-free replay.

Recommendation: do not add Graphiti to PR #11's critical path. First connect the existing deterministic memory foundation to the live Desk and measure retrieval quality. Then evaluate Graphiti behind a narrow, rebuildable `DerivedMemoryIndex` adapter in an offline shadow experiment. The journal remains canonical; Graphiti receives only journal-derived, allowlisted records and can supply candidates only. Sensei must reapply role, provenance, temporal, counter-evidence, and authority checks before a fact enters a context pack.

## What Graphiti provides

Graphiti models a temporal context graph with entities, relationship facts, and source episodes. Facts carry `valid_at`, `invalid_at`, and `expired_at`; entity edges retain episode UUIDs and a `reference_time`, while episodes contain source description, raw content, creation time, and document-valid time. This is a good fit for distinguishing source material from derived relationships and retaining lineage ([README](https://github.com/getzep/graphiti/blob/5e2be0faf7038a5b40e700d757b2c337e96b3a05/README.md), [edge model](https://github.com/getzep/graphiti/blob/5e2be0faf7038a5b40e700d757b2c337e96b3a05/graphiti_core/edges.py), [episode model](https://github.com/getzep/graphiti/blob/5e2be0faf7038a5b40e700d757b2c337e96b3a05/graphiti_core/nodes.py)).

Ingestion accepts message, text, JSON, and fact-triple episodes, supports caller-provided UUIDs and graph partitions (`group_id`), and can use prescribed Pydantic entity/edge types plus custom extraction instructions. It extracts, deduplicates, embeds, resolves contradictions, and incrementally updates the graph. The project explicitly recommends queued/background ingestion and sequentially awaiting episodes, because a single episode invokes several LLM and embedding operations ([`add_episode`](https://github.com/getzep/graphiti/blob/5e2be0faf7038a5b40e700d757b2c337e96b3a05/graphiti_core/graphiti.py), [README concurrency guidance](https://github.com/getzep/graphiti/blob/5e2be0faf7038a5b40e700d757b2c337e96b3a05/README.md#default-to-low-concurrency-llm-provider-429-rate-limit-errors)).

Retrieval combines vector similarity, BM25/full-text search, graph traversal/distance, and configurable reranking. Searches can be restricted by `group_ids`, node labels, edge types, edge UUIDs, custom properties, and date predicates over `valid_at`, `invalid_at`, `created_at`, and `expired_at` ([search API](https://github.com/getzep/graphiti/blob/5e2be0faf7038a5b40e700d757b2c337e96b3a05/graphiti_core/graphiti.py), [`SearchFilters`](https://github.com/getzep/graphiti/blob/5e2be0faf7038a5b40e700d757b2c337e96b3a05/graphiti_core/search/search_filters.py), [quickstart](https://github.com/getzep/graphiti/tree/5e2be0faf7038a5b40e700d757b2c337e96b3a05/examples/quickstart)). This is materially richer than vector-only RAG and could help find related losing, winning, rejected, or abstained episodes connected through shared regimes and evidence.

## The point-in-time limitation

Graphiti has useful temporal semantics, but Sensei needs stricter **bitemporal** semantics:

- `valid_at`/`invalid_at` describe when a fact was true in the represented world.
- `created_at`/`expired_at` describe graph processing and invalidation time.
- Later ingestion mutates existing edges: it may append another source episode and set `invalid_at` or `expired_at` on the prior edge ([edge resolution](https://github.com/getzep/graphiti/blob/5e2be0faf7038a5b40e700d757b2c337e96b3a05/graphiti_core/utils/maintenance/edge_operations.py), [edge save query](https://github.com/getzep/graphiti/blob/5e2be0faf7038a5b40e700d757b2c337e96b3a05/graphiti_core/models/edges/edge_db_queries.py)).

Consequently, filtering the current graph to `valid_at <= decision_time` is not sufficient to reconstruct what the agent actually knew then. A relationship created before a decision can later acquire a contradiction or invalidation that was unknown at decision time. Graphiti's current edge is not an immutable sequence of system-time versions, so a historical query can observe later graph processing unless Sensei independently gates every result by immutable journal knowledge time and source closure.

This is the decisive boundary: Graphiti can index “what relationships the extractor currently believes held at time T”; Sensei's journal answers “what evidence was recorded and available to this role at time T.” Only the latter may drive replay, governance, evaluation, or audit.

## Governance and safety fit

`group_id` is a useful partition/filter, not a substitute for Sensei's nine role-specific allowlists and authority model. The public core exposes add, delete, clear, and maintenance operations; the experimental MCP server exposes episode/entity management and graph maintenance. The official documentation does not present row-level role authorization, immutable decision-use receipts, or a mechanism equivalent to Sensei's audited context-pack identity ([MCP server README](https://github.com/getzep/graphiti/blob/5e2be0faf7038a5b40e700d757b2c337e96b3a05/mcp_server/README.md)). Therefore agents should never receive direct Graphiti credentials or MCP mutation tools.

LLM extraction introduces another trust boundary. Structured-output-capable models are recommended, and the README warns that weaker model support can cause invalid schemas and ingestion failures. Extracted entities, temporal dates, deduplication, summaries, and contradictions are probabilistic interpretations, not canonical trading facts ([installation guidance](https://github.com/getzep/graphiti/blob/5e2be0faf7038a5b40e700d757b2c337e96b3a05/README.md#installation)). Any extracted claim needs producer/model/prompt version, source episode IDs, confidence, lifecycle state, and a path back to immutable evidence. It must remain `CONTEXT_ONLY` and cannot change strategy stage, risk policy, capital allocation, or order authority.

## Deployment and operational cost

The self-hosted core supports Neo4j, FalkorDB, and Amazon Neptune plus OpenSearch for Neptune; Kuzu is deprecated. It requires Python 3.10+, a graph database, an embedding service, and normally an LLM service. Docker Compose examples and FastAPI/MCP services exist, but the project explicitly distinguishes self-managed Graphiti from managed Zep: with Graphiti, production performance, tooling, security, scaling, and operations are the adopter's responsibility ([backend matrix and Zep comparison](https://github.com/getzep/graphiti/blob/5e2be0faf7038a5b40e700d757b2c337e96b3a05/README.md)).

For Sensei this means operating an additional database, indices, credentials, migrations, backups/restores, monitoring, rate limits, model spend, reindex/rebuild jobs, and consistency lag between the journal and graph. The default service documentation is a runnable starting point, not a complete production runbook for authentication, encryption, tenant isolation, disaster recovery, or high availability ([server README](https://github.com/getzep/graphiti/blob/5e2be0faf7038a5b40e700d757b2c337e96b3a05/server/README.md)). The MCP v1.0.2 release also fixed a Cypher-injection vulnerability in earlier versions, reinforcing the need to pin versions, scan dependencies, and keep graph services private ([official release notice](https://github.com/getzep/graphiti/releases/tag/mcp-v1.0.2)).

Anonymous configuration telemetry is opt-out. It excludes graph content according to the project, but a trading deployment should set `GRAPHITI_TELEMETRY_ENABLED=false` and verify egress policy ([telemetry documentation](https://github.com/getzep/graphiti/blob/5e2be0faf7038a5b40e700d757b2c337e96b3a05/README.md#telemetry)).

Graphiti is licensed under Apache-2.0, permitting commercial use and modification subject to its notice and license conditions ([license](https://github.com/getzep/graphiti/blob/5e2be0faf7038a5b40e700d757b2c337e96b3a05/LICENSE), [package metadata](https://github.com/getzep/graphiti/blob/5e2be0faf7038a5b40e700d757b2c337e96b3a05/pyproject.toml)). Backend and model-provider licenses and terms must be assessed separately.

## Recommended experiment

Introduce Graphiti only after the existing live-memory integration, through this boundary:

1. Journal events and approved external-source records remain the immutable source of truth.
2. An idempotent projector writes allowlisted, redacted episodes with deterministic UUIDs into a dedicated Graphiti partition; checkpoints and hashes make lag and rebuilds observable.
3. Graphiti returns candidate source IDs and graph scores, never final context.
4. `DecisionMemoryService` rehydrates canonical journal facts, enforces `known_at`, role allowlists, evidence closure, lifecycle state, and counter-evidence-first ordering, then creates the content-addressed context pack.
5. The evaluation ledger compares the existing structured retrieval against structured-plus-Graphiti retrieval in shadow mode. Promotion requires better relevance and calibration without higher leakage, contradiction, false-approval, latency, or cost rates.

Acceptance tests should include backfilled and revised facts, later-known contradictions, duplicate and out-of-order ingestion, cross-role/cross-account isolation, graph loss and deterministic rebuild, stale-index fail-closed behavior, malicious document content, provider outage, and replay proving that no post-decision evidence entered a historical context pack.

## Decision

**Adopt the ideas; defer the dependency.** Graphiti is a credible candidate for a non-authoritative associative index once Sensei has a measured retrieval baseline. It is not a replacement for the PR #11 foundations, and integrating it now would add operational and probabilistic complexity before the live Desk consumes the deterministic memory already built.
