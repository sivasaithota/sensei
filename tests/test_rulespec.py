import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from sensei.backtest.rulespec import Condition, RuleSpec, compile_spec


def make_df(n=300, price=100.0, vol=1e6):
    p = np.full(n, price)
    return pd.DataFrame({"open": p, "high": p * 1.01, "low": p * 0.99,
                         "close": p, "volume": np.full(n, vol)},
                        index=pd.bdate_range("2020-01-01", periods=n))


def spec(conditions, **over):
    base = dict(name="test_rule", source="test", principle="test",
                conditions=conditions, stop_pct=5.0, target_pct=10.0,
                max_hold_days=20)
    base.update(over)
    return RuleSpec.model_validate(base)


def test_breakout_rule_fires_correctly():
    s = spec([{"left": "close", "op": ">", "right": "highest_55"},
              {"left": "volume", "op": ">", "right": "vol_sma_20", "factor": 1.5}])
    df = make_df(300)
    # day 250: price and volume spike
    df.iloc[250, df.columns.get_loc("close")] = 120.0
    df.iloc[250, df.columns.get_loc("volume")] = 2e6
    sig = compile_spec(s)(df)
    assert bool(sig.iloc[250])
    assert not sig.iloc[249] and not sig.iloc[251]


def test_constant_comparison():
    s = spec([{"left": "rsi_14", "op": "<", "right": 30.0}])
    df = make_df(100)
    rising = np.linspace(100, 150, 100)   # steadily rising → RSI near 100
    for col in ("open", "high", "low", "close"):
        df[col] = rising
    assert compile_spec(s)(df).sum() == 0    # oversold rule must not fire
    falling = np.linspace(150, 100, 100)  # steadily falling → RSI near 0
    for col in ("open", "high", "low", "close"):
        df[col] = falling
    assert compile_spec(s)(df).iloc[-1]      # and must fire when truly oversold


def test_sma_uptrend_condition():
    s = spec([{"left": "sma_50", "op": ">", "right": "sma_200"}])
    up = np.linspace(100, 200, 300)
    df = make_df(300)
    for col in ("open", "high", "low", "close"):
        df[col] = up
    sig = compile_spec(s)(df)
    assert bool(sig.iloc[-1])          # rising series → golden cross true at end
    assert not bool(sig.iloc[100])     # not before 200 bars of history


def test_unknown_indicator_rejected():
    with pytest.raises(ValidationError):
        spec([{"left": "macd_9", "op": ">", "right": 0}])
    with pytest.raises(ValidationError):
        spec([{"left": "close", "op": ">", "right": "bollinger_20"}])


def test_param_bounds_enforced():
    with pytest.raises(ValidationError):
        spec([{"left": "close", "op": ">", "right": 1}], stop_pct=50.0)
    with pytest.raises(ValidationError):
        spec([{"left": "close", "op": ">", "right": 1}], max_hold_days=365)


def test_bullish_engulfing_detector():
    s = spec([{"left": "bullish_engulfing", "op": ">", "right": 0.5}])
    df = make_df(20)
    # day 10: red candle; day 11: green body engulfing it
    df.iloc[10, df.columns.get_loc("open")] = 102.0
    df.iloc[10, df.columns.get_loc("close")] = 99.0
    df.iloc[11, df.columns.get_loc("open")] = 98.5
    df.iloc[11, df.columns.get_loc("close")] = 103.0
    sig = compile_spec(s)(df)
    assert bool(sig.iloc[11]) and not bool(sig.iloc[10])


def test_strong_close_detector():
    s = spec([{"left": "strong_close", "op": ">", "right": 0.5}])
    df = make_df(10)
    df.iloc[5, df.columns.get_loc("low")] = 95.0
    df.iloc[5, df.columns.get_loc("high")] = 101.0
    df.iloc[5, df.columns.get_loc("close")] = 100.5   # top quartile of 95-101
    df.iloc[6, df.columns.get_loc("low")] = 95.0
    df.iloc[6, df.columns.get_loc("high")] = 101.0
    df.iloc[6, df.columns.get_loc("close")] = 96.0    # bottom of range
    sig = compile_spec(s)(df)
    assert bool(sig.iloc[5]) and not bool(sig.iloc[6])


def test_range_ratio():
    s = spec([{"left": "range_ratio_20", "op": ">", "right": 2.0}])
    df = make_df(50)
    df.iloc[40, df.columns.get_loc("high")] = 110.0   # huge range day vs 2% avg
    df.iloc[40, df.columns.get_loc("low")] = 95.0
    sig = compile_spec(s)(df)
    assert bool(sig.iloc[40]) and not bool(sig.iloc[39])


def test_no_lookahead_in_highest():
    """highest_N must be the PRIOR N days — today's own high can't confirm itself."""
    s = spec([{"left": "close", "op": ">", "right": "highest_10"}])
    df = make_df(50)
    df.iloc[30, df.columns.get_loc("close")] = 150.0   # single spike day
    sig = compile_spec(s)(df)
    assert bool(sig.iloc[30])   # breaks the prior 10-day high (100)
    # next day back at 100: prior 10-day high now includes the 150 spike
    assert not bool(sig.iloc[31])
