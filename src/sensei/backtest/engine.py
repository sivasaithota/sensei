"""Backtest engine for swing/delivery signals (PRD §4.2, §8).

Event-per-signal simulator over daily bars. Deliberately simple and
honest rather than clever:

- Entry at next day's open after a signal (no look-ahead).
- Stop-loss and target checked intraday via the day's low/high;
  if both hit the same day, the stop is assumed to hit first
  (conservative).
- Time-stop exits at close after `max_hold_days`.
- Costs modelled as a flat round-trip percentage (delivery brokerage
  is zero at Zerodha; STT + slippage dominate).

Strategies are functions: (ohlcv DataFrame) -> boolean Series of
entry signals. The Playbook (playbook.py) stores the vetted results.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

SignalFn = Callable[[pd.DataFrame], pd.Series]

ROUND_TRIP_COST_PCT = 0.25  # STT, charges, slippage — conservative for delivery


@dataclass
class Trade:
    symbol: str
    entry_date: pd.Timestamp
    entry: float
    exit_date: pd.Timestamp
    exit: float
    exit_reason: str  # "stop" | "target" | "time"
    cost_pct: float = ROUND_TRIP_COST_PCT

    @property
    def ret_pct(self) -> float:
        return (self.exit / self.entry - 1) * 100 - self.cost_pct


@dataclass
class BacktestResult:
    strategy: str
    symbol: str
    trades: list[Trade]

    @property
    def n(self) -> int:
        return len(self.trades)

    @property
    def hit_rate(self) -> float:
        if not self.trades:
            return 0.0
        return sum(t.ret_pct > 0 for t in self.trades) / self.n

    @property
    def avg_ret_pct(self) -> float:
        if not self.trades:
            return 0.0
        return float(np.mean([t.ret_pct for t in self.trades]))

    @property
    def expectancy_pct(self) -> float:
        return self.avg_ret_pct

    @property
    def max_drawdown_pct(self) -> float:
        """Max drawdown of the compounded per-trade equity curve."""
        if not self.trades:
            return 0.0
        eq = np.cumprod([1 + t.ret_pct / 100 for t in self.trades])
        peak = np.maximum.accumulate(eq)
        return float(((peak - eq) / peak).max() * 100)

    def stats(self) -> dict:
        return {
            "strategy": self.strategy,
            "symbol": self.symbol,
            "trades": self.n,
            "hit_rate": round(self.hit_rate, 3),
            "expectancy_pct": round(self.expectancy_pct, 3),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
        }


def run_backtest(
    df: pd.DataFrame,
    signal_fn: SignalFn,
    *,
    strategy: str,
    symbol: str,
    stop_pct: float,
    target_pct: float,
    max_hold_days: int,
    cost_pct: float = ROUND_TRIP_COST_PCT,
) -> BacktestResult:
    """Simulate long-only swing trades on daily bars. One position at a time."""
    signals = signal_fn(df).fillna(False)
    dates = df.index
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))

    trades: list[Trade] = []
    i = 0
    n = len(df)
    sig = signals.to_numpy()

    while i < n - 1:
        if not sig[i]:
            i += 1
            continue
        # enter at next day's open
        e_idx = i + 1
        entry = o[e_idx]
        if not np.isfinite(entry) or entry <= 0:
            i += 1
            continue
        stop = entry * (1 - stop_pct / 100)
        target = entry * (1 + target_pct / 100)
        exit_price, exit_idx, reason = None, None, None

        for j in range(e_idx, min(e_idx + max_hold_days, n)):
            if o[j] <= stop:
                # Stops execute at the first available price after a gap.
                exit_price, exit_idx, reason = o[j], j, "stop_gap"
                break
            if l[j] <= stop:  # stop first — conservative
                exit_price, exit_idx, reason = stop, j, "stop"
                break
            if h[j] >= target:
                exit_price, exit_idx, reason = target, j, "target"
                break
        if exit_price is None:
            exit_idx = min(e_idx + max_hold_days, n) - 1
            exit_price, reason = c[exit_idx], "time"

        trades.append(Trade(symbol, dates[e_idx], float(entry),
                            dates[exit_idx], float(exit_price), reason,
                            cost_pct=cost_pct))
        i = exit_idx + 1  # no overlapping positions per symbol

    return BacktestResult(strategy=strategy, symbol=symbol, trades=trades)


def walk_forward_split(df: pd.DataFrame, train_frac: float = 0.7):
    """Simple out-of-sample split (PRD §12: overfitting mitigation)."""
    cut = int(len(df) * train_frac)
    return df.iloc[:cut], df.iloc[cut:]
