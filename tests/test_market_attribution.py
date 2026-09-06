from copy import deepcopy
import json

import numpy as np
import pandas as pd
import pytest

from sensei.research.market_attribution import market_states, attribute_market


def benchmark():
    return pd.Series(np.arange(210) + 100., index=pd.bdate_range("2024-01-01", periods=210))


def test_exact_warmup_and_current_future_prices_cannot_affect_state():
    levels = benchmark()
    states = market_states(levels)
    assert states.iloc[199]["state"] == "unknown"
    assert states.iloc[200]["state"] == "above_sma200"
    assert states.iloc[200]["prior_close"] == 299
    assert states.iloc[200]["prior_sma200"] == 199.5
    changed = levels.copy(); changed.iloc[200:] = 1.
    assert market_states(changed).iloc[:201].equals(states.iloc[:201])
    assert market_states(levels.iloc[:201]).equals(states.iloc[:201])
    assert market_states(pd.Series(100., index=levels.index)).iloc[200]["state"] == "at_or_below_sma200"


@pytest.mark.parametrize("bad", ["duplicate", "unordered", "nonfinite", "zero"])
def test_invalid_benchmark_cannot_be_classified(bad):
    levels = benchmark()
    if bad == "duplicate": levels = pd.concat([levels, levels.iloc[-1:]])
    if bad == "unordered": levels = levels.iloc[::-1]
    if bad == "nonfinite": levels.iloc[20] = np.nan
    if bad == "zero": levels.iloc[20] = 0
    with pytest.raises(ValueError): market_states(levels)


def campaign(levels):
    sessions = [str(d.date()) for d in levels.index[200:203]]
    return {"config": {"capital": 100.}, "net_pnl": 5., "final_equity": 105.,
        "equity_curve": [{"session": s, "equity": e, "invested": 50., "open_positions": 1}
            for s, e in zip(sessions, [110., 90., 105.])],
        "trades": [{"entry_date": sessions[0], "exit_date": sessions[2], "net_pnl": 5.,
            "costs": 2., "exit_reason": "time"}]}


def test_entry_cohort_does_not_reclassify_holding_when_daily_state_changes():
    levels = benchmark(); levels.iloc[200] = 1
    c = campaign(levels)
    result = attribute_market(c, levels, start=benchmark().index[200], end=benchmark().index[202])
    assert result["entry_cohorts"]["above_sma200"]["net_pnl"] == 5
    assert result["entry_cohorts"]["above_sma200"]["trades"] == 1
    assert result["daily_states"]["above_sma200"]["net_pnl"] == 25
    assert result["daily_states"]["at_or_below_sma200"]["net_pnl"] == -20
    assert sum(g["sessions"] for g in result["daily_states"].values()) == 3
    assert c == campaign(levels)


def test_daily_pnl_must_reconcile_and_calendar_must_match():
    levels = benchmark()
    for field in ("net_pnl", "interior", "first", "last"):
        c = deepcopy(campaign(levels))
        if field == "net_pnl": c["net_pnl"] = 15.
        else: c["equity_curve"].pop({"interior": 1, "first": 0, "last": -1}[field])
        with pytest.raises(ValueError): attribute_market(c, levels, start=benchmark().index[200], end=benchmark().index[202])


def test_insufficient_benchmark_history_stays_unknown_and_serializable():
    levels = benchmark()
    result = attribute_market(campaign(levels), levels.iloc[190:], start=levels.index[200], end=levels.index[202])
    assert result["entry_cohorts"]["unknown"]["trades"] == 1
    assert result["daily_states"]["unknown"]["sessions"] == 3
    assert all(row["prior_sma200"] is None for row in result["sessions"])
    json.dumps(result, allow_nan=False)
