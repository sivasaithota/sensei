"""Local, research-only reproduction of the frozen TradingView screen.

This module deliberately does not integrate with strategy governance.  It is a
fast cross-check for the development experiment documented in
``docs/operations/tradingview-poc.md``.  The current-survivor Yahoo price store
is not admissible evidence for real capital.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Iterable, Mapping, Sequence

import pandas as pd

from sensei.backtest.playbook import all_strategies
from sensei.data.store import load_prices
from sensei.research.tradingview_report import (
    EXPECTED_SYMBOLS,
    INITIAL_CAPITAL,
    development_gate_checks,
)

START_DATE = pd.Timestamp("2019-01-01")
LAST_ENTRY_SIGNAL_DATE = pd.Timestamp("2023-12-28")
LAST_EXIT_SESSION_DATE = pd.Timestamp("2023-12-29")
COMMISSION_PER_ORDER_PCT = 0.125
DEFAULT_TICK_SIZE = 0.05
WARMUP_START_DATE = pd.Timestamp("2018-01-01")
FROZEN_RULESET_SHA256 = "e4e4de617120aecab9bf4648908d82e63a393c96d8d781f93a8b938c3f1613de"
STUDIED_RULES_PATH = Path(__file__).resolve().parents[3] / "data" / "studied_rules.json"


@dataclass(frozen=True)
class LocalScreenTrade:
    symbol: str
    signal_date: pd.Timestamp
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_price: float
    exit_price: float
    quantity: int
    net_pnl: float
    net_return_pct: float
    exit_reason: str
    equity_after: float


def simulate_chart(
    bars: pd.DataFrame,
    signal: pd.Series,
    *,
    symbol: str,
    stop_pct: float,
    target_pct: float,
    max_hold_sessions: int,
    last_entry_signal_date: pd.Timestamp = LAST_ENTRY_SIGNAL_DATE,
    last_exit_session_date: pd.Timestamp = LAST_EXIT_SESSION_DATE,
    initial_capital: float = INITIAL_CAPITAL,
    commission_per_order_pct: float = COMMISSION_PER_ORDER_PCT,
    tick_size: float = DEFAULT_TICK_SIZE,
) -> tuple[LocalScreenTrade, ...]:
    """Simulate one independently funded chart using the frozen Pine timing.

    Protection is fixed from the signal close.  Entries fill at the next open,
    ambiguous daily bars are stop-first, and the final development session
    forcibly liquidates any open position.
    """

    required = {"open", "high", "low", "close"}
    missing = required - set(bars.columns)
    if missing:
        raise ValueError(f"missing OHLC columns: {sorted(missing)}")
    frame = bars.sort_index().copy()
    frame.index = pd.to_datetime(frame.index).tz_localize(None)
    aligned_signal = signal.reindex(frame.index).fillna(False).astype(bool)
    dates = frame.index
    equity = float(initial_capital)
    trades: list[LocalScreenTrade] = []
    i = 0

    while i < len(frame) - 1:
        signal_date = pd.Timestamp(dates[i])
        if signal_date < START_DATE or signal_date > last_entry_signal_date:
            i += 1
            continue
        if not bool(aligned_signal.iloc[i]):
            i += 1
            continue

        entry_idx = i + 1
        entry_date = pd.Timestamp(dates[entry_idx])
        if entry_date > last_exit_session_date:
            break
        signal_close = float(frame.iloc[i]["close"])
        raw_entry = float(frame.iloc[entry_idx]["open"])
        entry_price = raw_entry + tick_size
        quantity = math.floor(equity / entry_price)
        if quantity <= 0:
            i += 1
            continue

        stop = signal_close * (1.0 - stop_pct / 100.0)
        target = signal_close * (1.0 + target_pct / 100.0)
        exit_idx = entry_idx
        exit_price = float("nan")
        exit_reason = ""
        final_idx = min(entry_idx + max_hold_sessions - 1, len(frame) - 1)
        for j in range(entry_idx, final_idx + 1):
            row = frame.iloc[j]
            session = pd.Timestamp(dates[j])
            if session > last_exit_session_date:
                break
            if float(row["open"]) <= stop:
                exit_idx, exit_price, exit_reason = j, float(row["open"]) - tick_size, "stop_gap"
                break
            if float(row["low"]) <= stop:
                exit_idx, exit_price, exit_reason = j, stop - tick_size, "stop"
                break
            if float(row["open"]) >= target:
                exit_idx, exit_price, exit_reason = j, float(row["open"]) - tick_size, "target_gap"
                break
            if float(row["high"]) >= target:
                exit_idx, exit_price, exit_reason = j, target - tick_size, "target"
                break
            if session >= last_exit_session_date:
                exit_idx, exit_price, exit_reason = j, float(row["close"]) - tick_size, "final_session"
                break
        if not exit_reason:
            exit_idx = min(final_idx, frame.index.get_indexer([last_exit_session_date], method="pad")[0])
            exit_price = float(frame.iloc[exit_idx]["close"]) - tick_size
            exit_reason = "final_session" if dates[exit_idx] >= last_exit_session_date else "time"

        entry_notional = quantity * entry_price
        exit_notional = quantity * exit_price
        commission = (entry_notional + exit_notional) * commission_per_order_pct / 100.0
        net_pnl = exit_notional - entry_notional - commission
        net_return_pct = net_pnl / entry_notional * 100.0
        equity += net_pnl
        trades.append(
            LocalScreenTrade(
                symbol=symbol,
                signal_date=signal_date,
                entry_date=entry_date,
                exit_date=pd.Timestamp(dates[exit_idx]),
                entry_price=round(entry_price, 6),
                exit_price=round(exit_price, 6),
                quantity=quantity,
                net_pnl=round(net_pnl, 6),
                net_return_pct=round(net_return_pct, 6),
                exit_reason=exit_reason,
                equity_after=round(equity, 6),
            )
        )
        # A bracket exit leaves Pine flat before its close calculation, so that
        # session's signal remains eligible. A time exit is issued after Pine's
        # entry block and therefore cannot re-enter from the same close.
        bracket_exit = exit_reason in {"stop_gap", "stop", "target_gap", "target"}
        i = exit_idx if bracket_exit else exit_idx + 1

    return tuple(trades)


def analyze_local_screen(
    strategy: str,
    trades_by_symbol: Mapping[str, Sequence[LocalScreenTrade]],
    *,
    symbols: Iterable[str],
    initial_capital: float = INITIAL_CAPITAL,
) -> dict[str, object]:
    selected = tuple(sorted(symbols))
    trades = tuple(trade for symbol in selected for trade in trades_by_symbol.get(symbol, ()))
    pnls = [trade.net_pnl for trade in trades]
    returns = [trade.net_return_pct for trade in trades]
    gross_profit = sum(value for value in pnls if value > 0)
    gross_loss = abs(sum(value for value in pnls if value < 0))
    profit_factor = gross_profit / gross_loss if gross_loss else (math.inf if gross_profit else 0.0)
    symbol_pnl = {
        symbol: sum(trade.net_pnl for trade in trades_by_symbol.get(symbol, ()))
        for symbol in selected
    }
    total_pnl = sum(symbol_pnl.values())
    positive_fraction = sum(value > 0 for value in symbol_pnl.values()) / len(selected)
    contribution = max(symbol_pnl.values()) / total_pnl if total_pnl > 0 else math.inf
    median_return = median(returns) if returns else 0.0
    worst_drawdown = max(
        (_realized_drawdown(trades_by_symbol.get(symbol, ()), initial_capital) for symbol in selected),
        default=0.0,
    )
    early_pnl = sum(trade.net_pnl for trade in trades if trade.exit_date.year <= 2021)
    late_pnl = sum(trade.net_pnl for trade in trades if trade.exit_date.year >= 2022)
    checks = development_gate_checks(
        closed_trades=len(trades),
        median_return=median_return,
        profit_factor=profit_factor,
        worst_drawdown=worst_drawdown,
        positive_symbol_fraction=positive_fraction,
        early_pnl=early_pnl,
        late_pnl=late_pnl,
        concentration=contribution,
    )
    passed_screen = all(checks.values())
    return {
        "strategy": strategy,
        "phase": "development",
        "source": "Yahoo/current-survivor local parquet; research-only",
        "symbols": len(selected),
        "closed_trades": len(trades),
        "net_profit": round(total_pnl, 2),
        "median_net_return_pct": round(median_return, 4),
        "profit_factor": round(profit_factor, 4) if math.isfinite(profit_factor) else "inf",
        "worst_symbol_realized_drawdown_pct": round(worst_drawdown, 4),
        "positive_symbol_fraction": round(positive_fraction, 4),
        "largest_symbol_profit_contribution": round(contribution, 4) if math.isfinite(contribution) else "inf",
        "net_profit_2019_2021": round(early_pnl, 2),
        "net_profit_2022_2023": round(late_pnl, 2),
        "symbol_net_profit": {key: round(value, 2) for key, value in symbol_pnl.items()},
        "checks": checks,
        # This local reproduction is intentionally one-way: it can reject a
        # weak strategy cheaply, but current-survivor Yahoo data and
        # close-to-close realized drawdown cannot authorize use of the one-use
        # holdout.  A clean local screen therefore still requires the frozen
        # TradingView export (and, later, PIT portfolio validation).
        "verdict": "REQUIRES_TRADINGVIEW_VALIDATION" if passed_screen else "REJECTED",
    }


def run_local_screen(strategy_names: Sequence[str]) -> list[dict[str, object]]:
    ruleset_sha256 = assert_frozen_ruleset()
    catalog = all_strategies()
    symbols = tuple(sorted(EXPECTED_SYMBOLS))
    prices_by_symbol = {symbol: load_prices(symbol) for symbol in symbols}
    validate_price_coverage(prices_by_symbol)
    reports: list[dict[str, object]] = []
    for name in strategy_names:
        if name not in catalog:
            raise ValueError(f"unknown RuleSpec: {name}")
        spec = catalog[name]
        trades_by_symbol: dict[str, tuple[LocalScreenTrade, ...]] = {}
        for symbol in symbols:
            bars = prices_by_symbol[symbol]
            signal = spec["fn"](bars)
            trades_by_symbol[symbol] = simulate_chart(
                bars,
                signal,
                symbol=symbol,
                stop_pct=float(spec["stop_pct"]),
                target_pct=float(spec["target_pct"]),
                max_hold_sessions=int(spec["max_hold_days"]),
            )
        report = analyze_local_screen(name, trades_by_symbol, symbols=symbols)
        report["ruleset_sha256"] = ruleset_sha256
        reports.append(report)
    return reports


def assert_frozen_ruleset(path: Path = STUDIED_RULES_PATH) -> str:
    """Fail if the executable RuleSpecs no longer match the registered screen."""

    records = json.loads(path.read_text(encoding="utf-8"))
    selected = [record for record in records if record["name"] in EXPECTED_RULESPECS]
    payload = json.dumps(selected, sort_keys=True, separators=(",", ":")).encode()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != FROZEN_RULESET_SHA256:
        raise ValueError(
            "studied RuleSpecs changed after experiment registration; "
            "register a new experiment before screening"
        )
    return actual


def validate_price_coverage(prices_by_symbol: Mapping[str, pd.DataFrame]) -> None:
    """Require one complete, common development calendar plus indicator warm-up."""

    if set(prices_by_symbol) != set(EXPECTED_SYMBOLS):
        raise ValueError("price data must cover the complete frozen symbol basket")
    expected: pd.DatetimeIndex | None = None
    for symbol, bars in sorted(prices_by_symbol.items()):
        index = pd.DatetimeIndex(pd.to_datetime(bars.index)).tz_localize(None).sort_values()
        window = index[(index >= WARMUP_START_DATE) & (index <= LAST_EXIT_SESSION_DATE)]
        if len(window) < 252 or window[0] > WARMUP_START_DATE:
            raise ValueError(f"{symbol} lacks the frozen indicator warm-up history")
        if START_DATE not in window or LAST_EXIT_SESSION_DATE not in window:
            raise ValueError(f"{symbol} lacks a frozen development boundary session")
        if expected is None:
            expected = window
        elif not window.equals(expected):
            raise ValueError(f"{symbol} has missing or unexpected development sessions")


EXPECTED_RULESPECS = frozenset(
    {
        "minervini_breakout_volume",
        "minervini_trend_template",
        "gujral_trend_alignment_dual_ma",
        "sadekar_hammer_confirmation",
        "schwager_trend_with_pullback_strength",
    }
)


def _realized_drawdown(trades: Sequence[LocalScreenTrade], initial_capital: float) -> float:
    curve = [initial_capital, *(trade.equity_after for trade in trades)]
    peak = curve[0]
    drawdown = 0.0
    for value in curve:
        peak = max(peak, value)
        drawdown = max(drawdown, (peak - value) / peak * 100.0)
    return drawdown


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategies", nargs="+", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    reports = run_local_screen(args.strategies)
    payload = json.dumps(reports, indent=2, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
