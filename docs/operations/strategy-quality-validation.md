# Strategy quality validation — ₹3 lakh paper desk

Date: 2026-07-27

Status: research evidence; not live-capital authorization.

## Question

Does limiting concurrent exposure to one position per Strategy Plan lineage
improve the governed desk's decision quality without changing strategy rules or
risk thresholds?

This is a lineage-concentration control. It does not claim that distinct
lineages are economically uncorrelated strategy families.

## Method

- Capital: ₹300,000.
- Execution: production-faithful NSE paper model, including costs, impact,
  Committee admission, protection, reconciliation and episode learning.
- Point-in-time rule: each replay session observes data only through that
  session.
- Comparison: five identical, non-overlapping five-session windows before and
  after the lineage constraint.
- Continuous evaluation: two mutually non-overlapping 20-session windows.
  Their dates overlap the earlier five-window investigation, so they are not a
  locked or untouched confirmation dataset.
- Risk limits, plans, ranking weights and exit rules were unchanged.

## Five-window A/B result

| Policy | Marked P&L | Interpretation |
| --- | ---: | --- |
| Symbol-only diversification | −₹13,810.60 | 23 entries; all fills came from two Minervini lineages |
| One open candidate per lineage | −₹13,739.25 | Five lineages participated; ₹71.35 difference is immaterial |

The constraint improved strategy representation and reduced redundant candidate
evaluation, but did not establish a return improvement.

## Continuous evaluation results

| Source window | Closed trades | Targets | Stops | Open | Net/marked P&L |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2026-06-29 to 2026-07-24 | 5 | 1 | 4 | 0 | −₹2,052.57 |
| 2026-06-01 to 2026-06-26 | 5 | 1 | 4 | 1 | −₹1,874.30 |

The recent window's completed-trade expectancy was approximately −₹411 per
trade. The realized payoff distribution required a hit rate near 28% to break
even; observed hit rate was 20%.

Strategy outcomes changed between windows:

- Minervini breakout-volume hit a target in the recent window and a stop in the
  older evaluation window.
- Gujral trend alignment stopped in the recent window, then produced one target
  and one stop in the older evaluation window.
- Minervini trend-template recorded three stops across the two windows.
- Schwager pullback recorded one stop and one still-open position.

This is insufficient evidence to retire or promote any one plan. Disabling a
plan from these samples would be result-shopping.

## Operational findings

- The full governed path certified every completed 5- and 20-session replay.
- Repeated authentication of unchanged Account Snapshot truth previously caused
  a durable journal conflict; that defect was fixed and replayed successfully.
- Safety-state projection materialized the full journal for every candidate,
  causing nonlinear slowdown as decision snapshots accumulated. Ordinary
  no-reset projection now reads only the safety stream; historical reset
  verification still reads all linked evidence.

## Decision

Keep the lineage-concentration rule as portfolio hygiene. Do not describe it as
strategy-family diversification or evidence of alpha.

Remain in paper mode. Before any live-capital decision:

1. define provenance-backed strategy families or estimate plan-return
   correlations in a preregistered research campaign;
2. run longer train/validation/locked-confirmation windows;
3. provide a repository-owned, reproducible campaign command with pinned code,
   configuration and data identities;
4. report completed-trade expectancy, drawdown, capital utilization, stop/target
   distribution and strategy/regime attribution;
5. require improvements to survive genuinely untouched validation data.
