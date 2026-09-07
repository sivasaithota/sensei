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

## Pass 7 — explicit entry quantity increments implemented

Resumed from `ab8c6e3` around 06:24 IST. Added an optional dated quantity-increment
map and evidence hash to the portfolio simulator. Missing evidence blocks entry;
both cost models round down to the increment. Delivery cash and stop-risk limits
include fees. Existing holdings receive no second split credit. Identity and
report metadata bind and distinguish the explicit mode from legacy synthetic units.

The isolated, source-pinned reproduction corrects HEG 123→120 (24 shares),
MAZDOCK 35→34 (17 shares) and MAZDOCK 21→20 (10 shares); MAZDOCK 30 stays 30 (15 shares).
Each case occurs in both controls. This is a sizing correction, not a revised
full-portfolio return. The full runner remains in legacy mode pending coverage.

Both complete controls reran with every trade, equity point and economic value
unchanged. Baseline remains ₹294,661.96; hold60 ₹329,853.50. Full suite:
**957 passed**. Standards and Spec reviews clear. No Kite requests or spending.
[Artifacts, parity IDs and scope](entry-quantity-units-results-2026-09-07.md).

Next pass: classify the finite 27-symbol set with observed non-unit volume scaling
using primary corporate-action notices and measure coverage. Integer splits are
not the whole problem: OIL/TRENT are near 1.5, CUB near 4/3, and ABFRL/SIEMENS/TMPV/VEDL
show noninteger vendor factors that must not be assumed to represent shares.
Keep rational bonuses and demerger accounting distinct. Do not auto-build a unit
map from volume ratios or label the complete universe corrected from two stocks.

## Pass 8 — 27-symbol classification and expanded split audit

Resumed from `6e10a4a` around 06:38 IST after the owner confirmed usage had reset;
the work had not been blocked on usage and no reset credit was consumed.
Classified 27 flagged symbols against primary sources: ten pure splits, twelve
bonuses, one combined split/bonus and four demergers. Their 190 non-unit endpoint
records remain observations, not a generated share map. All 908 source trades,
1,770 matched endpoints and 46 missing endpoints are retained.

Added a separate eight-stock pure-split ledger and applied the existing strict
audit unchanged: nine additional fractional records, two integral, twelve price
scaling mismatches, seven outside pre-split scope and 878 outside the ledger.
The mismatches in TATAINVEST/MCX/COFORGE remain unresolved; sampled deviations
reach ₹0.50 in adjusted units, with mixed signs. No tolerances were loosened.

Demergers' noninteger factors approximately correspond to tax cost allocations,
not homogeneous parent-share increases. Rational bonus ratios and ten missing
explicit bonus ex dates also prevent automatic full-universe unit coverage.
Full suite: **961 passed**; Standards and Spec reviews clear. No portfolio results
changed, no Kite requests/spending/live orders. [Evidence and artifact IDs](corporate-action-inventory-results-2026-09-07.md).

Next pass: investigate dated NSE equity tick-size rules for the unresolved split
price differences. Prepare a bounded raw-execution reproduction of selected
pre-action trades using verified raw-session receipts, adjusted data only for
signals, and physical whole-share quantities. Keep unmodeled event intervals
blocked. Do not widen diagnostic tolerances or claim a corrected full portfolio.

## Pass 9 — selected raw execution replay

Resumed from `361dc58` around 06:56 IST after the owner's “what's next?” request.
Implemented optional constant-tick brackets using decimal arithmetic, preserving
the old mode. Built a source-pinned raw replay of four selected pre-action trades
(eight records across both controls), using whole physical shares and 28 verified
NSE raw-session receipts. Monthly reference closes establish the scoped 2024
₹0.05 tick assignment; no general historical security-master certification.

The initial rights/demerger coverage gap was resolved by full calendar-2024 NSE
action API responses: two HEG and three MAZDOCK records, no interval overlaps.
Exact bodies and manifest are retained; no conditional replay was run. Every
case passed scoped checks with matching exit dates/reasons and no horizon censoring.
Physical quantities: HEG 24; MAZDOCK 17, 15, 10. Results are isolated, not a revised
portfolio return. Overall DATA_BLOCKED/can_trade=false remains.

