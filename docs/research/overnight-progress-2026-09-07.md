# Overnight stock research progress — 7 September 2026

Scope: NSE cash equities, swing first, ₹300,000 research account. No live order
authority. Reuse local Kite data; do not purchase or renew services.

## Pass 1 — lower-turnover comparison

Started approximately 02:22 IST. Prior checkpoint: `1843c3d`, 889 tests passed.
The original momentum baseline and demerger sensitivity were identical at
₹294,661.96 final equity. Transaction costs exceeded gross realised P&L.

Frozen before execution at 20:53:12 UTC on 6 September (02:23:12 IST on 7
September): `config/stock-lower-turnover-experiment-v1.json`. Specification:
[lower-turnover comparison](../specs/lower-turnover-comparison.md).

Three configurations test a 60-session holding limit, then a 20% profit target,
then an existing trend-filtered entry package. All retain the 5% stop and other
control settings. All three completed through the frozen research runner;
no engine changes or new strategy registrations were needed.

| Configuration | Final equity | Return | Max drawdown | Trades |
|---|---:|---:|---:|---:|
| Control | ₹294,661.96 | −1.779% | 29.451% | 467 |
| Hold 60 | ₹329,853.50 | +9.951% | 23.974% | 441 |
| Hold 60, target 20 | ₹278,859.65 | −7.047% | 31.485% | 268 |
| Trend entry, hold 60, target 20 | ₹279,377.33 | −6.874% | 41.720% | 250 |

Nifty 500 gross TRI: +22.9535%. All four remain NO_CLEAR_NET_EDGE and
DATA_BLOCKED. No holdings crossed the two listed demerger events. Costs fell
from ₹68,191.57 to ₹64,723.86 / ₹37,742.58 / ₹35,213.49 respectively; lower
costs did not establish better economic performance.

Fixed a demonstrated shared exposure-journal race: two initial attempts stopped
before simulation with stale expected stream versions. A bounded retry rereads
exposure/holdout restrictions on every conflict, preserves identical-payload
deduplication and propagates integrity errors. Three real-SQLite collision tests
went from red to green. Both interrupted runs then completed concurrently with
their original frozen settings. Full suite: **892 passed**. Standards and Spec
implementation reviews clear.

Exact run IDs, hashes, turnover/holding/exit diagnostics and reproduction:
[comparison report](lower-turnover-comparison-2026-09-07.md). Local artifact:
`data/reports/stock-development/lower-turnover-comparison-v1-20260907.json`.

Do not repeat these runs as new evidence or extend them into a parameter sweep.
Next pass: describe losses in these existing trade ledgers by year/security,
stop and gap-stop contribution, and volatility measured strictly before entry.
Baseline exits were dominated by stops (308/467), versus 22 time exits. Keep
this descriptive: no widening stops, dropping losing stocks, new parameter
sweep or fictitious holdout. Continue actionable data/accounting work separately.

Stop or checkpoint and pause the heartbeat at 10:00 IST; provide the owner a
consolidated report. Preserve unrelated runtime JSON and LinkedIn files.

## Pass 2 — loss attribution

Resumed from `c246e7b` at approximately 03:00 IST. Completed descriptive
attribution of all four existing runs; no strategy change or new backtest.
Added `sensei.research.stock_attribution`, which verifies frozen source reports,
manifests, snapshots, scoped frames and benchmark before producing derivatives.
It groups every trade by exit year, security, exit reason and fixed pre-entry
ATR bins, reconciles rounded P&L, and preserves missing history as unknown.

- Baseline realised exit-year net P&L: 2024 +₹49,254.26; 2025 +₹5,409.88;
  2026 through evaluation end −₹60,002.18. These are not annual account returns.
- The five worst baseline securities account for only 6.85% of all losing-trade
  amounts. Losses are spread across many securities; do not delete the worst
  names after inspection.
- Stops/gap stops account for 99.64% of baseline losing-trade amounts, but the
  volatility bins do not establish a causal benefit from widening stops.
- Every run has one unknown prior ATR: FORCEMOT entered 2024-03-01, before
  enough sessions existed following its February 14 NSE resumption. The
  diagnostic keeps the trade and does not fill the inactive period.

Full suite: **903 passed**. Standards and Spec implementation reviews clear.
[Results and exact artifact IDs](stock-loss-attribution-2026-09-07.md).
Local index: `data/reports/stock-attribution/comparison-index-20260907.json`.

Next pass: describe these same trade entries by a fixed benchmark trend state
known at decision time. Measure state-level trade P&L and exposure without
introducing a regime-filter backtest or optimizing parameters. Retain all
current data/accounting limits, and pursue actionable FORCEMOT/history policy
or shareholder accounting evidence separately. Do not repeat completed
lower-turnover runs or this attribution as new evidence.

## Pass 3 — market-state attribution

Resumed from `3146510` around 03:39 IST. Added a fixed diagnostic comparing
the preceding Nifty 500 TRI close with its preceding 200-close mean. No
strategy filter or new backtest was run. All four saved portfolios have 504
above-average and 161 at-or-below sessions; none has unknown benchmark state.

- Baseline trade P&L grouped by state at entry: above +₹37,352.25;
  at-or-below −₹42,690.29. The hold60 variant's at-or-below entry cohort was
  slightly positive at +₹1,831.02, so a blanket deletion claim is unsupported.
- Actual baseline daily marked P&L: above +₹80,997.25; at-or-below −₹86,335.29.
  It stayed 72.649% invested on average at day-end in the latter state.
- All four portfolios lost marked value on at-or-below sessions. This view
  includes existing holdings crossing states and differs from entry cohorts.
