from dataclasses import replace

import pandas as pd
import pytest

from sensei.backtest.costs import delivery_charge, delivery_quantity
from sensei.backtest.portfolio_campaign import PortfolioCampaignConfig, run_portfolio_campaign
from sensei.research.stock_evaluation import EvaluationProtocol, audit_stock_data, evaluate_stock_portfolio


def fixture():
    dates = pd.bdate_range("2020-01-01", periods=70)
    frame = pd.DataFrame({"open": 100., "high": 101., "low": 99., "close": 100., "volume": 1e6}, index=dates)
    strategies = {"flat": {"fn": lambda f: pd.Series(True, index=f.index),
        "stop_pct": 5, "target_pct": 10, "max_hold_days": 5}}
    report = run_portfolio_campaign(frames={"A": frame}, strategies=strategies,
        config=PortfolioCampaignConfig(cost_model="current_delivery_schedule", liquidate_at_end=True),
        evaluation_start=dates[1])
    return frame, report


def test_delivery_round_trip_reconciles_cash_fees_and_stop_risk():
    quantity = delivery_quantity(price=100, stop=95, cash=60_000, size_budget=60_000,
        risk_budget=3000, dp_charge_inr=15.34)
    def risk(q):
        return q * 5 + delivery_charge(q * 100, "BUY") + delivery_charge(q * 95, "SELL")
    assert risk(quantity) <= 3000 < risk(quantity + 1)
    frame, report = fixture()
    costs = sum(trade.costs for trade in report.trades)
    assert report.final_equity == pytest.approx(report.config.capital - costs, abs=0.02)
    trade = report.trades[0]
    assert trade.costs == pytest.approx(delivery_charge(trade.quantity * 100, "BUY") + delivery_charge(trade.quantity * 100, "SELL"), abs=0.01)


def test_report_separates_data_risk_and_economic_evidence():
    frame, campaign = fixture()
    protocol = EvaluationProtocol(minimum_sessions=20, minimum_trades=5, bootstrap_samples=100)
    report = evaluate_stock_portfolio(campaign=campaign, protocol=protocol,
        data_audit=audit_stock_data({"A": frame}), benchmark=frame.close)
    assert report["decision"] == "DATA_BLOCKED"
    assert not report["can_trade"]
    assert report["economics"]["verdict"] == "INCONCLUSIVE"
    assert "account_drawdown_limit_unspecified" in report["economics"]["limitations"]
    assert report["benchmark"]["return_pct"] == 0
    assert report["benchmark"]["annualized_mean_daily_excess_interval_pct"][1] < 0
    decided = evaluate_stock_portfolio(campaign=campaign, protocol=replace(protocol, maximum_drawdown_pct=10),
        data_audit=audit_stock_data({"A": frame}), benchmark=frame.close)
    assert decided["economics"]["verdict"] == "NO_CLEAR_NET_EDGE"
    assert decided["evaluation_id"] != report["evaluation_id"]


def test_missing_benchmark_session_is_not_forward_filled():
    frame, campaign = fixture()
    report = evaluate_stock_portfolio(campaign=campaign, protocol=EvaluationProtocol(),
        data_audit=audit_stock_data({"A": frame}), benchmark=frame.close.drop(frame.index[30]))
    assert report["benchmark"] is None
    assert "benchmark_calendar_mismatch_or_missing_prior_session" in report["economics"]["limitations"]


def test_content_audit_retains_invalid_and_short_history_names():
    frame, _ = fixture()
    invalid = frame.copy()
    invalid.loc[invalid.index[1], "high"] = 90
    result = audit_stock_data({"bad": invalid, "short": frame.iloc[:10]})
    assert "bad:invalid_ohlcv" in result["content_issues"]
    assert result["instruments"]["short"]["rows"] == 10
    assert result["external_evidence_missing"]


def test_benchmark_cannot_use_stale_predecessor():
    frame, campaign = fixture()
    benchmark = frame.close.iloc[1:].copy()
    benchmark.loc[pd.Timestamp("2010-01-01")] = 10
    report = evaluate_stock_portfolio(campaign=campaign, protocol=EvaluationProtocol(),
        data_audit=audit_stock_data({"A": frame}), benchmark=benchmark)
    assert report["benchmark"] is None
    assert "benchmark_calendar_mismatch_or_missing_prior_session" in report["economics"]["limitations"]


def test_charge_schedule_changes_experiment_identity(monkeypatch):
    from sensei.backtest import costs
    from sensei.execution.nse import IndianDeliveryChargeSchedule

    _, original = fixture()
    monkeypatch.setattr(costs, "IndianDeliveryChargeSchedule", lambda: IndianDeliveryChargeSchedule(stt_ppm=2000))
    _, higher_fees = fixture()
    assert higher_fees.final_equity < original.final_equity
    assert higher_fees.experiment_id != original.experiment_id


def test_benchmark_rejects_session_missing_from_entire_stock_calendar():
    frame, campaign = fixture()
    first = pd.Timestamp(campaign.equity_curve[0].session)
    benchmark = frame.close.copy()
    benchmark.loc[first - pd.Timedelta(hours=12)] = 100
    report = evaluate_stock_portfolio(campaign=campaign, protocol=EvaluationProtocol(),
        data_audit=audit_stock_data({"A": frame}), benchmark=benchmark)
    assert report["benchmark"] is None


def test_total_loss_drawdown_budget_is_valid_but_does_not_create_an_edge():
    frame, campaign = fixture()
    protocol = EvaluationProtocol(maximum_drawdown_pct=100, minimum_sessions=20,
        minimum_trades=5, bootstrap_samples=100)
    report = evaluate_stock_portfolio(campaign=campaign, protocol=protocol,
        data_audit=audit_stock_data({"A": frame}), benchmark=frame.close)
    assert report["economics"]["verdict"] == "NO_CLEAR_NET_EDGE"
    assert not report["can_trade"]


@pytest.mark.parametrize("drawdown", [0, -1, 100.01, float("nan"), float("inf"), True])
def test_invalid_drawdown_budgets_are_rejected(drawdown):
    with pytest.raises(ValueError, match="maximum drawdown"):
        EvaluationProtocol(maximum_drawdown_pct=drawdown)
