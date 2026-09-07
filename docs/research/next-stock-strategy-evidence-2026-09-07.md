# Next stock strategy: evidence and priority

Reviewed 2026-09-07. Research only: no strategy changes, runs or orders.
Scope: one ₹300,000, long-only NSE cash-equity account. This narrows the
[previous evidence note](stock-strategy-evidence-2026-09-06.md).

The supplied local result is that four generic variants—55-day breakout with
30/60-day exits, 50-DMA pullback and RSI(2)—lost approximately 23–56% net over
January 2025–early September 2026. Those results were not rerun for this note.
They reject those implementations over that interval; they do not test every
form of momentum or establish that more indicators will help.

The current local diagnosis also reports shared ranking and percentage
stop/target machinery across the four variants. Gross P&L was negative for
all four, so fees are material but not the whole explanation. These shared
choices confound attributing losses to entry signals alone. Controls that
isolate selection, exits and turnover are more informative than changing them
all together; this observation does not establish a causal software bug.

## Recommendation

**Better-defined ideas are needed; the first should be medium-term relative
strength across stocks.** Rank eligible stocks against one another using
six- and twelve-month volatility-adjusted returns, then hold a diversified,
slowly rebalanced portfolio. This changes stock selection and holding horizon
materially from buying a stock because it crossed its own 55-day high. Treat
it as a research candidate, not an established retail edge.

1. **First: one price-only momentum baseline.** Freeze the universe, ranking,
   rebalance schedule and account-level risk budget before inspecting outcomes.
   Use the official index construction below as the reference. If a retail
   version changes weights, holding count or cadence, identify it as a separate
   hypothesis; do not claim exact index replication. For ₹300,000, model integer
   shares, residual cash, turnover, sale charges and executable fills explicitly.
   Thirty equal allocations would average ₹10,000 before cash and rounding;
   the official index itself is not equal weighted.
2. **Second: improve evidence depth before adding families.** Reliable raw
   execution/accounting history is currently limited to January 2024–early
   September 2026. A twelve-month formation period leaves roughly January
   2025 onward for evaluation: too little regime diversity to establish durable
   edge. Use this as a rejection/development screen. Extend trustworthy older
   raw prices, corporate actions and historical eligible-universe coverage;
   older adjusted signal prices alone do not establish executable returns.
   Compare with the parent total-return index and a costed passive alternative
   over identical dates. Previously examined dates remain examined; a new
   configuration does not create an untouched holdout.
3. **Third: controls and portfolio risk design within that one family.**
   Distinguish ranking from volatility-aware sizing, and compare the portfolio
   with its broad-universe control. Isolate inherited percentage brackets and
   turnover effects rather than copying them unquestioned into a slower
   holding strategy. Set position and sector concentration limits from the
   account mandate before results. A new name does not turn a previously
   rejected market-gate variant into fresh evidence. These are proposed
   research controls, not rules validated by the cited crash paper.
4. **Later: quality plus momentum.** The current validated dataset does not establish the required
   point-in-time historical fundamentals. Wait for original filings, public availability timestamps, revisions
   and enough comparable history. Today's ROE/debt/EPS snapshots cannot be
   inserted into earlier decisions. Archived-news or earnings-event strategies
   likewise wait for admissible timestamped inputs; they are not next merely
   because the current entries failed.

## Four primary sources and their limits

- **NSE Nifty200 Momentum 30 factsheet, dated August 31, 2026.** Selects 30
  Nifty 200 companies using six- and twelve-month price returns adjusted for
  daily-return volatility; weights combine free-float capitalization and
  normalized momentum, with caps; June/December rebalancing. Launch:
  **August 25, 2020**; base: **April 1, 2005**. History before launch is
  backfilled, not a contemporaneously published live index record. Post-launch
  index calculation is still not a funded retail account after expenses and
  execution friction. This establishes a transparent construction, not proof
  that a concentrated, faster-trading adaptation will profit.
  [Official factsheet](https://www.niftyindices.com/Factsheet/Factsheet_Nifty200_Momentum30.pdf).
- **NSE Nifty500 Multicap Momentum Quality 50 factsheet, dated August 31,
  2026.** Combines volatility-adjusted six/twelve-month momentum with quality
  based on ROE, debt/equity and five-year EPS growth variability; composite
  factor/free-float weights, 5% caps at rebalance, semiannual reviews. Launch:
  **September 4, 2024**; base: **April 1, 2005**. Its long since-base history
  therefore contains extensive backfill. The blend's existence motivates a
  future hypothesis; it does not prove adding quality improves our momentum
  candidate. Exact replication also requires historical eligibility and
  free-float inputs, beyond prices and current financial ratios.
  [Official factsheet](https://www.niftyindices.com/Factsheet/Factsheet_Nifty500MulticapMQ50.pdf).
- **Daniel and Moskowitz, “Momentum crashes,” JFE (2016).** Reports sharp
  momentum losses around rebounds following declines and high volatility.
  A central mechanism is the strong rebound of the short loser portfolio in
  winner-minus-loser strategies. Transfer the need to inspect stressful
  reversals, not its loss magnitudes or hedging prescriptions, to a long-only
  Indian account. The paper does not validate a particular NSE sizing rule.
  [Authors' published paper](https://www.kentdaniel.net/papers/published/jfe_16.pdf).
- **Bailey and López de Prado, “The Deflated Sharpe Ratio” (2014).** Explains
  performance inflation from selecting among many trials and non-normal
  returns. Record failed variants and manual tuning, limit the search, and
  reserve genuinely future observations for confirmation. A precise deflated
  statistic needs the relevant trial/history assumptions; it cannot cure
  insufficient data, bad accounting or information leakage.
  [Authors' paper](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf).

No return target, allocation recommendation or live-capital decision follows
from these sources. The immediate deliverable is a small, explicit hypothesis
and an evidence-gap decision—not another broad implementation campaign.
