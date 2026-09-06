# Stock portfolio evaluation

Scope: NSE cash-equity swing, ₹300,000 shared capital. The user confirmed a
100% maximum acceptable account drawdown on 6 September 2026, accepting the
possibility of complete capital loss. This is the research evaluation budget;
per-trade stops, daily/weekly operational limits and live authorization are
separate controls.

The reusable settings are in `config/stock-research.json`. Edit
`evaluation.maximum_drawdown_pct` to choose the research budget (greater than
zero, up to 100%). Capital, position limits, costs, dates and strategy exits are
also explicit settings. Relative paths resolve against the JSON file's folder.
This threshold evaluates historical results; it does not change the running
paper/live kill-switch configuration in `config/risk.yaml`.

Run the frozen development baseline:

```bash
.venv/bin/python -m sensei.research.stock_evaluation --config config/stock-research.json
```

Override only the drawdown budget for a separate run:

```bash
.venv/bin/python -m sensei.research.stock_evaluation \
  --config config/stock-research.json --max-drawdown 20
```

The override leaves the saved file unchanged. It creates a different run
identity and output directory. Settings, actual signal definitions, input
hashes, runtime versions and implementation identity are recorded in
`manifest.json` before simulation. Cached reports require that manifest and
a matching `report.sha256`. Source captures and results are local data artifacts,
not checked into Git.

The baseline retains every instrument but limits input dates to the declared
2024-01-01 through 2026-09-03 evaluation and each instrument's preceding 252
stored sessions. Missing sessions remain visible. September 3 is the explicit
endpoint selected from local availability, before performance inspection.

The official benchmark has been captured locally. To reproduce the capture
on a fresh checkout, run:

```bash
.venv/bin/python -m sensei.data.nifty_benchmark \
  --start 2022-12-01 --end 2026-09-04 \
  --output data/research/benchmarks/nifty500-tri-20260906.parquet
```

This uses the request format published by the official
[NSE Indices historical-data page](https://www.niftyindices.com/reports/historical-data)
and retains raw responses and a hash-bound manifest. It rejects an existing
destination; choose a new filename for a new capture.

The earlier direct CLI remains available for explicit exploratory inputs:

```bash
.venv/bin/python -m sensei.research.stock_evaluation \
  --start 2024-01-01 --end 2026-09-04 \
  --strategy momentum_breakout_55 \
  --benchmark /absolute/path/to/benchmark.parquet \
  --benchmark-name 'Nifty 500 total return' \
  --entry-slippage-bps 10 \
  --max-drawdown 100 \
  --report data/reports/stock-portfolio-development.json
```

An external benchmark file is also accepted by that direct CLI. It must
contain a `close` series indexed by dates, including the exact preceding
portfolio session. Missing dates are not forward-filled. Specify
`--max-drawdown 100` for the owner's confirmed budget. Omitting the option
still produces an inconclusive economic verdict; the library has no implicit
owner-specific risk default.

The report gives net return, CAGR, maximum drawdown, longest time underwater,
capital utilization, turnover, completed trades, realized costs and benchmark
excess. A circular moving-block bootstrap reports exploratory uncertainty in
annualized mean daily excess. The default 252-session/30-trade minimum is an
explicit screening configuration, not statistical certification. It does not
correct for repeated strategy selection. Median trade P&L is descriptive.

The simulator buys whole shares from one cash account, reserves charges,
protects entry-day positions, processes opening exits before admissions and
liquidates remaining positions at the evaluation boundary. Current delivery
charges include the existing NSE schedule and ₹15.34 per simulated sale for
DP. Same-day sale DP is deliberately conservative; exact broker settlements,
historical taxes and exit slippage need separate validation. Repeat a frozen
candidate at larger slippage assumptions as sensitivity analysis and retain
every result. Do not select a favorable cost assumption after observing it.

Data and economics have separate verdicts. Current local files do not establish
historical membership or corporate-action treatment, so this command emits
`DATA_BLOCKED` even if performance looks promising. Missing held-position bars
stop simulation; short-lived securities are not deleted by future completeness.
The report is always `RESEARCH_ONLY`, `can_trade=false`, and reused development
history. It cannot publish a promotion dossier or change the trading account.

For strategy work, retain the existing frozen rules as controls and investigate
medium-horizon relative strength as a separately registered hypothesis. The
[strategy evidence review](../research/stock-strategy-evidence-2026-09-06.md)
explains its basis and limits. No new strategy is declared profitable by these
engineering corrections. Historical data validation, a benchmark, forward
paper evidence, and a governed broker adapter remain required for a live decision.

The first frozen run stopped on a calendar mismatch: four real sessions are
missing from all local stock files and four holidays have zero-volume rows.
The raw NSE archive contains all four missing sessions, but their prices must
be reconciled to the adjusted series before insertion. See the
[source verification report](../research/stock-data-admissibility-next-actions-2026-09-06.md)
for exact dates, counts and exchange circulars.

The calendar cleanup is now implemented as a separate snapshot:

```bash
.venv/bin/python -m sensei.data.stock_repair
.venv/bin/python -m sensei.research.stock_evaluation \
  --config config/stock-research-calendar-clean.json
```

The repair validates every proposed holiday exclusion before writing, retains
all instruments, records each removed row and verifies output hashes on reuse.
It also audits the missing-session factors against verified raw NSE sessions.
Agreement between neighboring factors is diagnostic and never inserts a price.
The frozen runner verifies and records the snapshot manifest before evaluation.
The original price directory and original run configuration remain available.

The 6 September cleanup removed 1,917 placeholders. Its frozen rerun has no
extra holiday dates, but still lacks four real sessions and stops before
simulation. The owner subsequently declined AccelPix because of cost; the
[lower-cost source review](../research/stock-low-cost-data-options-2026-09-06.md)
replaces that acquisition path. See the
[repair results](../research/stock-calendar-repair-results-2026-09-06.md)
for the snapshot, factor audit and remaining evidence requirements.
