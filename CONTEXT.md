# Sensei Domain Language

This glossary is the shared language for the trading system. Terms describe domain meaning, not a particular implementation.

## Research and knowledge

**Source Artifact** — An immutable copy or stable reference to material the system studies, such as a book excerpt, document, web page, or video transcript.

**Citation** — A locator into a Source Artifact, such as an edition and page range or a video time range, that supports a claim.

**Claim** — A provenance-backed statement extracted from one or more Source Artifacts. A Claim is not yet a trading rule.

**Provenance Corpus** — The durable, immutable store of source bytes, deterministic extraction manifests, precise citations, and content-addressed Claims. Its authority is research-only; RAG, Obsidian, and Hermes are not alternate authorities.

**Hypothesis Version** — An immutable, testable proposition derived from claims, trade observations, or human research. A revision creates a new version rather than changing prior evidence.

**Strategy Plan** — A source-faithful, executable description of entry, exit, timing, sizing, and applicability rules used consistently by research and trading simulations.

**Strategy Plan Version** — An immutable revision of a Strategy Plan whose identity covers every behavior that can change a decision. A display name is never its identity.

**Plan Decision Trace** — The deterministic, time-ordered decisions produced by applying one Strategy Plan Version to normalized observations. Research, shadow, paper, and live adapters consume the same trace.

**Decision Trace Attestation** — A producer-signed durable fact binding one exact Plan Decision Trace to the exact Market Data Snapshot used to create it. A matching trace ID without this attestation is not admission evidence.

**Market Data Snapshot** — An immutable, point-in-time view of a universe and its market data, including lineage and a data-quality report.

**Stable Instrument** — A listed security identified independently of its current ticker. Symbol changes do not create a new Stable Instrument; a genuinely different security does.

**Membership Interval** — An inclusive-start, exclusive-end period during which a Stable Instrument belongs to a named research universe. Historical membership is evaluated for each session, not inferred from current constituents.

**Entry Eligibility** — The session-level fact that a Strategy Plan may originate a new position in a Stable Instrument. Universe membership governs Entry Eligibility; later removal does not by itself force an existing position to exit.

**Data Lineage** — Immutable provenance connecting a Market Data Snapshot to its source catalog, retrieval date, adjustment policy, and content hashes for membership, price, and corporate-action artifacts.

**Manifest Trust Pin** — An independently configured content identity that authorizes one exact market-data manifest. An issuer name inside a manifest cannot create or change its own trust.

**Examination Protocol** — A versioned set of validation rules, costs, chronological folds, holdout policy, thresholds, and stress tests fixed before a Hypothesis Version is examined.

**Examination** — The deterministic evaluation of one Hypothesis Version against one Market Data Snapshot under one Examination Protocol.

**Research Campaign** — The declared family of related hypotheses, parameters, and experiments over which selection and multiple-testing risk is counted.

**Experiment Registration** — An immutable declaration, made before results are known, that pins a Research Campaign, Strategy Plan Version, data policy, and Examination Protocol.

**Locked Confirmation** — A one-use examination against data kept opaque during discovery. Beginning access permanently consumes the confirmation opportunity even if the examination crashes.

**Evidence Dossier** — The immutable result of an Examination. It records identity, evidence, uncertainty, warnings, and at most eligibility for a shadow trial; it cannot activate a strategy.

**Research Backtest Lab** — The coordinator that binds a Coach-produced Mistake Hypothesis to a researcher-supplied executable Hypothesis Version, preregisters the discovery experiment, runs the Research Examiner, and records a research-only verdict. It cannot synthesize rules from prose, edit the Playbook, promote lifecycle state, or authorize trades.

## Strategy governance

**Strategy Lifecycle** — The governed progression `proposed → examined → shadow → paper → canary → active`, with `quarantined`, `rejected`, `retired`, and `rolled_back` terminal or safety states.

**Promotion** — An explicit, audited lifecycle transition based on evidence and authority separate from the agents that proposed or examined the strategy.

**Stage Dossier** — Immutable evidence that one Strategy Plan Version satisfied the declared requirements of a lifecycle stage. A recommendation is not itself authorization to transition.

**Signal Playbook** — The versioned set of active Strategy Plans that may be cited by a Trade Thesis. Research candidates and rejected strategies are not part of the active Playbook.

**Shadow Trial** — Forward observation of a Strategy Plan without orders or simulated capital, used to check implementation and distribution drift.

**Paper Trial** — Forward simulation with realistic order and accounting behavior but no real capital.

**Canary Trial** — A tightly capped live-capital trial that follows successful shadow and paper evidence and can be rolled back automatically.

