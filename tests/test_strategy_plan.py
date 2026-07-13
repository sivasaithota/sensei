from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from pydantic import ValidationError

from sensei.strategy import (
    ApplicabilityPolicy,
    AttributedValue,
    ComparisonOperator,
    DecisionAction,
    EntryCondition,
    EntryPolicy,
    ExitPolicy,
    FieldAttribution,
    FieldAuthority,
    ObservableField,
    PlanEvaluationRequest,
    SizingPolicy,
    StrategyPlan,
    StrategyPlanEngine,
    TemporalReference,
    TimingPolicy,
)

CLAIM_HAMMER = "claim:" + "a" * 64


def source(*claim_ids: str) -> FieldAttribution:
    return FieldAttribution(
        authority=FieldAuthority.SOURCE_CLAIM,
        claim_ids=claim_ids,
    )


def assumption(reason: str = "Research protocol choice") -> FieldAttribution:
    return FieldAttribution(
        authority=FieldAuthority.RESEARCH_ASSUMPTION,
        rationale=reason,
    )


def safety(reason: str) -> FieldAttribution:
    return FieldAttribution(
        authority=FieldAuthority.SAFETY_OVERRIDE,
        rationale=reason,
    )


def value(raw, attribution: FieldAttribution | None = None):
    return AttributedValue(value=raw, attribution=attribution or assumption())


def hammer_follow_through_plan(
    *, source_claim_id: str = CLAIM_HAMMER, **updates
) -> StrategyPlan:
    fields = dict(
        name="hammer follow-through",
        strategy_family=value("candlestick_reversal", source(source_claim_id)),
        entry=EntryPolicy(
            conditions=(
                EntryCondition(
                    condition_id="prior-session-hammer",
                    left=TemporalReference(
                        field=ObservableField.HAMMER,
                        sessions_ago=1,
                    ),
                    operator=ComparisonOperator.GT,
                    right=0.5,
                    attribution=source(source_claim_id),
                ),
                EntryCondition(
                    condition_id="follow-through-above-hammer-high",
                    left=TemporalReference(
                        field=ObservableField.CLOSE,
                        sessions_ago=0,
                    ),
                    operator=ComparisonOperator.GT,
                    right=TemporalReference(
                        field=ObservableField.HIGH,
                        sessions_ago=1,
                    ),
                    attribution=source(source_claim_id),
                ),
            )
        ),
        exits=ExitPolicy(
            stop_loss_pct=value(5.0, safety("Bound downside per trade")),
            take_profit_pct=value(10.0, assumption("Initial reward target")),
            max_hold_sessions=value(20, assumption("Daily swing horizon")),
        ),
        timing=TimingPolicy(
            decision_point=value("session_close", source(source_claim_id)),
            entry_point=value("next_session_open", assumption("Avoid same-close fill")),
        ),
        sizing=SizingPolicy(
            risk_budget_fraction=value(0.005, safety("Half-percent risk budget")),
            max_position_fraction=value(0.10, safety("Single-name concentration cap")),
        ),
        applicability=ApplicabilityPolicy(
            min_price=value(10.0, safety("Exclude penny stocks")),
            max_price=value(10_000.0, assumption()),
            min_average_volume=value(100_000.0, safety("Minimum liquidity")),
            average_volume_lookback_sessions=value(3, assumption()),
        ),
    )
    fields.update(updates)
    return StrategyPlan(**fields)


def hammer_bars() -> pd.DataFrame:
    index = pd.bdate_range("2025-01-01", periods=7)
    return pd.DataFrame(
        {
            "open": [110.0, 108.0, 106.0, 104.0, 100.0, 101.0, 106.0],
            "high": [111.0, 109.0, 107.0, 105.0, 103.0, 105.0, 107.0],
            "low": [109.0, 107.0, 105.0, 103.0, 99.0, 94.0, 100.0],
            "close": [110.0, 108.0, 106.0, 104.0, 100.0, 103.0, 106.0],
            "volume": [1_000_000.0] * 7,
        },
        index=index,
    )


def test_source_claim_attribution_requires_claim_ids():
    with pytest.raises(ValidationError, match="claim ID"):
        FieldAttribution(authority=FieldAuthority.SOURCE_CLAIM)


