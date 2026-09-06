# Stock bot assessment and bounded path to a live decision

**Follow-up implementation, 6 September:** the executable defects below have
been remediated: shared daily/gap ordering (including governed paper exits),
initial drawdown, replay entry timing, provider timestamps, dated ranking
evidence, shared selection, future-coverage filtering, exposure recording and
benchmark evaluation. See the [implementation closeout](stock-remediation-closeout-2026-09-06.md)
and [execution contract](../operations/daily-research-execution-contract.md).
The findings below retain the original audit observations. The new dataset
audit is blocked; these fixes establish neither profitability nor live readiness.

Reviewed 6 September 2026 against code based on `b465653`, repository evidence,
and the task **Upgrade trading bot architecture**. The user confirmed NSE
cash-equity swing first and ₹300,000 capital. Intraday and crypto are outside
this work. The user has not yet specified a maximum tolerable account drawdown.

## Decision

Keep the architecture. Concentrate the next implementation on one credible,
shared-capital examination of the exact trading policy. The current evidence
does not establish a strategy ready for live money. It also does not justify
discarding every trend-following idea: several experiments test materially
different sizing, selection, prices and success criteria.

There are three separate questions: is the implementation correct, is the
strategy economically useful, and can the broker path operate safely? Passing
one cannot answer the other two. More agents, more source ingestion and more
combinations of the existing rules will not close those gaps.

The original review supplied an arithmetic fix, an execution discrepancy probe
and a proposed campaign. The subsequent remediation implements the code fixes
and the new development evaluator. It does not claim a completed validation
campaign or a governed live broker adapter.

## Findings, ordered by impact on the next decision

### 1. The simulations disagree on a winning versus losing trade

With a position entered at 100, stop 95, target 110, and a later daily bar with
open 120, high 125, low 90 and close 100:

| Path | Outcome before costs |
|---|---|
| `backtest/engine.py:127` | Stop, −5% |
| `research/simulation.py:79` | Target, +10% |

The legacy engine considers the later low before an opening target gap. The
examiner resolves the known opening gap first. `portfolio_campaign.py:159` and
`:209` also prioritize gap stops and then intraday stops without resolving an
opening target first. The TradingView local screen has yet another gap-price
policy and freezes brackets from the signal close (`:109–130`).

An opening price is chronologically known before the later daily high/low
ordering becomes ambiguous. The new execution contract must distinguish those
cases and specify whether targets are limits, triggers, or another order type.
Stop-first remains a defensible pessimistic assumption only for unresolved
intrabar ordering. Broker execution details still need verification.

**Action:** share the event-order implementation and version the execution
policy. Preserve the frozen old screen and historical reports; a revised policy
creates a new experiment. Do not quietly change their meaning.

### 2. The production replay does not simulate an achievable next-session entry

`runtime/production_replay.py:538` initializes entry with the previous source
session. `_quote` at `:386` and `_execution_observation` at `:401` use that bar's
close and full volume. Current-session data is bound for EOD at `:586`. This is
useful counterfactual workflow evidence; it cannot validate actual morning gap
prices or executable morning liquidity. The fast campaign enters at the next
open, while the forward paper desk uses a fetched Yahoo last price.

**Action:** separate decision-time observations from execution-time
observations. Given an identical execution fixture, research and paper replay
must agree on selected orders, fills, costs and equity. Daily bars cannot certify
a limit order's fill at a specific 09:21 timestamp; use a declared conservative
daily proxy for research and timestamped observations for execution validation.

### 3. The stock ranking policy changes between research and paper

`backtest/portfolio_campaign.py:262` ranks by 20/63-session returns and volume.
`automation/governed_entry.py:110` uses nine weighted inputs and correlation
controls. The Strategy Plan identifies entry/exit/sizing behavior, but does not
by itself identify that entire portfolio policy. The type check in
`strategy/conformance.py:17` does not prove equality of portfolio decisions.

The portfolio campaign also permits only one holding per strategy. With its
20%-of-initial-capital position cap, a single-strategy run has at most one such
allocation; a five-strategy combination can deploy much more. The August
breakout-only one-year result used about 19.15% average capital. Comparing raw
returns/drawdowns without that context confounds signal quality and exposure.

**Action:** bind plan, universe, ranking, portfolio sizing, costs and execution
policy into each experiment identity. Test at matched risk/exposure as well as
the intended actual allocation. One strategy family may select several stocks
if that is the preregistered portfolio design; lineage count is not economic
diversification. Historical OOS statistics used by ranking must themselves have
been available before the replay decision, not learned from its future.

### 4. The newest screen rejects a different risk model

September's protocol allocates 100% of each independently funded chart account
to one stock, and requires worst per-chart drawdown ≤15%. Twenty such accounts
represent ₹60 lakh initial capital, not a single ₹3 lakh portfolio. A 40%
single-stock drawdown is not a measured 40% portfolio drawdown; correlations,
sizing, overlapping positions and cash determine the latter.

