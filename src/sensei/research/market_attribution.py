"""Prior-session benchmark state and descriptive portfolio attribution."""

from __future__ import annotations

import numpy as np
import pandas as pd


def market_states(benchmark):
    index = benchmark.index
    if (not isinstance(index, pd.DatetimeIndex) or index.has_duplicates or index.hasnans
            or not index.is_monotonic_increasing or index.tz is not None
            or not index.equals(index.normalize()) or not np.isfinite(benchmark.to_numpy(dtype=float)).all()
            or (benchmark <= 0).any()):
        raise ValueError("benchmark must be finite positive levels on an ordered unique daily calendar")
    prior = benchmark.shift(1)
    average = benchmark.rolling(200, min_periods=200).mean().shift(1)
    state = pd.Series("unknown", index=index)
    known = prior.notna() & average.notna()
    state.loc[known & (prior > average)] = "above_sma200"
    state.loc[known & (prior <= average)] = "at_or_below_sma200"
    return pd.DataFrame({"state": state, "prior_close": prior, "prior_sma200": average})


def attribute_market(campaign, benchmark, *, start, end):
    states = market_states(benchmark)
    curve = pd.DataFrame(campaign["equity_curve"])
    if curve.empty:
        raise ValueError("market attribution requires an equity curve")
    dates = pd.DatetimeIndex(curve["session"])
    expected = benchmark.index[(benchmark.index >= pd.Timestamp(start)) & (benchmark.index <= pd.Timestamp(end))]
    if not dates.equals(expected):
        raise ValueError("portfolio calendar must match benchmark sessions")
    equity = curve.equity.to_numpy(dtype=float)
    invested = curve.invested.to_numpy(dtype=float)
    capital = campaign["config"]["capital"]
    if (not np.isfinite(equity).all() or not np.isfinite(invested).all()
            or not np.isfinite(capital) or capital <= 0 or (equity <= 0).any() or (invested < 0).any()):
        raise ValueError("invalid portfolio equity or investment values")
    daily = np.diff(np.r_[capital, equity])
    if (not np.isfinite(campaign["net_pnl"]) or not np.isfinite(campaign["final_equity"])
            or abs(daily.sum() - campaign["net_pnl"]) > .010001
            or abs(equity[-1] - campaign["final_equity"]) > .010001):
        raise ValueError("daily market attribution does not reconcile to campaign")
    daily_rows = []
    for i, stamp in enumerate(dates):
        observed = states.loc[stamp]
        daily_rows.append({"session": str(stamp.date()), "state": observed["state"],
            "prior_close": float(observed["prior_close"]) if pd.notna(observed["prior_close"]) else None,
            "prior_sma200": float(observed["prior_sma200"]) if pd.notna(observed["prior_sma200"]) else None,
            "net_pnl": round(float(daily[i]), 2),
            "end_of_day_utilization_pct": float(invested[i] / equity[i] * 100)})
    groups = {}
    for state in sorted({row["state"] for row in daily_rows}):
        rows = [row for row in daily_rows if row["state"] == state]
        groups[state] = {"sessions": len(rows), "net_pnl": round(sum(r["net_pnl"] for r in rows), 2),
            "mean_end_of_day_utilization_pct": round(float(np.mean([r["end_of_day_utilization_pct"] for r in rows])), 3)}
    cohorts = {}
    for trade in campaign["trades"]:
        entry = pd.Timestamp(trade["entry_date"])
        if entry not in dates:
            raise ValueError("trade entry is outside the campaign calendar")
        state = states.loc[entry, "state"]
        group = cohorts.setdefault(state, {"trades": 0, "net_pnl": 0., "costs": 0., "stop_or_gap_stop_trades": 0})
        group["trades"] += 1
        group["net_pnl"] += trade["net_pnl"]
        group["costs"] += trade["costs"]
        group["stop_or_gap_stop_trades"] += trade["exit_reason"] in {"stop", "stop_gap"}
    for group in cohorts.values():
        group["net_pnl"], group["costs"] = round(group["net_pnl"], 2), round(group["costs"], 2)
    return {"entry_cohorts": cohorts, "daily_states": groups, "sessions": daily_rows,
        "definitions": {"state": "prior benchmark close versus mean of prior 200 benchmark closes; equality belongs to at_or_below",
            "entry_cohorts": "complete trade P&L attributed to state at entry, even if exited in another state",
            "daily_states": "actual daily marked P&L and mean end-of-day utilization, grouped by state known before each session",
            "limitation": "neither view is a backtest of a market filter; cash, positions, exits and rankings would change"}}
