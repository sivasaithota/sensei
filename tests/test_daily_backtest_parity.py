"""Exercise the public simulation paths with the same executable trade."""

import pandas as pd
import pytest

from sensei.backtest.engine import run_backtest
from sensei.backtest.portfolio_campaign import PortfolioCampaignConfig, run_portfolio_campaign
from sensei.backtest.rulespec import Condition, RuleSpec
from sensei.research.models import EvaluationFold
from sensei.research.simulation import simulate_fold


@pytest.mark.parametrize(
    ("open_price", "high", "low", "expected_exit", "expected_price"),
    [
        (120, 125, 90, "target", 110),  # Open is before the later stop touch.
        (90, 125, 85, "stop_gap", 90),  # Gap loss cannot fill at the stop.
        (100, 125, 90, "stop", 95),  # Intraday order remains unknown.
        (110, 125, 90, "target", 110),
        (95, 125, 90, "stop_gap", 95),
        (100, 125, 99, "target", 110),
    ],
)
def test_three_daily_simulators_agree_on_bracket_outcome(
    open_price, high, low, expected_exit, expected_price,
):
    dates = pd.bdate_range("2020-01-01", periods=3)
    bars = pd.DataFrame({
        "open": [100, 100, open_price], "high": [101, 101, high],
        "low": [99, 99, low], "close": [100, 100, 100],
        "volume": [1_000_000] * 3,
    }, index=dates, dtype=float)
    signal = lambda frame: pd.Series([True, False, False], index=frame.index)
    # Test exact trigger equality, including the engine's floating-point value.
    target_pct = 10.0
    if open_price == 110:
        bars.loc[dates[-1], "open"] = 100 * (1 + target_pct / 100)
    rule = RuleSpec(
        name="parity_probe", source="synthetic", principle="execution parity",
        conditions=(Condition(left="close", op=">", right=0),),
        stop_pct=5, target_pct=target_pct, max_hold_days=3,
    )
    legacy = run_backtest(
        bars, signal, strategy=rule.name, symbol="TEST", stop_pct=5,
        target_pct=target_pct, max_hold_days=3, cost_pct=0.25,
    )
    examiner = simulate_fold(
        "TEST", bars, signal(bars),
        EvaluationFold("audit", dates[0].date(), dates[-1].date()), rule, 0.25,
    )
    portfolio = run_portfolio_campaign(
        frames={"TEST": bars},
        strategies={rule.name: {"fn": signal, "stop_pct": 5,
                               "target_pct": target_pct, "max_hold_days": 3}},
        config=PortfolioCampaignConfig(
            capital=1000, max_position_pct=50, max_risk_per_trade_pct=5,
            cost_pct=0.25,
        ),
    )
    expected_return = (expected_price / 100 - 1) * 100 - 0.25
    assert len(legacy.trades) == len(examiner.trades) == len(portfolio.trades) == 1
    assert legacy.trades[0].exit_reason == portfolio.trades[0].exit_reason == expected_exit
    assert legacy.trades[0].exit == pytest.approx(expected_price)
    assert portfolio.trades[0].exit_price == pytest.approx(expected_price)
    assert legacy.trades[0].ret_pct == pytest.approx(expected_return)
    assert examiner.trades[0].ret_pct == pytest.approx(expected_return)
    assert portfolio.final_equity == pytest.approx(1000 + 5 * (expected_price - 100) - 1.25)
    assert portfolio.open_positions == 0
    assert portfolio.equity_curve[-1].cash == portfolio.final_equity


@pytest.mark.parametrize("exit_at_open", [True, False])
def test_only_opening_target_proceeds_are_available_before_new_entries(exit_at_open):
    dates = pd.bdate_range("2020-01-01", periods=4)
    bars = pd.DataFrame({
        "open": [100, 100, 120, 120], "high": [101, 101, 125, 121],
        "low": [99, 99, 90, 119], "close": [100, 100, 120, 120],
        "volume": [1_000_000] * 4,
    }, index=dates)
    if not exit_at_open:
        bars.loc[dates[2], ["open", "low"]] = [100, 99]
    next_bars = bars.copy()
    next_bars[["open", "high", "low", "close"]] = [200, 201, 199, 200]
    strategies = {
        name: {"fn": lambda frame: pd.Series(False, index=frame.index),
               "stop_pct": 5, "target_pct": 10, "max_hold_days": 10}
        for name in ("first", "second")
    }
    signals = {
        (name, symbol): pd.Series(False, index=dates)
        for name in strategies for symbol in ("A", "B")
    }
    signals[("first", "A")].iloc[0] = True
    signals[("second", "B")].iloc[1] = True
    report = run_portfolio_campaign(
        frames={"A": bars, "B": next_bars}, strategies=strategies,
        prepared_signals=signals,
        config=PortfolioCampaignConfig(
            capital=1000, max_position_pct=100, max_risk_per_trade_pct=100,
            max_open_positions=1, cost_pct=0,
        ),
    )
    assert report.trades[0].exit_reason == "target"
    assert report.equity_curve[2].open_positions == (1 if exit_at_open else 0)
    assert report.equity_curve[2].invested == (1000 if exit_at_open else 0)
    assert report.equity_curve[2].cash == pytest.approx(100 if exit_at_open else 1100)
    assert report.final_equity == pytest.approx(1100)
