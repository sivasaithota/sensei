# Configurable stock development run

User request, 6 September 2026: make account drawdown configurable and start
the next data-validation and frozen-portfolio actions. Existing drawdown choice
is 100% of the ₹300,000 research account; it is a setting, not a fixed default
or a live activation mandate.

Acceptance:

1. Provide a reusable JSON run configuration with explicit strategy parameters,
   capital/position/risk/cost settings, evaluation thresholds, dates, 252-session
   warmup, benchmark and output paths. CLI drawdown override affects only that
   run. Reject ambiguous or silently ignored configuration flags.
2. Capture the official Nifty 500 gross total-return series with bounded date
   requests, raw responses and hashes. Reject wrong-index, duplicate, invalid
   or out-of-request data; preserve missing dates. Retain source attribution.
3. Scope data by declared dates and warmup while retaining every supplied
   instrument. Do not select stocks by future completeness or forward-fill
   missing stock/benchmark sessions. Calendar mismatch blocks simulation.
4. Persist input/config/code identities before evaluating. Changed settings
   produce a distinct run directory; completed artifacts must pass hash checks
   before reuse. These development runs never authorize trades.
5. Investigate historical membership, adjustments and calendar provenance using
   primary evidence. Publish the actual first-run outcome and exact remaining
   blockers. Do not manufacture performance or data certification when blocked.

The initial baseline is momentum_breakout_55, 5% stop, 12% target and 30-session
time exit. End date 2026-09-03 was selected from observed local coverage before
running the strategy. All prior history remains reused development data.
