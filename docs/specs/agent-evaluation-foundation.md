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
Invocations without a Trade Episode remain unlabeled until a horizon-closed
`CounterfactualOutcomeAttributed` fact names the exact invocation, replay
methodology and finite simulated P&L. Realized and counterfactual labels remain
distinguishable.

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

`variant_report()` groups the same metrics by exact prompt/model identity for
champion-challenger shadow comparison. It cannot select or promote a variant.

`AgentVariantShadowRunner` executes at least two variants against the same
role-scoped context under child evaluation cycles. It records measured wall
latency and adapter-supplied prompt/model/cost identity and exposes no execution
authority. `CounterfactualReplayProducer` scans mature veto/abstention
invocations and records labels only when a configured replay returns
horizon-closed market evidence.

## Current boundary

The live Desk automatically records invocation facts for all nine role outcomes.
Realized labels still require reconciled Trade Episodes; no-trade labels require
registered counterfactual evidence. Production adapters validate and materialize
their role-scoped context before acting. Desk calls use exact callable identities
for deterministic adapters, measured latency and zero provider cost; future
paid-model adapters must supply their exact prompt/model/cost receipt.
Champion-challenger execution remains shadow-only by construction.