Positive median trade return is also not a necessary property of a profitable
trend system. For illustration, 40% wins of +3R and 60% losses of −1R have
negative median but positive mean +0.6R before costs. This does not demonstrate
that Sensei has that distribution.

**Action:** retain all five September rejections under their frozen protocol.
Treat them as rejection of that particular experiment, not proof that all
descendant hypotheses lack an edge. In a newly declared campaign, use net
portfolio results, uncertainty, tail risk and benchmark comparisons as primary
criteria; report median and hit rate as descriptive statistics. Do not choose
new thresholds to make the observed winners pass.

### 5. “2024 onward” is already research-exposed

The September TradingView document calls 2024 onward a one-use holdout.
However, `strategy-diagnostic-matrix-300k.json` already contains windows ending
2026-08-06, and August analyses discuss their performance. The same years were
therefore visible to the research process. A new tool, vendor or run identifier
cannot make those market outcomes unseen again.

**Action:** mark previously inspected periods as development/validation.
Reconstruct exposure across related experiments and data sources. Any genuinely
unexamined archive must have credible access history; otherwise accumulate
prospective frozen observations. Walk-forward tests on exposed history remain
useful, but must not be represented as fresh confirmation.

### 6. Data quality still limits what can be concluded

The August matrix explicitly excludes incomplete price histories: 409/500
symbols at one year, 365/500 at three and 337/500 at five. The code chooses that
cohort using the entire future evaluation window
(`strategy_diagnostic_matrix.py:159`). This avoids missing marks by selecting
survivors. Prior reports also identify unresolved price discontinuities.

The AccelPix adapter is useful preparation, not evidence that its corpus now
contains complete historical membership, inactive securities and corporate
actions. The other task's last completed ingestion work made no authenticated
vendor calls. No new vendor calls were made in this review.

**Action:** validate one available price source against an explicit data
contract: stable instrument identity, historical entry eligibility, raw prices,
corporate actions, adjustments, missing-bar treatment, delisting outcomes and
publication/availability times. Retain distributions and exclusion counts. Use
the existing current-survivor data only for labelled development checks. A
negative result on corrupted data is not automatically valid rejection evidence
either; unresolved events can bias losses as well as gains.

Do not wait for a complete fundamental/news platform to research a price-based
swing strategy. Do not claim that acquiring five years of current constituents
solves survivorship bias.

### 7. A drawdown arithmetic defect is fixed in this review

`BacktestResult.max_drawdown_pct` omitted the initial capital high-water mark.
A single −10% trade reported 0%; two successive −10% trades reported 10%
instead of 19%. The fix includes starting capital in the running peak.
Four regression cases cover an initial loss, consecutive losses, loss after a
gain and no trades. The tests failed before the fix and pass after it.

This fixes the legacy per-trade compounded metric only. It does not reconstruct
intratrade or shared-portfolio drawdown, does not change trade P&L, and is not an
explanation for all negative strategy results. Existing stored reports were
not rewritten.

### 8. Live readiness still requires implementation

`execution/openalgo.py:59` rejects off/live calls and accepts sandbox only.
`reporting/prelive.py:1504` explicitly reports no live backend. Conversely,
the durable paper gateway, production composition, account projection and
scheduler already exist. Older architecture documents claiming they are absent
are historical descriptions, not today's implementation inventory.

Forward paper observations stamp fetch time as `observed_at` and estimate
spread/circuit limits (`runtime/production.py:763`). That cannot establish actual
source freshness or tradability. The governed live adapter needs authentic
broker/market observations, reconciliation, restart recovery, partial fills,
idempotency and persistent protection tests. No live orders were submitted.

## Architecture to keep, and the one seam to deepen first

Keep the Strategy Plan engine, source/claim provenance, lifecycle, signed
evidence, journal, reservations, Committee, supervisor and protect-first kernel.
These modules hide meaningful complexity. Deleting them would push risk and
ordering rules into callers.

Deepen the Examination module using shared portfolio decisions and execution
semantics. Fast research and governed replay are real adapters at that seam.
The goal is locality: a fill or ranking correction should reach both. The
leverage is one meaningful paired test surface for every Strategy Plan version.
Keep source ingestion and agent debate out of the per-bar statistical loop.

Second, deepen the Market Data Snapshot/observation seam so historical and
forward adapters distinguish available-at time, observed-at time and fetch time.
Third, replace broad interpretations of the shallow conformance type check with
evidence of exactly which decision and accounting behaviors were compared.

## Bounded swing research campaign

The external evidence and qualifications are documented separately in
[stock-strategy-evidence-2026-09-06.md](stock-strategy-evidence-2026-09-06.md).
Published momentum evidence is a rationale to test a hypothesis, not a promise
that this implementation will outperform.

Start with one price-based family and one retained control:

