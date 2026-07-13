"""Daily-bar simulation used only by the Research Examiner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

import numpy as np
import pandas as pd

from sensei.backtest.rulespec import RuleSpec
from sensei.research.models import EvaluationFold, EvidenceSummary


@dataclass(frozen=True)
class ResearchTrade:
    symbol: str
    ret_pct: float
    exit_reason: Literal["stop", "target", "time"]


@dataclass(frozen=True)
class FoldSimulation:
    trades: tuple[ResearchTrade, ...]
    censored_trades: int


def simulate_fold(
    symbol: str,
    frame: pd.DataFrame,
    signals: pd.Series,
    fold: EvaluationFold,
    strategy: RuleSpec,
    cost_pct: float,
) -> FoldSimulation:
    dates = frame.index
    opens = frame["open"].to_numpy(dtype=float)
    highs = frame["high"].to_numpy(dtype=float)
    lows = frame["low"].to_numpy(dtype=float)
    closes = frame["close"].to_numpy(dtype=float)
    signal_values = signals.fillna(False).to_numpy(dtype=bool)
    trades: list[ResearchTrade] = []
    censored_trades = 0

    i = 0
    while i < len(frame) - 1:
        signal_day = dates[i].date()
        if not signal_values[i] or signal_day < fold.start or signal_day > fold.end:
            i += 1
            continue

        entry_index = i + 1
        if dates[entry_index].date() > fold.end:
            censored_trades += 1
            break
        entry = opens[entry_index]
        stop = entry * (1 - strategy.stop_pct / 100)
        target = entry * (1 + strategy.target_pct / 100)
        last_hold_index = entry_index + strategy.max_hold_days - 1
        last_available_index = min(last_hold_index, len(frame) - 1)
        exit_index: int | None = None
        exit_price: float | None = None
        exit_reason: Literal["stop", "target", "time"] | None = None

        for j in range(entry_index, last_available_index + 1):
            if dates[j].date() > fold.end:
                break
            if opens[j] <= stop:
                exit_index, exit_price, exit_reason = j, opens[j], "stop"
                break
            if opens[j] >= target:
                exit_index, exit_price, exit_reason = j, target, "target"
                break
            if lows[j] <= stop:
                exit_index, exit_price, exit_reason = j, stop, "stop"
                break
            if highs[j] >= target:
                exit_index, exit_price, exit_reason = j, target, "target"
                break

        if exit_index is None:
            if last_hold_index >= len(frame) or dates[last_hold_index].date() > fold.end:
                censored_trades += 1
                break
            exit_index, exit_price, exit_reason = (
                last_hold_index,
                closes[last_hold_index],
                "time",
            )

        ret_pct = (float(exit_price) / float(entry) - 1) * 100 - cost_pct
        trades.append(
            ResearchTrade(symbol=symbol, ret_pct=ret_pct, exit_reason=exit_reason)
        )
        i = exit_index + 1

    return FoldSimulation(trades=tuple(trades), censored_trades=censored_trades)


def summarize(trades: Sequence[ResearchTrade]) -> EvidenceSummary:
    if not trades:
        return EvidenceSummary(
            trades=0,
            symbols_with_trades=0,
            hit_rate=None,
            expectancy_pct=None,
            avg_win_pct=None,
            avg_loss_pct=None,
            worst_trade_pct=None,
            stop_exits=0,
            target_exits=0,
            time_exits=0,
        )
    returns = np.array([trade.ret_pct for trade in trades])
    wins = returns[returns > 0]
    losses = returns[returns <= 0]
    return EvidenceSummary(
        trades=len(trades),
        symbols_with_trades=len({trade.symbol for trade in trades}),
        hit_rate=round(float(np.mean(returns > 0)), 6),
        expectancy_pct=round(float(np.mean(returns)), 6),
        avg_win_pct=round(float(np.mean(wins)), 6) if len(wins) else None,
        avg_loss_pct=round(float(np.mean(losses)), 6) if len(losses) else None,
        worst_trade_pct=round(float(np.min(returns)), 6),
        stop_exits=sum(trade.exit_reason == "stop" for trade in trades),
        target_exits=sum(trade.exit_reason == "target" for trade in trades),
        time_exits=sum(trade.exit_reason == "time" for trade in trades),
    )
