# Liquid relative strength v1 — proposed development experiment

Status: researched design, 2026-09-07. Not implemented, not backtested, not a live
mandate. [Evidence and rationale](../research/stock-strategy-recommendation-2026-09-07.md).
Every numerical choice below is frozen for the first development batch once
implemented and registered; it is not an optimized or empirically validated value.

## Hypothesis and boundaries

Liquid NSE stocks with strong six- and twelve-month volatility-adjusted price
returns may reward months-long ownership after executable costs. Monthly buffered
selection is the retail candidate; semiannual selection is a diagnostic control.
The official momentum index supports the signal family, not our universe, ten
holdings, sizing, monthly timing or exits.

Long-only ordinary cash equities; ₹300,000 starting capital; no leverage. No news,
fundamental signal, fixed profit target, fixed maximum holding age, or 200-DMA
market gate. Holdings may last weeks to months. The drawdown field remains
configurable; retain the existing 100% research acceptance value in development
comparisons. Do not interpret that value as a live capital-preservation plan.

## Information and universe

Formation occurs after the final exchange session's close each calendar month.
Use only data available by the recorded decision cutoff. Next-session source
publication must delay the decision/fill rather than be backdated. The existing
historical master availability convention is a labeled research proxy until
publication timing is verified; a structurally correct backtest cannot certify it.

Start from the closure pipeline's provisional dated normal, non-SME, ordinary-share
EQ eligibility proxy, one-share lot and permission checks. Do not substitute today's Nifty
200 constituents. Require positive valid prices, at least one calendar year's
listing/history and a complete common exchange-session history between the twelve-
month endpoint and formation. Exclude missing observations, identity discontinuity
or non-dividend actions inside that signal window in v1. Do not bridge such a
window using unverified vendor adjustment factors. Retain raw price returns with
ordinary cash dividends unadjusted; these are price, not total, return signals.

Among eligible stocks with a complete preceding sixty-session turnover history,
require median daily traded value of at least **₹50,000,000 (₹5 crore)**. Take the
**200 highest** median-turnover names, or all qualifying names if fewer. Include
formation-session information only after it is available. Sort ties by ISIN, then
symbol, ascending. This is an observed historical liquidity universe, not a
certified index membership history. Report exclusion counts and coverage each month.

## Signal and roster

For month-end `t`, `P(t-k)` is the closing price on the final exchange session of
calendar month `t-k`. Use the same endpoints for every name:

```text
R6  = P(t) / P(t-6)  - 1
R12 = P(t) / P(t-12) - 1
sigma = sqrt(252) * sample_std(log daily returns from P(t-12) through P(t))
X6 = R6 / sigma; X12 = R12 / sigma
score = 0.5 * zscore_universe(X6) + 0.5 * zscore_universe(X12)
```

Both z-scores use population standard deviation across that formation universe.
Exclude a zero/undefined individual sigma before normalization; if a cross-section
has fewer than two names or either cross-sectional standard deviation is zero,
declare that formation invalid and create no performance claim until resolved.
Rank descending, ties by ISIN then symbol. No winsorization, positive-momentum
threshold or extra skipped month. The official monotonic positive score transform
is unnecessary for ranking because we do not use score-weighted allocations.

Initial roster: top ten, or all eligible names if fewer. Subsequent roster:

1. Include ranks 1–5.
2. Add members of the previous **scheduled model roster** still ranked ≤20, in
   current rank order, until ten places are occupied.
3. Fill vacancies with the highest-ranked remaining names until ten are selected.

Keep this model roster independent of actual holdings and stop exits so the exit
control shares identical target rosters. A name stopped between reviews cannot
re-enter until the next scheduled review. No replacement trade occurs mid-month.
Missing history or a liquidity exclusion removes a name from the next roster;
held corporate actions still require complete accounting before any such sale.

There is no sector cap in this price-only v1: historical sector labels are not yet
certified. Report stock concentration and any available dated sector diagnostics;
do not claim sector diversification from holding ten names.

## Targets, sizing and cash

At each scheduled review set each selected name's target value to at most **9.5%
of current marked account equity**, with maximum target gross exposure **95%**.
Fewer than ten names leave more cash; do not redistribute their vacant weights.
Equity includes valid marked holdings and receivables less liabilities/costs;
spendable cash excludes unpaid dividends, unsettled sales and reserved charges.

