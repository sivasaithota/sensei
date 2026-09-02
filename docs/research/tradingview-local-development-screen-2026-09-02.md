# Frozen local development screen: all five RuleSpecs

Date: 2026-09-02

Phase: development only, 2019-01-01 through 2023-12-31

Capital model: independently funded ₹3,00,000 account per symbol

Overall verdict: **all five REJECTED; do not inspect the 2024+ holdout**

## Why this run exists

TradingView's Basic plan blocked CSV export and browser automation was too slow
and unreliable for a 100-chart experiment. The same frozen experiment was
therefore reproduced locally with the executable Sensei RuleSpecs. The runner
uses next-session-open entries, signal-close protection, stop-first treatment
of ambiguous daily bars, the frozen costs and dates, and forced liquidation on
the final development session.

This is a fast rejection screen over the current-survivor Yahoo parquet store.
It is not survivorship-honest evidence and cannot authorize the holdout, paper
promotion, or real capital. Aggregate net profit below sums twenty separately
funded accounts; it is not the return on one shared ₹3 lakh portfolio.

## Results

| RuleSpec | Trades | Net profit | Median trade | Profit factor | Worst realized DD | Positive symbols | Largest contribution | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `minervini_breakout_volume` | 202 | +₹1,182,080 | +1.22% | 1.532 | 39.98% | 65% | 15.56% | **REJECTED** |
| `minervini_trend_template` | 265 | +₹2,289,969 | +0.24% | 1.670 | 38.81% | 75% | 14.78% | **REJECTED** |
| `gujral_trend_alignment_dual_ma` | 491 | +₹1,248,784 | -1.50% | 1.297 | 40.17% | 75% | 18.40% | **REJECTED** |
| `sadekar_hammer_confirmation` | 167 | +₹71,554 | -0.89% | 1.062 | 19.38% | 50% | 94.92% | **REJECTED** |
| `schwager_trend_with_pullback_strength` | 141 | +₹728,060 | -0.87% | 1.577 | 25.95% | 60% | 29.30% | **REJECTED** |

The maximum-drawdown gate was 15%. Every strategy exceeded it. Four of five
also failed at least one additional gate:

- Minervini breakout: excessive drawdown.
- Minervini trend: excessive drawdown.
- Gujral alignment: negative median trade and excessive drawdown.
- Sadekar hammer: negative median, weak profit factor, excessive drawdown,
  insufficient breadth, a negative 2019-2021 segment, and extreme symbol
  concentration.
- Schwager pullback: negative median, excessive drawdown, and excessive symbol
  concentration.

Positive summed P&L does not rescue a failed pre-registered gate. In particular,
large drawdowns, plus negative median trades in three strategies, describe a
fragile payoff rather than a capital-ready process.

## Cross-check against TradingView

The manually completed TradingView Minervini breakout screen independently
reached the same rejection: negative median and 42.47% worst drawdown. Its trade
count and P&L differ from the local reproduction because TradingView and Yahoo
do not share identical adjusted bars, tick metadata, or broker-emulator rules.
Those differences reinforce why the local runner is restricted to rejecting
weak candidates rather than certifying successful ones.

## Decision

Do not run any of these versions on the one-use 2024+ holdout. Do not tune their
parameters against these results. The current five strategies have reached a
terminal POC conclusion: none satisfies the frozen development standard.

The next strategy experiment must be a materially new, pre-registered
hypothesis with explicit portfolio drawdown control. It should first pass this
cheap local rejection screen, then the exact TradingView development export,
then a point-in-time shared-capital portfolio test before any real-capital
canary is considered.
