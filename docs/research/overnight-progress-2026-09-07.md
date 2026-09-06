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
