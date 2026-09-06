# Stock strategy evidence and a bounded research campaign

Reviewed: 2026-09-06. Scope: personal, long-only, unlevered NSE cash equities.
This is a research recommendation; it changes no strategy, lifecycle, account,
holdout access, or execution state. Published evidence and proposed local rules
are deliberately distinguished below.

## Conclusion

Keep the platform, but reduce the strategy search to one finite campaign. Start
with transparent medium-horizon relative strength; compare an exposure-controlled
version separately; defer a slow quality/value family until its historical
accounting inputs are admissible. More agents and more entry indicators cannot
substitute for an executable, benchmarked portfolio with trustworthy data.

No examined source establishes a best-performing retail bot or proves an edge
for Sensei. A useful objective is positive after-cost excess return against an
appropriate passive alternative within an agreed account drawdown budget.
Benchmark-relative returns, capital efficiency and uncertainty matter alongside
absolute profits. A lower-risk mandate can rationally accept lower absolute
returns, but that mandate must be fixed before selecting results.

## What the repository already establishes

- The [August diagnosis](existing-strategy-diagnosis-2026-08-07.md) showed
  Minervini breakout positive in eight of nine window/cost cells. Its five-year
  base-cost return was +24.95% cumulatively, approximately 4.56% annualized
  assuming exactly five years, not 24.95% per year. No matching benchmark was
  supplied. Current-constituent and complete-series filtering biased coverage.
- The newer [September local screen](tradingview-local-development-screen-2026-09-02.md)
  rejected all five existing versions. Minervini breakout exceeded the frozen
  drawdown ceiling locally and in the [TradingView screen](tradingview-minervini-breakout-development-2026-09-02.md).
  The old “provisional survivor” description is therefore not a current
  promotion decision. Keep those versions rejected under their original rules.
- These results measure different objects: thousands of independently simulated
  signals, twenty separately funded single-stock accounts, and a shared-capital
  account are not interchangeable. Summed chart profits cannot establish the
  return on one ₹3 lakh account. See the [August validation campaign](../operations/strategy-validation-campaign.md).
- The September positive-median-trade gate deserves prospective redesign. As a
  mathematical example, 40% wins of +3R and 60% losses of -1R have +0.6R mean
  expectancy before costs and a negative median. A negative median alone does
  not disprove a positively skewed strategy. Likewise a worst single-stock
  account drawdown is not a diversified account drawdown. Neither observation
  rescues an old rejected version; register a new portfolio-level protocol.
- A fresh configuration hash does not create fresh information. Earlier
  campaigns already examined recent history. The proposed 2024+ “holdout” must
  be audited for researcher exposure across the entire campaign history,
  including aggregate results. Treat previously consulted periods as
  development/validation and retain genuinely future data for confirmation.

The [point-in-time specification](../specs/point-in-time-market-data.md) explicitly
excludes raw corporate-action application and rejects the legacy Yahoo universe
for governed evidence. The [data continuity note](sustainable-daily-indian-equity-data-2026-08-23.md)
also distinguishes daily ingestion from historical membership and delisting
coverage. More recent bars alone do not repair those historical gaps.

## Bounded strategy families

### 1. Medium-horizon relative strength — first implementation candidate

