# Canonical Strategy Plan foundation

Status: implemented foundation contract. This specification does not authorize
broker execution or live capital.

## Purpose

A Strategy Plan is the sole conformant executable strategy description. It is
immutable and content-addressed, and the identifier covers every configurable
semantic that can change a decision: family, entry conditions and temporal
offsets, exit policy, daily timing, sizing intent, applicability, and the
authority attached to those values. The display name is deliberately not an
identity input.

Every configurable value or indivisible condition is classified as one of:

- `SOURCE_CLAIM` — requires one or more immutable claim IDs.
- `RESEARCH_ASSUMPTION` — requires a rationale.
- `SAFETY_OVERRIDE` — requires a rationale and may constrain a source rule.

Free-text provenance is not enough. A legacy `RuleSpec` therefore remains
nonconformant even when it has positive historical statistics.

For governed paper admission, every `SOURCE_CLAIM` identity used anywhere in the
plan must also resolve and verify in the immutable Provenance Corpus. Syntax
validation alone is insufficient. Corpus claims remain `RESEARCH_ONLY`; they
explain plan semantics but cannot promote a plan or approve a trade.

## Foundation execution contract

The first contract is intentionally narrow: long-only, one completed daily bar
per session, decision at session close, and intended entry at the next session
open. Entry conditions are ANDed. Every market reference contains an explicit
`sessions_ago` value, including zero for the evaluation session.

The hammer follow-through rule is represented as two separate temporal facts:

1. `hammer[sessions_ago=1] > 0.5`
2. `close[sessions_ago=0] > high[sessions_ago=1]`

This prevents a hammer on the current session from being mistaken for confirmed
follow-through. Evaluation first slices observations through the requested
session, so future observations — even invalid ones — cannot alter a historical
decision.

`StrategyPlanEngine.evaluate(PlanEvaluationRequest)` has no research, shadow,
paper, sandbox, or live branch. All adapters must consume the same immutable
`PlanDecisionTrace`. A successful entry trace contains exit and risk-budget
intent, but never order quantity; portfolio risk owns capital reservation and
the trading kernel owns order construction.

## Failing closed

The engine rejects malformed or incomplete daily OHLCV inputs. Insufficient
lookback or failed applicability produces `NO_ACTION` and no sizing/exit intent.
The current contract is not an exit-state machine, portfolio allocator, broker
adapter, intraday engine, or lifecycle authorization system; those are separate
modules that consume the plan and trace identities.
