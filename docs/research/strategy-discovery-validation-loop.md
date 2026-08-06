# Strategy discovery and validation loop for Indian equities

Date: 2026-08-06

Status: research agenda only. Nothing in this note authorizes paper, canary, or
real-capital trading.

## Decision summary

Sensei should become a learning research system, but not a system that changes a
tradable strategy after every disappointing backtest. The safe loop is:

```text
primary-source research
    -> immutable economic hypothesis
    -> preregistered strategy version and experiment family
    -> point-in-time discovery backtests
    -> diagnosis and falsification
    -> new version (all attempts retained)
    -> rolling/purged validation
    -> one-use locked confirmation
    -> governed shadow -> paper -> canary -> active
    -> post-trade attribution feeds the next research campaign
```

Research and discovery may iterate many times. A locked confirmation set may
not. Each revision is a new experiment, and every attempted variant—including a
failure—counts toward the campaign's multiple-testing correction. This is the
central safeguard against turning “research a lot” into data mining.

The strongest near-term research candidates are:

1. India-native cross-sectional momentum/relative strength;
2. timestamp-correct post-earnings-announcement drift (PEAD);
3. quality/value as a slow strategy or quality gate on momentum;
4. volatility-scaled trend and a separately tested volatility-contraction
   breakout hypothesis.

Raw short-term reversal is lower priority. Its apparent return is often
concentrated in illiquid stocks and may not survive real execution costs.

## Evidence standard

This note separates evidence into two classes:

- **India-specific evidence** can justify an Indian-market hypothesis, but still
  must be reproduced on Sensei's point-in-time data and costs.
- **General evidence** is only a source of ideas. Results from US stocks, global
  futures, or other markets are not evidence that a rule works in Indian cash
  equities.

No source below authorizes a particular parameter, portfolio, or live trade.
Research papers and index whitepapers can contain selection, publication, and
backtest biases. The bot must reproduce baselines before modifying them.

## Research families

### 1. Cross-sectional momentum and relative strength — first priority

