# Governed research and backtest loop

Status: research-only workflow. It cannot modify the active Playbook, promote a
Strategy Plan, authorize capital, or consume locked confirmation evidence.

## Objective

Sensei should repeatedly learn, but repeated access to the same historical
outcomes must not be mistaken for independent evidence. The loop therefore
separates idea discovery from portfolio validation and final confirmation:

1. collect primary-source claims and operational lessons;
2. translate one claim into a constrained, versioned hypothesis;
3. preregister its rule, universe, folds, costs and success criteria;
4. run chronological discovery and validation folds;
5. stress the unchanged hypothesis across a cost ladder;
6. retire, revise once with a stated reason, request more evidence, or advance;
7. replay advancing hypotheses in the production-faithful ₹300,000 portfolio;
8. use a genuinely untouched, one-use confirmation dataset only after the
   research family is frozen;
9. require governed paper evidence before any owner decision about real money.

Research results are allowed to create another research hypothesis. They are
not allowed to edit a live strategy, change a threshold after seeing results,
or promote themselves.

## Broad-cycle command

```bash
uv run sensei research-cycle \
  --folds 5 \
  --costs 0.25 0.50 1.00 \
  --maximum-variants 30 \
  --cycle-id current-library-2026-08-06 \
  --report data/reports/research-cycle-20260806.json
```

The command tests every currently encoded hypothesis, rather than only the
adopted set. It loads market data once, evaluates fixed chronological folds at
each declared round-trip cost, records reproducibility fingerprints, and emits
one disposition per hypothesis:

- `retire_hypothesis`: baseline economics did not validate;
- `revise_hypothesis`: baseline evidence existed but did not survive stress;
- `needs_more_evidence`: the sample was insufficient;
- `advance_to_portfolio_replay`: trade-level evidence survived the cost ladder.

Advancement is not promotion. A portfolio replay and clean-data confirmation
are still mandatory. The report explicitly records `can_change_playbook=false`
and `locked_confirmation_consumed=false`. It can only report readiness for the
portfolio-replay gate; it always records `ready_for_confirmation=false`.

Before reading outcomes, the command writes the complete cost ladder, fold
count, executable variant identities, data/execution identity and fixed family
budget to `data/research/research-cycle-ledger.json`. Later cycles in the same
family cannot increase that budget, and the cumulative union of attempted
variant identities cannot exceed it.

## Current first-cycle result

The 2026-08-06 run evaluated 19 hypotheses over 500 stored Indian equities,
five chronological folds and three cost assumptions. Three survived the full
cost ladder and should advance to ₹300,000 portfolio replay:

- `minervini_breakout_volume`;
- `minervini_trend_template`;
- `schwager_trend_with_pullback_strength`.

Five were cost-fragile and should only be revised from a new, documented
economic thesis. Eleven should be retired from the active research queue.

No hypothesis is ready for confirmation. All results remain blocked by current
constituent survivorship bias and unresolved price/corporate-action
discontinuities. Running more variants on those contaminated inputs increases
false-discovery risk; it does not remove the blocker.

## Iteration budget

Every research family must declare a finite maximum number of variants before
testing. A changed condition, lookback, stop, target, holding period, universe,
ranking weight or regime rule is a new variant. Cost sensitivity of an
unchanged rule is diagnostic and remains part of the same trial.

When a family exhausts its budget, it is frozen or retired. Opening a new family
requires a genuinely new source-backed economic mechanism, not a renamed
parameter search.

## Required next slice

The next implementation should consume only the three advancing hypotheses in
a production-faithful ₹300,000 portfolio campaign and report calendar equity,
drawdown, exposure, turnover, sector and strategy concentration, completed
trade expectancy, and regime attribution. It must then be rerun after the
point-in-time universe and corporate-action data foundation is repaired.
