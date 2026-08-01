# Strategy validation campaign

Date: 2026-08-01

Status: research evidence only; not real-capital authorization.

## Reproduce

```bash
uv run sensei validate-strategies \
  --folds 5 \
  --cost-pct 0.25 \
  --report data/reports/strategy-validation-latest.json
```

The command evaluates only strategies marked adopted in the supplied Playbook.
It records a content fingerprint over every OHLCV input, executable strategy
source and exit parameter plus an execution fingerprint covering the campaign
engine, backtest engine, dependency versions, Git revision, Playbook,
`pyproject.toml` and `uv.lock`. The first folds are development, the penultimate
fold is validation and the final chronological fold is a reusable holdout. It
is deliberately not called locked confirmation because a durable preregistered
one-use access boundary is required. To consume a genuinely one-use final fold,
add `--consume-locked`; the command preregisters the exact campaign identity in
`data/research/strategy-validation-locks.json` before evaluating outcomes and
refuses a second access. A crashed run is still recorded as consumed.

The fast strategy-edge campaign is deliberately separate from
`sensei replay-desk`: the latter certifies the nine-agent, L1-L4, broker,
protection and learning machinery. Repeating that operational ceremony for
every historical signal would not provide additional statistical independence.

## Baseline result

Universe: 500 currently stored Indian equities. Five chronological folds.
Round-trip friction: 0.25%.

| Strategy | Trades | Overall expectancy | Holdout expectancy | Holdout profit factor | Preliminary economic result |
| --- | ---: | ---: | ---: | ---: | --- |
| Minervini trend template | 33,020 | +1.779% | +2.197% | 1.475 | Promising, data-blocked |
| Minervini breakout volume | 19,805 | +1.697% | +1.986% | 1.433 | Promising, data-blocked |
| Schwager trend with pullback | 9,882 | +1.534% | +1.871% | 1.478 | Promising, data-blocked |
| Gujral trend alignment | 54,630 | +0.585% | +0.795% | 1.234 | Cost-sensitive, data-blocked |
| Sadekar hammer confirmation | 9,592 | +0.261% | +0.601% | 1.238 | Fragile, data-blocked |

## Cost sensitivity

The 0.50% and 1.00% runs reuse the same history and therefore are diagnostics,
not independent confirmations.

- Minervini trend template, Minervini breakout volume and Schwager pullback
  remained above the preregistered locked expectancy and profit-factor floors
  at 1.00% friction.
- Gujral passed 0.50% but failed at 1.00%.
- Sadekar failed at 0.50% and 1.00%.

## Blocking data-quality finding

The stored adjusted histories contain apparent corporate-action or vendor
adjustment discontinuities. Examples include PATANJALI (about -97%), CIPLA
(about -92%), SAREGAMA (about -90%) and GPIL (about -77%) across a held trade.
These are not credible ordinary overnight market moves. Because targets are
capped while gap losses are uncapped, such discontinuities distort expectancy,
profit factor and the reported trade-sequence drawdown.

The command now detects greater-than-50% overnight discontinuities and
mechanically prevents an unqualified `PROMISING` verdict. It also blocks on
missing historical universe membership. Do not silently remove these
observations. The next data revision must:

1. ingest point-in-time split, bonus, merger, symbol-change and delisting facts;
2. identify contaminated instrument intervals before results are calculated;
3. publish raw and corporate-action-normalized results side by side;
4. fail confirmation when unresolved discontinuities cross a declared limit;
5. replace current-constituent history with historical universe membership to
   remove survivorship bias.

## Decision

There is credible preliminary evidence for the two Minervini strategies and the
Schwager strategy. There is weaker evidence for Gujral and insufficiently robust
evidence for Sadekar. None is yet validated for real capital because the input
history is survivorship-biased and contains unresolved corporate-action
discontinuities. Continue paper-only operation while the data foundation is
repaired and the confirmation campaign is rerun on a fresh locked dataset.
