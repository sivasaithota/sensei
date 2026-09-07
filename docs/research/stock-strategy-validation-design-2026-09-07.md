# Relative-strength strategy: validation and risk design

Reviewed 2026-09-07. Proposed research protocol for one ₹300,000, long-only NSE
cash-equity account. No implementation, backtest, Kite call or order in this note.

This is the supporting design review. The subsequent
[candidate specification](../specs/liquid-relative-strength-v1.md) selects the
concrete development rules and explains its three diagnostic controls, replacing
the preliminary two-control search-budget suggestion below. The forward
confirmation requirements remain separate from that development experiment.

**Recommendation:** register one relative-strength candidate and a small control
set; use inspected history only for development/rejection, then collect genuinely
future paper evidence. Successful accounting or a better historical result does
not establish a deployable edge.

## Evidence already available

The [closure report](stock-closure-results-2026-09-07.md) records four failed
implementations over 413 sessions, January 2025–September 2026, all below aligned
Nifty 500 gross TRI. Raw accounting is trusted only within January 2024–September
2026 under the report's stated assumptions. Universe completeness, publication
timing, corporate-action completeness and actual share/cash availability remain
provisional. With a twelve-month formation period, the usable evaluation is
shorter still. Every previously inspected date remains development data.
The [candidate note](next-stock-strategy-evidence-2026-09-07.md) proposes slower
cross-sectional relative strength; it does not supply independent validation.

Three primary sources support specific, limited claims:

