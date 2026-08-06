import pandas as pd

from sensei.backtest.portfolio_campaign import PortfolioCampaignConfig
from sensei.backtest.strategy_diagnostic_matrix import (
    DiagnosticScenario,
    run_strategy_diagnostic_matrix,
)


def test_matrix_compares_scenarios_windows_and_costs_without_trade_authority():
    index = pd.bdate_range("2025-01-01", periods=8)
    frame = pd.DataFrame({
        "open": [100] * 8,
        "high": [101, 101, 101, 101, 101, 111, 101, 101],
        "low": [99] * 8,
        "close": [100, 101, 102, 103, 104, 105, 106, 107],
        "volume": [1_000_000] * 8,
    }, index=index)
    strategies = {
        "winner": {
            "fn": lambda bars: pd.Series(
                bars.index == index[4], index=bars.index
            ),
            "stop_pct": 5, "target_pct": 10, "max_hold_days": 10,
        },
        "quiet": {
            "fn": lambda bars: pd.Series(False, index=bars.index),
            "stop_pct": 5, "target_pct": 10, "max_hold_days": 10,
        },
    }

    report = run_strategy_diagnostic_matrix(
        frames={"TEST": frame},
        strategies=strategies,
        scenarios=(
            DiagnosticScenario("winner_only", ("winner",)),
            DiagnosticScenario("quiet_only", ("quiet",)),
        ),
        windows=(4,),
        costs=(0.0, 1.0),
        base_config=PortfolioCampaignConfig(
            capital=1_000, max_position_pct=50, max_risk_per_trade_pct=5,
            max_open_positions=2, cost_pct=0,
        ),
    )

    payload = report.to_dict()
    assert len(payload["results"]) == 4
    assert payload["results"][0]["evaluation_start"] == str(index[4].date())
    assert payload["rankings"][0]["scenario"] == "winner_only"
    assert payload["rankings"][0]["positive_cells"] == 2
    assert payload["authority"] == "RESEARCH_ONLY"
    assert payload["can_trade"] is False
