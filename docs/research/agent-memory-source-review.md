# Agent-memory source review for Sensei

Date: 2026-07-16

## Bottom line

The sources contain useful design cues, but neither demonstrates that an autonomous memory loop can safely improve a live strategy. The transferable idea is a governed evidence pipeline: preserve immutable decision episodes, derive versioned hypotheses from them, test those hypotheses out of sample, and allow only the existing strategy lifecycle to change trading behavior. Memory should inform research and decisions; it must not silently rewrite production strategy or risk policy.

## What the sources actually show

### Video: self-improving trading agent with Hermes

Lewis Jackson's [video](https://www.youtube.com/watch?v=6njREUQAFdg) demonstrates a prompt-driven deployment around Hermes: organize a strategy, goals and a trade ledger; review outcomes periodically; form a hypothesis; change one variable at a time; and host the loop independently of a laptop. The demo also separates two agents' responsibilities, begins with a read-only review, and describes a manual switch before writes become active.

Those are sound workflow patterns, not validation of trading alpha. The video supplies no reproducible benchmark, point-in-time dataset, leakage analysis, transaction-cost model, statistical test, or evidence that a Hermes-generated change improved risk-adjusted live returns. Its own example discusses only 46 realized trades, while ambitious return goals are presented as configuration rather than justified constraints. Treat it as an orchestration demo.