- Review found and fixed a derivative calendar check that could accept a
  missing first session and shift state attribution despite total P&L matching.
  The check now uses full frozen evaluation dates. Original curves were complete;
  final regenerated metrics and earlier trade/ATR attributions are unchanged.

Full suite: **911 passed**. Standards clear; Spec calendar finding resolved and
re-reviewed. [Detailed results and final artifact IDs](market-state-attribution-2026-09-07.md).
Local index: `data/reports/stock-attribution/market-index-20260907.json`.

Next pass: freeze two actual SMA200 new-entry-gate experiments, one on the
original baseline and one on hold60. Same benchmark definition, demerger guard,
universe, fees and sizing; existing holdings retain their original exits.
Unknown state blocks new entries. Run each once, compare against both saved
controls, report all outcomes and keep reused-development/data-blocked status.
No moving-average grid, historical date selection or new automatic liquidation
policy. Preserve these descriptive artifacts as prior exposure.

## Pass 4 — actual market-entry gate experiment

Resumed from `65408a5` around 04:17 IST. Frozen declaration at 04:20:24 IST:
`config/stock-market-entry-experiment-v1.json`. Completed both gates and reran
both controls. Control campaigns, trades and equity curves reproduce exactly.

| Run | Return | Max drawdown | Trades | Costs |
|---|---:|---:|---:|---:|
| Original control | −1.779% | 29.451% | 467 | ₹68,191.57 |
| Original with gate | −4.921% | 26.928% | 373 | ₹54,664.77 |
| Hold60 control | +9.951% | 23.974% | 441 | ₹64,723.86 |
| Hold60 with gate | −5.316% | 27.332% | 360 | ₹52,659.99 |

The gate reduced costs and below-average exposure but worsened both returns.
Baseline below-average EOD utilization fell from 72.649% to 5.989%; its gains
on above-average sessions also shrank sharply. This confirms that deleting a
retrospective losing cohort does not reproduce a portfolio filter's outcome.
All gated entries were checked to be above the prior SMA200. Existing exits
remained unchanged; separate demerger counts stayed ABFRL259/VEDL95.

Full suite: **917 passed**. Standards and Spec implementation reviews clear.
All four remain NO_CLEAR_NET_EDGE, DATA_BLOCKED and research-only.
[Results and exact report IDs](market-entry-gate-results-2026-09-07.md).
Local comparison: `data/reports/stock-development/market-entry-comparison-v1-20260907.json`.

Next pass: stop tuning this seed/filter family. Investigate actual held-trade
corporate-action exposure with verified raw NSE bhavcopies and Kite bars;
start split/bonus and cash-dividend accounting checks. Raw/adjusted factor
changes are screening evidence, not confirmed action events or a license to
rescale prices. Use primary company/exchange evidence and retain missing
receipts/entitlements explicitly. No invented cash credits or new price repair
without a verified convention. No new subscriptions or Kite requests needed
for the initial local comparison. Keep all failed experiments as prior exposure.

## Pass 5 — held-trade endpoint evidence

Resumed from `8799f1b` around 04:58 IST. Compared all 908 baseline/hold60 trade
records against 485 verified local raw NSE sessions. Of 1,816 endpoint records,
1,770 matched and 46 fall beyond the August 14 raw archive. Matched endpoints
include 66 differing historical ISINs, explicitly unverified. Canonical NSE
symbol matching fixed four false missing candidates for the Kite HEG-BE alias.

No greater-than-1% entry/exit volume-scaling change appeared among 880 comparable
trade records; 28 lack a comparison. This is endpoint screening, not proof of
complete corporate-action accounting. Primary dividend research documents the
unresolved Kite adjustment formula and the danger of double-crediting dividends
against already-adjusted prices. No prices, cash or strategy results changed.

Full suite: **922 passed**. Spec implementation review clear; Standards matching
finding fixed with a regression. [Results and artifact identity](held-price-screen-results-2026-09-07.md).
No Kite requests, new spending or live orders were made.

Next pass: reconcile historical ISIN changes against official split/bonus notices,
starting with MAZDOCK and HEG. Preserve effective dates, ratios and identity
uncertainty; use this evidence to scope actual-price/entitlement accounting.
Continue to stop strategy parameter tuning until the accounting basis is sound.

## Pass 6 — evidenced split-unit defect

Resumed from `7d3f5aa` around 05:45 IST. Official company/exchange records establish
MAZDOCK's 2-for-1 split (December 27, 2024) and HEG's 5-for-1 split (October 18,
2024), including ISIN transitions. Added a bounded, hash-pinned event ledger and
share-unit audit that retains every one of the 908 source trade records.

Three shared trades have fractional physical-share equivalents: HEG 123 adjusted
units = 24.6 shares; MAZDOCK 35 = 17.5 and 21 = 10.5. Each occurs in both controls,
so six records are flagged. Two records are integral and 900 unevaluated. This
is a demonstrated sizing representation defect, not a revised portfolio return.
No source trades, prices, cash or results changed. No Kite requests or spending.

Full suite: **938 passed**. Standards and Spec reviews clear; exact artifact counts independently checked.
[Results, artifact identity and implementation boundary](share-unit-audit-results-2026-09-07.md).

Next pass: implement evidence-aware entry quantity increments in portfolio sizing,
rounding down within cash/risk/allocation limits including fees, with missing
unit evidence blocking entry in the explicit mode. Bind the map into experiment
identity. Reproduce the known fractional cases and test the correction without
claiming a fully corrected portfolio from only two stocks' evidence. Preserve
control behavior and make its synthetic-unit limitation explicit. Keep dividends,
ticks and demerger entitlements separate; do not double-credit split quantities.