Full suite: **978 passed**. Standards and Spec reviews clear. Both legacy controls
reran with exact trade, equity-curve and economic parity. Baseline remains
₹294,661.96; hold60 ₹329,853.50. No Kite requests/spending/live orders; only public
NSE history retrieval for the specific coverage gap. [Detailed evidence, outcomes and IDs](selected-raw-replay-results-2026-09-07.md).

Next pass: measure raw-session and action-history coverage across the remaining
saved holdings; reuse existing captures and fetch only needed missing NSE sessions.
Intervals crossing actions need explicit entitlements, not forced no-action replay.
Keep dated tick evidence separate. Broaden actual-price cash accounting before
claiming a corrected portfolio or returning to strategy selection.

## Pass 10 — complete held-trade raw accounting comparison

The owner explicitly prioritized the trading work and asked to extend coverage
across remaining trades, rerun coherent portfolio accounting and compare against
Nifty 500 TRI. LinkedIn and unrelated runtime files remain untouched.

Captured the 14 missing raw sessions; verified all 665 evaluation sessions.
Reconciled whole-market action captures against half-period captures: 2024's
whole-year response omits one COASTCORP dividend, retained through the partition
union. Added PGEL plus 21 other dated split identities, used only for lineage.
All 499 stocks remain in the simulation. All 908 saved and 908 raw rerun trades
have zero held raw/tick issues, covering 6,538 trade-sessions per comparison pair.

Added separate adjusted-signal and raw-execution inputs, whole physical shares,
dated ticks and ex-date gross dividend entitlements excluded from buying power.
Unsupported mandatory held actions stop the full run. No split/bonus/demerger
crossings occur in the completed controls; their event intersections require
dividends, an ordinary AGM and nonparticipation in one verified voluntary tender.

Baseline now finishes **₹286,796.32 (−4.401%, DD29.660%)**; hold60
**₹323,748.95 (+7.916%, DD24.126%)**; benchmark **+22.9535%**.
Gross dividends are ₹5,481 and ₹6,026.25, kept outside buying power. Both verdicts
remain NO_CLEAR_NET_EDGE/DATA_BLOCKED. A raw/adjusted rounding difference changes
GODFRYPHLP's September 2024 exit and a subsequent portfolio admission; do not
change the valid raw bar to recover the better legacy result.

Full suite: **1,013 passed**. Independent Standards and Spec reviews clear after
fixing same-path frozen-input substitution and conflicting raw-row collapse.
Both complete legacy controls preserve exact campaign economics and serialization
apart from experiment identity. No Kite calls/extra credits/live orders.
[Final artifact hashes, cash reconciliation and interpretation](raw-portfolio-results-2026-09-07.md).

Next pass: preserve this completed comparison and stop tuning this filter family.
Investigate causal signal prefix invariance and required historical-identity/
membership inputs before claiming point-in-time strategy evidence. This is not
another request to repeat the raw holding audit. Preregister any genuinely new
strategy hypotheses and evaluation rules; retain all failures and development
history exposure. Do not activate live trading from these results.

## Pass 11 — signal prefix invariance and membership evidence gaps

Resumed from `8e749a5` at about 08:23 IST under the authorized heartbeat.
Preregistered a read-only diagnostic against the frozen raw comparison and its
original control identities. Checked all 499 instruments at every available
evaluation-date cutoff: **315,950 prefixes**, of which 315,451 contain genuinely
later data in the full frame, and **175,403,081 Boolean cells**. No earlier signal
changed. A deliberate future-mean control produced two mismatches. Uniform
reciprocal OHLC/volume multipliers 3 and 5 changed no signals; all final-date
ranking components matched within the declared 1e−12 tolerance.

This establishes fixed-data append invariance only. It does not recover historic
vendor adjustment vintages or cure current-universe survivorship bias. The bounded
primary-source membership review located scheduled and ad hoc official notices,
but not a complete starting set, change register or dated reconciliation anchors.
No membership dates, prices or corporate-action transforms were invented.

