# Stock backtest remediation

User request: fix all findings in the 6 September stock-bot review. Preserve
the existing governed architecture. Target ₹300,000 NSE cash-equity swing;
intraday/crypto are excluded. This document tracks implementation acceptance,
not authorization to activate live orders.

## Acceptance

1. Daily research paths use consistent opening/intraday ordering, entry-day
   protection, cash timing and initial-capital drawdown. Frozen experiments
   retain their historical identities and explicit limitations.
2. Historical production replay uses prior-session observations for decisions,
   current-session opening prices for entry execution, and never the current
   day's future high/low/close/volume for morning fills. Missing execution data
   rejects a candidate rather than using its old close.
3. Forward paper quotes preserve provider observation timestamps. Missing,
   stale, future or malformed timestamps cannot be relabelled as current.
4. Research and paper share ranking/correlation calculations with policy
   identity. Research inputs that use historical evidence must have an explicit
   availability date. Reports identify residual allocation/execution differences;
   a canonical type check alone must not claim portfolio parity.
5. Research membership/coverage decisions do not silently select securities by
   their survival through the evaluation window. Missing held-position data is
   an explicit blocker. Data provenance/admissibility status is separate from
   economic performance and cannot be manufactured by code.
6. A new versioned shared-portfolio evaluation reports benchmark-relative
   returns, exposure, drawdown, costs and dependence-aware uncertainty. Median
   trade return is descriptive, not a universal gate. Old screen rejections are
   not rewritten. No strategy gains trading authority from a research result.
7. Research-exposed periods and repeated confirmation access are recorded
   across experiment identifiers. Known inspected history cannot be called a
   fresh holdout just by changing configuration or provider.
8. Current architecture docs reflect the implemented paper runtime and the
   actual remaining live gap. Live integration is not activated without broker
   evidence and a specific canary/loss mandate. Absent external data or broker
   evidence must remain explicitly blocked, not passed by fixtures.

Validation uses synthetic regression/integration fixtures first, then labelled
local development evidence only. Review changed code against this spec and
the domain vocabulary before committing. Preserve unrelated runtime-state and
LinkedIn work in the working tree.

Implementation and independent-review status are recorded in
[the closeout](../research/stock-remediation-closeout-2026-09-06.md). The software
corrections are complete within the stated scope. Market-data certification,
strategy profitability and the governed live broker path remain explicit
external/integration work; they are not passed by synthetic tests.
