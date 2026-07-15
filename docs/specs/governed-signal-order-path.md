# Governed signal-to-order path

New paper entries must originate from canonical plans already authorized at
`PAPER`. The scheduler-facing planner evaluates those exact plans through
`StrategyPlanEngine`, over retained daily bars, and records a content-addressed
decision-market snapshot. It deterministically selects at most one candidate
per bounded scheduler session and binds the exact executable quote, account
snapshot, operational health, strategy evidence and committee inputs into a
`DeskCycleRequest`.

`GovernedPaperEntrySession` routes that request through the existing nine-role
`DeskRuntime`: Orchestrator, Historian, Reporter, Crowd Reader, Analyst, the
authenticated L1–L4 Committee, Trader, Coach and Secretary. The Trader admits
only through `GovernedPaperCoordinator`, then dispatches through
`TradingKernel` using a one-use Supervisor authorization. Positive fills are
protected before the cycle returns, and the Trade Episode and every role result
remain in the operational journal.

The entry session maps expected no-trade outcomes—no signal, events block,
Analyst decline, or Committee veto—to successful scheduler completion. Runtime
or authorization failures halt the task. Notifications are intentionally out
of scope.

The legacy paper book remains an exit/position-maintenance bridge for positions
that predate governed gateway history. It is not an authority source for this
canonical entry planner.