Full suite: **1,020 passed**; independent Standards and Spec reviews clear.
No production strategy/portfolio behavior changed, no new return experiment, no
Kite calls or spending. [Artifact hashes, exact test scope and interpretation](signal-causality-results-2026-09-07.md).

Next pass: acquire/pin the finite official membership notices listed in
[the coverage note](nifty500-membership-coverage-2026-09-07.md), preserving revisions,
effective dates and temporary dummy constituents; continue seeking dated baseline
and checkpoint sets. Keep an incomplete ledger inadmissible. Define the required
dated corporate-action transformation contract before claiming causal adjusted
indicators. Do not repeat this completed signal audit or tune the rejected family.

## Pass 12 — pinned membership announcements and correction handling

Resumed from `92fccb7` at about 09:03 IST. Captured all 12 finite official notice
PDFs successfully, pinned their exact bytes and visually verified each relevant
Nifty 500 table. The versioned register retains 342 rows: 283 observed effective
rows within the evaluation window, 55 future rows, two cancelled original rows
and two revocation records. March 2024's correction cancels IREDA inclusion and
VGUARD exclusion. September 2026's upcoming changes and DUMMYHEG do not enter
historical membership. Temporary placeholders do not imply tradable instruments.

The bounded official-source anchor search obtained no complete dated starting
constituent list or checkpoint. Neither a current CSV nor aggregate whitepaper
statistics can establish that list. The register remains explicitly incomplete;
it emits no membership intervals or entry eligibility. DATA_BLOCKED remains.

Added capture verification and publication-aware classification, with 17 focused
tests. Independent Standards review found compact date comparison and final-URL
validation gaps; both are fixed and regression-tested. Final Standards and Spec
reviews are clear. Full suite: **1,037 passed**. Final audit report SHA-256:
`ebc9fc21be2a6b1d4a0e598bb45789e148041a3a412063d7f62f0932bb05de78`.
[Evidence, source table and exact hashes](nifty500-notice-register-results-2026-09-07.md).

No strategy or portfolio behavior changed, no new return experiment and no Kite
requests, credit spending or live orders. Next: define a bounded date-aware
corporate-action transformation contract and acceptance tests. Do not recapture
these notices, repeat completed audits or tune the rejected family. Historical
membership still requires a complete dated anchor, reconciled changes/checkpoints
and stable instrument/dummy lineage. Keep unsupported evidence inadmissible.

## Pass 13 — dated split/bonus signal-history contract

Resumed from `109d04a` at 09:49 IST. Wrote the scoped contract before implementing
a pure research transform. It reconstructs one instrument's indicator history in
decision-session units from raw OHLCV and declared split/bonus events. Only events
effective and known by that decision may normalize earlier rows. Ex-session raw
rows, supplied currency turnover and input arrays remain unchanged. Events already
effective but not yet known block, as do unsupported effective kinds. This neither
certifies the caller's evidence nor changes the production catalog or portfolios.

Twenty synthetic acceptance tests pass, including compound factors and preservation
of genuine price moves. Spec review found malformed future ratios were being
skipped; validation now precedes the skip, with three regressions. Final Standards
and Spec reviews are clear. Full suite: **1,057 passed**, 27.26 seconds.
[Contract and exact scope](../specs/dated-action-signal-history.md),
[acceptance results](dated-action-history-results-2026-09-07.md).

No new return experiment, Kite requests/credits, live orders or external messages.
The portfolio comparison and DATA_BLOCKED status remain unchanged. Next bounded
step: preregister source-pinned real split/bonus reproductions with conservative
first-known-session mapping and complete raw identity/action coverage, then daily
ranking/correlation replay. Physical entitlements and complete dated membership
remain separate unmet requirements. Do not rerun completed diagnostics or tune
the rejected strategy family. [Consolidated overnight report](overnight-summary-2026-09-07.md).

## Owner follow-up — two real split reproductions

After the 10:00 IST pause, the owner's “what's next?” resumed bounded interactive
work. The overnight heartbeat remains paused. Preregistered HEG Oct14–25 and
MAZDOCK Dec23–Jan3 split-history checks, capturing five original contemporary PDFs
and reusing 19 verified raw sessions. No Kite request or price repair was needed.

