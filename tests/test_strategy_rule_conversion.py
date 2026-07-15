from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from sensei.backtest.rulespec import Condition, RuleSpec, compile_spec
from sensei.strategy import (
    ApplicabilityPolicy,
    AttributedValue,
    DecisionAction,
    FieldAttribution,
    FieldAuthority,
    PlanEvaluationRequest,
    RuleSpecPlanPolicy,
    SizingPolicy,
    StrategyPlanEngine,
    TimingPolicy,
    convert_rule_spec,
)


def research(reason: str = "Legacy rule encoded as a research hypothesis"):
    return FieldAttribution(
        authority=FieldAuthority.RESEARCH_ASSUMPTION,
        rationale=reason,
    )


def safety(reason: str):
    return FieldAttribution(
        authority=FieldAuthority.SAFETY_OVERRIDE,
        rationale=reason,
    )


def value(raw, attribution):
    return AttributedValue(value=raw, attribution=attribution)


def policy_for(spec: RuleSpec) -> RuleSpecPlanPolicy:
    return RuleSpecPlanPolicy(
        strategy_family=value(spec.name, research("Legacy strategy family mapping")),
        condition_attributions=tuple(
            research(f"Legacy condition {index + 1} requires fresh examination")
            for index in range(len(spec.conditions))
        ),
        stop_loss_attribution=safety("Legacy stop bounded by migration policy"),
        take_profit_attribution=research("Legacy target requires fresh examination"),
        max_hold_attribution=research("Legacy holding horizon requires fresh examination"),
        timing=TimingPolicy(
            decision_point=value("session_close", research("Daily close decision")),
            entry_point=value("next_session_open", research("No same-close fill")),
        ),
        sizing=SizingPolicy(
            risk_budget_fraction=value(0.005, safety("Migration risk budget")),
            max_position_fraction=value(0.10, safety("Migration concentration cap")),
        ),
        applicability=ApplicabilityPolicy(
            min_price=value(1.0, safety("Exclude invalid low-price observations")),
            max_price=value(1_000_000.0, research("Broad research price range")),
            min_average_volume=value(0.0, safety("Research fixture liquidity floor")),
            average_volume_lookback_sessions=value(
                1, research("Research fixture volume lookback")
            ),
        ),
    )


def market_history() -> pd.DataFrame:
    sessions = pd.bdate_range("2024-01-01", periods=340)
    x = np.arange(len(sessions), dtype=float)
    close = 100.0 + 0.08 * x + 8.0 * np.sin(x / 11.0) + 2.0 * np.sin(x / 3.0)
    open_ = close - 0.7 * np.sin(x / 2.0)
    high = np.maximum(open_, close) + 1.5 + 0.2 * np.cos(x)
    low = np.minimum(open_, close) - 1.8 - 0.2 * np.sin(x)
    volume = 1_000_000.0 + 450_000.0 * (1.0 + np.sin(x / 7.0))
    volume[::17] *= 4.0
    bars = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=sessions,
    )
    for position in range(20, len(bars), 19):
        close_at_position = float(bars["close"].iloc[position])
        bars.iloc[position, bars.columns.get_loc("open")] = close_at_position - 0.5
        bars.iloc[position, bars.columns.get_loc("high")] = close_at_position + 0.1
        bars.iloc[position, bars.columns.get_loc("low")] = close_at_position - 2.0
    for position in (100, 180, 260):
        earlier = float(bars["close"].iloc[position - 4])
        bars.iloc[position - 1, bars.columns.get_loc("close")] = earlier - 5.0
        bars.iloc[position - 1, bars.columns.get_loc("low")] = min(
            float(bars["low"].iloc[position - 1]), earlier - 6.0
        )
        bars.iloc[position, bars.columns.get_loc("open")] = earlier - 1.0
        bars.iloc[position, bars.columns.get_loc("close")] = earlier
        bars.iloc[position, bars.columns.get_loc("high")] = earlier + 0.2
        bars.iloc[position, bars.columns.get_loc("low")] = earlier - 5.0
    return bars


def adopted_rule_specs() -> tuple[RuleSpec, ...]:
    path = Path(__file__).resolve().parents[1] / "data" / "studied_rules.json"
    adopted_names = {
        "minervini_trend_template",
        "minervini_breakout_volume",
        "gujral_trend_alignment_dual_ma",
        "sadekar_hammer_confirmation",
        "schwager_trend_with_pullback_strength",
    }
    records = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        RuleSpec.model_validate(record)
        for record in records
        if record["name"] in adopted_names
    )


