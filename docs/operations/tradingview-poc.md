# TradingView strategy POC

This is the fast, independent screening workflow demonstrated in Zerodha's
TradingView/Claude backtesting video. It does not depend on AccelPix and it does
not authorize live capital.

The Pine asset is [`tradingview/sensei_strategy_poc.pine`](../../tradingview/sensei_strategy_poc.pine).
It contains a selector for the five current Sensei RuleSpecs and uses their
actual executable conditions, stops, targets, and holding periods.

## Frozen experiment

Do not change rules or thresholds after looking at results. A changed condition,
parameter, date, cost, or symbol basket starts a new experiment.

- Chart interval: `1D`.
- Initial capital: ₹3,00,000.
- Position model: one long position at a time per chart, using 100% of that
  chart's current equity.
- Entry: signal at daily close, market fill at the next session open. Protective
  stop and target prices are frozen from the signal close and submitted with
  the entry. This avoids TradingView's historical after-fill look-ahead.
- Friction: 0.125% commission per order (0.25% round trip) and one tick of
  slippage per order.
- Development window: 2019-01-01 through 2023-12-31.
- Development last entry-signal date: 2023-12-28. This ensures a next-session
  fill cannot cross into the holdout.
- Development last exit-session date: 2023-12-29, the final NSE session of the
  frozen development period. Any open position is liquidated at that close.
- One-use holdout: 2024-01-01 through the most recent complete session.
- Use split-adjusted equity charts consistently. Do not switch dividend
  adjustment on for only some runs.
- Bar Magnifier is disabled for this Basic-plan-compatible screening run. A
  future high-detail run is a separate experiment and must not be mixed with
  these results.

Use this pre-registered, sector-diverse NSE basket. It was selected before any
TradingView result was inspected:

`ASIANPAINT, BHARTIARTL, DRREDDY, HDFCBANK, HINDUNILVR, ICICIBANK, INFY, ITC,
LT, M&M, MARUTI, NTPC, POWERGRID, RELIANCE, SBIN, SUNPHARMA, TATASTEEL, TCS,
TITAN, ULTRACEMCO`.

This current-survivor basket is acceptable only for rapid signal screening. It
is not survivorship-honest evidence and cannot certify real capital.

## Procedure

1. Open one basket symbol in TradingView and select the daily chart.
2. Open Pine Editor, paste the Pine asset, save it, and add it to the chart.
3. Select one RuleSpec and set the development dates.
4. Export Strategy Tester `List of trades` as CSV. Name it
   `<rulespec>__<symbol>__development.csv`.
5. Repeat across the frozen basket without editing any rule.
6. Put all exports in one directory and run the deterministic analyzer:

   ```bash
   uv run python -m sensei.research.tradingview_report \
     path/to/exports --phase development
   ```

   It prints a JSON report and a pass/fail verdict. It fails closed on missing
   columns, malformed values, filename mismatches, or exports from the wrong
   date window.
7. Only a strategy that passes development may be run once on the holdout.
8. Save the holdout exports separately. Never tune from holdout results.

## Development gate

A strategy must satisfy every condition after modeled costs:

- at least 100 closed trades across the basket;
- positive median net return per trade;
- aggregate profit factor at least 1.25;
- maximum drawdown no greater than 15%;
- positive net profit on at least 60% of tested symbols;
- positive net profit in both 2019-2021 and 2022-2023; and
- no single symbol contributes more than 25% of aggregate net profit.

The analyzer treats each TradingView chart as an independently funded ₹3 lakh
account. Aggregate profit factor and concentration sum those equal-capital
accounts. Maximum drawdown is the worst independently reconstructed per-symbol
equity drawdown. The reconstruction conservatively assumes each trade's exported
run-up occurred before its exported drawdown. These are screening metrics, not a
shared-capital portfolio.

## Holdout gate

The frozen strategy must then satisfy every condition on 2024 onward:

- positive net profit after costs;
- profit factor at least 1.15;
- maximum drawdown no greater than 15%;
- positive net profit on at least 50% of symbols; and
- no single symbol contributes more than 30% of aggregate net profit.

Failure means `REJECTED` for the current version. Passing means
`CANDIDATE_FOR_PORTFOLIO_VALIDATION`, not permission to trade real money.

## Known TradingView differences

- TradingView tests one chart at a time. It does not model Sensei's shared ₹3
  lakh cash, cross-sectional signal ranking, five-position rail, or sector
  concentration.
- Without Bar Magnifier, TradingView's broker emulator infers the intrabar price
  path. Sensei conservatively assumes the stop is hit first when stop and target
  are both touched in one daily bar. Treat such ambiguous trades as stop-first
  during final analysis.
- TradingView screening freezes protection from the signal close rather than
  the next-open fill because the latter requires historical after-fill
  recalculation and triggers a look-ahead warning. Final portfolio validation
  must continue using Sensei's actual fill-price-based protection.
- The current Sadekar RuleSpec does not implement the prose description
  "follow-through above the hammer high". It requires a hammer and a close above
  the previous close on the same session. The Pine script preserves that
  executable behavior so the comparison is honest.
- Results on the fixed current-survivor basket are screening evidence only.
  Portfolio validation still requires point-in-time membership and shared-capital
  simulation before a real-capital decision.
