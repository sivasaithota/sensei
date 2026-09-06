# Frozen SMA200 new-entry gate experiment

Overnight pass 4: run exactly two gated variants of the existing original
momentum baseline and its 60-session counterpart. Preserve both controls.
The previous market-state attribution is descriptive reused history, not a
forecast of the gate's return.

1. Add an explicit optional research setting `market_entry_gate`, accepting
   only `benchmark_above_sma200` or null/omission. Reuse the reviewed preceding
   close / preceding 200-close benchmark state calculation. Allow entry only
   in the above state. Unknown or missing states block entry. Reject invalid
   settings and benchmark data instead of silently falling back.
2. Combine the market mask with the existing demerger mask using logical AND.
   Neither can override the other. Preserve their separate audit counts and
   report the market gate's timing and entry-only scope. Keep every stock,
   price and evaluation session. Missing or misaligned existing masks fail.
3. Eligibility is checked for the prospective entry session; signals still use
   the preceding stock bar. Existing positions retain all original exit rules,
   including during below/unknown states. Do not introduce forced liquidation.
4. Bind the gate setting and both gate/state implementation modules to frozen
   run identity; benchmark hash and portfolio mask identities remain bound.
   The original two controls must reproduce their saved trades and equity.
5. Freeze both new configs and all four config hashes/timestamp before running.
   Original: 5% stop / 12% target / 30 sessions; counterpart: 5% / 12% / 60.
   All other universe, dates, costs, risk, demerger policy and benchmark settings
   match the respective controls. No moving-average grid or further tuning.
6. Report all four results: return/excess return, drawdown, trade count, costs,
   turnover, utilization and existing economic/data decisions. Do not infer a
   new holdout or live readiness from any improvement. Holding-event blockers
   must remain effective. These are two additional reused-development tests.
7. Verify unknown-state denial, prior-only timing, mask conjunction, existing
   position retention, config/run-identity changes and invalid-policy rejection
   with meaningful tests. Run checks and both reviews, save exact artifacts and
   an overnight checkpoint, commit/push. Use no new Kite requests or orders.
