# Market-state attribution — 7 September 2026

All four saved portfolios lost marked value on sessions classified below the
benchmark’s 200-session average. Yet the 60-session variant’s trades entered in
that state were slightly profitable over their full lives. Entry permission
and risk on existing holdings are different questions. This diagnostic does
not establish the return of a market filter, and no strategy was changed.

## Fixed definition and timing

The state for a session compares the **preceding** Nifty 500 gross TRI close
with the average of the **preceding 200** closes. Above means strictly greater;
equality belongs to at-or-below. Neither the current session nor future prices
can affect that session’s state. Less than 200 prior observations is unknown.
This rule was declared before inspecting the state-attributed outcomes.

The 2024-01-01 through 2026-09-03 evaluation has **504 above-average sessions
and 161 at-or-below sessions**. All have sufficient preceding benchmark history.
No dates, securities, prices or trades were dropped. The same fixed state
definition applies to all four runs.

## Complete trades grouped by state at entry

A trade remains in its entry cohort even if the market state changes before
exit. Values include all of its realised P&L and costs; they are not the result
of replaying only that subset of orders.

| Run | State at entry | Trades | Stop/gap-stop exits | Net P&L | Costs |
|---|---|---:|---:|---:|---:|
| control | above_sma200 | 351 | 228 | ₹+37,352.25 | ₹51,390.66 |
| control | at_or_below_sma200 | 116 | 80 | ₹-42,690.29 | ₹16,800.91 |
| hold60 | above_sma200 | 327 | 220 | ₹+28,022.46 | ₹47,978.87 |
| hold60 | at_or_below_sma200 | 114 | 77 | ₹+1,831.02 | ₹16,744.99 |
| hold60-target20 | above_sma200 | 185 | 135 | ₹+42,168.00 | ₹26,474.40 |
| hold60-target20 | at_or_below_sma200 | 83 | 65 | ₹-63,308.31 | ₹11,268.18 |
| trend-hold60-target20 | above_sma200 | 172 | 126 | ₹+21,731.43 | ₹24,791.87 |
| trend-hold60-target20 | at_or_below_sma200 | 78 | 61 | ₹-42,354.08 | ₹10,421.62 |

The original baseline’s at-or-below entry cohort lost ₹42,690.29, whereas that
cohort in the 60-session variant gained ₹1,831.02. This difference prevents a
blanket claim that every trade opened below the average was harmful. The four
runs share most of their data and are not independent replications.

## Actual daily marked P&L and exposure

This separate view attributes the actual daily change in total equity to the
state known before that session. Positions carry across state changes. Exposure
is the mean end-of-day invested value divided by end-of-day equity, not an
intraday average or a claim of capital available at the opening bell.

| Run | State before session | Sessions | Daily marked P&L sum | Mean EOD utilization |
|---|---|---:|---:|---:|
| control | above_sma200 | 504 | ₹+80,997.25 | 75.693% |
| control | at_or_below_sma200 | 161 | ₹-86,335.29 | 72.649% |
| hold60 | above_sma200 | 504 | ₹+99,756.62 | 74.178% |
| hold60 | at_or_below_sma200 | 161 | ₹-69,903.12 | 71.313% |
| hold60-target20 | above_sma200 | 504 | ₹+76,556.13 | 87.301% |
| hold60-target20 | at_or_below_sma200 | 161 | ₹-97,696.48 | 84.533% |
| trend-hold60-target20 | above_sma200 | 504 | ₹+55,457.00 | 86.539% |
| trend-hold60-target20 | at_or_below_sma200 | 161 | ₹-76,079.67 | 78.646% |

The baseline remained 72.649% invested on average during below-average sessions,
which contributed −₹86,335.29 in marked P&L. All variants retained substantial
exposure in that state. This suggests a specific risk-control question worth
testing, but does not imply those losses would disappear under an entry gate.
Some holdings were opened in an above-average state and subsequently crossed
into a below-average state; a new-entry restriction would leave them in place.

Trade-cohort sums can differ from daily equity sums by a few paise because each
trade amount is rounded separately. The earlier attribution records this
reconciliation residual explicitly. Daily groups reconcile to the campaign’s
final net P&L. Neither table is an annual return, causal treatment effect or
newly earned out-of-sample result.

## Reporting defect found and fixed in review

The first implementation checked the equity calendar between the curve’s own
minimum and maximum dates. Review showed that dropping its first session could
still reconcile final P&L while moving the missing day’s loss into a later state.
The corrected implementation requires the full frozen evaluation start/end from
the verified run settings, then checks every expected benchmark session. Tests
reject first, last and interior omissions before attribution.

All four original curves were complete. Regeneration with the corrected check
preserved the observed metrics. Earlier derivative artifacts remain on disk;
the final reviewed artifact IDs below bind the corrected code. No backtest
engine, source trade or original campaign result was altered.

## Artifacts and verification

The existing source report/manifest, settings, Kite provenance, scoped frame and
benchmark checks remain required. The derivative now also binds the market-state
module hash. All prior per-trade/ATR attribution fields exactly match the saved
pass-2 derivatives. New files remain research-only, DATA_BLOCKED and can_trade=false.

| Run | Final reviewed derivative ID |
|---|---|
| control | `229c5bc772f232aa41ccb405d78003cf8afba31ad3b706874b4ae32636a466a1` |
| hold60 | `50fde6a2e3f9c94d67afd1a82dbb747fdbbf0f697597fde8ca934d276f2a6759` |
| hold60-target20 | `999615ab66fa362dfbc720194f6cbc0fada325819887e5c6617ed548c97f20d2` |
| trend-hold60-target20 | `87fdcfcd1299912bcde679dfa537145256752e73026f2bd3d4be99b07d031454` |

Files: `data/reports/stock-attribution/<ID>/report.json`. Each ID is the content
SHA-256. Index: `data/reports/stock-attribution/market-index-20260907.json`.
The full session rows include the preceding benchmark close and average used.

```bash
.venv/bin/python -m sensei.research.stock_attribution \
  --report data/reports/stock-development/7e9a282839b09e84f25668c3e20bf60bbfa8e8372079e8c21ae2bbaa2411a579/report.json
```

Validation: **911 tests passed**. Standards review cleared; the Spec calendar
finding was fixed and re-reviewed with no remaining implementation findings.
Tests cover timing, warmup, invalid benchmark data, unknown states, holdings
crossing state changes, calendar boundaries and equity reconciliation.

## Next bounded experiment

Predeclare a separate SMA200 new-entry gate on the original baseline and its
60-session counterpart, with the same fixed benchmark timing, demerger policy,
universe, sizing, costs and all other settings. Existing holdings must continue
through their original exits. Unknown benchmark state must not permit entry.
Run each once, preserve both controls, and report all outcomes without adjusting
the moving-average length or selecting a favorable date window. This is reused
development history; membership and shareholder accounting remain uncertified.
Do not introduce an automatic liquidation policy based on this attribution.

No new Kite requests, subscriptions, credentials or live orders were used.
