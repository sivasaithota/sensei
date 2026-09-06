# Stock portfolio evaluation

Scope: NSE cash-equity swing, ₹300,000 shared capital. The user confirmed a
100% maximum acceptable account drawdown on 6 September 2026, accepting the
possibility of complete capital loss. This is the research evaluation budget;
per-trade stops, daily/weekly operational limits and live authorization are
separate controls.

Run the new development report with a frozen strategy and declared benchmark:

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

The benchmark file is an explicit input, not supplied by this change. It must
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