Both cases pass 19 daily cutoffs and 500 scalar-oracle cells. Conservative
all-support knowledge is Oct18 for HEG and Dec27 for MAZDOCK. Normalized prior
closes are ₹514.08 and ₹2,364.875; genuine ex-session moves remain −3.44888% and
−2.00751%. Both ex-date files retain previous close in old units, so that field
must not be an unconditional adjustment-factor oracle.

Fixed a pandas ISIN attribute collision exposed by the first actual run and an
immutability gap after the rejected late-knowledge control. Thirteen focused tests
pass; independent reviews clear. No strategy/portfolio return changed. This does
not certify upload times, revisions, complete actions or historical membership.
Full suite: **1,070 passed**, 26.91 seconds.
[Final artifact, source hashes and next bounded scope](real-split-reproduction-results-2026-09-07.md).

## Owner continuation — real bonus and full-warmup indicators

The owner's “okay continue” authorized the next bounded milestone. Captured BSE's
May12 pre-ex company notice, May14 exchange circular and May26 allotment confirmation.
The first two establish the modeled May15 knowledge date and 3/1 total-share factor
for the May23 bonus; the later confirmation remains corroboration only.

Preregistered a price-only dividend convention and 262 raw sessions for BSE/HEG,
with 252 observations at the first of 11 decision dates. All five observed actions
are explicitly classified, including three dividend rows. The real replay passes
28,270 rational-oracle OHLCV cells, 5,654 Boolean cells, all ranking components,
correlation and append/input-immutability checks. BSE's May30 signal is true with
coherent units and false in unnormalized raw contrast. This is not a comparison
against the frozen adjusted portfolio or a profitability claim.

Strengthened the late-knowledge negative control after review found a silent-fallback
false-pass path; added fallback and mutation regressions. Thirteen focused tests
pass; final reviews clear. All captures, decisions and earlier artifact versions
are retained. [Final results and exact hashes](bonus-indicator-replay-results-2026-09-07.md).

Full suite: **1,083 passed**, 29.02 seconds.

No portfolio return changed and no Kite credits, purchases, live orders or external
messages were used. Overnight automation remains paused. Next integration needs
dated universe/action coverage plus physical entitlement/credit-time handling;
do not repeat the completed real split/bonus diagnostic or tune the rejected family.

## Owner implementation — bonus share entitlements and availability

The owner's “okay implement” authorized the portfolio integration. Bonus shares
now accrue as economic holdings separate from available shares and cash. Ex-date
exits sell original shares; pending bonus shares retain the exit request until
explicit availability/knowledge dates. Unknown availability remains pending even
under final liquidation. Whole-share rational entitlements, proportional basis,
fees, dividend attribution and position/cash constraints are covered.

The real BSE forced holding buys eight at ₹7,305 on May22, sells eight at ₹2,448 on
May23, and sells sixteen at ₹2,450 on May27 only under the labelled planned-date
scenario. Unknown availability retains sixteen shares worth ₹42,784 on May30 and
₹261,038.87 cash. Neither is a strategy test or evidence of actual account credit.
Ten captured raw receipts, action evidence, primary PDFs and implementation pins
are checked. [Final artifact and full results](bonus-portfolio-entitlement-results-2026-09-07.md).

Review corrected missing-calendar accrual, zero-sale strategy blocking, a fee-source
pin and a misleading inherited signal label. Final Standards and Spec reviews are
clear. **28 focused tests, 12 no-bonus economic/serialization parity fixtures,
1,111 full-suite tests passed** (29.33 seconds).

The independent universe assessment finds a viable custom lagged-liquidity route
without an index anchor, but dated stock classification and identities remain
missing. EQ/STK includes ETFs. The present 252-session raw warmup first supports
Jan6,2025 entry, rather than the existing Jan2024 start. Do not infer historical
membership or erase missing evidence through eligibility filtering.

No complete portfolio result, Kite usage, purchase, live activation or automation
state changed. Next: dated classification/identity evidence and deterministic
eligibility, remaining mandatory-action accounting, then coherent portfolio
evaluation against Nifty500 gross TRI. Do not retune the rejected family or repeat
the completed BSE reproduction without a changed input or new failure.

