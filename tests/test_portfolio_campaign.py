import pandas as pd

from sensei.backtest.portfolio_campaign import (
    PortfolioCampaignConfig,
    run_portfolio_campaign,
)


def _bars():
    index = pd.bdate_range("2026-01-01", periods=4)
    return pd.DataFrame({
        "open": [100, 100, 105, 110],
        "high": [101, 102, 111, 111],
        "low": [99, 99, 104, 109],
        "close": [100, 101, 110, 110],
        "volume": [1_000_000] * 4,
    }, index=index)


def test_campaign_uses_integer_sizing_costs_and_daily_equity():
    def first_day(frame):
        return pd.Series([True, False, False, False], index=frame.index)

    report = run_portfolio_campaign(
        frames={"TEST": _bars()},
        strategies={"trend": {
            "fn": first_day, "stop_pct": 5, "target_pct": 10,
            "max_hold_days": 10,
        }},
        config=PortfolioCampaignConfig(
            capital=1_000, max_position_pct=50, max_risk_per_trade_pct=5,
            max_open_positions=2, cost_pct=0.25,
        ),
    )

    assert report.trades[0].quantity == 5
    assert report.trades[0].entry_price == 100
    assert report.trades[0].exit_price == 110
    assert report.trades[0].net_pnl == 48.75
    assert report.final_equity == 1_048.75
    assert len(report.equity_curve) == 4
    assert report.max_drawdown_pct == 0


def test_campaign_assumes_stop_before_target_on_ambiguous_daily_bar():
    bars = _bars()
    bars.loc[bars.index[2], ["high", "low"]] = [120, 90]

    report = run_portfolio_campaign(
        frames={"TEST": bars},
        strategies={"trend": {
            "fn": lambda frame: pd.Series(
                [True, False, False, False], index=frame.index
            ),
            "stop_pct": 5, "target_pct": 10, "max_hold_days": 10,
        }},
        config=PortfolioCampaignConfig(
            capital=1_000, max_position_pct=50, max_risk_per_trade_pct=5,
            max_open_positions=2, cost_pct=0,
        ),
    )

    assert report.trades[0].exit_reason == "stop"
    assert report.trades[0].exit_price == 95
    assert report.final_equity == 975


def test_campaign_applies_protection_on_the_entry_session():
    bars = _bars()
    bars.loc[bars.index[1], ["high", "low"]] = [120, 90]
    report = run_portfolio_campaign(
        frames={"TEST": bars},
        strategies={"trend": {"fn": lambda frame: pd.Series(
            [True, False, False, False], index=frame.index),
            "stop_pct": 5, "target_pct": 10, "max_hold_days": 10}},
        config=PortfolioCampaignConfig(capital=1_000, max_position_pct=50,
            max_risk_per_trade_pct=5, max_open_positions=2, cost_pct=0),
    )
    assert report.trades[0].entry_date == report.trades[0].exit_date
    assert report.trades[0].exit_reason == "stop"
    assert report.final_equity == 975


def test_campaign_uses_pre_window_history_only_for_indicator_warmup():
    index = pd.bdate_range("2026-01-01", periods=8)
    bars = pd.DataFrame({
        "open": [100] * 8,
        "high": [101, 101, 101, 101, 101, 101, 111, 101],
        "low": [99] * 8,
        "close": [100, 101, 102, 103, 104, 105, 106, 107],
        "volume": [1_000_000] * 8,
    }, index=index)

    def warmed_signal(frame):
        return (frame["close"].rolling(5).mean() > 100).where(
            frame.index == index[4], False
        )

    report = run_portfolio_campaign(
        frames={"TEST": bars},
        strategies={"trend": {
            "fn": warmed_signal, "stop_pct": 5, "target_pct": 10,
            "max_hold_days": 10,
        }},
        config=PortfolioCampaignConfig(
            capital=1_000, max_position_pct=50, max_risk_per_trade_pct=5,
            max_open_positions=2, cost_pct=0,
        ),
        evaluation_start=index[4],
    )

    assert report.equity_curve[0].session == str(index[4].date())
    assert report.trades[0].entry_date == str(index[5].date())
