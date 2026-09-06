"""Offline review probe; never reads market stores or writes trading state.

Run from the repo: .venv/bin/python docs/research/probes/backtest_contract_audit.py
Exit 1 means an audited contract is still unresolved; this is not a strategy test.
"""

from __future__ import annotations

import json
import math

import pandas as pd

from sensei.backtest.engine import BacktestResult, Trade, run_backtest
from sensei.backtest.portfolio_campaign import PortfolioCampaignConfig, run_portfolio_campaign
from sensei.backtest.rulespec import Condition, RuleSpec
from sensei.research.models import EvaluationFold
from sensei.research.simulation import simulate_fold


def audit() -> dict:
    dates = pd.bdate_range("2020-01-01", periods=3)
    bars = pd.DataFrame(
        {"open": [100, 100, 120], "high": [101, 101, 125],
         "low": [99, 99, 90], "close": [100, 100, 100],
         "volume": [1_000_000] * 3},
        index=dates,
    )
    signals = pd.Series([True, False, False], index=dates)
    spec = RuleSpec(
        name="audit_probe", source="Synthetic audit fixture", principle="Parity",
        conditions=(Condition(left="close", op=">", right=0),),
        stop_pct=5, target_pct=10, max_hold_days=3,
    )
    legacy = run_backtest(
        bars, lambda _: signals, strategy=spec.name, symbol="SYNTHETIC",
        stop_pct=5, target_pct=10, max_hold_days=3, cost_pct=0,
    ).trades[0]
    examiner = simulate_fold(
        "SYNTHETIC", bars, signals,
        EvaluationFold("audit", dates[0].date(), dates[-1].date()), spec, 0,
    ).trades[0]
    portfolio = run_portfolio_campaign(
        frames={"SYNTHETIC": bars},
        strategies={spec.name: {
            "fn": lambda _: signals, "stop_pct": 5, "target_pct": 10, "max_hold_days": 3,
        }},
        config=PortfolioCampaignConfig(
            capital=1000, max_position_pct=50, max_risk_per_trade_pct=5, cost_pct=0,
        ),
    ).trades[0]
    portfolio_trade_return = portfolio.net_pnl / (portfolio.entry_price * portfolio.quantity) * 100
    drawdown = BacktestResult(
        "audit", "SYNTHETIC",
        [Trade("SYNTHETIC", dates[0], 100, dates[1], 90, "time", 0)],
    ).max_drawdown_pct
    return {
        "authority": "SYNTHETIC_REVIEW_ONLY",
        "initial_loss_drawdown": {
            "expected_pct": 10, "actual_pct": round(drawdown, 8),
            "passed": math.isclose(drawdown, 10),
        },
        "held_position_opening_gap_parity": {
            "legacy_return_pct": round(legacy.ret_pct, 8),
            "examiner_return_pct": round(examiner.ret_pct, 8),
            "portfolio_trade_return_pct": round(portfolio_trade_return, 8),
            "legacy_exit": legacy.exit_reason,
            "examiner_exit": examiner.exit_reason,
            "passed": math.isclose(legacy.ret_pct, examiner.ret_pct) and math.isclose(
                legacy.ret_pct, portfolio_trade_return,
            ),
            "meaning": "Compares daily research bracket policies only; no market alpha inference.",
        },
    }


if __name__ == "__main__":
    result = audit()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if all(
        value["passed"] for value in result.values() if isinstance(value, dict)
    ) else 1)
