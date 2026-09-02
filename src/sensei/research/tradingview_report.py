"""Deterministic analyzer for TradingView Strategy Report trade exports."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Iterable, Literal

import pandas as pd


INITIAL_CAPITAL = 300_000.0
EXPECTED_SYMBOLS = frozenset(
    {
        "ASIANPAINT",
        "BHARTIARTL",
        "DRREDDY",
        "HDFCBANK",
        "HINDUNILVR",
        "ICICIBANK",
        "INFY",
        "ITC",
        "LT",
        "M&M",
        "MARUTI",
        "NTPC",
        "POWERGRID",
        "RELIANCE",
        "SBIN",
        "SUNPHARMA",
        "TATASTEEL",
        "TCS",
        "TITAN",
        "ULTRACEMCO",
    }
)
Phase = Literal["development", "holdout"]
_FILE_RE = re.compile(
    r"^(?P<strategy>[a-z0-9_]+)__(?P<symbol>[A-Z0-9&-]+)__(?P<phase>development|holdout)\.csv$"
)


class TradingViewExportError(ValueError):
    """Raised when an export cannot support a fail-closed verdict."""


@dataclass(frozen=True)
class ClosedTrade:
    strategy: str
    symbol: str
    phase: Phase
    exited_at: pd.Timestamp
    net_pnl: float
    net_return_pct: float
    run_up: float
    drawdown: float


@dataclass(frozen=True)
class ExportBatch:
    strategy: str
    symbols: frozenset[str]
    trades: tuple[ClosedTrade, ...]


def load_exports(directory: Path, *, phase: Phase) -> ExportBatch:
    files = sorted(directory.glob(f"*__{phase}.csv"))
    if not files:
        raise TradingViewExportError(f"no {phase} CSV exports found in {directory}")

    trades: list[ClosedTrade] = []
    event_timestamps: list[pd.Timestamp] = []
    strategies: set[str] = set()
    exported_symbols: set[str] = set()
    for path in files:
        match = _FILE_RE.fullmatch(path.name)
        if match is None:
            raise TradingViewExportError(f"invalid export filename: {path.name}")
        strategy = match.group("strategy")
        symbol = match.group("symbol")
        strategies.add(strategy)
        exported_symbols.add(symbol)
        file_trades, file_timestamps = _load_file(
            path, strategy=strategy, symbol=symbol, phase=phase
        )
        trades.extend(file_trades)
        event_timestamps.extend(file_timestamps)

    if len(strategies) != 1:
        raise TradingViewExportError(
            f"one report may contain only one RuleSpec, found {sorted(strategies)}"
        )
    if exported_symbols != EXPECTED_SYMBOLS:
        raise TradingViewExportError(
            "exports must cover the frozen basket; "
            f"missing={sorted(EXPECTED_SYMBOLS - exported_symbols)}, "
            f"unexpected={sorted(exported_symbols - EXPECTED_SYMBOLS)}"
        )
    _validate_dates(event_timestamps, phase=phase)
    return ExportBatch(
        strategy=next(iter(strategies)),
        symbols=frozenset(exported_symbols),
        trades=tuple(trades),
    )


def analyze_exports(directory: Path, *, phase: Phase) -> dict[str, object]:
    batch = load_exports(directory, phase=phase)
    trades = batch.trades
    symbols = sorted(batch.symbols)
    pnl = [trade.net_pnl for trade in trades]
    returns = [trade.net_return_pct for trade in trades]
    positive = sum(value for value in pnl if value > 0)
    negative = abs(sum(value for value in pnl if value < 0))
    profit_factor = positive / negative if negative else (math.inf if positive else 0.0)

    symbol_pnl = {
        symbol: sum(trade.net_pnl for trade in trades if trade.symbol == symbol)
        for symbol in symbols
    }
    total_pnl = sum(pnl)
    positive_symbol_fraction = sum(value > 0 for value in symbol_pnl.values()) / len(symbols)
    concentration = (
        max(symbol_pnl.values()) / total_pnl if total_pnl > 0 else math.inf
    )
    worst_drawdown = max(_symbol_drawdown(trades, symbol) for symbol in symbols)
    median_return = median(returns) if returns else 0.0

    checks = _checks(
        trades,
        phase=phase,
        closed_trades=len(trades),
        total_pnl=total_pnl,
        median_return=median_return,
        profit_factor=profit_factor,
        worst_drawdown=worst_drawdown,
        positive_symbol_fraction=positive_symbol_fraction,
        concentration=concentration,
    )

    metrics: dict[str, object] = {
        "strategy": batch.strategy,
        "phase": phase,
        "symbols": len(symbols),
        "closed_trades": len(trades),
        "net_profit": round(total_pnl, 2),
        "median_net_return_pct": round(median_return, 4),
        "profit_factor": round(profit_factor, 4) if math.isfinite(profit_factor) else "inf",
        "worst_symbol_max_drawdown_pct": round(worst_drawdown, 4),
        "positive_symbol_fraction": round(positive_symbol_fraction, 4),
        "largest_symbol_profit_contribution": (
            round(concentration, 4) if math.isfinite(concentration) else "inf"
        ),
        "symbol_net_profit": {key: round(value, 2) for key, value in symbol_pnl.items()},
    }

    return {**metrics, "checks": checks, "verdict": "PASS" if all(checks.values()) else "REJECTED"}


def _load_file(
    path: Path, *, strategy: str, symbol: str, phase: Phase
) -> tuple[list[ClosedTrade], list[pd.Timestamp]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise TradingViewExportError(f"missing CSV header: {path.name}")
        columns = {_normalise(name): name for name in reader.fieldnames}
        type_col = _required_column(columns, lambda name: name == "type", "Type", path)
        date_col = _required_column(
            columns, lambda name: name in {"date time", "datetime"}, "Date/Time", path
        )
        pnl_col = _required_column(
            columns,
            lambda name: name.startswith("net p l") and "percent" not in name,
            "Net P&L currency",
            path,
        )
        return_col = _required_column(
            columns,
            lambda name: name.startswith("net p l") and "percent" in name,
            "Net P&L percent",
            path,
        )
        run_up_col = _required_column(
            columns,
            lambda name: name.startswith("run up") and "percent" not in name,
            "Run-up currency",
            path,
        )
        drawdown_col = _required_column(
            columns,
            lambda name: name.startswith("drawdown") and "percent" not in name,
            "Drawdown currency",
            path,
        )

        trades: list[ClosedTrade] = []
        event_timestamps: list[pd.Timestamp] = []
        for row_number, row in enumerate(reader, start=2):
            try:
                event_at = _timestamp(row[date_col])
                event_timestamps.append(event_at)
                if "exit" not in str(row[type_col]).lower():
                    continue
                net_pnl = _number(row[pnl_col])
                net_return_pct = _number(row[return_col])
                run_up = abs(_number(row[run_up_col]))
                drawdown = abs(_number(row[drawdown_col]))
            except (TypeError, ValueError) as exc:
                raise TradingViewExportError(
                    f"invalid closed trade in {path.name}:{row_number}: {exc}"
                ) from exc
            trades.append(
                ClosedTrade(
                    strategy=strategy,
                    symbol=symbol,
                    phase=phase,
                    exited_at=event_at,
                    net_pnl=net_pnl,
                    net_return_pct=net_return_pct,
                    run_up=run_up,
                    drawdown=drawdown,
                )
            )
    return trades, event_timestamps


def _timestamp(value: object) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("Asia/Kolkata").tz_localize(None)
    return timestamp


def _normalise(value: str) -> str:
    value = value.replace("%", " percent ").replace("&", " ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def _required_column(
    columns: dict[str, str], predicate, label: str, path: Path
) -> str:
    matches = [original for normalised, original in columns.items() if predicate(normalised)]
    if len(matches) != 1:
        raise TradingViewExportError(
            f"{path.name} requires exactly one {label} column, found {matches}"
        )
    return matches[0]


def _number(value: object) -> float:
    text = str(value).strip().replace("−", "-").replace(",", "")
    negative = text.startswith("(") and text.endswith(")")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if match is None:
        raise ValueError(f"not numeric: {value!r}")
    parsed = float(match.group())
    return -abs(parsed) if negative else parsed


def _validate_dates(timestamps: Iterable[pd.Timestamp], *, phase: Phase) -> None:
    if phase == "development":
        lower, upper = pd.Timestamp("2019-01-01"), pd.Timestamp("2023-12-31 23:59:59")
    else:
        lower, upper = pd.Timestamp("2024-01-01"), pd.Timestamp.max
    invalid = [timestamp for timestamp in timestamps if not lower <= timestamp <= upper]
    if invalid:
        raise TradingViewExportError(
            f"{len(invalid)} {phase} trade events fall outside the frozen date window"
        )


def _symbol_drawdown(trades: Iterable[ClosedTrade], symbol: str) -> float:
    equity = INITIAL_CAPITAL
    peak = INITIAL_CAPITAL
    maximum = 0.0
    ordered = sorted(
        (trade for trade in trades if trade.symbol == symbol),
        key=lambda trade: trade.exited_at,
    )
    for trade in ordered:
        # The trade export does not identify whether run-up or drawdown happened
        # first. Assuming run-up first creates the larger drawdown and therefore
        # keeps this screening gate conservative.
        peak = max(peak, equity + trade.run_up)
        trough = equity - trade.drawdown
        maximum = max(maximum, (peak - trough) / peak * 100.0)
        equity += trade.net_pnl
        peak = max(peak, equity)
        maximum = max(maximum, (peak - equity) / peak * 100.0)
    return maximum


def _checks(
    trades: tuple[ClosedTrade, ...],
    *,
    phase: Phase,
    closed_trades: int,
    total_pnl: float,
    median_return: float,
    profit_factor: float,
    worst_drawdown: float,
    positive_symbol_fraction: float,
    concentration: float,
) -> dict[str, bool]:
    if phase == "development":
        early = sum(
            trade.net_pnl for trade in trades if trade.exited_at.year <= 2021
        )
        late = sum(
            trade.net_pnl for trade in trades if trade.exited_at.year >= 2022
        )
        return development_gate_checks(
            closed_trades=closed_trades,
            median_return=median_return,
            profit_factor=profit_factor,
            worst_drawdown=worst_drawdown,
            positive_symbol_fraction=positive_symbol_fraction,
            early_pnl=early,
            late_pnl=late,
            concentration=concentration,
        )
    return {
        "positive_net_profit": total_pnl > 0,
        "profit_factor_at_least_1_15": profit_factor >= 1.15,
        "drawdown_at_most_15_pct": worst_drawdown <= 15,
        "positive_on_50_pct_symbols": positive_symbol_fraction >= 0.50,
        "symbol_contribution_at_most_30_pct": concentration <= 0.30,
    }


def development_gate_checks(
    *,
    closed_trades: int,
    median_return: float,
    profit_factor: float,
    worst_drawdown: float,
    positive_symbol_fraction: float,
    early_pnl: float,
    late_pnl: float,
    concentration: float,
) -> dict[str, bool]:
    """Evaluate the single frozen development gate shared by both analyzers."""

    return {
        "minimum_100_trades": closed_trades >= 100,
        "positive_median_return": median_return > 0,
        "profit_factor_at_least_1_25": profit_factor >= 1.25,
        "drawdown_at_most_15_pct": worst_drawdown <= 15,
        "positive_on_60_pct_symbols": positive_symbol_fraction >= 0.60,
        "positive_2019_through_2021": early_pnl > 0,
        "positive_2022_through_2023": late_pnl > 0,
        "symbol_contribution_at_most_25_pct": concentration <= 0.25,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--phase", choices=("development", "holdout"), required=True)
    args = parser.parse_args()
    print(json.dumps(analyze_exports(args.directory, phase=args.phase), indent=2))


if __name__ == "__main__":
    main()
