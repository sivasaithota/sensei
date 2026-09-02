from __future__ import annotations

import json

import pandas as pd
import pytest

from sensei.research.tradingview_local_screen import (
    EXPECTED_RULESPECS,
    LocalScreenTrade,
    analyze_local_screen,
    assert_frozen_ruleset,
    simulate_chart,
    validate_price_coverage,
)
from sensei.research.tradingview_report import EXPECTED_SYMBOLS


def _bars(rows: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=("date", "open", "high", "low", "close"),
    ).set_index(pd.to_datetime([row[0] for row in rows])).drop(columns="date")


def test_simulator_uses_next_open_and_signal_close_protection() -> None:
    bars = _bars(
        [
            ("2023-01-02", 100, 102, 99, 100),
            ("2023-01-03", 110, 111, 94, 108),
            ("2023-01-04", 108, 109, 107, 108),
        ]
    )
    signal = pd.Series([True, False, False], index=bars.index)

    trades = simulate_chart(
        bars,
        signal,
        symbol="TEST",
        stop_pct=5,
        target_pct=15,
        max_hold_sessions=30,
        last_entry_signal_date=pd.Timestamp("2023-12-28"),
        last_exit_session_date=pd.Timestamp("2023-12-29"),
    )

    assert len(trades) == 1
    trade = trades[0]
    assert trade.entry_date == pd.Timestamp("2023-01-03")
    assert trade.entry_price == 110.05
    assert trade.exit_reason == "stop"
    assert trade.exit_price == 94.95


def test_simulator_is_stop_first_when_stop_and_target_touch() -> None:
    bars = _bars(
        [
            ("2023-01-02", 100, 101, 99, 100),
            ("2023-01-03", 100, 120, 94, 110),
        ]
    )
    signal = pd.Series([True, False], index=bars.index)

    trade = simulate_chart(
        bars,
        signal,
        symbol="TEST",
        stop_pct=5,
        target_pct=15,
        max_hold_sessions=30,
        last_entry_signal_date=pd.Timestamp("2023-12-28"),
        last_exit_session_date=pd.Timestamp("2023-12-29"),
    )[0]

    assert trade.exit_reason == "stop"


def test_simulator_forces_final_development_exit() -> None:
    bars = _bars(
        [
            ("2023-12-27", 100, 101, 99, 100),
            ("2023-12-28", 101, 102, 100, 101),
            ("2023-12-29", 102, 103, 101, 102),
            ("2024-01-01", 103, 104, 102, 103),
        ]
    )
    signal = pd.Series([False, True, False, False], index=bars.index)

    trade = simulate_chart(
        bars,
        signal,
        symbol="TEST",
        stop_pct=20,
        target_pct=40,
        max_hold_sessions=30,
        last_entry_signal_date=pd.Timestamp("2023-12-28"),
        last_exit_session_date=pd.Timestamp("2023-12-29"),
    )[0]

    assert trade.exit_date == pd.Timestamp("2023-12-29")
    assert trade.exit_reason == "final_session"


def test_simulator_evaluates_a_new_signal_on_bracket_exit_day() -> None:
    bars = _bars(
        [
            ("2023-01-02", 100, 101, 99, 100),
            ("2023-01-03", 100, 116, 99, 115),
            ("2023-01-04", 110, 111, 109, 110),
            ("2023-01-05", 111, 112, 110, 111),
        ]
    )
    signal = pd.Series([True, True, False, False], index=bars.index)

    trades = simulate_chart(
        bars,
        signal,
        symbol="TEST",
        stop_pct=5,
        target_pct=15,
        max_hold_sessions=30,
        last_entry_signal_date=pd.Timestamp("2023-12-28"),
        last_exit_session_date=pd.Timestamp("2023-12-29"),
    )

    assert len(trades) == 2
    assert trades[0].exit_date == pd.Timestamp("2023-01-03")
    assert trades[1].signal_date == pd.Timestamp("2023-01-03")
    assert trades[1].entry_date == pd.Timestamp("2023-01-04")


def test_simulator_does_not_reenter_from_a_time_exit_close() -> None:
    bars = _bars(
        [
            ("2023-01-02", 100, 101, 99, 100),
            ("2023-01-03", 100, 101, 99, 100),
            ("2023-01-04", 100, 101, 99, 100),
        ]
    )
    signal = pd.Series([True, True, False], index=bars.index)

    trades = simulate_chart(
        bars,
        signal,
        symbol="TEST",
        stop_pct=20,
        target_pct=20,
        max_hold_sessions=1,
        last_entry_signal_date=pd.Timestamp("2023-12-28"),
        last_exit_session_date=pd.Timestamp("2023-12-29"),
    )

    assert len(trades) == 1
    assert trades[0].exit_reason == "time"


def test_development_gate_fails_closed_on_bad_median_and_drawdown() -> None:
    losing = LocalScreenTrade(
        symbol="A",
        signal_date=pd.Timestamp("2020-01-01"),
        entry_date=pd.Timestamp("2020-01-02"),
        exit_date=pd.Timestamp("2020-01-03"),
        entry_price=100,
        exit_price=90,
        quantity=100,
        net_pnl=-1_025,
        net_return_pct=-10.25,
        exit_reason="stop",
        equity_after=298_975,
    )
    report = analyze_local_screen(
        "example", {"A": (losing,)}, symbols=("A",), initial_capital=300_000
    )

    assert report["verdict"] == "REJECTED"
    assert report["checks"]["minimum_100_trades"] is False
    assert report["checks"]["positive_median_return"] is False


def test_local_screen_cannot_authorize_holdout_even_when_all_checks_pass() -> None:
    trades_by_symbol: dict[str, tuple[LocalScreenTrade, ...]] = {}
    for symbol in ("A", "B", "C", "D"):
        equity = 300_000.0
        trades: list[LocalScreenTrade] = []
        for trade_number in range(25):
            equity += 1_000
            trades.append(
                LocalScreenTrade(
                    symbol=symbol,
                    signal_date=pd.Timestamp("2020-01-01"),
                    entry_date=pd.Timestamp("2020-01-02"),
                    exit_date=pd.Timestamp("2020-01-03")
                    if trade_number < 13
                    else pd.Timestamp("2022-01-03"),
                    entry_price=100,
                    exit_price=101,
                    quantity=1_000,
                    net_pnl=1_000,
                    net_return_pct=1.0,
                    exit_reason="target",
                    equity_after=equity,
                )
            )
        trades_by_symbol[symbol] = tuple(trades)

    report = analyze_local_screen(
        "example", trades_by_symbol, symbols=tuple(trades_by_symbol)
    )

    assert all(report["checks"].values())
    assert report["verdict"] == "REQUIRES_TRADINGVIEW_VALIDATION"


def test_frozen_ruleset_rejects_a_changed_rule(tmp_path) -> None:
    path = tmp_path / "studied_rules.json"
    path.write_text(
        json.dumps([{"name": name, "changed": True} for name in EXPECTED_RULESPECS])
    )

    with pytest.raises(ValueError, match="RuleSpecs changed"):
        assert_frozen_ruleset(path)


def test_price_coverage_rejects_a_symbol_with_missing_session() -> None:
    dates = pd.bdate_range("2018-01-01", "2023-12-29")
    complete = pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}, index=dates
    )
    prices = {symbol: complete for symbol in EXPECTED_SYMBOLS}
    missing = complete.drop(pd.Timestamp("2022-07-01"))
    prices[sorted(EXPECTED_SYMBOLS)[-1]] = missing

    with pytest.raises(ValueError, match="missing or unexpected"):
        validate_price_coverage(prices)