Calculate ATR20 as the simple mean of the final twenty true ranges available at
formation, using twenty-one closes/highs/lows. Freeze formation equity `E0`, ATR
`a`, turnover `T0` and reference buy price `p0` (formation close plus declared
adverse slippage and tick rounding). For a new position, form this maximum
whole-share target:

```text
q0 = floor(min(0.095*E0/p0, 0.0075*E0/(3*a), 0.001*T0/p0))
```

At formation, reduce buy targets for estimated charges and aggregate projected
cash after the planned sales, in rank order, leaving a 5% equity reserve. Projected
sales fund target planning only, not executable buys. Freeze the resulting buy
order quantity. At each execution attempt, cap its remaining quantity again using
the same formula with current marked equity, executable price and preceding
available turnover; ATR remains frozen. Also constrain it by spendable cash after
charges and the 5% current-equity reserve. If that reserve cannot be maintained,
block buys; do not assume an unfilled sale or receivable supplied cash. A favorable
price move cannot increase the original buy order. Never round upward or enlarge
another position to use residue. Process sales first, then purchases in model rank
order, recomputing bounds before each purchase. The 0.75% figure is initial
price-distance risk, not a maximum realized loss.

For retained positions, freeze a target at formation toward 9.5% of review equity, subject to total
quantity × original 3-ATR entry distance ≤0.75% of review equity, availability,
capacity and cash. Keep original entry ATR and stop state when topping up or
trimming; report this conservative original-distance budget separately from
distance to the current trailing threshold. Freeze a top-up's original buy delta
as `max(0, target_quantity - held_quantity)` after formation cash allocation; later
fills obey that delta ceiling and the current-equity total-position bounds. Freeze
trim orders as the opposite delta; they persist until filled or superseded at the
next review. Full exits persist until executable and override top-ups and trims.
A fully exited name starts new state on its next permitted entry. Nonpositive ATR
or a resulting zero quantity means no buy. No additional minimum ticket size or
daily weight rebalancing.

Apply the 0.1% preceding-sixty-session median-turnover cap to aggregate one-day
orders per stock, including sales; unfinished exits can carry forward. A 9.5%
target is an allocation-time limit, not a guarantee against concentration drift
between reviews or after other holdings fall. Report daily realized weights.

Implementation clarification: partially exited and unavailable-share holdings
continue to occupy one of the ten holding slots. A new name waits for a slot.
The whole day's observed volume is an additional physical fill ceiling, applied
only to reduce the simulated fill after order formation; it never increases an
order using future volume. It does not prove availability at the opening price.

## Daily exit and corporate actions

Use a **daily-close trailing exit**, not an assumed intraday guaranteed stop fill.
At entry, set threshold `S = entry_price - 3*a`, high-water close `H = entry_price`.
At each subsequent closing observation:

1. If close ≤ the threshold already active for that session, schedule an exit at
   the next available execution session; do not cancel it on a rebound.
2. Otherwise update `H = max(H, close)` and `S = max(S, H - 3*a)` for the following
   session. Do not use this new threshold to trigger an earlier intraday fill.

Process the entry-session close too, after establishing entry state. A nonpositive
initial threshold blocks entry. A roster departure also schedules an exit. Stops
take precedence over a scheduled top-up; no same-session sale and repurchase.

Splits/bonuses transform share quantities, frozen ATR, `H` and `S` into the new
share unit before price comparisons. Ordinary cash dividends reduce `H` and `S`
by the per-share ex-date cash amount, leaving ATR unchanged, to avoid a mechanical
exit caused solely by the distribution; book the cash separately as a receivable.
This dividend rule is a local portfolio convention, not the index signal formula.
Rights, demergers, unsupported distributions and missing held marks require
reconciliation; do not invent a fill, erase a loss or drop the position. Preserve
the closure pipeline's documented action and share-availability assumptions.

## Execution and costs

Base reference is the next eligible session's open with adverse **10 bps on each
side**, dated tick rounding and explicit delivery charges, including aggregate
sell-side DP treatment. Quantity calculations use information available at the
execution quote; a historical open is a fill scenario, not proof of an obtainable
auction order. No same-close fills. Freeze the inherited fee-schedule identifier
and source hashes in the registration manifest before producing results.

