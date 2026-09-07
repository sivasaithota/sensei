# Real BSE bonus and indicator replay

The real BSE bonus and full-warmup BSE/HEG replay pass the preregistered checks.
This adds dated signal, score and correlation evidence across a real bonus;
it does not add a portfolio result or establish strategy profitability.

The [contract](../specs/bonus-indicator-replay.md) and
[plan](../../config/bonus-indicator-replay-v1.json) were written before replay.
Raw history spans 13 May 2024–30 May 2025: **262 sessions**, two instruments and
524 identity-checked stock/session rows. Eleven daily decisions span 16–30 May
2025, with 252 observations through the first decision and 262 through the last.

## Dated events and explicit dividend policy

The [contemporary BSE evidence](dated-bse-bonus-publication-evidence-2026-09-07.md)
establishes INE118H01025, two additional shares per existing share, and the
23 May ex-date. Total shares are **3/1**, not 2/1. Only the 12 May company notice
and 14 May exchange circular establish the modeled 15 May first-known session.
The 26 May allotment confirmation is post-event corroboration and never supplies
earlier knowledge. These printed-date conventions do not prove historical upload
times or actual broker credit/tradability for a particular holding.

The pinned observed action list has five rows: BSE's June 2024 and May 2025
dividends, HEG's July 2024 AGM/dividend, HEG's October 2024 split and BSE's May 2025
bonus. All five require explicit matching treatments. `share-unit-price-only-v1`
retains dividend price moves and applies no dividend adjustment to indicators.
It neither ignores those rows in coverage nor simulates their cash entitlements.
Any extra, missing or unsupported observed action blocks the diagnostic.

Raw currency turnover remains unchanged and feeds the existing trailing-60-session
liquidity calculation. The policy is fixed here; it does not replace frozen
portfolio inputs. Each action's factor applies only to earlier rows, after both
the action's effective and modeled knowledge sessions.

## Outcomes

All **28,270 OHLCV cells** and **5,654 Boolean signal cells** match the independent
rational-factor history. Every ranking component and pairwise correlation matches
the oracle at all 11 cutoffs. Full and truncated inputs give identical histories,
and raw inputs remain unchanged. The checks reject an omitted bonus factor, future
dependence and an effective bonus whose knowledge is later than the decision.

The BSE raw preceding close is **₹6,996.50**. In ex-session units it is
**₹2,332.1666666666665**, compared with the ex-session raw close of **₹2,448**.
No execution-tick rounding or physical bonus shares are inferred from this value.

| Diagnostic observation | Dated history | Unnormalized raw contrast |
|---|---:|---:|
| BSE total ranking score, 23 May | 0.671076 | 0.254846 |
| BSE/HEG return correlation, 26 May | 0.223495 | 0.008597 |
| BSE total ranking score, 30 May | 0.732950 | 0.261303 |
| BSE breakout signal, 30 May | True | False |

Score order differs on six decisions; one latest signal differs. Score order
includes both diagnostic stocks, while signal-eligible ordering is reported
separately. These are not six changed trades. The correlation policy intentionally
retains its existing exclusion of the latest return, so the bonus-related raw
discontinuity first affects that comparison on 26 May.

The contrast is deliberately unnormalized raw history. **It is not a comparison
against the frozen Kite-adjusted portfolio**, and does not establish that the
previous backtest missed BSE's signal. Portfolio capital, return and drawdown
results remain unchanged. No holding, order, admission, fee or entitlement is
simulated in this pass.

## Verification and artifacts

Thirteen focused tests cover full warmup, missing sessions, bonus ratio orientation,
explicit dividend classification, observed-action coverage, scalar-oracle failures,
future dependence, negative controls and input mutation. A cloned-instrument
synthetic fixture initially exposed floating-point tie ordering. The normal fixture
now uses distinct profiles; the diagnostic still rejects an actual/oracle order
disagreement and does not widen tolerances. The real instrument pair passed.

Standards review found that the initial combined negative-control loop could
accept a silent raw fallback for later knowledge. The controls are now separate:
the missing factor must disagree with the oracle, and the later-known event must
raise the expected error. Silent fallback and mutation-on-rejection regressions
cover the fix. Final reviews have no remaining findings.

Full suite: **1,083 passed**, 29.02 seconds.

Final artifact:
`data/reports/bonus-indicator-replay/45f45f67dceb4fc7e997c5c0b19fb7d5acf73097680415f7e83e40c1b4a78309/report.json`.
The directory equals the report SHA-256. Plan SHA-256:
`5c9d816ed20bdd57c417ca3f00419be3b501455f42247e5eaee75a4cd4759ec3`.
The report includes the plan, implementation and dependency pins, source manifests,
all raw receipts, all five observed actions and every decision result. The earlier
artifact is retained but superseded after strengthening the negative controls.

```sh
.venv/bin/python -m sensei.research.bonus_indicator_replay
```

The raw and PDF captures remain in their local research archives. Reproduction
requires those pinned bytes. No Kite calls or credits, purchases, live orders,
external messages or automation resumption occurred.

## Next integration requirements

This resolves the real bonus and scoped indicator/ranking replay milestone. It
does not provide complete historical membership, corporate-action history or data
vintages. Physical entitlements, credit timing and fractional settlements remain
separate before holdings can cross mandatory actions in a portfolio. A wider
strategy evaluation must keep these requirements explicit and retain all rejected
experiments. The result remains RESEARCH_ONLY, DATA_BLOCKED and can_trade=false.
