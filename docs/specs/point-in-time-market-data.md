# Point-in-Time Market Data Catalog

## Objective

Materialize reproducible Market Data Snapshots without survivorship bias. A snapshot must include every Stable Instrument whose Membership Interval overlaps the requested research window, including removed, delisted, and renamed constituents, while permitting new positions only on Entry-Eligible sessions.

The public seam is:

```python
catalog.snapshot(SnapshotRequest) -> MarketDataSnapshot
```

Two adapters make this a real seam:

- a manifest-backed catalog with verified membership and artifact lineage;
- a legacy current-constituent/Yahoo catalog that is always marked inadmissible for point-in-time examination.

## Snapshot request

A `SnapshotRequest` fixes:

- the named universe;
- the first historical bar required for research and indicator warm-up;
- the inclusive as-of market date beyond which no bar may enter;
- daily frequency for this slice.

The first date must not be after the as-of date. A manifest cannot attest to an as-of date later than its retrieval date; a future request fails closed until a newer pinned manifest exists.

## Manifest catalog

The catalog root contains a versioned JSON manifest. The manifest identifies:

- the catalog and source dataset;
- source URI, retrieval date, and license/usage note;
- one content-hashed membership CSV;
- one content-hashed daily-bar Parquet artifact per Stable Instrument;
- each instrument's exchange and current display symbol;
- the price adjustment policy and optional content-hashed corporate-action artifact.

Membership CSV records contain `universe`, `instrument_id`, `symbol`, `effective_from`, and nullable `effective_to`. Dates use inclusive-start, exclusive-end semantics. Multiple non-overlapping records for the same Stable Instrument support removal/re-entry and symbol changes.

All referenced paths must resolve inside the catalog root. Every artifact hash is verified before its content is used. Missing, changed, duplicate, overlapping, or unreferenced instrument records fail materialization explicitly.

Materialization is resource-bounded before Parquet page decode: manifest, artifact, instrument, membership-row, total compressed-byte, total row, column, and peak working-memory limits fail closed. Daily-bar Parquet must have a flat fixed-width schema containing numeric OHLCV and exactly one timestamp index. Its row count and shape—not compressed size or row-group estimates—produce a conservative bound for Arrow decode, pandas conversion, date filtering, retained frames, hashing, and the later defensive snapshot copy. Variable-width and nested bar fields are rejected. Corporate-action Parquet is hash- and metadata-verified but not decoded until a bounded application schema exists.

Manifest content cannot declare itself trusted. Point-in-time admissibility requires both an independently configured issuer allowlist and an independently pinned canonical manifest content ID. The pin binds the complete manifest—including membership, artifact hashes, adjustment policy, and source lineage—while the issuer check prevents a pinned artifact from being relabelled as a different provider. Signature-based issuer verification may replace manual pins in a later slice.

## Snapshot semantics

1. Stable Instrument identity, not ticker text, keys price history and evidence.
2. The snapshot includes any instrument with membership overlapping the requested window, even if it is absent on the as-of date.
3. Price bars are capped at the request's inclusive as-of date and begin no earlier than the requested history start.
4. Membership intervals are part of snapshot identity. Changing a boundary, symbol history, artifact hash, adjustment policy, or source lineage changes the snapshot ID.
5. Entry Eligibility is evaluated on the simulated entry session. A signal from the prior session may enter on the first eligible session.
6. A position opened while eligible may complete after universe removal; removal does not create an implicit exit.
7. A Membership Interval with no matching bars, or insufficient eligible coverage under an Examination Protocol, fails closed with evidence issues.
8. Raw/unadjusted bars are not admissible in this slice because corporate-action application is not yet implemented.
9. Snapshot construction is internal to catalogs (with a private test-fixture constructor); callers cannot set the point-in-time flag through a public snapshot constructor.
10. Public snapshot identity comes from the versioned materializer request, canonical membership, lineage, and exact artifact content IDs—not library-dependent DataFrame hashes. A separate private runtime hash detects in-memory mutation.
11. Daily artifacts contain at most one row per market-session date. Distinct intraday timestamps on one date cannot masquerade as separate daily sessions.
12. Every Examination Protocol fold must overlap point-in-time universe membership somewhere; a fold with zero universe coverage cannot borrow favorable evidence from other folds.

## Legacy adapter

The existing Yahoo/current-Nifty-500 store remains available only as a compatibility adapter bound to one constructor-configured universe name. It may produce a reproducible snapshot of files currently on disk, but it always declares `point_in_time_universe=False`. It rejects requests for any other universe, and no amount of positive performance can make its Evidence Dossier eligible for shadow trading.

## Acceptance criteria

1. A manifest fixture with one removed constituent and one later replacement materializes both Stable Instruments for an overlapping request window.
2. Membership boundaries create the independently expected Entry-Eligibility sessions and are included in snapshot identity.
3. The Research Examiner counts entries only when the Stable Instrument is eligible on the entry date.
4. A removed constituent's valid historical trade is retained; a post-removal signal cannot originate a trade.
5. Changing one membership date or one bar artifact changes the snapshot ID.
6. Hash mismatch, path traversal, overlapping membership, missing artifact, unsupported adjustment policy, or bars after the as-of date cannot silently materialize an admissible snapshot.
7. The legacy adapter produces `NEEDS_MORE_EVIDENCE` through the unchanged Research Examiner seam.
8. Snapshot materialization never writes Playbook, study, paper, order, execution, or user data files.
9. An allowlisted issuer name without the pinned manifest content ID remains inadmissible.

## Out of scope

- Purchasing or selecting a production Indian-market data vendor.
- Applying raw corporate actions or reconstructing adjustment factors.
- Intraday ticks, exchange-session microstructure, news, fundamentals, or sentiment.
- Portfolio simulation, locked holdout access, strategy promotion, or execution.