**General evidence.** Jegadeesh and Titman found that portfolios buying past
winners and selling past losers earned significant returns over intermediate
formation and holding horizons; some gains later reversed. This supports the
economic family of medium-horizon relative strength, not an arbitrary moving
average combination ([original Journal of Finance paper](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1993.tb04702.x)).
Daniel and Moskowitz document that momentum crashes cluster after market
declines, amid high volatility, and during sharp rebounds
([original Journal of Financial Economics paper](https://www.kentdaniel.net/papers/published/jfe_16.pdf)).

**Indian evidence.** NSE Indices publishes transparent momentum indices and
methodologies. The Nifty200 Momentum 30 family uses volatility-adjusted six- and
twelve-month price returns, eligible constituents, buffering and capped weights
([Nifty200 Momentum 30 page](https://www.niftyindices.com/indices/equity/strategy-indices/nifty200-momentum-30),
[2026 NSE momentum whitepaper](https://www.niftyindices.com/docs/default-source/indices/nifty200-momentum-30/momentum-strategy-whitepaper_2026.pdf)).
NSE's own analysis shows long-run outperformance in its backtested index series,
but also maximum drawdowns around 68%–73% for the cited momentum indices. This is
evidence for both the hypothesis and its crash risk, not a promise of future
return. Independent Indian studies also report momentum in Indian equities and
important interaction with liquidity
([IIMB Management Review study](https://doi.org/10.1016/j.iimb.2019.07.007),
[momentum, reversals and liquidity in India](https://doi.org/10.1016/j.pacfin.2023.102193),
[size, value and momentum in Indian equities](https://doi.org/10.1177/0256090917733848)).

**First frozen experiments.** Reproduce an NSE-style long-only baseline before
testing enhancements:

- point-in-time Nifty 200 and Nifty 500 membership;
- six- and twelve-month returns, skipping only a preregistered recent interval;
- volatility-normalized composite rank;
- scheduled rebalancing and buffer rules;
- integer shares and a ₹3 lakh account;
- benchmark against the appropriate total-return parent and NSE momentum index;
- separately preregister trend confirmation, liquidity floor, quality overlay,
  and volatility-scaled exposure instead of combining them in one opaque model.

Report rebound regimes explicitly. A crash-risk rule may be adopted only if it
improves locked portfolio outcomes, not because the full-sample equity curve
looks smoother after tuning.

### 2. Post-earnings-announcement drift — high priority

**General evidence.** Bernard and Thomas document returns continuing in the
direction of earnings surprises after announcements
([original study](https://doi.org/10.2307/2491062)). Later work shows the
implementation question is material: one study found positive net returns under
its timing and cost assumptions, while another found PEAD concentrated in
illiquid securities and estimated that costs consumed much of the paper return
([Battalio and Mendenhall](https://papers.ssrn.com/sol3/Papers.cfm?abstract_id=937257),
[Chordia et al.](https://business.columbia.edu/faculty/research/liquidity-and-post-earnings-announcement-drift)).

**Indian evidence and source of truth.** Research on actively traded BSE stocks
reported Indian PEAD after controlling for common risk and transaction-cost
factors ([Journal of Contemporary Accounting & Economics](https://doi.org/10.1016/j.jcae.2008.11.001)).
NSE corporate filings expose the exchange broadcast timestamp, attachment, and
financial-result records
([NSE announcements](https://www.nseindia.com/companies-listing/corporate-filings-announcements?tabIndex=equity),
[SEBI corporate-filing directory](https://www.sebi.gov.in/curation/corporate_filings.html)).
SEBI's disclosure regime requires periodic financial results, generally within
45 days after non-final quarters and 60 days after the financial year
([SEBI Regulation 33 discussion](https://www.sebi.gov.in/sebi_data/meetingfiles/apr-2023/1681702875120_1.pdf)).

**First frozen experiment.** Build a long-only event strategy using only
information available at the exchange broadcast timestamp:

- standardized unexpected earnings or a preregistered year-over-year surprise;
- comparable standalone/consolidated treatment fixed in advance;
- sales and earnings-quality confirmation;
- entry no earlier than the first executable session after dissemination;
- price/volume confirmation frozen before testing;
- exclusion of results released during a session until a realistically delayed
  bar or the next session;
- strict traded-value and estimated-impact-cost filters;
- event windows that do not overlap without portfolio concurrency accounting.

The reporting-period end date must never be used as the availability date.
Restated filings must not overwrite the version investors saw at the time.

### 3. Quality and value — high-priority diversifier/overlay

**General evidence.** Fama and French found size and book-to-market related to
the cross-section of average returns
([original paper](https://doi.org/10.1111/j.1540-6261.1992.tb04398.x)).
Novy-Marx found gross profits relative to assets had predictive power comparable
to book-to-market and improved value strategies, especially among larger, more
liquid stocks
([NBER working paper and published reference](https://www.nber.org/papers/w15940)).

**Indian evidence.** NSE maintains Indian quality, value and multi-factor index
methodologies
([official methodology catalogue](https://www.niftyindices.com/resources/index-methodology),
[Nifty Alpha Quality Value Low-Volatility 30](https://niftyindices.com/indices/equity/strategy-indices/nifty-alpha-quality-value-low-volatility30)).
NSE's multi-factor paper illustrates that single factors are cyclical and that
combining factors can reduce performance swings, but it remains an index-provider
backtest and must be independently reproduced
([NSE multi-factor paper](https://www.niftyindices.com/docs/default-source/indices/nifty-alpha-quality-low-volatility-30/nifty-alpha-quality-low-volatility-30-whitepaper_2017.pdf)).

**Frozen research branches.** Test these separately:

1. a slower, periodically rebalanced quality-value portfolio;
2. quality as an eligibility gate on medium-term momentum;
3. momentum and quality-value as separately sized portfolio sleeves.

Use announcement timestamps and lag each accounting field until public. Avoid
large composite scores initially: each extra field, transformation, and weight
is another researched degree of freedom. Require sector-neutral and unconstrained
results side by side so a sector bet cannot masquerade as a stock-selection edge.

### 4. Trend, volatility scaling, and volatility contraction/breakout

**General evidence.** Brock, Lakonishok and LeBaron found moving-average and
trading-range-break signals inconsistent with several null models on a long Dow
Jones history, using bootstrap tests
([original Journal of Finance paper](https://doi.org/10.1111/j.1540-6261.1992.tb04681.x)).
Time-series momentum has also been documented across liquid global futures, but
that is not direct evidence for Indian individual equities
([Moskowitz, Ooi and Pedersen](https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf)).
Moreira and Muir found that reducing exposure when volatility was high improved
risk-adjusted results across several factors
([original paper](https://www.nber.org/papers/w22208)).

There is not comparable primary evidence here that a particular ATR squeeze,
Bollinger squeeze, NR4/NR7, or volume-breakout recipe is an established Indian
edge. Therefore **volatility contraction is a hypothesis, not inherited truth**.

**Frozen experiment.** Define one simple version before seeing its returns:

- realized volatility or ATR percentile over a fixed past window;
- contraction duration and percentile threshold;
- close-based range breakout;
- volume confirmation using only prior and current executable information;
- next-session entry and gap-aware fill;
- maximum hold and initial/trailing exit rules;
- no parameter grid in the confirmation campaign.

Test signal selection and volatility-based portfolio sizing as separate variants.
India VIX and realized Nifty volatility are attribution variables first, not
automatic hard gates. NSE defines India VIX as an option-derived estimate of
expected Nifty volatility over the next 30 calendar days
([NSE India VIX](https://www.nseindia.com/static/products-services/indices-indiavix-index)).

### 5. Short-term reversal and mean reversion — research queue only

Jegadeesh documented negative first-order serial correlation in US monthly stock
returns ([original paper](https://doi.org/10.1111/j.1540-6261.1990.tb05110.x)).
Later research separates price moves associated with fundamental information
from those more likely to reverse
([Da, Liu and Schaumburg](https://doi.org/10.1287/mnsc.2013.1766)).

Indian research reports both momentum and reversal, but finds reversal stronger
among illiquid stocks while momentum is stronger among liquid stocks
([Indian evidence](https://doi.org/10.1016/j.pacfin.2023.102193)). This is a major
execution warning, not a free anomaly. A ₹3 lakh long-only system should not
prioritize “buy the biggest loser.” Only later test an industry-relative,
market-residual move with news/event exclusions, a strict liquidity floor, and
fully size-dependent costs.

## Controls that apply to every family

### Regime attribution, not intuition

Every campaign reports results by preregistered states:

- Nifty trend and drawdown state;
- market breadth;
- realized volatility and India VIX bucket;
- sharp-rebound state;
- RBI policy-rate and inflation state for longer-horizon strategies;
- sector and industry;
- liquidity and market-cap bucket.

RBI DBIE is the official source for historical policy rates and macro series
([RBI historical-data guidance](https://www.rbi.org.in/Scripts/bs_viewcontent.aspx?Id=624),
[DBIE release calendar](https://dbieold.rbi.org.in/DBIE/doc/Release_Calender.pdf)).
These labels explain when a strategy works or fails. A label becomes a binding
gate only in a new preregistered variant. No agent may turn a post-hoc story such
as “weak breadth caused the losses” into a production rule without that test.

### Liquidity and capacity

NSE defines impact cost as the markup/markdown of the actual execution price for
a specified order size relative to the ideal mid-price. It varies by side, order
size, and current order book; a penal value applies when liquidity is insufficient
([NSE impact-cost definition](https://www.nseindia.com/static/products-services/indices-impact-cost)).
The Nifty 500 methodology itself uses trading-frequency and impact-cost
eligibility rules
([NSE Nifty 500 paper](https://www.niftyindices.com/docs/default-source/indices/nifty-500/nifty-500-whitepaper_2024.pdf)).

Every experiment must therefore record:

- rolling median daily traded value and zero-volume sessions;
- trade notional as a fraction of daily traded value;
- bid/ask or an explicitly conservative proxy when quotes are unavailable;
- a size-dependent impact curve, not one universal slippage percentage;
- inability to fill, partial fills, upper/lower circuits, and price-band risk;
- results with the bottom liquidity buckets removed;
- portfolio capacity at ₹3 lakh and at larger future capital levels.

Amihud's absolute-return-to-traded-value measure is a useful daily-data proxy,
but it measures an illiquidity dimension rather than the exact fill cost
([original paper](https://doi.org/10.1016/S1386-4181(01)00024-6)).

### Indian transaction costs and taxes

Cost inputs must be effective-dated configuration, because they change. A cash-
equity delivery simulation must include, on the correct side:

- brokerage and minimum-ticket effects;
- exchange transaction charges and SEBI turnover fees;
- GST on taxable services;
- STT on delivery purchase and sale;
- buyer-side stamp duty;
- bid/ask spread, slippage, market impact, partial fills and gap risk;
- DP/depository sale charges where applicable.

NSE's official levy page explains STT, GST, stamp-duty and turnover-fee categories
([NSE investor levy page](https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies));
SEBI requires market-infrastructure charges to be passed through “true to label”
([SEBI circular](https://www.sebi.gov.in/legal/circulars/jul-2024/charges-levied-by-market-infrastructure-institutions-true-to-label_84506.html)).

Income tax is investor/account-level reporting, not execution friction. Show
pre-tax and after-tax performance separately; do not deduct a generic capital-
gains rate from every exit without the account's holding-period and tax context.

### Point-in-time identity, membership, filings and corporate actions

The current 500-symbol store cannot confirm a strategy because it applies a
present-day universe to history and contains unresolved price discontinuities.
Confirmation requires:

- stable instrument identity (ISIN or equivalent), not ticker text alone;
- effective-dated Nifty membership, including removed and delisted securities;
- symbol changes and re-listings;
- split, bonus, rights, dividend, merger, demerger and spin-off facts;
- raw and adjusted prices with a declared adjustment policy;
- original filing versions and exact exchange dissemination timestamps;
- delisting and suspension outcomes rather than silently dropping instruments;
- trading calendars, price bands, surveillance restrictions and series changes.

NSE warns that displayed historical quote charts are not adjusted for corporate
actions, while its downloadable reports include corporate-action records
([example NSE quote-page note](https://www.nseindia.com/get-quote/equity/AHLUCONT/Ahluwalia-Contracts-%28India%29-Limited),
[NSE market-data reports](https://www.nseindia.com/static/products-services/equity-market-data-reports-download),
[NSE corporate actions](https://www.nseindia.com/companies-listing/corporate-filings-actions)).
An unexplained 50%–90% overnight move is a data incident until proven otherwise,
not a stop loss or alpha observation.

## Validation protocol

### Immutable hypothesis record

Before execution, register:

- economic mechanism and exact direction of effect;
- universe and point-in-time eligibility rules;
- signal formula, parameters, entry delay and exits;
- portfolio construction and all risk limits;
- benchmark and primary metric;
- minimum economically meaningful effect and confidence bound;
- cost scenarios and liquidity exclusions;
- development, validation and locked-confirmation periods;
- all regime slices that will be examined;
- family identifier and total planned variant budget;
- explicit falsification conditions.

A failed result stays in the registry. A changed threshold, feature, filter,
universe, exit, or cost assumption creates a new strategy-plan version and trial.

### Chronological, purged evaluation

Use anchored or rolling walk-forward folds; random K-fold is invalid for this
task. Training precedes validation. Purge observations whose signal/holding
interval overlaps the next fold and embargo enough adjacent sessions to stop a
label or position from leaking across the boundary. Scikit-learn's official
`TimeSeriesSplit` documents the basic time-ordered constraint and `gap`
([official API](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html));
Sensei's finance-specific protocol must additionally purge overlapping trades.

Report both per-trade and portfolio-level uncertainty. Trades on the same date,
sector, or market regime are not independent samples. Use a declared
dependence-aware method such as purged walk-forward folds, moving-block
bootstrap, or cluster-robust inference, consistent with Sensei's Experiment
Registry specification.

### Multiple testing and false discovery

The best of hundreds of variants is expected to look good by chance. White's
Reality Check was designed to test whether the best model in a specification
search has genuine predictive superiority after accounting for reuse of the same
data ([original Econometrica paper](https://doi.org/10.1111/1468-0262.00152)).
Harvey, Liu and Zhu argue that conventional `t > 2` is inadequate in a large
factor search and estimate a materially higher hurdle for a new factor
([NBER paper](https://www.nber.org/papers/w20592)). Bailey et al. show why a
single ordinary holdout can fail after repeated strategy selection and propose a
probability-of-backtest-overfitting framework
([original paper](https://scholarworks.wmich.edu/math_pubs/42/)).

Sensei should preserve its current campaign-level family-wise correction and add
diagnostics for:

- total attempted variants, including abandoned notebooks and agent proposals;
- corrected p-value/confidence result;
- probability of backtest overfitting or equivalent rank-instability measure;
- selection-adjusted Sharpe or a preregistered conservative substitute;
- fold-to-fold parameter and rank stability;
- performance decay from discovery to validation and confirmation.

The Research Agent may propose; the Experiment Registry counts; the Examiner
evaluates; no proposing agent may declare its own strategy validated.

### One-use confirmation

Discovery and ordinary validation data may be reused with every attempt charged
to the experiment family. A final confirmation snapshot is server-selected,
opaque to the researcher, consumed once, and remains consumed even if the run
crashes. After it is opened, the campaign is sealed: no new variants may inherit
that result as “out of sample.” A failure returns to a new discovery campaign,
not to parameter tweaking against the exposed lockbox.

## The ₹3 lakh portfolio campaign

Trade-level expectancy is insufficient. Every surviving strategy must run
through the same portfolio simulator with:

- initial cash exactly ₹300,000 and integer shares;
- no implicit leverage, shorting, or fractional fills;
- chronological signal arrival and next-executable-price fills;
- simultaneous positions, cash reservation and skipped trades when capital is
  unavailable;
- a preregistered maximum-position rule and per-position risk budget;
- sector, issuer and correlation concentration reports;
- stop, target, trailing and time exits resolved with a conservative intrabar
  rule when order is unknowable from daily OHLC;
- taxes/fees/impact separated and reconciled trade by trade;
- daily marked equity, drawdown, turnover and capital utilization;
- comparison to cash, Nifty 50/200/500 total return, and the nearest official
  strategy-index baseline;
- 3-, 6-, and 12-month rolling outcomes plus full walk-forward folds;
- stress runs at base, adverse and severe cost/slippage assumptions;
- crash, gap, stale-data, missed-session and partial-fill scenarios.

Primary decision metrics should include net CAGR/return, maximum drawdown,
Calmar or another preregistered return-to-drawdown measure, portfolio expectancy,
profit factor, hit rate, average win/loss, turnover, exposure, capacity, worst
gap, and confidence bounds. No single metric passes a strategy. Results must be
positive and stable across folds rather than rescued by one market episode.

## Automated learning loop and agent responsibilities

| Stage | Responsible role | Durable output | Forbidden shortcut |
| --- | --- | --- | --- |
| Source intake | Historian / Reporter | Timestamped, licensed primary-source record | Treat a blog or LLM summary as evidence |
| Hypothesis | Analyst | Economic claim and falsification rule | Generate parameters after viewing holdout |
| Registration | Desk Head / Experiment Registry | Immutable campaign and variant IDs | Hide failed or abandoned variants |
| Data examination | Historian / Examiner | Point-in-time snapshot and quality report | Drop delisted names or data anomalies silently |
| Backtest | Research Lab | Reproducible trade and portfolio artifacts | Use trade expectancy as portfolio proof |
| Challenge | Committee research admission | Deterministic evidence verdict | Conversational votes or self-approval |
| Confirmation | Independent Examiner | One-use locked dossier | Re-open or retune against the lockbox |
| Shadow/paper | Scheduler / Trader | Governed forward observations and fills | Bypass lifecycle because a backtest is attractive |
| Reflection | Coach | Attribution and a new research proposal | Mutate an authorized plan in place |
| Reporting | Secretary | Complete successes, failures and costs | Publish only winning experiments |

Agents may work asynchronously on source collection, data quality, hypothesis
generation and independent review. Promotion remains one deterministic admission
result over immutable artifacts. The production scheduler must never wait for a
free-form agent debate in the entry window.

## Ordered implementation and research backlog

### Foundation gate — before claiming another confirmation

1. Complete the point-in-time Indian universe and stable-instrument catalog.
2. Reconstruct and verify corporate actions and quarantine unexplained breaks.
3. Add exchange dissemination timestamps and versioned financial statements.
4. Implement effective-dated Indian fees plus size-dependent execution impact.
5. Build the common ₹3 lakh chronological portfolio simulator.
6. Extend the experiment ledger to count every agent-generated and human variant.

### Campaign A — reproduce, do not innovate

1. Reproduce NSE-style Nifty200/Nifty500 momentum.
2. Reproduce simple quality, value, and multi-factor baselines.
3. Compare Sensei's current five strategies to those baselines under identical
   data, capital, costs, and folds.
4. Freeze or reject any strategy that cannot add robust portfolio value over a
   simpler official baseline.

### Campaign B — controlled new hypotheses

1. Momentum plus preregistered crash-risk volatility sizing.
2. Timestamp-correct Indian PEAD.
3. Quality-gated momentum.
4. Separate quality-value portfolio sleeve.
5. One frozen volatility-contraction/range-break definition.
6. Short-term reversal only after the above, with hard liquidity and event
   exclusions.

### Campaign C — portfolio combinations

Combine only families that independently pass. Compare simple equal-risk sleeves
before optimizing weights. Any optimized allocation is itself a new experiment.
Require that diversification improves drawdown and regime coverage after costs,
not merely full-sample return.

## Promotion and live-capital boundary

A strategy is not ready for real capital because it has many backtests. It is a
candidate for governed forward stages only when:

- input data is point-in-time and corporate-action clean;
- its hypothesis was registered before results;
- it survives realistic ₹3 lakh portfolio simulation and adverse costs;
- it clears campaign-level multiple-testing correction;
- it is stable across chronological folds, liquidity buckets and regimes;
- it passes a one-use locked confirmation with reproducible artifacts;
- shadow and paper operation demonstrate reliable data, agent, risk, order,
  protection, reconciliation, and exit paths;
- canary approval is explicit and exposure is small enough to survive a full
  stop/gap scenario.

The learning loop improves research throughput, not the authority of the Coach or
Analyst. It must be fast at rejecting weak ideas and deliberately slow at risking
capital.

## Immediate conclusion for Sensei

The current five strategies are not a sufficiently diverse strategy portfolio:
most are variants of trend/momentum or price-pattern continuation. The next step
is not to tune all five until their historical curves improve. It is to repair
the data/cost/portfolio foundation, reproduce transparent Indian baselines, and
test economically distinct families under one immutable protocol.

“Unique” is not a validation criterion. The target is a small collection of
explainable, operationally executable, statistically defensible edges whose
failures occur in different conditions. The strongest initial research order is
momentum reproduction, PEAD, quality/value, then volatility contraction; raw
short-term reversal remains exploratory.