def test_plan_identity_covers_semantics_but_not_display_name():
    plan = hammer_follow_through_plan()
    renamed = plan.model_copy(update={"name": "same plan, friendlier label"})
    revised_exit = plan.model_copy(
        update={
            "exits": plan.exits.model_copy(
                update={"max_hold_sessions": value(21, assumption())}
            )
        }
    )
    revised_temporal_reference = plan.model_copy(
        update={
            "entry": EntryPolicy(
                conditions=(
                    plan.entry.conditions[0].model_copy(
                        update={
                            "left": TemporalReference(
                                field=ObservableField.HAMMER,
                                sessions_ago=0,
                            )
                        }
                    ),
                    plan.entry.conditions[1],
                )
            )
        }
    )

    assert plan.plan_id.startswith("sha256:")
    assert plan.source_claim_ids == (CLAIM_HAMMER,)
    assert renamed.plan_id == plan.plan_id
    assert revised_exit.plan_id != plan.plan_id
    assert revised_temporal_reference.plan_id != plan.plan_id


def test_plan_is_immutable():
    plan = hammer_follow_through_plan()

    with pytest.raises(ValidationError, match="frozen"):
        plan.name = "mutated"  # type: ignore[misc]


def test_hammer_requires_prior_session_pattern_and_current_follow_through():
    bars = hammer_bars()
    plan = hammer_follow_through_plan()
    engine = StrategyPlanEngine()

    trace = engine.evaluate(
        PlanEvaluationRequest(
            plan=plan,
            instrument_id="NSE:TEST",
            bars=bars,
            evaluation_session=bars.index[-1].date(),
        )
    )

    assert trace.action is DecisionAction.ENTER_LONG
    assert [outcome.passed for outcome in trace.condition_outcomes] == [True, True]
    assert trace.condition_outcomes[0].left_value == 1.0
    assert trace.condition_outcomes[1].left_value == 106.0
    assert trace.condition_outcomes[1].right_value == 105.0
    assert trace.sizing_intent is not None
    assert trace.sizing_intent.risk_budget_fraction == 0.005
    assert not hasattr(trace.sizing_intent, "quantity")


def test_hammer_on_current_session_is_not_follow_through():
    bars = hammer_bars().iloc[:-1]

    trace = StrategyPlanEngine().evaluate(
        PlanEvaluationRequest(
            plan=hammer_follow_through_plan(),
            instrument_id="NSE:TEST",
            bars=bars,
            evaluation_session=bars.index[-1].date(),
        )
    )

    assert trace.action is DecisionAction.NO_ACTION
    assert trace.condition_outcomes[0].passed is False


def test_future_bars_cannot_change_a_prior_session_decision():
    original = hammer_bars()
    future = pd.DataFrame(
        {
            "open": [1.0, 1_000.0],
            # Deliberately malformed future observations prove validation is
            # bounded by evaluation_session too, not only signal calculation.
            "high": [-2.0, 20.0],
            "low": [0.5, 500.0],
            "close": [1.5, 1_500.0],
            "volume": [-1.0, 99_000_000.0],
        },
        index=pd.bdate_range(original.index[-1] + pd.offsets.BDay(), periods=2),
    )
    engine = StrategyPlanEngine()
    request = dict(
        plan=hammer_follow_through_plan(),
        instrument_id="NSE:TEST",
        evaluation_session=original.index[-1].date(),
    )

    prefix_trace = engine.evaluate(PlanEvaluationRequest(bars=original, **request))
    full_trace = engine.evaluate(
        PlanEvaluationRequest(bars=pd.concat([original, future]), **request)
    )

    assert full_trace == prefix_trace


def test_engine_is_mode_agnostic_and_trace_is_deterministic():
    bars = hammer_bars()
    request = PlanEvaluationRequest(
        plan=hammer_follow_through_plan(),
        instrument_id="NSE:TEST",
        bars=bars,
        evaluation_session=date(2025, 1, 9),
    )
    engine = StrategyPlanEngine()

    first = engine.evaluate(request)
    repeated = engine.evaluate(request)
    assert first == repeated
    assert first.trace_id == repeated.trace_id
    assert first.trace_id.startswith("trace:")
    assert "mode" not in PlanEvaluationRequest.__dataclass_fields__
    assert "mode" not in type(engine.evaluate(request)).model_fields


def test_applicability_fails_closed_before_emitting_a_sizing_intent():
    bars = hammer_bars()
    bars.loc[bars.index[-3] :, "volume"] = 1.0

    trace = StrategyPlanEngine().evaluate(
        PlanEvaluationRequest(
            plan=hammer_follow_through_plan(),
            instrument_id="NSE:ILLIQUID",
            bars=bars,
            evaluation_session=bars.index[-1].date(),
        )
    )

    assert trace.action is DecisionAction.NO_ACTION
    assert trace.sizing_intent is None
    assert "applicability_failed" in trace.reason_codes