1. **Simple relative-strength momentum baseline:** rank liquid, historically
   eligible equities using a declared medium-term return measure excluding the
   most recent month; rebalance monthly; use explicit position/sector limits and
   a common ₹3 lakh cash account. Freeze rank definitions, rebalance timing,
   replacement rules and membership before evaluating. This is a new executable
   hypothesis, not an existing supported RuleSpec feature.
2. **One controlled momentum variant:** keep that signal fixed and change only
   the predeclared risk control, for example volatility-scaled sizing. Compare at
   matched exposure/risk. Test a market trend filter separately only if there is
   a registered reason; do not bundle a dozen improvements into one candidate.
3. **Unchanged Minervini breakout control:** retain exact old conditions for
   attribution under the corrected common engine. Its old failure remains on
   record. A new shared-portfolio evaluation is a different campaign, not a
   retroactive promotion.

Do not assume multiple momentum names are independent strategies. Defer
earnings-drift/quality combinations until point-in-time historical filings and
revisions are available. Defer short-term reversal/intraday until reliable
execution data supports their higher turnover and timing demands.

Before results, freeze a small experiment budget: the baseline, one variant,
and the existing control. Count prior related trials when assessing selection
bias. No parameter grid or repeated holdout access. A failure means reject or
inconclusive for this campaign, with any follow-on experiment separately
justified and registered.

### Required report from that campaign

Use one daily marked account equity curve including cash, open positions,
dividends/actions, actual integer sizing and every trading charge. Preserve raw
execution prices separately from adjusted indicator prices. Costs must include
applicable delivery taxes/fees, DP debits, spread, slippage and capacity; use
effective-dated schedules or label a constant schedule as a current-cost
counterfactual. Stress variable execution costs and missing/partial fills.

Report CAGR, max drawdown and duration, net profit, turnover, exposure, cash
utilization, risk concentration, worst months, regime/fold results and
uncertainty. Compare against cash, an appropriate broad-market total-return
benchmark, a simple momentum benchmark, and matched-exposure controls. Separate
benchmark index history from the practical cost of investing in its vehicle.

Use common chronological walk-forward windows, pre-window indicator warm-up,
and purge/embargo treatment based on the actual information/holding horizon.
Do not pool symbol trades as independent observations; quantify uncertainty
with time blocks or other dependence-aware methods. Respect campaign-wide
multiple testing. A small sample or an interval spanning no edge is
**inconclusive**, not evidence to force a live decision.

The user must set their maximum acceptable account drawdown before performance
selection. Historical drawdown is an estimate, not a guaranteed future loss cap.
No final numerical deployment threshold is approved by this document.

## Completion gates — a finite decision, not endless polishing

| Step | Concrete output | Exit condition |
|---|---|---|
| 1. Backtest contract | Versioned decisions/execution policy and paired fixtures | Identical selected orders, quantities, fees and cash under identical observations; all declared differences explained |
| 2. Data admission | One immutable snapshot with a coverage/action/identity audit | No unresolved admissibility blocker for the intended experiment; otherwise explicitly data-blocked |
| 3. Fixed campaign | Baseline + one variant + retained control, benchmarked portfolio report | Economic criteria fixed in advance met with adequate uncertainty, or reject/inconclusive and close campaign |
| 4. Frozen forward paper | Timestamped signal/fill log, reconciliation and drift report | Sufficient forward observations for strategy frequency plus operational recovery checks; elapsed days alone do not prove edge |
| 5. Governed canary integration | Real broker adapter and reviewed capital/loss interlocks | Broker constraints verified and operational tests pass; explicit activation and risk budget still required |
| 6. Capital decision | Retain, scale, stop or continue collecting evidence | Scale only from measured net execution/results under the agreed policy |

₹3 lakh is the target account, not automatic permission to deploy the whole
amount on the first day. Canary allocation and loss budget must be explicit.
No promise of a launch date or highest returns is warranted. Closure means an
auditable decision with a defined stop condition, including rejecting a weak
strategy, rather than continuing until a backtest finally turns green.

## Reproduction and limits of this review

Run the synthetic contract probe:

```bash
.venv/bin/python docs/research/probes/backtest_contract_audit.py
```

At the initial audit it reported drawdown **PASS** (10%) and gap parity **FAIL**
(−5% versus +10%). After the follow-up implementation, it reports **PASS** for
both checks, with +10% before costs in all three daily research paths and exit
code 0. It uses three synthetic daily bars, no remote data, and no trading state.

The initial targeted suite passed 45 tests and the baseline full suite passed
769 tests. After the arithmetic correction, the full suite passes **773 tests**
(`.venv/bin/python -m pytest -q`, 25.84 seconds), including the four new
regression cases. Passing software tests is not evidence of alpha.
No full market campaign was rerun: repeating the exposed history under the old
conflicting policies would not answer the user's economic question.