## Trading and learning

**Trade Thesis** — A structured proposal containing instrument, direction, entry, size, stop, target, horizon, executable invalidation, and cited evidence.

**Per-Trade Committee Approval** — The content-addressed, unanimous and ordered decision of L1 risk-officer, L2 devil's advocate, L3 compliance, and L4 orchestrator on one exact Trade Thesis and derived Trade Intent. Lifecycle eligibility never substitutes for it.

**Committee Verdict Evidence** — A producer-signed durable verdict from exactly one Committee seat. Four freely constructed verdict objects are not Per-Trade Committee Approval.

**Trade Intent** — A fully approved, immutable request to trade. It is not an order and carries no broker side effect by itself.

**Kernel Admission** — A signed paper-only capability binding one exact Trade Intent to its trace, lifecycle, health, provenance, Committee and verdict evidence. The Trading Kernel rejects an intent without it.

**Account Snapshot** — Immutable reconciled account truth whose content-derived identity covers cash, marked equity, high-water mark, P&L, positions, included reservations, reconciliation state, and capture time. A caller label cannot preserve identity after content changes. `AccountSnapshotAuthority` separately proves that the exact content came from the configured account adapter; identity alone is not authenticity.

**Trade Episode** — The complete immutable history from signal snapshot through thesis, approvals, orders, fills, protection, exit, attribution, and post-mortem.

**Operational Journal** — The append-only, ordered record of governance, risk, trading, episode, and operator facts from which rebuildable views are derived.

**Decision Memory** — A read-only, point-in-time projection over the Operational Journal that retrieves typed facts, counter-evidence and derived research for a specific agent role. It is not a second source of truth and has no trading, strategy or risk authority.

**Memory Context Pack** — A content-addressed record of the exact Decision Memory query and source event IDs made available to one agent as of one instant. Its authority is `CONTEXT_ONLY`; recording or retrieving it cannot approve a trade or mutate policy.

**Signed Fact** — A canonical domain fact authenticated by a producer credential and checked against independently configured trust. Journal durability and producer authenticity are separate properties and both may be required.

**Desk Cycle** — One durable Desk Head orchestration of Historian, Reporter, Crowd Reader, Analyst, Committee, Trader, Coach and Secretary. It records each role as completed or skipped but does not itself grant trading authority.

**Governed Desk Supervisor** — The paper-only session owner above Desk Cycles. It holds an inode-identity single-writer lease, serializes its lifecycle, verifies the existing Operational Journal, recovers protective kernel work, captures authenticated account, broker and operational truth, reconciles, enforces freshness and the Safety latch, binds queued cycles to that exact truth, and records content-linked truth manifests plus terminal session evidence. Production replay resolves those manifests to their signed evidence and re-enforces protection for non-completed terminals. Immediately before an entry, the Kernel invokes the Supervisor gate again after protect-first recovery and requires a signed, one-use capability bound to the exact intent, cycle and Account Snapshot. Rejection, invalid evidence or a pre-authorization failure durably quarantines the accepted intent; unscoped Kernel recovery never dispatches accepted intents. It cannot create truth, reset safety, admit a live gateway, or promote a Strategy Plan.

**Quarantined Trade Intent** — An admitted paper intent that failed the final Supervisor dispatch gate before any entry command was prepared. Its durable reason codes and truth-manifest evidence permanently exclude it from scoped dispatch; unscoped Kernel recovery is protective-only. It is not a Safety reset or a broker cancellation.

**Broker Snapshot** — Content-addressed, producer-signed broker account and order truth used by reconciliation. Caller-selected labels and unsigned snapshots are not broker truth.

**Observation** — A fact inferred from a closed Trade Episode with exact reconciled-attribution and review evidence. The Coach discovers eligible episodes from the journal. One loss may create an Observation, never an active rule.

**Mistake Hypothesis** — A scoped, testable explanation formed from repeated or high-severity Observations and counterfactual evidence.

**Risk Reservation** — Capital and risk capacity atomically held for an approved Trade Intent until it is rejected, cancelled, expired, or reconciled with fills.

**Kill Switch** — A latched safety action that blocks new exposure, repairs known protection gaps first, and then cancels only broker-confirmed working entry remainders unless an explicit flatten policy applies. It never treats an accepted-only or merely prepared entry as a broker order.

**Post-Reconnect Feed Watermark** — Market data received strictly after a feed reconnect. A fresh Post-Reconnect Feed Watermark plus explicit authorization is required to reset a feed latch; cached pre-disconnect data never qualifies.
