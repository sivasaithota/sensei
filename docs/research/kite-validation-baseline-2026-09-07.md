# Kite validation and first swing development baseline

The price-data pipeline now produces a frozen, reproducible development run.
The unchanged momentum-breakout baseline does not demonstrate a net edge.
Corporate-action and historical-membership certification remain incomplete;
this is not a live-trading approval or a validated crisis-performance claim.

## Completed work

- The complete archive contains 18,822 retained request windows: 18,677 pass
  structural validation and 145 remain rejected. Of the accepted windows,
  10,830 are honest empty responses. There are 7,047,800 accepted daily rows and
  416,084,344 raw bytes including rejected responses. Empty windows are not
  fabricated prices or proof that no other provider has history.
- An offline audit verifies original manifests and response hashes, diagnoses
  rejected rows, and counts observed crisis coverage. Rejection reasons are
  67 duplicate-session responses and 78 invalid-OHLCV responses. Original bytes
  remain unchanged; no conflicting bar was selected automatically.
- A separate 2022-01-01 through 2026-09-04 development snapshot contains all 499
  matched stocks from the existing 500-symbol research list, with 527,077 rows.
  JBCHEPHARM is explicitly unmapped. No matched stock was removed for history
  length, missing sessions or subsequent performance. This current-stock cohort
  is not historical Nifty 500 membership. No holiday rows required removal.
- The snapshot binds the frozen plan, universe, raw inputs, code, mappings and
  output hashes. The run requires `snapshot_type: kite_development`, so losing
  the manifest cannot silently bypass provenance verification. Full-archive
  normalization remains blocked by the 145 rejected responses.
