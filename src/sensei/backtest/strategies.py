"""Seed strategy library — starting hypotheses for the Playbook.

Each is a SignalFn: (daily OHLCV) -> boolean entry Series. These are
hypotheses, not truths: nothing here is live-tradable until it passes
backtest thresholds (playbook.py) on in-sample AND out-of-sample data.
"""

from __future__ import annotations

import pandas as pd


def momentum_breakout_55(df: pd.DataFrame) -> pd.Series:
    """Close breaks above the prior 55-day high with above-average volume."""
    prior_high = df["close"].rolling(55).max().shift(1)
    vol_ok = df["volume"] > df["volume"].rolling(20).mean() * 1.5
    return (df["close"] > prior_high) & vol_ok


def pullback_to_50dma(df: pd.DataFrame) -> pd.Series:
    """Uptrend (50>200 DMA), price pulls back to touch the 50 DMA then closes up."""
    ma50 = df["close"].rolling(50).mean()
    ma200 = df["close"].rolling(200).mean()
    uptrend = ma50 > ma200
    touched = df["low"] <= ma50
    closed_up = df["close"] > df["open"]
    return uptrend & touched & closed_up


def mean_reversion_rsi(df: pd.DataFrame) -> pd.Series:
    """RSI(2) < 10 while above the 200 DMA — classic short-term oversold bounce."""
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(2).mean()
    loss = (-delta.clip(upper=0)).rolling(2).mean()
    rsi = 100 - 100 / (1 + gain / loss.replace(0, 1e-9))
    above_trend = df["close"] > df["close"].rolling(200).mean()
    return (rsi < 10) & above_trend


def gap_down_reversal(df: pd.DataFrame) -> pd.Series:
    """Gap down >2% in an uptrend that recovers to close above the open."""
    gap = df["open"] / df["close"].shift(1) - 1
    uptrend = df["close"] > df["close"].rolling(100).mean()
    recovered = df["close"] > df["open"]
    return (gap < -0.02) & uptrend & recovered


def high_tight_consolidation(df: pd.DataFrame) -> pd.Series:
    """Within 5% of 52w high after a >30% run-up in 6 months, range tightening."""
    high_52w = df["high"].rolling(250).max()
    near_high = df["close"] >= high_52w * 0.95
    runup = df["close"] / df["close"].shift(125) - 1 > 0.30
    rng = (df["high"] - df["low"]) / df["close"]
    tightening = rng.rolling(10).mean() < rng.rolling(50).mean() * 0.7
    return near_high & runup & tightening


SEED_STRATEGIES = {
    "momentum_breakout_55": dict(fn=momentum_breakout_55, stop_pct=5.0,
                                 target_pct=12.0, max_hold_days=30),
    "pullback_to_50dma": dict(fn=pullback_to_50dma, stop_pct=4.0,
                              target_pct=10.0, max_hold_days=25),
    "mean_reversion_rsi": dict(fn=mean_reversion_rsi, stop_pct=4.0,
                               target_pct=6.0, max_hold_days=10),
    "gap_down_reversal": dict(fn=gap_down_reversal, stop_pct=3.5,
                              target_pct=8.0, max_hold_days=15),
    "high_tight_consolidation": dict(fn=high_tight_consolidation, stop_pct=6.0,
                                     target_pct=15.0, max_hold_days=40),
}
