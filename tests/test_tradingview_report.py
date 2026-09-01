from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest

from sensei.research.tradingview_report import (
    ClosedTrade,
    EXPECTED_SYMBOLS,
    TradingViewExportError,
    _checks,
    _symbol_drawdown,
    analyze_exports,
)


HEADERS = [
    "Trade #",
    "Type",
    "Date/Time",
    "Net P&L INR",
    "Net P&L %",
    "Run-up INR",
    "Drawdown INR",
]


def _write_export(path: Path, rows: list[list[object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADERS)
        writer.writerows(rows)


def test_analyzer_builds_a_deterministic_passing_development_report(tmp_path: Path) -> None:
    for symbol in sorted(EXPECTED_SYMBOLS):
        rows: list[list[object]] = []
        for trade_index in range(5):
            year = 2020 if trade_index < 2 else 2022
            pnl = 3_000 if trade_index % 2 == 0 else -1_000
            return_pct = 1.0 if pnl > 0 else -0.3333
            rows.extend(
                [
                    [trade_index + 1, "Entry long", f"{year}-01-02", "", "", "", ""],
                    [trade_index + 1, "Exit long", f"{year}-01-03", pnl, return_pct, 1_000, 500],
                ]
            )
        _write_export(
            tmp_path / f"minervini_breakout_volume__{symbol}__development.csv",
            rows,
        )

    report = analyze_exports(tmp_path, phase="development")

    assert report["verdict"] == "PASS"
    assert report["closed_trades"] == 100
    assert report["profit_factor"] == 4.5
    assert report["largest_symbol_profit_contribution"] == 0.05
    assert all(report["checks"].values())


def test_analyzer_rejects_a_trade_outside_the_phase_window(tmp_path: Path) -> None:
    for symbol in EXPECTED_SYMBOLS:
        _write_export(
            tmp_path / f"minervini_breakout_volume__{symbol}__development.csv",
            [[1, "Exit long", "2024-01-02", 100, 0.1, 100, 50]],
        )

    with pytest.raises(TradingViewExportError, match="outside the frozen date window"):
        analyze_exports(tmp_path, phase="development")


def test_analyzer_rejects_a_holdout_trade_entered_before_the_holdout(tmp_path: Path) -> None:
    for symbol in EXPECTED_SYMBOLS:
        _write_export(
            tmp_path / f"minervini_breakout_volume__{symbol}__holdout.csv",
            [
                [1, "Entry long", "2023-12-29", "", "", "", ""],
                [1, "Exit long", "2024-01-02", 100, 0.1, 100, 50],
            ],
        )

    with pytest.raises(TradingViewExportError, match="outside the frozen date window"):
        analyze_exports(tmp_path, phase="holdout")


def test_analyzer_fails_closed_when_percent_return_is_missing(tmp_path: Path) -> None:
    path = tmp_path / "minervini_breakout_volume__ASIANPAINT__holdout.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Type", "Date/Time", "Net P&L INR"])
        writer.writerow(["Exit long", "2024-01-02", 100])

    with pytest.raises(TradingViewExportError, match="Net P&L percent"):
        analyze_exports(tmp_path, phase="holdout")


def test_zero_trade_symbol_counts_as_covered_but_not_positive(tmp_path: Path) -> None:
    for symbol in EXPECTED_SYMBOLS:
        rows = [] if symbol == "TITAN" else [[1, "Exit long", "2024-01-02", 100, 0.1, 50, 25]]
        _write_export(
            tmp_path / f"minervini_breakout_volume__{symbol}__holdout.csv",
            rows,
        )

    report = analyze_exports(tmp_path, phase="holdout")

    assert report["symbols"] == 20
    assert report["closed_trades"] == 19
    assert report["symbol_net_profit"]["TITAN"] == 0
    assert report["positive_symbol_fraction"] == 0.95


def test_gate_thresholds_use_raw_values_instead_of_rounded_display_values() -> None:
    checks = _checks(
        (),
        phase="development",
        closed_trades=100,
        total_pnl=1,
        median_return=0.00001,
        profit_factor=1.24996,
        worst_drawdown=15.00004,
        positive_symbol_fraction=0.60,
        concentration=0.25004,
    )

    assert checks["profit_factor_at_least_1_25"] is False
    assert checks["drawdown_at_most_15_pct"] is False
    assert checks["symbol_contribution_at_most_25_pct"] is False


def test_drawdown_includes_intratrade_adverse_excursion() -> None:
    trade = ClosedTrade(
        strategy="minervini_breakout_volume",
        symbol="TITAN",
        phase="holdout",
        exited_at=pd.Timestamp("2024-01-02"),
        net_pnl=0,
        net_return_pct=0,
        run_up=30_000,
        drawdown=60_000,
    )

    assert _symbol_drawdown((trade,), "TITAN") == pytest.approx(27.272727)
