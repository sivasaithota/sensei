# Market-state attribution of existing stock runs

Overnight pass 3, fixed before inspection: reuse the four completed lower-turnover
trade and equity ledgers. Do not simulate a market filter or change parameters.

1. Classify a benchmark session as above its 200-session simple average or at
   or below it, using the preceding benchmark close and the preceding 200
   benchmark closes. The current session and all future data are unavailable.
   Insufficient history is unknown. Require an ordered unique daily benchmark
   with finite positive levels. Retain the original source-verification chain.
2. Group completed-trade net P&L, costs, trade counts and stop/gap-stop counts
   by state at entry. This is a retrospective entry cohort: its exits may occur
   in another state. Preserve every trade and unknown observation.
3. Separately group actual daily mark-to-market P&L and mean end-of-day invested
   equity fraction by state known before each session. Retain all sessions and
   carry holdings across state changes. Reconcile summed daily P&L against the
   campaign result and reject calendar or equity inconsistencies. Exposure is
   descriptive end-of-day utilization, not a causal effect of admission filters.
4. Keep these two attribution views distinct. Neither is a backtest of taking
   only one cohort: filtering would change cash, positions, exits and ranking.
   Report all four runs. No parameter search, omitted dates, invented holdout,
   shareholder-return certification or order authority.
5. Bind diagnostic code and verified source identities to immutable derivative
   artifacts. Add regressions for prior-only classification, the exact warmup
   boundary, unknown state, holdings crossing states and P&L reconciliation.
   Run checks/reviews, update the overnight note with findings and a bounded
   next action, then commit/push completed work.
