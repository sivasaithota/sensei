# Agent Evaluation Foundation

## Purpose

Measure whether each Desk role adds value without allowing the evaluator to
approve trades, change risk, promote strategies or call execution.

## Facts

`AgentInvocationRecorded` binds a cycle and role to:

- exact Memory Context Pack;
- prompt and model identity;
- proceed, abstain, veto or error outcome;
- optional confidence in the chosen action (`proceed` or `veto`);
- latency and cost.

The original decision fact never contains hindsight. A later
`AgentInvocationOutcomeLabeled` event references the invocation and supplies
the realized positive/negative label. Labels cannot predate their invocation
and require exactly one point-in-time `OutcomeAttributed` event with canonical
`realized_net_pnl`, reconciled P&L and the same Trade Episode identity.
Invocations without a Trade Episode remain unlabeled until a separately
governed counterfactual-replay evidence type is implemented.

## Projection

`AgentEvaluationService.report(as_of=...)` uses both occurrence and durable
recording time. It reports per role:

- invocation, abstention, veto and error counts;
- false vetoes and false approvals when labels exist;
- average latency and total cost;
- Brier score for confidence calibration. Veto confidence is converted to
  positive-outcome probability as `1 - confidence`; abstentions and errors are
  excluded from calibration.

The report is `EVALUATION_ONLY` and explicitly cannot authorize trading or
mutate strategy/risk.

## Current boundary

This PR provides the durable ledger and read-only evaluation projection. The
next Desk integration must automatically record invocation facts around each
role call, then label them only from reconciled Trade Episodes or registered
counterfactual replay. Champion–challenger execution remains shadow-only.
