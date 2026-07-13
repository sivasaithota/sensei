"""The single deterministic execution semantics for canonical Strategy Plans."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import pandas as pd

from .models import (
    ApplicabilityOutcome,
    ComparisonOperator,
    ConditionOutcome,
    DecisionAction,
    EntryCondition,
    ObservableField,
    PlanDecisionTrace,
    PlanExitIntent,
    PlanSizingIntent,
    StrategyPlan,
    TemporalReference,
)


class PlanInputError(ValueError):
    """Raised when daily observations cannot be evaluated safely."""


@dataclass(frozen=True)
class PlanEvaluationRequest:
    """Inputs to the mode-independent plan engine.

    There is intentionally no research/paper/live mode.  Every caller supplies
    the same plan and observations and receives the same decision trace.
    """

    plan: StrategyPlan
    instrument_id: str
    bars: pd.DataFrame
    evaluation_session: date

    def __post_init__(self) -> None:
        if not self.instrument_id.strip():
            raise ValueError("instrument_id must not be blank")


class StrategyPlanEngine:
    """Evaluate long-only daily Strategy Plans without looking past ``as_of``."""

    _REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")

    def evaluate(self, request: PlanEvaluationRequest) -> PlanDecisionTrace:
        bars = self._observations_through(
            request.bars,
            request.evaluation_session,
        )
        current_position = len(bars) - 1

        applicability = self._evaluate_applicability(request.plan, bars)
        outcomes = tuple(
            self._evaluate_condition(condition, bars, current_position)
            for condition in request.plan.entry.conditions
        )

        reasons: list[str] = []
        if not all(outcome.passed for outcome in applicability):
            reasons.append("applicability_failed")
        if any(
            outcome.left_value is None or outcome.right_value is None
            for outcome in outcomes
        ):
            reasons.append("insufficient_history")
        if not all(outcome.passed for outcome in outcomes):
            reasons.append("entry_conditions_failed")

        eligible = not reasons
        action = DecisionAction.ENTER_LONG if eligible else DecisionAction.NO_ACTION
        sizing_intent = None
        exit_intent = None
        if eligible:
            sizing_intent = PlanSizingIntent(
                risk_budget_fraction=request.plan.sizing.risk_budget_fraction.value,
                max_position_fraction=request.plan.sizing.max_position_fraction.value,
            )
            exit_intent = PlanExitIntent(
                stop_loss_pct=request.plan.exits.stop_loss_pct.value,
                take_profit_pct=request.plan.exits.take_profit_pct.value,
                max_hold_sessions=request.plan.exits.max_hold_sessions.value,
            )
            reasons.append("entry_conditions_satisfied")

        return PlanDecisionTrace(
            plan_id=request.plan.plan_id,
            instrument_id=request.instrument_id.strip(),
            evaluation_session=request.evaluation_session.isoformat(),
            action=action,
            applicability_outcomes=applicability,
            condition_outcomes=outcomes,
            reason_codes=tuple(reasons),
            sizing_intent=sizing_intent,
            exit_intent=exit_intent,
        )

    def _observations_through(
        self,
        source: pd.DataFrame,
        evaluation_session: date,
    ) -> pd.DataFrame:
        if not isinstance(source, pd.DataFrame):
            raise PlanInputError("bars must be a pandas DataFrame")
        if not isinstance(source.index, pd.DatetimeIndex):
            raise PlanInputError("daily bars require a DatetimeIndex")

        # Slice first.  Data arriving after the requested session is not an
        # input and therefore cannot invalidate or alter the historical trace.
        mask = [timestamp.date() <= evaluation_session for timestamp in source.index]
        bars = source.loc[mask, list(self._REQUIRED_COLUMNS)].copy() if all(
            column in source.columns for column in self._REQUIRED_COLUMNS
        ) else source.loc[mask].copy()

        missing = [column for column in self._REQUIRED_COLUMNS if column not in bars]
        if missing:
            raise PlanInputError(f"daily bars are missing columns: {', '.join(missing)}")
        if bars.empty:
            raise PlanInputError("no observation exists at or before the evaluation session")
        if not bars.index.is_monotonic_increasing:
            raise PlanInputError("daily observations must be chronological")
        if bars.index.has_duplicates or len(set(bars.index.date)) != len(bars):
            raise PlanInputError("daily observations must contain one row per session")
        if bars.index[-1].date() != evaluation_session:
            raise PlanInputError("the evaluation session must have a completed daily bar")

        try:
            bars = bars.astype(float)
        except (TypeError, ValueError) as exc:
            raise PlanInputError("daily OHLCV values must be numeric") from exc

        values = bars.loc[:, self._REQUIRED_COLUMNS]
        if not values.map(math.isfinite).all(axis=None):
            raise PlanInputError("daily OHLCV values must be finite")
        if (bars.loc[:, ("open", "high", "low", "close")] <= 0).any(axis=None):
            raise PlanInputError("daily prices must be positive")
        if (bars["volume"] < 0).any():
            raise PlanInputError("daily volume must not be negative")
        if (
            (bars["high"] < bars[["open", "close", "low"]].max(axis=1)).any()
            or (bars["low"] > bars[["open", "close", "high"]].min(axis=1)).any()
        ):
            raise PlanInputError("daily bars violate OHLC bounds")
        return bars

    def _evaluate_applicability(
        self,
        plan: StrategyPlan,
        bars: pd.DataFrame,
    ) -> tuple[ApplicabilityOutcome, ...]:
        close = float(bars["close"].iloc[-1])
        lookback = plan.applicability.average_volume_lookback_sessions.value
        average_volume: float | None = None
        if len(bars) >= lookback:
            average_volume = float(bars["volume"].iloc[-lookback:].mean())

        return (
            ApplicabilityOutcome(
                check="price_range",
                observed_value=close,
                minimum=plan.applicability.min_price.value,
                maximum=plan.applicability.max_price.value,
                passed=(
                    plan.applicability.min_price.value
                    <= close
                    <= plan.applicability.max_price.value
                ),
            ),
            ApplicabilityOutcome(
                check="average_volume",
                observed_value=average_volume,
                minimum=plan.applicability.min_average_volume.value,
                lookback_sessions=lookback,
                passed=(
                    average_volume is not None
                    and average_volume
                    >= plan.applicability.min_average_volume.value
                ),
            ),
        )

    def _evaluate_condition(
        self,
        condition: EntryCondition,
        bars: pd.DataFrame,
        current_position: int,
    ) -> ConditionOutcome:
        left = self._resolve(condition.left, bars, current_position)
        if isinstance(condition.right, TemporalReference):
            right_reference = condition.right
            right = self._resolve(condition.right, bars, current_position)
        else:
            right_reference = None
            right = float(condition.right)

        passed = left is not None and right is not None and self._compare(
            left,
            condition.operator,
            right,
        )
        return ConditionOutcome(
            condition_id=condition.condition_id,
            left_reference=condition.left,
            operator=condition.operator,
            right_reference=right_reference,
            left_value=left,
            right_value=right,
            passed=passed,
        )

    def _resolve(
        self,
        reference: TemporalReference,
        bars: pd.DataFrame,
        current_position: int,
    ) -> float | None:
        position = current_position - reference.sessions_ago
        if position < 0:
            return None
        if reference.field is ObservableField.HAMMER:
            return self._hammer_at(bars, position)
        return float(bars[reference.field.value].iloc[position])

    @staticmethod
    def _hammer_at(bars: pd.DataFrame, position: int) -> float | None:
        # The reversal context itself is historical: the session before the
        # candle closed below the close four sessions before it.  No value to
        # the right of ``position`` participates in this detector.
        if position < 4:
            return None
        row = bars.iloc[position]
        body = abs(float(row["close"]) - float(row["open"]))
        candle_range = float(row["high"]) - float(row["low"])
        if candle_range <= 0:
            return 0.0
        lower_shadow = min(float(row["open"]), float(row["close"])) - float(row["low"])
        upper_shadow = float(row["high"]) - max(float(row["open"]), float(row["close"]))
        after_dip = float(bars["close"].iloc[position - 1]) < float(
            bars["close"].iloc[position - 4]
        )
        is_hammer = (
            body <= candle_range * 0.35
            and lower_shadow >= max(body * 2.0, candle_range * 0.40)
            and upper_shadow <= candle_range * 0.25
            and after_dip
        )
        return 1.0 if is_hammer else 0.0

    @staticmethod
    def _compare(left: float, operator: ComparisonOperator, right: float) -> bool:
        if operator is ComparisonOperator.GT:
            return left > right
        if operator is ComparisonOperator.GE:
            return left >= right
        if operator is ComparisonOperator.LT:
            return left < right
        if operator is ComparisonOperator.LE:
            return left <= right
        return left == right