def test_converted_five_rules_match_legacy_signal_semantics():
    bars = market_history()
    engine = StrategyPlanEngine()
    specs = adopted_rule_specs()
    assert {spec.name for spec in specs} == {
        "minervini_trend_template",
        "minervini_breakout_volume",
        "gujral_trend_alignment_dual_ma",
        "sadekar_hammer_confirmation",
        "schwager_trend_with_pullback_strength",
    }

    for spec in specs:
        plan = convert_rule_spec(spec, policy=policy_for(spec))
        legacy_signals = compile_spec(spec)(bars)
        for session in bars.index[-40:]:
            trace = engine.evaluate(
                PlanEvaluationRequest(
                    plan=plan,
                    instrument_id="NSE:FIXTURE",
                    bars=bars,
                    evaluation_session=session.date(),
                )
            )
            assert (trace.action is DecisionAction.ENTER_LONG) is bool(
                legacy_signals.loc[session]
            ), f"{spec.name} diverged on {session.date()}"


def test_each_migrated_operand_matches_the_rulespec_compiler():
    bars = market_history()
    cases = (
        Condition(left="close", op=">", right="sma_20"),
        Condition(left="volume", op=">", right="vol_sma_20", factor=1.4),
        Condition(left="close", op=">", right="highest_20"),
        Condition(left="close", op=">", right="lowest_252", factor=1.3),
        Condition(left="ret_20", op=">", right=0.0),
        Condition(left="rsi_14", op=">", right=50.0),
        Condition(left="strong_close", op=">", right=0.5),
        Condition(left="close", op=">=", right="high_52w", factor=0.75),
        Condition(left="hammer", op=">", right=0.5),
    )
    engine = StrategyPlanEngine()

    for index, condition in enumerate(cases):
        spec = RuleSpec(
            name=f"operand_fixture_{index}",
            source="Deterministic fixture",
            principle="One independently observable operand.",
            conditions=(condition,),
            stop_pct=5.0,
            target_pct=10.0,
            max_hold_days=10,
        )
        plan = convert_rule_spec(spec, policy=policy_for(spec))
        expected = compile_spec(spec)(bars)
        actual = []
        for session in bars.index:
            trace = engine.evaluate(
                PlanEvaluationRequest(
                    plan=plan,
                    instrument_id="NSE:FIXTURE",
                    bars=bars,
                    evaluation_session=session.date(),
                )
            )
            actual.append(trace.action is DecisionAction.ENTER_LONG)

        actual_series = pd.Series(actual, index=bars.index)
        assert actual_series.equals(expected.astype(bool)), condition
        assert expected.any(), f"fixture never exercises true for {condition}"
        assert (~expected.astype(bool)).any(), f"fixture never exercises false for {condition}"


def test_scaled_volume_average_is_visible_in_the_decision_trace():
    spec = RuleSpec(
        name="volume_factor_fixture",
        source="Free text is not provenance authority",
        principle="Require volume above 1.4 times its three-session average.",
        conditions=(
            Condition(left="volume", op=">", right="vol_sma_3", factor=1.4),
        ),
        stop_pct=5.0,
        target_pct=10.0,
        max_hold_days=10,
    )
    bars = market_history().iloc[:10].copy()
    plan = convert_rule_spec(spec, policy=policy_for(spec))

    trace = StrategyPlanEngine().evaluate(
        PlanEvaluationRequest(
            plan=plan,
            instrument_id="NSE:FIXTURE",
            bars=bars,
            evaluation_session=bars.index[-1].date(),
        )
    )

    outcome = trace.condition_outcomes[0]
    assert outcome.right_value == bars["volume"].iloc[-3:].mean() * 1.4
    assert plan.identity_payload()["engine_contract"] == "daily-long-only-v2"


def test_converter_never_turns_free_text_source_into_a_provenance_claim():
    spec = RuleSpec(
        name="research_only_fixture",
        source="A book title and URL are not content-addressed claims",
        principle="A free-text principle is research material only.",
        conditions=(Condition(left="close", op=">", right="sma_3"),),
        stop_pct=5.0,
        target_pct=10.0,
        max_hold_days=10,
    )

    plan = convert_rule_spec(spec, policy=policy_for(spec))

    assert plan.source_claim_ids == ()
    assert spec.source not in json.dumps(plan.model_dump(mode="json"))
