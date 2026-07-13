"""RuleSpec — a constrained DSL for entry rules extracted from literature.

The Scholar agent (agents/scholar.py) may only express strategy ideas
in this grammar. A deterministic compiler turns a spec into a signal
function for the backtester. The LLM never emits executable code —
it emits data, validated by pydantic, compiled here.

Indicator grammar (all computed on daily OHLCV):
    close | open | high | low | volume
    sma_N          — N-day simple moving average of close
    vol_sma_N      — N-day SMA of volume
    highest_N      — highest close of the PRIOR N days (shifted 1, no look-ahead)
    lowest_N       — lowest close of the prior N days (shifted 1)
    rsi_N          — N-day RSI of close
    ret_N          — % return over the last N days
    high_52w       — prior 250-day high of close (shifted 1)

A condition compares  left OP right * factor  (right may be a constant).
Conditions are AND-ed. Example — "close breaks the prior 55-day high on
1.5x average volume, in a long-term uptrend":

    conditions:
      - {left: close,  op: ">", right: highest_55}
      - {left: volume, op: ">", right: vol_sma_20, factor: 1.5}
      - {left: close,  op: ">", right: sma_200}
"""

from __future__ import annotations

import re
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

_INDICATOR_RE = re.compile(
    r"^(close|open|high|low|volume|sma_\d+|vol_sma_\d+|highest_\d+|"
    r"lowest_\d+|rsi_\d+|ret_\d+|high_52w|"
    r"bullish_engulfing|hammer|strong_close|inside_day_breakout|range_ratio_\d+)$")


class Condition(BaseModel):
    model_config = ConfigDict(frozen=True)

    left: str
    op: Literal[">", "<", ">=", "<="]
    right: str | float
    factor: float = 1.0

    @field_validator("left")
    @classmethod
    def _v_left(cls, v):
        if not _INDICATOR_RE.match(v):
            raise ValueError(f"unknown indicator: {v}")
        return v

    @field_validator("right")
    @classmethod
    def _v_right(cls, v):
        if isinstance(v, str) and not _INDICATOR_RE.match(v):
            raise ValueError(f"unknown indicator: {v}")
        return v


class RuleSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(pattern=r"^[a-z0-9_]{3,50}$")
    source: str = Field(description="Book/author/URL the principle came from")
    principle: str = Field(description="The principle in the source's own terms")
    conditions: tuple[Condition, ...] = Field(min_length=1, max_length=8)
    stop_pct: float = Field(ge=1.0, le=15.0)
    target_pct: float = Field(ge=2.0, le=40.0)
    max_hold_days: int = Field(ge=3, le=120)


def _indicator(df: pd.DataFrame, name: str) -> pd.Series:
    if name in ("close", "open", "high", "low", "volume"):
        return df[name]

    # ---- candlestick patterns: deterministic detectors, 1.0/0.0 series.
    # Compare with `> 0.5` to require, `< 0.5` to exclude.
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    rng = (h - l).replace(0, 1e-9)
    if name == "bullish_engulfing":
        # today's up-body engulfs yesterday's down-body
        return ((c > o) & (c.shift(1) < o.shift(1))
                & (o <= c.shift(1)) & (c >= o.shift(1))).astype(float)
    if name == "hammer":
        # small body near the top, long lower shadow (>= 2x body), after a dip
        body = (c - o).abs()
        lower = pd.concat([o, c], axis=1).min(axis=1) - l
        near_top = (h - pd.concat([o, c], axis=1).max(axis=1)) <= rng * 0.25
        return ((lower >= body * 2) & near_top
                & (c.shift(1) < c.shift(4))).astype(float)
    if name == "strong_close":
        # close in the top quartile of the day's range
        return ((c - l) / rng >= 0.75).astype(float)
    if name == "inside_day_breakout":
        # yesterday inside the day before; today closes above yesterday's high
        inside = (h.shift(1) <= h.shift(2)) & (l.shift(1) >= l.shift(2))
        return (inside & (c > h.shift(1))).astype(float)

    kind, _, n = name.rpartition("_")
    if name == "high_52w":
        return df["close"].rolling(250).max().shift(1)
    if kind == "range_ratio":
        # today's range vs its N-day average — "exceptional candle" fuel
        return rng / rng.rolling(int(n)).mean().replace(0, 1e-9)
    n = int(n)
    if kind == "sma":
        return df["close"].rolling(n).mean()
    if kind == "vol_sma":
        return df["volume"].rolling(n).mean()
    if kind == "highest":
        return df["close"].rolling(n).max().shift(1)
    if kind == "lowest":
        return df["close"].rolling(n).min().shift(1)
    if kind == "ret":
        return (df["close"] / df["close"].shift(n) - 1) * 100
    if kind == "rsi":
        delta = df["close"].diff()
        gain = delta.clip(lower=0).rolling(n).mean()
        loss = (-delta.clip(upper=0)).rolling(n).mean()
        return 100 - 100 / (1 + gain / loss.replace(0, 1e-9))
    raise ValueError(f"unknown indicator: {name}")


def compile_spec(spec: RuleSpec):
    """RuleSpec -> SignalFn for the backtest engine."""
    def signal(df: pd.DataFrame) -> pd.Series:
        mask = pd.Series(True, index=df.index)
        for c in spec.conditions:
            left = _indicator(df, c.left)
            right = (_indicator(df, c.right) * c.factor
                     if isinstance(c.right, str) else c.right * c.factor)
            if c.op == ">":
                mask &= left > right
            elif c.op == "<":
                mask &= left < right
            elif c.op == ">=":
                mask &= left >= right
            else:
                mask &= left <= right
        return mask.fillna(False)
    signal.__name__ = spec.name
    return signal
