# Lower-turnover swing comparison — 7 September 2026

Three predeclared variants completed. The 60-session holding limit improved the
observed result, but none demonstrated a net edge over Nifty 500 gross TRI.
Lower transaction costs alone did not solve the strategy weakness. All remain
reused development history and DATA_BLOCKED; no live setting changed.

## Results

Evaluation: 2024-01-01 through 2026-09-03, 665 sessions, ₹300,000 initial equity.
All use the same 499-stock snapshot, next-session fills, fees/slippage and two-event
demerger guard. The benchmark returned +22.9535%.

| Variant | Final equity | Return | Max drawdown | Trades | Costs | Excess vs TRI |
|---|---:|---:|---:|---:|---:|---:|
| control | ₹294,661.96 | -1.779% | 29.451% | 467 | ₹68,191.57 | -24.7325 pp |
| hold60 | ₹329,853.50 | +9.951% | 23.974% | 441 | ₹64,723.86 | -13.0025 pp |
| hold60-target20 | ₹278,859.65 | -7.047% | 31.485% | 268 | ₹37,742.58 | -30.0005 pp |
| trend-hold60-target20 | ₹279,377.33 | -6.874% | 41.720% | 250 | ₹35,213.49 | -29.8275 pp |

The control is the unchanged 5% stop / 12% target / 30-session momentum breakout.
`hold60` only extends its time limit to 60 sessions. `hold60-target20` also raises
the target to 20%. `trend-hold60-target20` adds the existing trend-filtered entry
package documented in [the specification](../specs/lower-turnover-comparison.md),
with the same 5% stop / 20% target / 60-session bracket. These are hypotheses,
not faithful implementations of a named author’s entire trading approach.

## Turnover and exits

| Variant | Buy + sell turnover | Turnover / initial equity | Turnover / mean daily equity | Utilization | Median / mean held sessions |
|---|---:|---:|---:|---:|---:|
| control | ₹54,822,741.93 | 182.742× | 162.800× | 74.96% | 4 / 7.00 |
| hold60 | ₹52,068,676.08 | 173.562× | 148.762× | 73.48% | 4 / 7.42 |
| hold60-target20 | ₹30,209,805.95 | 100.699× | 96.189× | 86.63% | 5 / 12.24 |
| trend-hold60-target20 | ₹28,185,967.49 | 93.953× | 91.224× | 84.63% | 5 / 12.93 |

Turnover ratios cover the entire evaluation period and are not annualized.
Holding-session counts include the entry and exit sessions. Fewer trades need
not mechanically lower rupee costs: quantities, prices and subsequent account
paths also affect notional turnover and charges. In these runs both fell.

| Variant | Stop + gap stop | Target | Time | Final session |
|---|---:|---:|---:|---:|
| control | 308 | 133 | 22 | 4 |
| hold60 | 297 | 136 | 4 | 4 |
| hold60-target20 | 200 | 46 | 18 | 4 |
| trend-hold60-target20 | 187 | 44 | 14 | 5 |

The baseline had 308 stop/gap-stop exits (65.95% of 467 trades), versus only 22
time exits. Extending the holding limit reduced time exits to four and improved
this observed path, but is insufficient evidence to select it for live use.
The 20% target variants approximately halved costs yet also reduced gross
realised profits substantially; their net returns and drawdowns worsened.
Do not widen stops merely to improve the hit rate.

All three annualized mean daily excess-return bootstrap intervals include zero.
These intervals are exploratory, with no adjustment for selecting among multiple
variants. Historical membership, ordinary dividends, executable-price treatment
and entitlement accounting remain uncertified. No positions crossed the two
listed demerger ex-dates in these runs; this is partial event coverage.

## Execution failure and fix

The first parallel attempt completed the trend variant, while the other two
stopped before simulation with JournalConflict in the shared research-exposure
stream. They read version 8 before another writer advanced the stream to 9.
No economic result existed for those two failed attempts; the exact frozen
configurations were resumed after fixing bookkeeping.

The exposure ledger now retries version conflicts up to eight attempts, rereading
the stream and rechecking confirmation overlap every time. An identical payload
is deduplicated. Its append key includes the command timestamp to avoid false
integrity errors when concurrent identical exposures have different occurred_at
values. Journal integrity errors are not swallowed, and persistent contention
still stops the operation. No price, signal, sizing, fill or fee code changed.

A deterministic barrier test with two real SQLite writers reproduced all three
failure cases before the fix: distinct discovery records, concurrent identical
exposure and competing confirmation campaigns. They now pass, preserving both
discovery records or one identical record while excluding the competing holdout
claim. The actual interrupted runs also completed concurrently after the fix.

## Frozen evidence and reproduction

Declaration: `config/stock-lower-turnover-experiment-v1.json`, saved before the
new evaluations at 2026-09-06 20:53:12.792871 UTC (7 September 02:23:12 IST).
Every control/variant config hash still matches that declaration.

```bash
.venv/bin/python -m sensei.research.stock_evaluation \
  --config config/stock-research-lower-turnover-hold60.json
.venv/bin/python -m sensei.research.stock_evaluation \
  --config config/stock-research-lower-turnover-hold60-target20.json
.venv/bin/python -m sensei.research.stock_evaluation \
  --config config/stock-research-lower-turnover-trend-hold60-target20.json
```

Reports live under `data/reports/stock-development/<run ID>/report.json`.
The local ignored comparison artifact `lower-turnover-comparison-v1-20260907.json`
records all metrics, report hashes and the declaration hash.

| Variant | Run ID | Report SHA-256 |
|---|---|---|
| control | `7e9a282839b09e84f25668c3e20bf60bbfa8e8372079e8c21ae2bbaa2411a579` | `9f974fb974bbdcb8dd5907754659a881bfb3039350ec7dcb78e2d0a53f57568c` |
| hold60 | `37cce8566182837832d6efb76528172453ca99ac5fc096e112d06c79c12a1a85` | `f07090ee85bef547f13ae4e7b7087324f46d4dc22183b9ea0ad110f576c1b43a` |
| hold60-target20 | `5477cdb854489b790554057c1daa2dc8279165b06911dacfbf44ce70d32bc934` | `6855339bdbab92818ecf5bcc38ddf5489dfcf092ac88d14f02a8650fbf1c0c84` |
| trend-hold60-target20 | `0ea62de96aed0177f22b12251dcaa169fe04630b40daf849876d6445fa2c6f6f` | `db2eab91edc89373f91ad0d4c5b00d1773c69bdb9144f57ff681137f1b9c8886` |

## Next bounded action

Examine the existing control and three completed trade ledgers for concentration
of losses by time period and security, stop/gap-stop contribution, and entry-date
volatility. This is descriptive diagnosis, not a new parameter search. Use only
pre-entry observations for any volatility measure. Do not exclude losing stocks
or relabel a later slice of already inspected history as a holdout. Continue the
remaining corporate-action/membership work where evidence is available.

No Kite API requests, credential changes, paid services or live orders were used.

Validation: **892 tests passed**. Standards and Spec implementation reviews found
no remaining issues. Configuration hashes and report checksums were verified.