## Owner continuation — split inventory and classification coverage

The owner's “go ahead” authorized the next implementation after `14bb914`.
Share-increasing subdivisions now replace all old shares, with every resulting
share pending until explicit availability and knowledge dates. Bonuses retain their
existing original-share availability. No-action/dividend and bonus fixture
economics/output fields remain unchanged, except implementation-dependent IDs.

The real HEG holding buys 24 shares at ₹2,483.50 on Oct17,2024. Its 5/1 split gives
120 shares at economic basis ₹496.70. The documented NSE new-ISIN admission control
sells all120 on Oct18 at ₹496.35; final cash ₹299,809.99 after ₹148.01 costs. Unknown
availability sells nothing and retains120 shares worth ₹49,728 with ₹240,325.17 cash
on Oct25. These verify inventory accounting, not strategy performance or account
credit. Eleven raw receipts and the earlier official evidence chain are pinned.

Review found that `_Position` logic was missing from general experiment identity.
The fix adds its source; a behavioral regression proves changed inventory outcomes
now receive changed IDs. The first artifact remains saved; the final case parameters
are unchanged. [Final reports and hashes](split-and-classification-results-2026-09-07.md).

The classification checker retains exact observed tuples, effective intervals and
knowledge dates, distinguishing confirmed classifications from missing evidence,
unknown subtype/board and incomplete raw identity. It never grants admissibility or
trading authority. Two pinned endpoint files retain6,318 observations:6,308 lack
dated classification facts and10 have empty raw series. No eligibility is inferred.

The official NSE MII daily-security-master route is identified, but historical
sample requests failed; a contemporary subtype schema is also unverified. No dated
master was captured and no parser schema was invented. Next acquisition should
resolve one NSE-only historical file and its applicable dictionary, then populate
the new coverage check before expanding sessions or deriving liquidity eligibility.

Fifteen split and fifteen classification tests pass, alongside28 bonus tests.
Twelve no-action/dividend and eight bonus economic/serialization parity fixtures
pass. Independent Standards and Spec reviews are clear. Full suite: **1,141 passed**,
30.22 seconds. No new full-portfolio comparison or tuning, Kite usage, purchase,
live activation, external message or automation-state change.

## Owner next step — historical master capture and schema breakthrough

The owner's “next?” continued data acquisition after `1e0cfb8`. The official
browser selector exposed the exact January 6, 2025 NSE-only report API request.
Browser downloading failed, but a direct HTTP request to that observed endpoint
with ordinary headers succeeded: 960,641 gzip bytes, 8,608,619 CSV bytes,
28,469 records and 120 columns. No guessed archive URL was accepted as evidence.

All 2,976 same-session bhavcopy observations match exact symbol/series/ISIN and
exchange token. The remaining 25,493 master records are not automatically tradable
stocks or delistings. The offline auditor retains all reconciliation categories
and raw codes, checks hashes/date descriptor/filename, and bounds gzip/CSV parsing.
Its source-date claim stops at request and attachment filename, not historical
pre-opening publication or immutable vintage.

Official `MSD55276.zip` and `CMTR61813.zip` also downloaded successfully after
standalone PDF paths failed. Both schema tag arrays match all 120 fields. The
classification-looking blank columns are documented fillers. Field 8 `SctyTpFlg`
maps to broad equities, preference shares, debentures, warrants and miscellaneous;
field 11 identifies SME through value 5. Status, eligibility and permission remain
distinct. Equities does not alone prove fully paid ordinary main-board shares,
and miscellaneous is not ETF-only. Publication/version boundaries are documented.

[Final evidence report and hashes](security-master-sample-results-2026-09-07.md).
Review corrected omitted matched rows/raw tokens; count conservation now tests the
complete reconciliation. Eleven focused tests pass; final Standards and Spec
reviews are clear. Full suite: **1,152 passed**, 32.73 seconds.

Next: a bounded cross-date master batch through the verified endpoint, per-date
reconciliation and version checks, then documented normalization/availability and
dated eligibility. This closes sample access, not the entire archive or all
corporate-action/identity prerequisites. No strategy tuning, Kite usage, purchase,
order, external message, live activation or automation-state change occurred.

