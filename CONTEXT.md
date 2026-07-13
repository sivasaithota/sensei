# Sensei Domain Language

This glossary is the shared language for the trading system. Terms describe domain meaning, not a particular implementation.

## Research and knowledge

**Source Artifact** — An immutable copy or stable reference to material the system studies, such as a book excerpt, document, web page, or video transcript.

**Citation** — A locator into a Source Artifact, such as an edition and page range or a video time range, that supports a claim.

**Claim** — A provenance-backed statement extracted from one or more Source Artifacts. A Claim is not yet a trading rule.

**Hypothesis Version** — An immutable, testable proposition derived from claims, trade observations, or human research. A revision creates a new version rather than changing prior evidence.

**Strategy Plan** — A source-faithful, executable description of entry, exit, timing, sizing, and applicability rules used consistently by research and trading simulations.

**Strategy Plan Version** — An immutable revision of a Strategy Plan whose identity covers every behavior that can change a decision. A display name is never its identity.

**Plan Decision Trace** — The deterministic, time-ordered decisions produced by applying one Strategy Plan Version to normalized observations. Research, shadow, paper, and live adapters consume the same trace.

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

**Trade Intent** — A fully approved, immutable request to trade. It is not an order and carries no broker side effect by itself.

**Trade Episode** — The complete immutable history from signal snapshot through thesis, approvals, orders, fills, protection, exit, attribution, and post-mortem.

**Operational Journal** — The append-only, ordered record of governance, risk, trading, episode, and operator facts from which rebuildable views are derived.

**Observation** — A fact inferred from a Trade Episode with stated uncertainty. One loss may create an Observation, never an active rule.

**Mistake Hypothesis** — A scoped, testable explanation formed from repeated or high-severity Observations and counterfactual evidence.

**Risk Reservation** — Capital and risk capacity atomically held for an approved Trade Intent until it is rejected, cancelled, expired, or reconciled with fills.

**Kill Switch** — A latched safety action that blocks new exposure and cancels entry orders while preserving or strengthening protective exits unless an explicit flatten policy applies.