- **Bailey and López de Prado (2014):** selection across trials inflates reported
  performance; repeated holdout use does not remove this problem. Their deflated
  Sharpe method incorporates track-record length, return distribution and trial
  information. It is conditional on inputs and assumptions, not a cure for
  contaminated data. [Authors' paper](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf).
- **NSE Indices:** the Nifty200 Momentum 30 construction supplies a transparent
  six/twelve-month volatility-adjusted momentum reference, with 30 constituents
  and semiannual rebalancing. Its index calculation is not this small account's
  executable performance. [Official factsheet](https://www.niftyindices.com/Factsheet/Factsheet_Nifty200_Momentum30.pdf).
- **NSE:** impact cost depends on order size, side and the available order book;
  the spread alone does not describe larger-order execution cost.
  [Official explanation](https://www.nseindia.com/static/products-services/indices-impact-cost).

Everything below is a proposed local design judgment, not a rule empirically
validated for this account by those sources.

## Registration before any candidate results

Save a dated, immutable plan plus code/configuration and data hashes. A proposal
with missing numerical fields is not ready to run. Freeze:

| Component | Required specification |
|---|---|
| Hypothesis | One economic claim; exact six/twelve-month lookbacks, volatility estimate, normalization, missing-history handling and tie breaker. |
| Admission | Dated universe definition and identity; ordinary-share/series rules; listing/history minimum; liquidity calculation and cap; exact source-availability cutoff. A historical observed proxy must be named as such. |
| Portfolio | Holding count, weights, rebalance calendar, rank buffer if any, position and sector caps, cash reserve, turnover limit and deterministic rounding/reallocation. |
| Timing | Observation cutoff, order-decision timestamp, earliest executable session, price/fill rule, expiry and partial-fill handling. No signal computed from a close and filled at that same close. |
| Exits | Rank/rebalance exits, forced eligibility/action exits and any risk response. Do not inherit percentage brackets merely because the old engine has them. |
| Costs/accounting | Fee schedule/date, taxes and sale DP aggregation, both-side slippage, action/share availability, dividend payment timing, cash-settlement rules and liquidation treatment. |
| Decision | Primary metric, comparator, uncertainty method, minimum economically worthwhile advantage, acceptable risk/execution limits, evidence-review rule and failure/inconclusive outcomes. |

Fix operational exceptions in advance: missing required entry information means
no new entry; an unsupported held action or unpriceable holding means an invalid
performance result until reconciled, not an invented liquidation or a deleted
observation. Source repairs must retain previous artifacts and apply consistently
to all controls; strategy changes create a new registered version.

## Bound the search and identify what is being tested

Permit **one candidate plus two diagnostic controls** in this research batch,
all specified before results. This is a search-budget choice, not a statistically
optimal number. Run no grid and do not select a winning control for promotion.

1. Candidate: the frozen retail relative-strength portfolio.
2. Selection control: identical eligible universe, rebalance dates, fee/fill
   treatment and applicable portfolio constraints, but broad-universe weighting
   without relative-strength selection. Report unavoidable differences in holding
   count, rounding and costs; it is not a perfectly isolated laboratory comparison.
3. Weighting control: the same selected stocks and trading schedule with a
   predeclared simpler weighting rule, holding other policies constant. If the
   candidate already uses that rule, omit this control rather than inventing one.

Record every performance inspection, failed run and manual change in a trial
ledger. Keep accounting-only replays distinguishable from economic strategy
trials, but disclose both. Include the earlier four families, turnover experiments
and repeatedly failed 200-DMA market gates; relabeling a gate does not make it new
alpha. Diagnostic or stress output cannot be mined to choose new parameters within
this batch. A new idea requires another registration and consumes future evidence.

Use older newly acquired, admissible history for additional development and
stress coverage. It is not automatically untouched evidence: historical market
outcomes may already have shaped the idea. Walk-forward splits inside inspected
history diagnose stability; they do not restore a fresh holdout. Preserve warmup
versus evaluation boundaries and any dependence across holding periods.

## Account risk and executable-cost envelope

Size from **current marked equity**, never repeatedly from the initial ₹300,000.
At rebalance let equity equal cash, marked holdings and valid receivables less
liabilities and accrued costs. Risk budgets use that equity; purchases also obey
independently verified spendable cash. Receivables and unavailable shares cannot
fund buys or sells. Floor target shares after reserving estimated charges; constrain
aggregate orders and exposure, not each order in isolation. Mark profits/losses
between rebalances and report cap drift rather than assuming continuously reset
weights. No leverage or short positions.

Before running, set numerical position/sector limits, maximum portfolio exposure,
turnover budget, stress-loss tolerance and the response to an equity-drawdown
breach from the account mandate. Distinguish research rejection limits from
executable risk actions. Stops cannot guarantee a loss cap through a gap,
suspension or unfilled exit. The old 100% drawdown acceptance setting is not a
meaningful capital-preservation mandate. This note cannot infer the owner's
acceptable loss from starting capital alone.

Freeze a small stress matrix alongside the candidate:

- Base documented charges plus explicitly assumed slippage on both sides;
  the old 10 bps entry assumption is not proof of realizable execution.
- Double the assumed slippage on both sides with charges unchanged; separately
  report break-even additional friction. This multiplier is a sensitivity choice.
- Delay every rebalance one exchange session and retain cash/positions until
  executable; do not backfill a missed fill at the original reference price.
- Constrain orders to a predeclared fraction of trailing traded value, then halve
  that cap. Model partial fills and missed exits; daily volume is only a capacity
  proxy, not order-book proof. Include observed circuit/suspension cases and a
  declared adverse multi-session non-fill scenario.

At ₹300,000, and separately at twice that capital only as a scaling diagnostic,
report integer-share shortfalls, cash drag, turnover, DP cost relative to sale
size, participation, expected liquidation time and worst modeled liquidation
loss. Do not combine whichever stress assumptions happen to improve results.
Unknown fill or availability assumptions remain labeled scenarios.

## Comparisons and future evidence

Align all comparisons to identical dates, starting wealth, valuation times and
cash-flow conventions. Report net ending wealth/total return, drawdown and its
duration, volatility, turnover, exposure, costs, concentration and contribution
by stock/sector. Use the parent-universe TRI as a market diagnostic, preserve
Nifty 500 TRI for continuity, and name one obtainable passive product as the
primary investable comparator before results. Model its actual expenses, tracking
and execution without double-counting expenses already embedded in NAV. An index
TRI is not an executable passive portfolio. Include cash as an opportunity-cost
reference using a declared cash-yield assumption. Do not choose the comparator
after seeing which one is easiest to beat.

Predeclare the primary claim as net advantage over that investable comparator
subject to mandate risk limits. Freeze an economically meaningful advantage and
an uncertainty procedure that respects serial dependence (for example a specified
block-resampling design), including confidence level, block choice and treatment
of multiple claims/reviews. These remain assumption-dependent estimates. Provide
a sensitivity range if the prior trial count is incomplete; do not publish a
precise deflated Sharpe number from an invented independent-trial count.

A forward paper run begins only after registration and admissible inputs exist.
Archive each input snapshot, timestamped target portfolio and hypothetical order
before the eligible fill window; log executable quotes/fill evidence, missed
orders, fees, actions and cash. Keep operational reconciliation separate from
performance judgment: paper execution does not prove real fills or market impact.
Operational monitoring may happen continuously; efficacy reviews follow the
registered stopping/precision rule, with no repeated unadjusted significance
checks. Any strategy alteration ends that version's confirmation period; earlier
paper observations become development evidence for the successor.

No fixed Sharpe/CAGR or arbitrary number of paper months establishes sufficiency.
Plan the evidence requirement around the minimum worthwhile advantage, return
dependence, estimation precision, number of reviews and relevant stress exposure;
if those cannot be justified, report **inconclusive**. Historical failure supports
rejection; historical success supports further observation. A future result must
clear the frozen net/risk criteria and unresolved data/execution issues before
any separate capital-deployment decision. This note starts no paper process or
live trading.