Implementation clarification before candidate results: the inherited charge model
is the **current delivery schedule effective 2026-03-01**, applied consistently as
a current-cost counterfactual, not reconstructed historical tax rates. This corrects
the proposal's earlier imprecise phrase “dated delivery charges.” No sector or
announcement alpha filter is added. Missing formation metadata blocks a complete
result; missing execution metadata defers orders. Absent circuit records, zero-
activity/one-price bars are conservative non-fill proxies, not certified fills on
all other bars. Missing future liquidation prices are reported, never invented.

Require available shares and spendable cash. In the absence of verified historical
broker cash availability, assume sale proceeds become spendable before the open
of the following exchange session; label this one-session-delay scenario. Pending
rebalance buys expire after five exchange sessions from the scheduled execution
session. Revalidate entry eligibility/capacity before each attempted fill; do not
rerank or increase the original order. Carry outstanding exits until executable,
subject to valid prices, dated permissions, circuits and capacity; missing evidence
must not become a favorable fill assumption. Cancel stale pending buys when an
exit is triggered. Define unavailable circuit evidence explicitly in the manifest;
unresolved execution evidence prevents promotion beyond a scenario result.

Charge ₹500 for each started monthly subscription cycle from evaluation inception;
record actual additional hosting/model/data overhead separately, rather than
silently assuming production overhead is zero. Cash yield is zero in this first
development scenario. Fees and subscription costs reduce equity/cash. Report
marked terminal wealth and a separately costed executable liquidation, retaining
unavailable positions/receivables rather than manufacturing terminal cash.

## Registered batch and decision

Run one candidate and **three diagnostic controls**, with no parameter grid:

| Run | Only intended policy difference |
|---|---|
| Candidate | Rules above |
| Selection control | Rank by median turnover instead of momentum, with the same roster buffer, risk rules and schedule |
| Exit control | Candidate roster and original ATR sizing, but omit daily trailing exits; retain scheduled exits |
| Cadence control | Candidate reviewed only at June/December month-ends, next-session execution; all other rules unchanged |

This expands the preliminary validation note's suggested two-control budget by
one because the published evidence specifically challenges faster review. It is
still a fixed four-run batch. The cadence control is **not** an official index
replication: its signal cutoff, universe and portfolio differ. Selection and
cadence controls create different holdings and cash paths; interpret total policy
differences, not perfect causal isolation. Do not promote a winning control.

For the primary four-policy comparison, initialize **each account at ₹300,000 with
empty holdings and an empty model roster** at the first jointly supported June
formation; execute after that formation. Do not rebase an already-running February
portfolio and call it the same inception. Separately run only the candidate from
its first supported monthly formation (potentially January 31, 2025, with February
1 an exchange session) as an extended-history development diagnostic. This is five
base account paths across four policies; register both windows before results.
Align Nifty 500 gross TRI to each actual investment window; include Nifty 200 and
Momentum 30 TRI as external diagnostics where complete. Warm-up is not invested
performance.

Freeze separate stresses before seeing output: 20 and 40 bps both-side slippage;
one additional execution-session delay; half the capacity cap; and an adverse
three-session delay of every otherwise triggered exit. Apply each separately to
the common-inception candidate, with unchanged signals. Report missed/partial orders, exposure,
turnover, fees/overhead, net wealth, drawdown/duration, worst months, concentration,
stock contributions and the extra friction that exhausts benchmark advantage.
Do not choose the most favorable fill/settlement scenario.

Development rejection: nonpositive net return, nonpositive aligned Nifty 500 TRI
excess return, or failure of either sign under doubled slippage means no demonstrated
net edge for this version on this sample. Passing is only a reason to investigate
further, not a promotion gate. Risk/coverage failures and costed-passive comparisons
must also be reported even if gross TRI is beaten. No annualized target or claimed
statistical significance is justified from this short inspected sample.

Before any run, register exact code/config/data/calendar/fee hashes and outstanding
source-availability assumptions. Historical repairs apply to every run and retain
old artifacts. All prior strategy trials remain disclosed. This design is not a
completed preregistration until those implementation artifacts exist.

A future confirmation plan must separately freeze an investable passive comparator,
minimum worthwhile net advantage, drawdown mandate and evidence-review procedure
before collecting future results. Existing history is development data. This
specification authorizes no orders and changes no live configuration.
