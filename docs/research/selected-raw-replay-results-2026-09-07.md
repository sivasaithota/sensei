# Selected trades replayed with raw prices and physical shares

Pass 9 completed a bounded raw-price replay of four distinct saved entries,
retaining all eight records across the baseline and hold60 controls. Each case
uses full initial cash independently. This is a forced-entry diagnostic, not a
complete strategy or portfolio rerun; no revised portfolio return is claimed.

## Evidence and execution

NSE's symbol-filtered, all-purpose calendar-2024 action responses contain two
HEG and three MAZDOCK actions, none inside the selected holding intervals.
The exact bodies and request manifest are retained under
`data/reports/raw-replay-action-evidence/`. Manifest SHA-256:
`488cf83426507a7747ac0548f87e08f17ebb713282edfd4ec05be5bcb0ebc9e9`.
[Coverage and provider limits](selected-raw-replay-action-coverage-2026-09-07.md).
The initially missing action coverage was resolved before any replay result;
no conditional replay was executed.

All required benchmark sessions from the predecessor through each saved exit
were matched to verified raw NSE EQ rows with the expected old ISIN. The result
pins 28 raw-session receipts, original report/proof hashes, action captures,
source-note hashes and implementation. Missing or mismatched evidence blocks
the case instead of being filled or silently dropped.

The optional constant-tick mode rounds the modeled buy fill upward after slippage,
the stop downward and target upward using decimal arithmetic. Sizing uses the
rounded stop and existing fee-inclusive cash/risk limits. The mode is a declared
single-fill modeling assumption; it does not claim to reproduce actual broker
fills or provide a general historical tick engine.

The selected cases use ₹0.05 based on the dated rules and raw reference closes.
For MAZDOCK's June and July cases, May 31 close was ₹3,184.05 and June 28 close
₹4,281.45, both above the then-relevant ₹250 threshold. Those reference sessions
are included in the verified receipts. The assignment is rule-based evidence,
not an archived security-master certificate. [Dated tick rules](nse-equity-tick-rules-2026-09-07.md).

## Isolated outcomes

| Entry | Physical shares | Raw modeled entry | Raw modeled exit | Saved net P&L | Raw replay net P&L |
|---|---:|---:|---:|---:|---:|
| HEG, 2024-04-16 | 24 | ₹2,432.20 | ₹2,310.55 | −₹3,137.04 | −₹3,061.88 |
| MAZDOCK, 2024-05-30 | 17 | ₹3,373.40 | ₹3,204.70 | −₹3,095.43 | −₹3,007.95 |
| MAZDOCK, 2024-06-18 | 15 | ₹3,907.65 | ₹4,376.60 | +₹6,880.55 | +₹6,881.11 |
| MAZDOCK, 2024-07-05 | 10 | ₹5,635.25 | ₹5,353.45 | −₹3,102.52 | −₹2,955.89 |

Each row appears in both controls with the same isolated result. Exit dates and
reasons match: May 3 stop, May 31 stop, June 27 target and July 5 stop. No case
required a forced horizon close. Reduced losses partly reflect smaller physical
positions; these differences are not strategy alpha or a correction to the
original portfolio cash path.

Final replay artifact:
`data/reports/raw-execution-replay/cea5aa633d5e9485264b7abe109d78c58ff5f01f69bf695c160e475aa1acc947/report.json`.
Its directory name equals its SHA-256. Plan: `config/selected-raw-replay-v1.json`.
All cases passed the scoped checks; the overall artifact remains DATA_BLOCKED,
research-only and unable to trade.

## Regression validation

**978 tests passed.** Independent Standards and Spec reviews clear. The Spec
reviewer verified all eight records, 28 receipts, quantities, prices and fee
arithmetic. Both complete controls were rerun with tick rounding omitted; every
trade, equity point and economic campaign value reproduces exactly after
excluding the new metadata and default-null tick field.

- Baseline rerun `dc2f2c35abed08eb4c86f5a43754edd3ace773aa5d1436cf2072442db2349e9d`:
  ₹294,661.96 final equity, 467 trades.
- Hold60 rerun `2bdc847ec4e4f14ae1d4e948d798d19d2ae2f4e2ea3f7c3dc228533f3ec9c480`:
  ₹329,853.50 final equity, 441 trades.

Parity record: `data/reports/stock-development/tick-rounding-control-parity-20260907.json`.
No Kite requests, new spending or live orders occurred. Public NSE action-history
requests were used to close the specific evidence gap.

## Next bounded step

Measure the same raw-calendar and action-history coverage for the remaining
saved holdings before broadening replay. Reuse raw sessions; capture missing
NSE sessions only where needed. Classify intervals crossing dividends, splits,
bonuses or demergers as requiring entitlement handling rather than forcing them
through this no-in-interval-action harness. Resolve dated tick evidence for new
intervals separately. Broader strategy comparisons need actual-price cash
accounting and explicit historical-universe limitations; this four-case result
does not establish a live-ready edge.
