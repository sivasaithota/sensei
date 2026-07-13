from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from sensei.orchestration.intents import (
    ExecutableQuote,
    IntentBuildError,
    TradeIntentFactory,
)
from sensei.portfolio_risk import AccountSnapshot, RiskLimits
from sensei.strategy import PlanEvaluationRequest, StrategyPlanEngine
from tests.test_strategy_plan import hammer_bars, hammer_follow_through_plan


def inputs():
    plan = hammer_follow_through_plan()
    bars = hammer_bars()
    trace = StrategyPlanEngine().evaluate(
        PlanEvaluationRequest(
            plan=plan,
            instrument_id="NSE:TEST",
            bars=bars,
            evaluation_session=bars.index[-1].date(),
        )
    )
    quote_time = datetime(2025, 1, 10, 9, 15, tzinfo=timezone.utc)
    quote = ExecutableQuote(
        instrument_id="NSE:TEST",
        snapshot_id="snapshot:quote-1",
        worst_entry_price_paise=10_000,
        observed_at=quote_time,
    )
    account = AccountSnapshot(
        available_cash_paise=10_000_000,
        marked_equity_paise=10_000_000,
        high_water_mark_paise=10_000_000,
        day_pnl_paise=0,
        week_pnl_paise=0,
        positions=(),
        included_reservation_ids=(),
        reconciled=True,
        captured_at=quote_time,
    )
    limits = RiskLimits(
        max_total_notional_paise=10_000_000,
        max_position_notional_paise=2_000_000,
        max_risk_per_trade_paise=100_000,
        max_total_risk_paise=500_000,
        max_open_positions=5,
        snapshot_max_age=timedelta(minutes=2),
        max_daily_loss_paise=500_000,
        max_weekly_loss_paise=1_000_000,
        max_drawdown_bps=2_000,
    )
    return plan, trace, quote, account, limits


def test_intent_factory_sizes_from_plan_and_reconciled_portfolio_without_caller_quantity():
    plan, trace, quote, account, limits = inputs()
    result = TradeIntentFactory(limits, maximum_quote_age=timedelta(minutes=1)).build(
        plan=plan,
        trace=trace,
        quote=quote,
        account_snapshot=account,
        now=quote.observed_at + timedelta(seconds=10),
    )

    assert result.intent.strategy_plan_id == plan.plan_id
    assert result.intent.decision_trace_id == trace.trace_id
    assert result.intent.market_snapshot_id == quote.snapshot_id
    assert result.intent.account_snapshot_id == account.snapshot_id
    assert result.intent.quantity == 100
    assert result.intent.limit_price_paise == 10_000
    assert result.intent.stop_price_paise == 9_500
    assert result.intent.target_price_paise == 11_000
    assert result.binding_capacity in {"PLAN_RISK_BUDGET", "PLAN_POSITION_CAP"}
    assert result.intent.risk_paise <= result.risk_budget_paise


def test_intent_factory_sizes_plan_budget_from_marked_equity():
    plan, trace, quote, account, limits = inputs()
    account = replace(
        account,
        available_cash_paise=7_000_000,
        marked_equity_paise=8_000_000,
        high_water_mark_paise=8_000_000,
    )

    result = TradeIntentFactory(limits, maximum_quote_age=timedelta(minutes=1)).build(
        plan=plan,
        trace=trace,
        quote=quote,
        account_snapshot=account,
        now=quote.observed_at + timedelta(seconds=10),
    )

    assert result.portfolio_value_paise == 8_000_000
    repeated = TradeIntentFactory(
        limits, maximum_quote_age=timedelta(minutes=1)
    ).build(
        plan=plan,
        trace=trace,
        quote=quote,
        account_snapshot=account,
        now=quote.observed_at + timedelta(seconds=20),
    )
    assert repeated.intent.intent_id == result.intent.intent_id


def test_intent_factory_fails_closed_on_stale_quote_or_non_entry_trace():
    plan, trace, quote, account, limits = inputs()
    factory = TradeIntentFactory(limits, maximum_quote_age=timedelta(minutes=1))

    with pytest.raises(IntentBuildError, match="stale"):
        factory.build(
            plan=plan,
            trace=trace,
            quote=quote,
            account_snapshot=account,
            now=quote.observed_at + timedelta(minutes=2),
        )

    no_action = trace.model_copy(
        update={"action": "no_action", "sizing_intent": None, "exit_intent": None}
    )
    with pytest.raises(IntentBuildError, match="entry decision"):
        factory.build(
            plan=plan,
            trace=no_action,
            quote=quote,
            account_snapshot=account,
            now=quote.observed_at,
        )

    forged = replace(account, day_pnl_paise=1)
    object.__setattr__(forged, "snapshot_id", account.snapshot_id)
    with pytest.raises(IntentBuildError, match="content identity"):
        factory.build(
            plan=plan,
            trace=trace,
            quote=quote,
            account_snapshot=forged,
            now=quote.observed_at,
        )


@pytest.mark.parametrize(
    "forged_trace",
    (
        lambda trace: trace.model_copy(
            update={
                "sizing_intent": trace.sizing_intent.model_copy(
                    update={"risk_budget_fraction": 1.0}
                )
            }
        ),
        lambda trace: trace.model_copy(
            update={
                "exit_intent": trace.exit_intent.model_copy(
                    update={"stop_loss_pct": 25.0}
                )
            }
        ),
        lambda trace: trace.model_copy(
            update={
                "exit_intent": trace.exit_intent.model_copy(
                    update={"max_hold_sessions": 99}
                )
            }
        ),
    ),
)
def test_intent_factory_rejects_trace_semantics_that_differ_from_plan(
    forged_trace,
):
    plan, trace, quote, account, limits = inputs()
    factory = TradeIntentFactory(limits, maximum_quote_age=timedelta(minutes=1))

    with pytest.raises(IntentBuildError, match="does not match the exact plan"):
        factory.build(
            plan=plan,
            trace=forged_trace(trace),
            quote=quote,
            account_snapshot=account,
            now=quote.observed_at,
        )