- Official Nifty 500 gross TRI history for 1999-01-01 through 2021-12-31 was
  captured separately: 5,728 sessions, original responses and hash manifest.
  This supplies benchmark history for the proposed crisis windows; it does not
  resolve stock membership or adjustments. It is stored at
  `data/research/benchmarks/nifty500-tri-crisis-history-20260907.parquet`, using
  the [official historical-data endpoint](https://www.niftyindices.com/reports/historical-data).

## Frozen baseline outcome

Evaluation: **2024-01-01 through 2026-09-03**, with 252 prior observations per
instrument for warmup. Strategy: `momentum_breakout_55`, unchanged 5% stop,
12% target and 30-session maximum hold. Account: ₹300,000, at most five positions,
20% capital per position, 2% initial risk per trade, 10 basis-point entry
slippage and the existing current delivery cost schedule. The configurable
research drawdown boundary remains the owner's 100%; it does not waive any
data-quality or live-readiness requirement.

| Metric | Observed development result |
|---|---:|
| Final equity | ₹294,661.96 |
| Net P&L | −₹5,338.04 |
| Total return | −1.779% |
| Maximum drawdown | 29.451% |
| Completed trades | 467 |
| Realised transaction costs | ₹68,191.57 |
| Average capital utilisation | 74.96% |
| Longest period below a prior equity peak | 258 sessions |
| Nifty 500 gross TRI return | +22.9535% |
| Excess total return | −24.7325 percentage points |

The strategy and benchmark calendars match exactly: **665 sessions**, no dates
missing from all stocks and no extra dates. There are **no simulation blockers**.
The economic verdict is `NO_CLEAR_NET_EDGE`; the separate overall decision is
`DATA_BLOCKED` because historical membership and corporate actions are not
certified. No strategy parameters were changed to improve this result.

The exploratory annualised mean daily excess-return interval is
[-28.1336%, +12.7457%], using the frozen 20-session circular moving-block bootstrap,
2,000 samples and 90% interval. This is reused-history development, not an
untouched holdout, a multiple-testing correction or a forward return forecast.
Costs use today's delivery schedule as a counterfactual, not historical tax
reconstruction; stop gaps fill at the opening price and additional exit slippage
is not modeled. These execution limits remain visible in the underlying report.

## Lifecycle and corporate-action findings

All 31 apparent within-history FORCEMOT gaps in the evaluation window fall inside
its confirmed NSE inactive interval, 2023-10-26 through 2024-02-13. They must not
be filled. JBCHEPHARM was suspended from July 17, 2026 for amalgamation; its local
Yahoo file is just one post-suspension, zero-volume row, not a usable historical
series. MAZDOCK's rejected pre-listing zero-price observation remains anomalous.
See [the primary-source security evidence](kite-security-exceptions-2026-09-07.md).

Six scoped price discontinuities require review: ABFRL, FORCEMOT, OFSS, SCI,
VEDL and ZEEL. The ABFRL and VEDL discontinuities coincide with demergers and
require parent/distribution accounting. No baseline position was held across
the flagged ABFRL, VEDL, FORCEMOT, OFSS or ZEEL dates, but rolling indicators and
rankings can still be affected. SCI's flagged date is in warmup. These facts
do not justify dropping the stocks or calling the entire adjustment chain
verified. See [the corporate-action investigation](kite-corporate-action-exceptions-2026-09-07.md).

## Crisis coverage, not crisis certification

| Window | Instruments with some accepted bars | Bars in both first and last month |
|---|---:|---:|
| 2000–2002 | 5 | 2 |
| 2007–2009 | 832 | 672 |
| 2020–2021 | 1,757 | 1,513 |

Bookend presence does not prove uninterrupted history. All counts refer to the
current vendor identities and accepted response windows; rejected windows are
excluded explicitly. The dot-com sample is too thin for a broad stock-portfolio
claim. Historical removals, delistings, exchange eligibility and corporate
actions must be established before declaring the strategy tested through a
crisis. Named event windows are reporting labels; any regime signal must use
only information available at the simulated decision time.

## Reproduction and exact artifacts

- Frozen capture plan: `4a26765db63fd41f2e11a1f40e718ef2517a0a3ac6a768eab03d99863b7d2c14`.
- Final recent snapshot: `111ffe46d9d3ee797882f63b080ea32817a78ad02e73bf5f19bdc6911b0b409c`,
  under `~/.local/share/sensei/kite/development/`.
- Final audit: `~/.local/share/sensei/kite/reports/validation-final-20260907.json`.
- Frozen run: `data/reports/stock-development/04b7b8d2757564fe492bd293e8cce58c6f0b2da8d195123fc387f120d7a5e88b/report.json`.
- Configuration: `config/stock-research-kite-development.json`.
- [Runbook](../runbooks/kite-history-ingestion.md) documents offline audit,
  snapshot construction, required manifest and the frozen run command.

The earlier provisional run has the same economic results. It is preserved as
development exposure; the final run adds the explicit required-manifest policy
and the reviewed snapshot implementation. Changing identifiers did not restore
an untouched holdout.

## Next experiments and acceptance boundaries

First resolve the remaining corporate-action treatment for the actual candidate
universe, including ordinary cash dividends and demerger entitlements. Recover
historical members where possible and retain unresolvable gaps explicitly.

Then predeclare a small comparison of lower-turnover swing hypotheses against
this unchanged baseline. Realised costs exceed realised gross profit in this
run, making turnover a measurable concern, not a reason to omit fees. Assess
net excess return, drawdown, turnover, liquidity and stress-period behaviour;
do not select solely by the best observed CAGR.

Verified exchange announcements should be the first future news input. Store
publication and first-seen times, original source, security identity, revisions,
event type and model version. Historical decisions must not see later revisions.
Social sentiment should first be collected and evaluated separately from orders;
measure incremental value against the price-only baseline on a genuinely later
evaluation period. No new news/social subscription or order authority was added
in this stage.

Validation: **878 tests passed**; independent Standards and Spec reviews cleared
after adding numeric-overflow/out-of-window diagnostics and required-manifest
regressions. Existing runtime state and unrelated LinkedIn files were preserved.