**Published India-specific evidence.** NSE's Nifty200 Momentum 30 uses six- and
twelve-month returns adjusted for volatility. Its published construction uses
30 constituents, factor-tilted capitalization weights, caps and semiannual
rebalancing. This is an implementable reference specification, not a guarantee
of profits. [Official index page](https://www.niftyindices.com/indices/equity/strategy-indices/nifty200-momentum-30),
[factsheet](https://www.niftyindices.com/Factsheet/Factsheet_Nifty200_Momentum30.pdf).

The April 2026 NSE paper reports 19.19% annualized for Nifty200 Momentum 30
versus 15.08% for Nifty 200 from its 2005 base date through February 27, 2026,
using total-return series. It also reports a 67.7% maximum drawdown for the
momentum index. This is provider-produced index research, not after-cost retail
execution. The factsheet states an August 25, 2020 launch, so pre-launch history
is not a live track record. [NSE paper](https://www.niftyindices.com/docs/default-source/indices/nifty200-momentum-30/momentum-strategy-whitepaper_2026.pdf),
[launch and base dates](https://www.niftyindices.com/Factsheet/Factsheet_Nifty200_Momentum30.pdf).

**Proposed local experiment.** First reproduce the documented index selection
and rebalance conventions where historical inputs permit. Separately register a
retail implementation with integer shares, one shared account, explicit cash,
membership on the trading date, a liquidity floor and deterministic tie-breaking.
If substituting equal weights, fewer holdings or monthly rebalancing, name it a
new hypothesis rather than an index replication. Do not search portfolio count,
lookbacks, rank buffers and rebalance frequency simultaneously.

Use the corresponding parent TRI, the momentum TRI and a costed passive
implementation as references. A concentrated five-stock sleeve must not inherit
the diversification or evidence of a thirty-stock index. Historical free-float
inputs unavailable for exact replication should be declared missing, not filled
with today's values.

### 2. Exposure-controlled momentum — paired risk hypothesis

**Published general evidence.** Moreira and Muir find benefits from reducing
factor exposure when volatility is high. Other original research finds that
out-of-sample volatility-managed portfolios do not systematically outperform
their unmanaged counterparts. Neither paper validates a particular NSE filter.
[Moreira and Muir](https://www.nber.org/papers/w22208),
[Cederburg et al.](https://www.sciencedirect.com/science/article/pii/S0304405X2030132X).

Momentum crash research highlights high-volatility rebounds after declines.
Much of the mechanism concerns long-short winner-minus-loser portfolios;
transferring its exact crash magnitude to a long-only NSE account would be
incorrect. Treat rebound regimes as required attribution, not as proof that a
particular moving-average gate works.
[Daniel and Moskowitz](https://www.kentdaniel.net/papers/published/jfe_16.pdf).

**Proposed local experiment.** Keep family 1's selection unchanged and test one
preregistered, lagged realized-volatility exposure rule bounded between cash and
100% invested. Select the target risk from the account mandate, not the best
backtest. Compare with constant exposure at comparable realized risk to isolate
timing benefit from merely holding less equity. Report turnover, whipsaw costs,
cash drag, crash losses and missed rebounds. Do not add a market trend filter,
ATR stop, sentiment gate and quality gate in the same experiment.

This is a related risk variant, not an economically independent diversifier.
Any subsequent breakout redesign must earn a separate experiment identity and
budget; the existing rejected breakout remains a diagnostic reference only.

### 3. Slow quality/value — defer until historical fundamentals pass audit

**Published India-specific construction evidence.** NSE's quality index uses
return on equity, debt/equity and five-year EPS variability. Its value index
uses earnings, book value, sales and dividends relative to price. The existence
of these transparent benchmarks motivates replication; it does not prove
Sensei can combine them profitably.
[Nifty200 Quality 30](https://www.niftyindices.com/indices/equity/strategy-indices/nifty200-quality-30),
[Nifty200 Value 30](https://www.niftyindices.com/indices/equity/strategy-indices/nifty200-value-30).

**Proposed local experiment.** One slowly rebalanced sleeve with fixed accounting
definitions and explicit sector handling, evaluated standalone before any
combination. Preserve original filings and revisions, and make each fact usable
only after its actual public dissemination. Period-end dates and latest
restated financials are insufficient. If historical availability timestamps or
five-year comparable facts are missing, defer this family. Do not fill them
using current vendor snapshots.

PEAD, short-term reversal, intraday trading, options, crypto and broad LLM signal
generation add new data or execution problems and are outside this first
campaign. Deferring them is a scope choice, not a claim they cannot work.

## Backtest and evidence contract

The following is a proposed local protocol, not a universal statistical recipe:

1. **Freeze the decision before outcomes.** Write the account capital, objective,
   drawdown budget, passive references, dates, research families, maximum number
   of variants, costs, exclusion rules and stopping decision. Keep failed trials
   and manual experiments. If no candidate passes, close the campaign without
   automatically generating more variants.
2. **Audit actual historical information.** Include removed/delisted instruments,
   timestamped membership, symbol/ISIN lineage and corporate actions. Reconcile
   major actions against raw prices and share/cash transformations. Use a
   consistent adjusted signal series and executable price/share accounting;
   avoid combining total-return-adjusted bars with separately credited dividends.
   Do not drop broken instruments after observing strategy returns.
3. **Simulate one funded account.** Track daily marked equity including cash,
   positions, dividends and pending orders. Model next executable entries,
   gaps through stops, price-band/locked-market failures, fills, fees, cash
   release and the actual broker's constraints. An OHLC touch does not establish
   that the intended quantity could trade at that price. Use conservative
   ambiguous-bar rules and disclose their effect.
4. **Separate selection from deployment.** Use chronological development and
   validation with explicit treatment of trades crossing fold boundaries. Purge
   overlapping outcome information when tuning a learned model. The final
   selection gets one confirmation decision on genuinely unconsulted data;
   checking multiple revisions on the same interval consumes that interval.
5. **Measure the portfolio.** Publish net CAGR, benchmark excess return, daily
   marked drawdown, time underwater, exposure, turnover, capacity, trade
   expectancy and profit factor. Attribute returns by era, sector, liquidity,
   issuer and signal cohort. Inspect dependence on the best few trades without
   assuming that positive skew is automatically invalid.
6. **Quantify uncertainty and search risk.** Use time-block resampling of daily
   portfolio/benchmark returns rather than treating simultaneous trades as
   independent. Report sensitivity to block length. Where inputs support it,
   report a Deflated Sharpe Ratio with the complete trial history and disclose
   effective-trial assumptions; do not manufacture a precise statistic when
   those inputs are absent. These tools supplement the campaign design.
7. **Stress execution before confirmation.** Increase slippage/impact, delay
   entries, reduce fill availability and test nearby parameters on development
   data only. A result that needs optimistic fills or a unique parameter spike
   is not robust enough to consume final confirmation.

Multiple testing inflates selected performance; the Deflated Sharpe Ratio
addresses selection and non-normality using information beyond one winning
backtest. A holdout alone does not account for the search that preceded it.
These are the relevant published findings behind the protocol, rather than
claims that any one metric certifies an edge.
[Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf),
[Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).

## Indian cash-equity costs and practical live readiness

As checked on September 6, NSE lists delivery-equity STT of 0.1% on purchase and
sale, delivery stamp duty of 0.015% on purchase, and SEBI turnover fees of
0.0001% per side. GST applies to broker services; use the broker's actual charge
bases. The STT and stamp-duty components alone are approximately 0.215% of an
equal-value round trip, before exchange fees, brokerage, DP charges or slippage.
[NSE levies](https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies).

For illustration, Zerodha currently lists zero delivery brokerage, NSE cash
transaction charges of 0.00307%, GST of 18% on specified service charges, and a
₹15.34 per-scrip sale DP charge. The DP component alone is about 0.1534% of a
₹10,000 sale or 0.0256% of ₹60,000. Actual billing grouping, applicable account
discounts and rounding must follow the chosen broker. A flat 0.25% round-trip
assumption leaves little execution allowance, particularly for small positions.
This is an example, not a broker selection.
[Zerodha charges](https://zerodha.com/charges/).

Implement effective-dated schedules for historical fees rather than applying
today's rates to every past year. Keep investor-specific income/capital-gains
tax outside the execution-fee model unless an explicitly specified after-tax
scenario is needed. Include infrastructure/data costs separately when evaluating
whether operating the system is worthwhile at the intended capital.

SEBI's September 30, 2025 extension states that the retail algo framework and
exchange operational modalities apply to all brokers from April 1, 2026. Broker
onboarding must therefore be checked against the actual current integration.
[SEBI extension](https://www.sebi.gov.in/sebi_data/attachdocs/sep-2025/1759232056254.pdf).

For a concrete broker example, Zerodha documents a registered static IP for
API order placement. Its March 2026 announcement specifies a 10-order-per-second
limit and required market protection for market/SL-M orders. These are verified
Kite behaviors, not a blanket statement of every broker's capabilities.
[Static IP documentation](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/static-ip),
[Kite implementation announcement](https://kite.trade/forum/discussion/15912/preparing-to-comply-with-sebis-retail-algo-rules-static-ip-ratelimits-order-types).

Before a real-capital proposal, demonstrate actual order-state reconciliation,
restart recovery, duplicate prevention, partial-fill protection, rejected-order
handling, end-of-day/overnight protective behavior and the ability to stop new
risk. Broker order acceptance is not proof of a fill; paper success is not proof
that equivalent protection persists at the live broker.

Keep economic readiness and operational readiness as separate decisions. Shadow
and paper stages establish behavioral parity and operating reliability; a fixed
number of paper days cannot establish statistical edge. A later small-capital
pilot can calibrate live execution only after a concrete capital/loss mandate
and explicit live authorization, not retroactively rescue failed research.
