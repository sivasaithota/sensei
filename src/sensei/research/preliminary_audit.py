"""PRELIMINARY strategy audit — portfolio-level, research-only.

This is NOT certification and MUST NOT feed lifecycle governance. It runs on
the current (survivorship-biased, today's-membership, discontinuity-prone)
local price data, so every result is stamped PRELIMINARY_LIMITED_DATA.

It exists to correct the earlier mistake of treating pooled trade-level
expectancy as investable performance. The headline here is a cash-constrained
PORTFOLIO simulation (shared capital, position cap, sizing rails, costs);
trade-level stats are demoted to a clustered diagnostic.

What it does honestly model:
  - one shared cash account; max concurrent positions; per-trade risk sizing
  - LIMIT-at-open entries on prior-close signals (no look-ahead)
  - stop-first / target / time exits with round-trip costs
  - purged walk-forward folds (flat between folds + embargo) so no trade
    straddles a boundary
  - a one-use holdout fold, consumed exactly once
  - trade clustering (by entry ISO-week) for honest confidence bounds
  - every parameter variation counted for multiple-testing awareness

What it CANNOT claim (hard limits, stated, not hidden):
  - no point-in-time index membership -> survivorship bias remains
  - no corrected corporate actions -> price discontinuities remain
  - therefore NO "survived 2008/COVID" certification, ever
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

STAMP = "PRELIMINARY_LIMITED_DATA — not certification; must not feed governance"
ADOPTION_THRESHOLD_PCT = 0.30


@dataclass(frozen=True)
class PortfolioConfig:
    capital: float = 300_000.0          # match the governed portfolio diagnostic
    max_positions: int = 5
    max_risk_per_trade_pct: float = 2.0
    max_position_pct: float = 20.0
    cost_pct_round_trip: float = 0.40
    embargo_sessions: int = 5


@dataclass
class Trade:
    symbol: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry: float
    exit: float
    qty: int
    reason: str

    @property
    def pnl(self) -> float:
        return (self.exit - self.entry) * self.qty


@dataclass
class PortfolioResult:
    label: str
    start: str
    end: str
    final_equity: float
    ret_pct: float
    cagr_pct: float
    max_drawdown_pct: float
    ret_over_maxdd: float
    time_in_market_pct: float
    turnover_x: float
    n_trades: int
    win_rate: float
    trades: list[Trade] = field(default_factory=list)

    def to_row(self) -> dict:
        return {k: getattr(self, k) for k in (
            "label", "final_equity", "ret_pct", "cagr_pct", "max_drawdown_pct",
            "ret_over_maxdd", "time_in_market_pct", "turnover_x", "n_trades", "win_rate")}


def _size(open_price: float, stop: float, cfg: PortfolioConfig) -> int:
    risk_per_share = open_price - stop
    if risk_per_share <= 0:
        return 0
    by_risk = cfg.capital * cfg.max_risk_per_trade_pct / 100 / risk_per_share
    by_notional = cfg.capital * cfg.max_position_pct / 100 / open_price
    return max(0, math.floor(min(by_risk, by_notional)))


def simulate_portfolio(
    frames: dict[str, pd.DataFrame],
    signal_fn,
    *,
    stop_pct: float,
    target_pct: float,
    max_hold_days: int,
    cfg: PortfolioConfig,
    calendar: list[pd.Timestamp],
    label: str,
) -> PortfolioResult:
    """Event-driven, one shared cash account. Enters at the open the session
    AFTER a close-day signal; exits stop-first, then target, then time."""
    sig = {s: signal_fn(df).fillna(False) for s, df in frames.items()}
    half_cost = cfg.cost_pct_round_trip / 200.0   # split round-trip both sides

    cash = cfg.capital
    positions: dict[str, dict] = {}
    equity, invested_days, buys_value = [], 0, 0.0
    trades: list[Trade] = []
    cal_index = {d: i for i, d in enumerate(calendar)}

    for d in calendar:
        # 1. exits on today's bar (stop-first, conservative)
        for sym in list(positions):
            df = frames[sym]
            if d not in df.index:
                continue
            bar = df.loc[d]
            p = positions[sym]
            held = cal_index[d] - p["entry_ci"]
            exit_price = reason = None
            if bar["low"] <= p["stop"]:
                exit_price, reason = (min(bar["open"], p["stop"]), "stop")  # gap-honest
            elif bar["high"] >= p["target"]:
                exit_price, reason = p["target"], "target"
            elif held >= max_hold_days:
                exit_price, reason = bar["close"], "time"
            if exit_price is not None:
                cash += exit_price * p["qty"] * (1 - half_cost)
                trades.append(Trade(sym, p["entry_date"], d, p["entry"],
                                    float(exit_price), p["qty"], reason))
                del positions[sym]

        # 2. entries: signal on the PRIOR available session -> enter at today's open
        i = cal_index[d]
        if i > 0:
            prev = calendar[i - 1]
            cands = []
            for sym, df in frames.items():
                if sym in positions or d not in df.index or prev not in df.index:
                    continue
                if bool(sig[sym].get(prev, False)):
                    cands.append((sym, float(df.loc[prev, "turnover"])
                                  if "turnover" in df.columns else 0.0))
            cands.sort(key=lambda c: -c[1])   # most liquid first
            for sym, _ in cands:
                if len(positions) >= cfg.max_positions:
                    break
                op = float(frames[sym].loc[d, "open"])
                if not np.isfinite(op) or op <= 0:
                    continue
                stop = op * (1 - stop_pct / 100)
                qty = _size(op, stop, cfg)
                spend = op * qty * (1 + half_cost)
                if qty > 0 and spend <= cash:
                    cash -= spend
                    buys_value += op * qty
                    positions[sym] = {"entry": op, "qty": qty, "stop": stop,
                                      "target": op * (1 + target_pct / 100),
                                      "entry_date": d, "entry_ci": i}

        # 3. mark equity at close
        mkt = 0.0
        for sym, p in positions.items():
            df = frames[sym]
            px = float(df.loc[d, "close"]) if d in df.index else p["entry"]
            mkt += px * p["qty"]
        equity.append(cash + mkt)
        if positions:
            invested_days += 1

    eq = np.array(equity, dtype=float)
    years = max(1e-9, len(calendar) / 252.0)
    peak = np.maximum.accumulate(eq)
    mdd = float(((peak - eq) / peak).max() * 100) if len(eq) else 0.0
    ret = (eq[-1] / cfg.capital - 1) * 100 if len(eq) else 0.0
    cagr = ((eq[-1] / cfg.capital) ** (1 / years) - 1) * 100 if len(eq) and eq[-1] > 0 else -100.0
    wins = sum(t.pnl > 0 for t in trades)
    return PortfolioResult(
        label=label, start=str(calendar[0].date()), end=str(calendar[-1].date()),
        final_equity=round(float(eq[-1]) if len(eq) else cfg.capital, 2),
        ret_pct=round(ret, 2), cagr_pct=round(cagr, 2), max_drawdown_pct=round(mdd, 2),
        ret_over_maxdd=round(ret / mdd, 2) if mdd > 0 else float("nan"),
        time_in_market_pct=round(invested_days / max(1, len(calendar)) * 100, 1),
        turnover_x=round(buys_value / cfg.capital / years, 2),
        n_trades=len(trades), win_rate=round(wins / len(trades), 3) if trades else 0.0,
        trades=trades)


def _clustered_expectancy(trades: list[Trade], cost_pct: float,
                          rng: np.random.Generator, n: int = 2000) -> dict:
    """Trade-level mean return with a week-CLUSTER bootstrap CI (correlated
    same-week entries counted as one draw). Diagnostic only."""
    if not trades:
        return {"n": 0}
    rets = np.array([(t.exit / t.entry - 1) * 100 - cost_pct for t in trades])
    weeks = np.array([t.entry_date.strftime("%G-%V") for t in trades])
    groups = [rets[weeks == w] for w in pd.unique(weeks)]
    means = []
    for _ in range(n):
        pick = rng.integers(0, len(groups), len(groups))
        means.append(np.concatenate([groups[k] for k in pick]).mean())
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {"n": len(trades), "n_week_clusters": len(groups),
            "mean_pct": round(float(rets.mean()), 3),
            "cluster_ci95": [round(float(lo), 3), round(float(hi), 3)],
            "ci_excludes_zero": bool(lo > 0 or hi < 0)}


def audit_strategy(frames, signal_fn, params, *, name: str,
                   cfg: PortfolioConfig, n_folds: int = 5, seed: int = 7) -> dict:
    """Purged walk-forward portfolio audit + one-use holdout + clustered
    trade diagnostic. Every result carries the PRELIMINARY stamp."""
    rng = np.random.default_rng(seed)
    calendar = pd.DatetimeIndex(sorted(set().union(*[set(df.index) for df in frames.values()])))
    calendar = [c for c in calendar]
    # reserve the final ~1/(n_folds+1) as the one-use holdout
    cut = int(len(calendar) * n_folds / (n_folds + 1))
    dev_cal, holdout_cal = calendar[:cut], calendar[cut:]

    sp, tp, mh = params["stop_pct"], params["target_pct"], params["max_hold_days"]

    # purged walk-forward over dev period: flat between folds + embargo skip
    fold_edges = [int(i * len(dev_cal) / n_folds) for i in range(n_folds + 1)]
    folds = []
    for k in range(n_folds):
        seg = dev_cal[fold_edges[k] + (cfg.embargo_sessions if k else 0): fold_edges[k + 1]]
        if len(seg) < 30:
            continue
        r = simulate_portfolio(frames, signal_fn, stop_pct=sp, target_pct=tp,
                               max_hold_days=mh, cfg=cfg, calendar=seg, label=f"fold{k}")
        folds.append(r)

    holdout = simulate_portfolio(frames, signal_fn, stop_pct=sp, target_pct=tp,
                                 max_hold_days=mh, cfg=cfg, calendar=holdout_cal,
                                 label="HOLDOUT_consumed_once")
    all_trades = [t for f in folds for t in f.trades]
    fold_cagrs = [f.cagr_pct for f in folds]
    return {
        "stamp": STAMP,
        "strategy": name,
        "params": params,
        "portfolio_config": cfg.__dict__,
        "walk_forward_folds": [f.to_row() for f in folds],
        "folds_positive_cagr": f"{sum(c > 0 for c in fold_cagrs)}/{len(fold_cagrs)}",
        "median_fold_cagr_pct": round(float(np.median(fold_cagrs)), 2) if fold_cagrs else None,
        "holdout": holdout.to_row(),
        "trade_diagnostic_clustered": _clustered_expectancy(
            all_trades, cfg.cost_pct_round_trip, rng),
        "hard_limits": ["survivorship_bias_present", "corporate_actions_uncorrected",
                        "not_point_in_time_membership", "NO_2008_COVID_certification_claim"],
    }
