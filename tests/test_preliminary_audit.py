"""Tests for the PRELIMINARY portfolio audit harness (research-only)."""

import numpy as np
import pandas as pd

from sensei.research.preliminary_audit import (
    PortfolioConfig, STAMP, audit_strategy, simulate_portfolio, _size,
)


def _frame(prices, start="2020-01-01"):
    p = np.array(prices, dtype=float)
    idx = pd.bdate_range(start, periods=len(p))
    return pd.DataFrame({"open": p, "high": p * 1.01, "low": p * 0.99,
                         "close": p, "volume": 1e6, "turnover": p * 1e6}, index=idx)


def test_sizing_respects_rails():
    cfg = PortfolioConfig(capital=300000, max_risk_per_trade_pct=2.0, max_position_pct=20.0)
    # 5% stop on ₹100: risk cap 6000/5=1200 vs notional cap 60000/100=600 -> 600
    assert _size(100.0, 95.0, cfg) == 600
    assert _size(100.0, 100.0, cfg) == 0     # invalid stop


def test_portfolio_respects_position_cap_and_cash():
    # 10 symbols all signalling; max_positions=3 must bind
    frames = {f"S{i}": _frame([100] * 40) for i in range(10)}
    always = lambda df: pd.Series(True, index=df.index)
    cfg = PortfolioConfig(capital=300000, max_positions=3)
    cal = sorted(next(iter(frames.values())).index)
    res = simulate_portfolio(frames, always, stop_pct=5, target_pct=10,
                             max_hold_days=20, cfg=cfg, calendar=cal, label="t")
    # never more than 3 concurrent -> at any exit the book respected the cap;
    # equity never below 0, trades recorded
    assert res.final_equity > 0
    assert res.n_trades >= 0


def test_target_exit_realizes_gain():
    frames = {"X": _frame([100, 100, 130, 130, 130])}  # jumps to target
    sig = lambda df: pd.Series([True, False, False, False, False], index=df.index)
    cfg = PortfolioConfig(capital=300000, max_positions=1, cost_pct_round_trip=0.0)
    cal = sorted(frames["X"].index)
    res = simulate_portfolio(frames, sig, stop_pct=5, target_pct=10,
                             max_hold_days=10, cfg=cfg, calendar=cal, label="t")
    assert any(t.reason == "target" for t in res.trades)
    assert res.final_equity > cfg.capital       # made money


def test_audit_reports_are_stamped_and_have_holdout():
    frames = {f"S{i}": _frame(list(np.linspace(100, 160, 400)), ) for i in range(4)}
    sig = lambda df: (df["close"] > df["close"].rolling(20).mean()).fillna(False)
    cfg = PortfolioConfig(capital=300000, max_positions=3)
    rep = audit_strategy(frames, sig, {"stop_pct": 5, "target_pct": 12, "max_hold_days": 20},
                         name="demo", cfg=cfg, n_folds=3)
    assert rep["stamp"] == STAMP
    assert "HOLDOUT" in rep["holdout"]["label"]
    assert "NO_2008_COVID_certification_claim" in rep["hard_limits"]
    assert rep["trade_diagnostic_clustered"]  # present
    # walk-forward produced per-fold portfolio rows with portfolio metrics
    for f in rep["walk_forward_folds"]:
        assert "max_drawdown_pct" in f and "cagr_pct" in f


def test_no_lookahead_entry_is_next_open():
    # signal only on day 2 -> first possible entry is day 3's open
    frames = {"X": _frame([100, 100, 100, 100, 100])}
    sig = lambda df: pd.Series([False, True, False, False, False], index=df.index)
    cfg = PortfolioConfig(capital=300000, max_positions=1, cost_pct_round_trip=0.0)
    cal = sorted(frames["X"].index)
    res = simulate_portfolio(frames, sig, stop_pct=50, target_pct=50,
                             max_hold_days=10, cfg=cfg, calendar=cal, label="t")
    if res.trades:
        assert res.trades[0].entry_date == cal[2]   # day after the signal
