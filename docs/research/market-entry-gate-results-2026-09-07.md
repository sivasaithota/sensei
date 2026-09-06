# SMA200 new-entry gate results — 7 September 2026

The fixed market entry gate **worsened both observed returns**. It reduced
transaction costs and below-average exposure, but did not establish an edge.
Both unchanged controls reproduced their complete saved campaigns exactly.
Do not adopt the gate or continue changing its moving-average length to seek
a favorable result.

## Frozen experiment

Declaration: `config/stock-market-entry-experiment-v1.json`, saved before the
runs at 2026-09-06 22:50:24.130404 UTC (7 September 04:20:24 IST). Two additional
development tests: original baseline plus gate; 60-session counterpart plus gate.
Each pair differs only by campaign name and the explicit market-entry setting.

The gate requires the preceding Nifty 500 gross TRI close to be above the mean
of its preceding 200 closes. Unknown or missing states deny entry. It combines
with the existing demerger eligibility using AND and does not change exits on
existing holdings. Both retain the same 499-stock snapshot, 665-session window,
5% stop, 12% target, ₹300,000 account, sizing, fees and slippage. The pair-specific
holding limit remains 30 or 60 sessions. Nifty 500 gross TRI returned +22.9535%.

## Complete results

| Run | Final equity | Return | Excess vs TRI | Max drawdown | Trades | Costs |
|---|---:|---:|---:|---:|---:|---:|
| baseline-control | ₹294,661.96 | -1.779% | -24.7325 pp | 29.451% | 467 | ₹68,191.57 |
| hold60-control | ₹329,853.50 | +9.951% | -13.0025 pp | 23.974% | 441 | ₹64,723.86 |
| baseline-gate | ₹285,236.53 | -4.921% | -27.8745 pp | 26.928% | 373 | ₹54,664.77 |
| hold60-gate | ₹284,050.82 | -5.316% | -28.2695 pp | 27.332% | 360 | ₹52,659.99 |

Both gated variants report NO_CLEAR_NET_EDGE. All four remain DATA_BLOCKED and
can_trade=false. Their exploratory annualized excess-return intervals include
zero; these are reused-history tests with no multiple-testing correction. No
listed demerger holding exposure or simulation blocker was present.

| Run | Buy + sell turnover | Average utilization | Below-average EOD utilization | Below-average marked P&L |
|---|---:|---:|---:|---:|
| baseline-control | ₹54,822,741.93 | 74.96% | 72.649% | ₹-86,335.29 |
| hold60-control | ₹52,068,676.08 | 73.48% | 71.313% | ₹-69,903.12 |
| baseline-gate | ₹43,966,313.06 | 59.37% | 5.989% | ₹-19,807.30 |
| hold60-gate | ₹42,344,376.09 | 59.26% | 5.395% | ₹-27,759.76 |

For the baseline, below-average EOD exposure fell from 72.649% to 5.989%, and
losses on those sessions shrank. But marked P&L on above-average sessions also
fell from +₹80,997.25 to +₹5,043.83. The full admission, cash and holding path
changed; the gate is not equivalent to subtracting the losing entry cohort from
the previous run. This is why the earlier attribution was not a filter backtest.

The 60-session control gained 9.951%, while its gated variant lost 5.316%.
The gate reduced trades and costs, but its drawdown rose from 23.974% to 27.332%.
Neither a lower trade count nor a plausible market narrative is sufficient
evidence of an improved strategy. No control config or live strategy was replaced.

## Implementation and checks

`market_entry_gate` accepts only `benchmark_above_sma200` or omission/null.
It reuses the reviewed state function, checks the prospective entry session,
denies unknown/missing states and preserves all input stocks and sessions.
Existing eligibility must cover exactly the universe with aligned boolean
masks. The market mask cannot override an event exclusion.

Event audit counts remain ABFRL 259 and VEDL 95 sessions for every run. The
market audit separately records 504 above and 161 at-or-below sessions. Every
gated entry was independently checked against the prior-only state and was
above SMA200. Gate settings, benchmark hashes, gate/state implementation code
and resulting campaign eligibility masks participate in the frozen identities.

Tests exercise unknown and below-average denial, current/future data isolation,
mask composition, missing/misaligned input masks, retained existing holdings,
invalid settings and changed run identities. The original controls have new
run IDs because the runner implementation changed; their campaign objects,
including all trades and daily equity marks, equal the saved originals.

Validation: **917 tests passed**. Standards and Spec implementation reviews
found no remaining issues. All runs used saved local data, with no Kite requests,
subscription changes, credential access or live orders.

## Exact artifacts and reproduction

All source reports are under `data/reports/stock-development/<ID>/report.json`.
Local comparison: `market-entry-comparison-v1-20260907.json`, including report
hashes, daily-state diagnostics and control/mask verification results.

| Run | Run ID | Report SHA-256 |
|---|---|---|
| baseline-control | `2d2f2ea5243c850bb4758f7dd52b8898dd0beb863cf507127ccd11e3a3734b9a` | `c9d5a2672eab1f80f403acc4599b3a5b2e2d94fe33e40f24f91767515d6e4d4a` |
| hold60-control | `281eb8d7f7f8eb29a81f391924149b03b4ad4965ed133db83ff7acd549fc2b99` | `917c27cd170b1be3400ccf8f89c7abf5841111dd009a212beeee832ab8b22a82` |
| baseline-gate | `db8f8e87296c48be515a618b5caa0b013f2760f28c765d25946eccdf1fa30a2b` | `0b17d282cc0cc24d97e6e592c4cf03670e93d834930dc7e1e6d5abc2f20b77cd` |
| hold60-gate | `a037b374e3a5292e40efc1b45973896cc97c1c5bb72254aef7adfc0d0dcbba79` | `fd62ad8fce95311d29f8a59f039b17817e84996c34489bd112294f18b96dfaa9` |

```bash
.venv/bin/python -m sensei.research.stock_evaluation \
  --config config/stock-research-market-gate-baseline.json
.venv/bin/python -m sensei.research.stock_evaluation \
  --config config/stock-research-market-gate-hold60.json
```

## Next bounded action

Stop this seed/filter tuning sequence. Inspect corporate-action exposure in the
actual held securities using the existing verified raw NSE bhavcopies and saved
Kite bars, starting with split/bonus and cash-dividend accounting. Distinguish
observed raw/adjusted factor changes from verified corporate-action events.
Use primary company/exchange evidence for confirmation; keep missing receipts
and unresolved entitlement/cash treatment explicit. Do not invent a multiplier
or credit dividends on top of an unknown adjusted-return convention. No price
repair or economic upgrade is justified by an unexplained ratio alone.

These failures are retained evidence, not a reason to erase runs or relabel the
same history as an untouched test. Architecture and live permissions remain
unchanged; a performant, deployable strategy has not yet been demonstrated.