## Owner build next — cross-date acquisition and candidate screen

The five-date sample was frozen before acquisition. The runner makes one bounded
request per uncached session, saves failures, reuses verified cached bytes and
rejects corruption. Four NSE master requests plus the existing January capture
completed the probe; repeating capture made zero requests. No Kite calls or credits.

January 6, 2025 reconciles all 2,976 observations and April 1 all 3,014. March 28 matches
3,000 of 3,001; its raw AHL identity differs from master AFSL despite shared ISIN and
token, so the row remains missing rather than being joined by symbol fallback.
February 5, 2024 returned 404. September 3, 2026 returned a 120-field master with changed
fields 24 and 59; the old schema rejects it. Bounded source research did not establish
the two new definitions/effective dates. These are concrete coverage gaps, not
evidence of archive-wide absence or acceptable silent repairs.

Three validated masters retain 87,835 normalized rows with separate broad type,
market identifier, status, eligibility and permission. Provisional candidate counts
among matched observations are 1,760 / 1,858 / 1,863 respectively. All rows retain
ordinary-share, board, schema and historical-availability blockers. No candidates
are admitted to a backtest or trading universe. Full daily history is still needed.

Review fixed malformed-DEFLATE batch abortion and missing row-level token-conflict
annotations. Both Standards and Spec reviews cleared. Focused suite: 33 passed; full
suite: **1,174 passed in 30.28 seconds**. Final v2 audit pins all responses and receipts,
including failures, while preserving v1 plan/report/original source bytes.

[Results, hashes and reproduction](security-master-batch-results-2026-09-07.md).
Next: establish the changed dated schema and AHL/AFSL identity timing, acquire a
frozen contiguous daily block, then formalize lagged metadata knowledge and stock
eligibility. No new strategy performance claim, full-portfolio rerun, order,
purchase, activation, external message or automation change occurred.

## Owner go — dated schema and preceding-session identity agreement

CMTR73845 and its attachment resolve the September schema: effective August 3,
2026, field 24 becomes CAS eligibility and field 59 changes its tag while remaining
filler. Field 23 also becomes filler despite retaining its header. The new daily
auditor applies the exact dated header and preserves fillers without interpretation.
CML67269 documents AHL → AFSL from April 1, 2025. Its March 28 master discrepancy
is now explicitly identified as ahead of the effective symbol, without source repair.

The frozen initial plan contains January's 23 sessions, nine around the rename,
and the cached September 3 probe. V2 adds September 2 solely to test the preceding
snapshot for TCC. Thirty new NSE master requests plus four reused files produce
29 validated masters with 852,039 retained normalized rows. Five HTTP 404 gaps remain:
January 13 and 22, and April 2–4. Longest validated runs are eight January sessions
and six transition-window sessions. No master is carried across a missing date.

The key diagnostic compares each raw session with its immediately preceding
exchange-session master. **All 80,320 observations across 27 available pairs match
exactly.** On the 24 dates where both source choices exist, same-day masters match
71,429 / 71,442 versus 71,442 / 71,442 using the preceding master. The 13 discrepancies
in that paired subset therefore disappear. This supports an explicit research
snapshot policy; it does not certify archival publication time or ordinary-stock
eligibility. September 2's own MANBRO/KDGREEN discrepancy is unpaired because
September 1 is outside the sample, and remains unresolved.

[Daily results, source notes and all final hashes](security-master-daily-results-2026-09-07.md).
The new module preserves exact identities, records notice diagnostics separately,
validates full calendar windows, and writes deterministic gzip JSONL artifacts.
Focused suite: 52 passed. Full suite: **1,193 passed in 31.55 seconds**. Standards
and Spec reviews found no actionable issues. A repeat capture made zero requests.

Next: implement the explicitly labelled preceding-session metadata policy with
missing-snapshot entry blocks, establish ordinary-share/board and price-history
identity continuity, then expand the frozen daily coverage and rerun the coherent
portfolio against Nifty 500 TRI. No new strategy result, Kite call/credit usage,
order, purchase, activation, external message or automation change occurred.
