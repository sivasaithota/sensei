# TradingView development-screen verdict: Minervini breakout volume

Date: 2026-09-02

RuleSpec: `minervini_breakout_volume`

Phase: frozen development window, 2019-01-01 through 2023-12-31

Capital model: independently funded ₹3,00,000 account per chart

Verdict: **REJECTED — do not run the holdout and do not allocate real capital**

## Method

The experiment followed the frozen settings and 20-symbol basket in
[`docs/operations/tradingview-poc.md`](../operations/tradingview-poc.md). Results
were read from TradingView's Strategy Tester in the signed-in desktop app. The
Basic plan did not permit CSV export, so this report records TradingView's
per-symbol summary figures and visible trade rows rather than claiming a
deterministic analyzer run.

TradingView displayed trade rows newest first. For symbols with more than eight
trades, the oldest visible row was in 2021 or earlier. Therefore all 2022-2023
trades were visible; 2019-2021 P&L was derived as authoritative total P&L minus
the visible 2022-2023 P&L.

This is a current-survivor basket and remains screening evidence only. It is not
survivorship-honest portfolio certification.

## Aggregate result

| Metric | Result |
|---|---:|
| Symbols | 20 |
| Closed trades | 175 |
| Profitable trades | 75 (42.86%) |
| Aggregate net P&L | +₹928,526.04 |
| Aggregate profit factor | 1.545 |
| Positive symbols | 15/20 (75%) |
| Worst per-symbol maximum drawdown | 42.47% (MARUTI) |
| Largest positive contribution | 17.06% (ULTRACEMCO) |
| 2019-2021 net P&L | +₹809,389.25 |
| 2022-2023 net P&L | +₹119,136.79 |

The positive aggregate P&L does not override the gate. Only 42.86% of trades
were profitable, so the median trade cannot have a positive net return. The
42.47% worst drawdown is almost three times the allowed 15% ceiling.

## Pre-registered gate

| Condition | Threshold | Result | Status |
|---|---:|---:|---|
| Closed trades | >=100 | 175 | PASS |
| Median net return per trade | >0 | Not positive; only 75/175 profitable | **FAIL** |
| Aggregate profit factor | >=1.25 | 1.545 | PASS |
| Maximum drawdown | <=15% | 42.47% | **FAIL** |
| Positive symbols | >=60% | 75% | PASS |
| Positive in both eras | Required | Both positive | PASS |
| Largest contribution | <=25% | 17.06% | PASS |

Every condition was required. Two failures make the strategy `REJECTED` for
this version. Per the frozen protocol, the 2024+ one-use holdout must remain
untouched.

## Per-symbol results

| Symbol | Trades | Net P&L | Profit factor | Max DD | Profitable trades |
|---|---:|---:|---:|---:|---:|
| ASIANPAINT | 9 | -₹47,402.49 | 0.509 | 18.39% | 22.22% |
| BHARTIARTL | 5 | +₹9,656.45 | 1.144 | 19.59% | 40.00% |
| DRREDDY | 11 | +₹20,294.81 | 1.158 | 22.46% | 36.36% |
| HDFCBANK | 5 | +₹38,779.11 | 2.022 | 10.91% | 60.00% |
| HINDUNILVR | 6 | -₹16,485.69 | 0.789 | 21.55% | 33.33% |
| ICICIBANK | 9 | +₹113,664.32 | 2.689 | 8.76% | 55.56% |
| INFY | 10 | +₹141,359.10 | 4.138 | 8.51% | 40.00% |
| ITC | 6 | +₹51,719.55 | 3.219 | 10.20% | 50.00% |
| LT | 11 | +₹46,075.27 | 1.469 | 23.02% | 54.55% |
| M&M | 11 | +₹89,719.57 | 1.748 | 17.31% | 45.45% |
| MARUTI | 7 | -₹104,213.54 | 0.120 | 42.47% | 14.29% |
| NTPC | 12 | +₹67,573.93 | 1.950 | 20.08% | 41.67% |
| POWERGRID | 13 | +₹520.96 | 1.004 | 25.73% | 23.08% |
| RELIANCE | 4 | -₹3,658.68 | 0.937 | 14.18% | 25.00% |
| SBIN | 11 | -₹13,110.13 | 0.909 | 33.49% | 18.18% |
| SUNPHARMA | 6 | +₹83,388.25 | 20.236 | 7.39% | 83.33% |
| TATASTEEL | 10 | +₹151,435.08 | 1.812 | 28.80% | 50.00% |
| TCS | 7 | +₹83,978.65 | 2.287 | 10.27% | 57.14% |
| TITAN | 11 | +₹56,862.73 | 1.542 | 26.98% | 45.45% |
| ULTRACEMCO | 11 | +₹158,368.79 | 3.234 | 19.98% | 72.73% |

## Decision

Do not tune this result and do not inspect its holdout. A changed rule,
parameter, cost, date, or basket must be registered as a new experiment. The
next productive step is to formulate a materially different strategy hypothesis
with a drawdown-control mechanism, then run a new frozen development screen.
