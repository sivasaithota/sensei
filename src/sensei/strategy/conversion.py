"""Deterministic conversion of quarantined RuleSpecs into canonical plans.

The converter deliberately receives every authority-bearing value from its
caller.  A RuleSpec's free-text ``source`` and ``principle`` are never treated
as provenance claims and never enter the resulting plan implicitly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sensei.backtest.rulespec import RuleSpec

from .models import (
    ApplicabilityPolicy,
    AttributedValue,
    ComparisonOperator,
    EntryCondition,
    EntryPolicy,
    ExitPolicy,
    FieldAttribution,
    IndicatorKind,
    IndicatorReference,
    MarketReference,
    ObservableField,
    ScaledOperand,
    SizingPolicy,
    StrategyPlan,
    TemporalReference,
    TimingPolicy,
)

_WINDOWED_INDICATOR = re.compile(
    r"^(?P<kind>sma|vol_sma|highest|lowest|ret|rsi)_(?P<window>[1-9][0-9]*)$"
)
_RAW_FIELDS = {
    "open": ObservableField.OPEN,
    "high": ObservableField.HIGH,
    "low": ObservableField.LOW,
    "close": ObservableField.CLOSE,
    "volume": ObservableField.VOLUME,
}
_INDICATOR_KINDS = {
    "sma": IndicatorKind.SMA,
    "vol_sma": IndicatorKind.VOLUME_SMA,
    "highest": IndicatorKind.ROLLING_HIGH,
    "lowest": IndicatorKind.ROLLING_LOW,
    "ret": IndicatorKind.RETURN_PCT,
    "rsi": IndicatorKind.RSI,
}


@dataclass(frozen=True)
class RuleSpecPlanPolicy:
    """Explicit attributed values needed to make a RuleSpec canonical."""

    strategy_family: AttributedValue[str]
    condition_attributions: tuple[FieldAttribution, ...]
    stop_loss_attribution: FieldAttribution
    take_profit_attribution: FieldAttribution
    max_hold_attribution: FieldAttribution
    timing: TimingPolicy
    sizing: SizingPolicy
    applicability: ApplicabilityPolicy

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "condition_attributions",
            tuple(self.condition_attributions),
        )
        if not self.condition_attributions:
            raise ValueError("at least one condition attribution is required")
        if any(
            not isinstance(attribution, FieldAttribution)
            for attribution in self.condition_attributions
        ):
            raise TypeError("condition attributions must be FieldAttribution values")


def convert_rule_spec(
    spec: RuleSpec,
    *,
    policy: RuleSpecPlanPolicy,
) -> StrategyPlan:
    """Convert one validated RuleSpec without inventing authority or claims."""

    if not isinstance(spec, RuleSpec):
        raise TypeError("spec must be a RuleSpec")
    if not isinstance(policy, RuleSpecPlanPolicy):
        raise TypeError("policy must be a RuleSpecPlanPolicy")
    if len(policy.condition_attributions) != len(spec.conditions):
        raise ValueError(
            "condition attribution count must match the RuleSpec condition count"
        )

    conditions = tuple(
        EntryCondition(
            condition_id=f"legacy-condition-{index + 1:02d}",
            left=_reference(condition.left),
            operator=ComparisonOperator(condition.op),
            right=_scaled_right(condition.right, condition.factor),
            attribution=policy.condition_attributions[index],
        )
        for index, condition in enumerate(spec.conditions)
    )
    return StrategyPlan(
        name=spec.name,
        strategy_family=policy.strategy_family,
        entry=EntryPolicy(conditions=conditions),
        exits=ExitPolicy(
            stop_loss_pct=AttributedValue(
                value=spec.stop_pct,
                attribution=policy.stop_loss_attribution,
            ),
            take_profit_pct=AttributedValue(
                value=spec.target_pct,
                attribution=policy.take_profit_attribution,
            ),
            max_hold_sessions=AttributedValue(
                value=spec.max_hold_days,
                attribution=policy.max_hold_attribution,
            ),
        ),
        timing=policy.timing,
        sizing=policy.sizing,
        applicability=policy.applicability,
    )


def _scaled_right(
    operand: str | float,
    factor: float,
) -> MarketReference | ScaledOperand | float:
    resolved: MarketReference | float = (
        _reference(operand) if isinstance(operand, str) else float(operand)
    )
    if factor == 1.0:
        return resolved
    return ScaledOperand(operand=resolved, factor=factor)


def _reference(name: str) -> MarketReference:
    raw = _RAW_FIELDS.get(name)
    if raw is not None:
        return TemporalReference(field=raw, sessions_ago=0)
    if name == "strong_close":
        return IndicatorReference(indicator=IndicatorKind.STRONG_CLOSE)
    if name == "hammer":
        return IndicatorReference(indicator=IndicatorKind.RULESPEC_HAMMER)
    if name == "high_52w":
        return IndicatorReference(
            indicator=IndicatorKind.ROLLING_HIGH,
            window_sessions=250,
            sessions_ago=1,
        )

    matched = _WINDOWED_INDICATOR.fullmatch(name)
    if matched is None:
        raise ValueError(f"RuleSpec indicator {name!r} is not canonical-plan capable")
    kind_name = matched.group("kind")
    sessions_ago = 1 if kind_name in {"highest", "lowest"} else 0
    return IndicatorReference(
        indicator=_INDICATOR_KINDS[kind_name],
        window_sessions=int(matched.group("window")),
        sessions_ago=sessions_ago,
    )
