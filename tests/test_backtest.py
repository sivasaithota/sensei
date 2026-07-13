import numpy as np
import pandas as pd
import pytest

from sensei.backtest.engine import run_backtest, walk_forward_split


def make_df(prices: list[float]) -> pd.DataFrame:
    """Synthetic daily bars: open=close of the series, small hi/lo band."""
    p = np.array(prices, dtype=float)
    return pd.DataFrame(
        {"open": p, "high": p * 1.01, "low": p * 0.99, "close": p,
         "volume": np.full(len(p), 1e6)},
        index=pd.bdate_range("2020-01-01", periods=len(p)),
    )


def signal_on_day(day: int):
    def fn(df: pd.DataFrame) -> pd.Series:
        s = pd.Series(False, index=df.index)
        s.iloc[day] = True
        return s
    return fn


def test_entry_is_next_day_open_no_lookahead():
    df = make_df([100] * 10)
    res = run_backtest(df, signal_on_day(3), strategy="t", symbol="X",
                       stop_pct=5, target_pct=10, max_hold_days=5)
    assert res.n == 1
    assert res.trades[0].entry_date == df.index[4]  # signal day 3 → entry day 4


def test_target_exit():
    # price jumps 20% after entry → target (10%) should hit
    df = make_df([100, 100, 100, 120, 120, 120])
    res = run_backtest(df, signal_on_day(1), strategy="t", symbol="X",
                       stop_pct=5, target_pct=10, max_hold_days=5)
    assert res.trades[0].exit_reason == "target"
    assert res.trades[0].ret_pct > 9


def test_stop_exit_conservative():
    # price collapses → stop hit
    df = make_df([100, 100, 100, 80, 80, 80])
    res = run_backtest(df, signal_on_day(1), strategy="t", symbol="X",
                       stop_pct=5, target_pct=10, max_hold_days=5)
    assert res.trades[0].exit_reason == "stop_gap"
    assert res.trades[0].exit == 80.0  # gap loss fills at the open, not the stop
    assert res.trades[0].ret_pct < 0


def test_time_stop():
    df = make_df([100] * 12)
    res = run_backtest(df, signal_on_day(1), strategy="t", symbol="X",
                       stop_pct=50, target_pct=50, max_hold_days=3)
    assert res.trades[0].exit_reason == "time"


def test_no_overlapping_positions():
    def always(df):
        return pd.Series(True, index=df.index)
    df = make_df([100] * 30)
    res = run_backtest(df, always, strategy="t", symbol="X",
                       stop_pct=50, target_pct=50, max_hold_days=5)
    # entries can't overlap: each trade consumes >= max_hold_days
    for a, b in zip(res.trades, res.trades[1:]):
        assert b.entry_date > a.exit_date


def test_walk_forward_split():
    df = make_df([100] * 100)
    train, test = walk_forward_split(df, 0.7)
    assert len(train) == 70 and len(test) == 30
    assert train.index[-1] < test.index[0]
