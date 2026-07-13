"""Turn one canonical entry trace into a conservatively sized Trade Intent."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_FLOOR

from sensei.portfolio_risk import AccountSnapshot, RiskLimits, TradeIntent
from sensei.strategy import DecisionAction, PlanDecisionTrace, StrategyPlan


class IntentBuildError(RuntimeError):
    """The available facts cannot safely produce a trade intent."""


@dataclass(frozen=True)
class ExecutableQuote:
    instrument_id: str
    snapshot_id: str
    worst_entry_price_paise: int
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.instrument_id.strip() or not self.snapshot_id.strip():
            raise ValueError("instrument_id and snapshot_id are required")
        if (
            isinstance(self.worst_entry_price_paise, bool)
            or not isinstance(self.worst_entry_price_paise, int)
            or self.worst_entry_price_paise <= 0
        ):
            raise ValueError("worst_entry_price_paise must be a positive integer")
        _aware("observed_at", self.observed_at)


@dataclass(frozen=True)
class IntentBuildResult:
    intent: TradeIntent
    market_snapshot_id: str
    account_snapshot_id: str
    portfolio_value_paise: int
    risk_budget_paise: int
    position_budget_paise: int
    binding_capacity: str


class TradeIntentFactory:
    """Own sizing arithmetic; callers cannot supply or enlarge quantity."""

    def __init__(
        self,
        limits: RiskLimits,
        *,
        maximum_quote_age: timedelta,
    ) -> None:
        if maximum_quote_age <= timedelta(0):
            raise ValueError("maximum_quote_age must be positive")
        self._limits = limits
        self._maximum_quote_age = maximum_quote_age

    def build(
        self,
        *,
        plan: StrategyPlan,
        trace: PlanDecisionTrace,
        quote: ExecutableQuote,
        account_snapshot: AccountSnapshot,
        now: datetime,
    ) -> IntentBuildResult:
        _aware("now", now)
        if trace.plan_id != plan.plan_id:
            raise IntentBuildError("decision trace does not belong to the exact plan")
        if quote.instrument_id != trace.instrument_id:
            raise IntentBuildError("quote instrument does not match the decision trace")
        if trace.action is not DecisionAction.ENTER_LONG:
            raise IntentBuildError("an entry decision trace is required")
        if trace.sizing_intent is None or trace.exit_intent is None:
            raise IntentBuildError("entry trace is missing sizing or exit intent")
        evaluation_date = datetime.fromisoformat(trace.evaluation_session).date()
        if quote.observed_at.date() <= evaluation_date:
            raise IntentBuildError("entry quote must be after the decision session")
        quote_age = now - quote.observed_at
        if quote_age < timedelta(0):
            raise IntentBuildError("quote timestamp is in the future")
        if quote_age > self._maximum_quote_age:
            raise IntentBuildError("executable quote is stale")
        if not account_snapshot.reconciled:
            raise IntentBuildError("account snapshot is not reconciled")
        account_age = now - account_snapshot.captured_at
        if account_age < -self._limits.snapshot_max_age:
            raise IntentBuildError("account snapshot is implausibly in the future")
        if account_age > self._limits.snapshot_max_age:
            raise IntentBuildError("account snapshot is stale")

        entry = quote.worst_entry_price_paise
        stop = _floor_money(
            Decimal(entry)
            * (
                Decimal("1")
                - Decimal(str(trace.exit_intent.stop_loss_pct)) / Decimal("100")
            )
        )
        target = _floor_money(
            Decimal(entry)
            * (
                Decimal("1")
                + Decimal(str(trace.exit_intent.take_profit_pct)) / Decimal("100")
            )
        )
        risk_per_unit = entry - stop
        if stop <= 0 or risk_per_unit <= 0 or target <= entry:
            raise IntentBuildError("plan exits do not produce valid executable levels")

        portfolio_value = account_snapshot.marked_equity_paise
        risk_budget = _floor_money(
            Decimal(portfolio_value)
            * Decimal(str(trace.sizing_intent.risk_budget_fraction))
        )
        position_budget = _floor_money(
            Decimal(portfolio_value)
            * Decimal(str(trace.sizing_intent.max_position_fraction))
        )
        total_headroom = max(
            0,
            self._limits.max_total_notional_paise
            - account_snapshot.held_notional_paise,
        )
        capacities = {
            "PLAN_RISK_BUDGET": risk_budget // risk_per_unit,
            "PLAN_POSITION_CAP": position_budget // entry,
            "AVAILABLE_CASH": account_snapshot.available_cash_paise // entry,
            "RISK_LIMIT": self._limits.max_risk_per_trade_paise // risk_per_unit,
            "POSITION_LIMIT": self._limits.max_position_notional_paise // entry,
            "TOTAL_NOTIONAL_LIMIT": total_headroom // entry,
        }
        quantity = min(capacities.values())
        if quantity <= 0:
            raise IntentBuildError("no positive quantity fits all sizing constraints")
        binding = next(name for name, capacity in capacities.items() if capacity == quantity)
        intent = TradeIntent(
            strategy_plan_id=plan.plan_id,
            decision_trace_id=trace.trace_id,
            market_snapshot_id=quote.snapshot_id,
            account_snapshot_id=account_snapshot.snapshot_id,
            instrument_id=trace.instrument_id,
            quantity=quantity,
            limit_price_paise=entry,
            stop_price_paise=stop,
            target_price_paise=target,
            # The executable quote is the durable decision boundary. Wall-clock
            # retry time must not create a second logical intent.
            created_at=quote.observed_at,
        )
        return IntentBuildResult(
            intent=intent,
            market_snapshot_id=quote.snapshot_id,
            account_snapshot_id=account_snapshot.snapshot_id,
            portfolio_value_paise=portfolio_value,
            risk_budget_paise=risk_budget,
            position_budget_paise=position_budget,
            binding_capacity=binding,
        )


def _floor_money(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def _aware(label: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