Hermes itself is a general-purpose agent runtime. Its official repository describes persistent conversation search, agent-curated memories, self-modifying skills, scheduled jobs and remote deployment ([Nous Research, Hermes Agent](https://github.com/NousResearch/hermes-agent)). These capabilities may be useful around Sensei, but a general agent's mutable memories and skills are the wrong authority boundary for capital allocation. Hermes should not own order approval, risk limits, strategy promotion, or the canonical trade record.

### DEV article and TradeMemory

The [DEV article](https://dev.to/mnemox/why-your-ai-trading-agent-needs-a-memory-and-how-we-built-one-kjo) proposes three stages: raw trade records, reflected patterns, then strategy adjustments. Its strongest transferable features are contextual decision capture, queryable recall, scheduled reflection and explicit promotion between memory levels.

The article overstates the evidence when it says Reflexion and FinMem “proved” layered memory improves LLM trading performance. [Reflexion](https://arxiv.org/abs/2303.11366) reports improvement on sequential decision-making, coding and reasoning tasks, not live trading. [FinMem](https://arxiv.org/abs/2311.13743) evaluates a layered-memory trading agent on historical financial data; it supports further investigation, not production safety or generalizable alpha.

The implementation's own canonical [limitations document](https://github.com/mnemox-ai/tradememory-protocol/blob/master/LIMITATIONS.md) is more informative than the promotional article. It says the integrated four-tier gate failed its Phase 5 validation because the calibrated agent skipped 97% of trades; 0/100 experiments passed its deflated-Sharpe gate. It also reports single-tenant SQLite, no authentication/RBAC/rate limiting, no HA, a partly migrated second database stack, and several unvalidated thresholds. This is useful prior art to study, not a component to insert wholesale.

## Patterns worth adopting

1. **Immutable episodic memory.** Record the full decision episode, not merely fills: point-in-time inputs and provenance, plan/version, agent and model versions, retrieved memories, thesis, alternatives, committee votes, risk state, intended order, broker acknowledgements, fills, exits and later-labelled outcomes. Link it to Sensei's append-only operational journal rather than creating a competing truth.
2. **Separate facts from interpretations.** Market events, orders and outcomes are immutable facts. Reflections, regime labels and causal explanations are derived artifacts with producer/version, source episode IDs, confidence, creation time and expiry. A newer interpretation supersedes; it never edits history.
3. **Outcome-aware, counter-evidence-first recall.** Retrieve comparable episodes using structured filters (strategy, regime, instrument, timeframe, volatility, event risk) before semantic similarity. Return winners, losers, abstentions and rejected trades; expose sample size and uncertainty. Similarity alone creates confirmation loops.
4. **Memory lifecycle.** Use explicit states such as candidate, corroborated, contradicted, stale and retired. Promotion requires minimum independent observations, out-of-sample evidence and stability across regimes. Time decay should affect retrieval priority, not erase audit evidence.
5. **Reflection produces hypotheses, not policy.** The Coach may create a pre-registered experiment specifying one proposed change, mechanism, eligible population, baseline, metrics, costs, power/sample requirements and rejection criteria. The research/backtest lab evaluates it; governance promotes it. The LLM never patches live parameters directly.
6. **Read and write scopes by agent.** Agents share selected evidence through typed queries, not unrestricted shared scratch memory. The Trader reads approved plan/risk state and relevant episodes but cannot write semantic rules. The Coach writes reflections/hypotheses but cannot approve them. The Committee consumes evidence but cannot rewrite it.
7. **Portable service boundary.** For deployment away from the Mac, expose a versioned memory API over a durable database with migrations, backups, encryption, tenant/account boundaries and health/lag metrics. MCP can be an adapter for agent access; it is not the storage model or governance mechanism. The official [MCP specification](https://modelcontextprotocol.io/specification/2025-06-18) standardizes context exchange, not truth, authorization or trading safety.

## Failure modes to design against

- **Outcome leakage:** attaching later information to the memory available at decision time.
- **Selection bias:** remembering executed trades but not rejected signals, missed trades or data failures.
- **Narrative causality:** an LLM inventing a persuasive cause from a small, dependent sample.
- **Regime mixing:** recalling superficially similar setups from materially different volatility/liquidity/event regimes.
- **Feedback resonance:** a generated reflection influences later decisions, whose outcomes then appear to validate that same reflection.
- **Metric gaming:** “improvement” achieved by rarely trading, as TradeMemory's adverse validation illustrates.
- **Unsafe mutation:** a reflection, retrieved document or prompt injection changing live strategy/risk behavior.
- **Distributed inconsistency:** multiple agents or deployed replicas reading different versions or writing duplicate episodes.

## Implication for Sensei

The next memory milestone should be a **governed decision-memory foundation**, not RAG over books and not adoption of Hermes/TradeMemory. Start with a canonical decision-episode schema, point-in-time provenance, idempotent ingestion from existing journal events, typed retrieval with negative examples, and an offline evaluation harness that measures recall quality and decision impact. Then connect the Coach only to hypothesis creation and the research lab. External knowledge ingestion can follow as a separately sourced corpus whose claims expire and can never outrank market facts, approved strategy plans or risk policy.

Suggested acceptance tests:

- Reconstruct exactly what every agent knew at any historical decision time.
- Replays cannot see later outcomes or revised documents.
- Rejected, missed and no-trade decisions are queryable alongside trades.
- Every retrieved memory includes provenance, temporal validity and strategy/model version.
- Reflection cannot mutate an approved plan or risk limit.
- A proposed learning is adopted only through the existing experiment and lifecycle evidence gates.
- Backup/restore and concurrent idempotent writes work on the target deployment platform.
- Offline evaluation detects whether memory improves calibrated decisions rather than merely reducing trade frequency.

## Source assessment

- [Video](https://www.youtube.com/watch?v=6njREUQAFdg): useful workflow inspiration; promotional demonstration, not empirical evidence.
- [DEV article](https://dev.to/mnemox/why-your-ai-trading-agent-needs-a-memory-and-how-we-built-one-kjo): useful conceptual summary; claims should be checked against repository state and papers.
- [TradeMemory repository](https://github.com/mnemox-ai/tradememory-protocol) and [limitations](https://github.com/mnemox-ai/tradememory-protocol/blob/master/LIMITATIONS.md): valuable implementation ideas and unusually candid adverse results; currently unsuitable as Sensei's production memory substrate without substantial hardening.
- [FinMem paper](https://arxiv.org/abs/2311.13743): relevant research precedent for layered financial memory; historical experimental evidence only.
- [Reflexion paper](https://arxiv.org/abs/2303.11366): relevant precedent for storing verbal feedback; not evidence of trading profitability.
- [Hermes Agent repository](https://github.com/NousResearch/hermes-agent): useful general-agent runtime patterns; not a governed trading-memory or risk system.
