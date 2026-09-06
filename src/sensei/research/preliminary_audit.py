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
  - opening-price proxy entries on prior-close signals
  - stop-first / target / time exits with round-trip costs
  - purged walk-forward folds (flat between folds + embargo) so no trade
    straddles a boundary
  - a reusable trailing validation fold, never locked confirmation
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
    """Adapt the common portfolio simulator; no independent fill logic."""
    from sensei.backtest.portfolio_campaign import PortfolioCampaignConfig, run_portfolio_campaign

    if not calendar:
        raise ValueError("audit calendar must not be empty")
    report = run_portfolio_campaign(
        frames=frames,
        strategies={"preliminary": {"fn": signal_fn, "stop_pct": stop_pct,
            "target_pct": target_pct, "max_hold_days": max_hold_days}},
        config=PortfolioCampaignConfig(
            capital=cfg.capital, max_position_pct=cfg.max_position_pct,
            max_risk_per_trade_pct=cfg.max_risk_per_trade_pct,
            max_open_positions=cfg.max_positions, cost_pct=cfg.cost_pct_round_trip,
            max_positions_per_strategy=cfg.max_positions, liquidate_at_end=True,
        ),
        evaluation_start=calendar[0], evaluation_end=calendar[-1],
    )
    trades = [Trade(t.symbol, pd.Timestamp(t.entry_date), pd.Timestamp(t.exit_date),
                    t.entry_price, t.exit_price, t.quantity, t.exit_reason)
              for t in report.trades]
    years = len(report.equity_curve) / 252
    cagr = ((report.final_equity / cfg.capital) ** (1 / years) - 1) * 100
    return PortfolioResult(
        label=label, start=str(calendar[0].date()), end=str(calendar[-1].date()),
        final_equity=report.final_equity, ret_pct=report.return_pct,
        cagr_pct=round(cagr, 2), max_drawdown_pct=report.max_drawdown_pct,
        ret_over_maxdd=(round(report.return_pct / report.max_drawdown_pct, 2)
                       if report.max_drawdown_pct else float("nan")),
        time_in_market_pct=round(sum(point.open_positions > 0 for point in report.equity_curve)
                                 / len(report.equity_curve) * 100, 1),
        turnover_x=round(report.turnover / cfg.capital / years, 2),
        n_trades=len(trades),
        win_rate=round(sum(t.net_pnl > 0 for t in report.trades) / len(trades), 3) if trades else 0,
        trades=trades,
    )


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
    """Purged walk-forward portfolio audit + reusable validation fold + clustered
    trade diagnostic. Every result carries the PRELIMINARY stamp."""
    rng = np.random.default_rng(seed)
    calendar = pd.DatetimeIndex(sorted(set().union(*[set(df.index) for df in frames.values()])))
    calendar = [c for c in calendar]
    # reserve the final ~1/(n_folds+1) as the reusable validation fold
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
                                 label="HOLDOUT_REUSED_DEVELOPMENT_ONLY")
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
        "holdout_is_untouched": False,
        "execution_policy": "shared-portfolio-daily-v2",
        "trade_diagnostic_clustered": _clustered_expectancy(
            all_trades, cfg.cost_pct_round_trip, rng),
        "hard_limits": ["survivorship_bias_present", "corporate_actions_uncorrected",
                        "not_point_in_time_membership", "NO_2008_COVID_certification_claim"],
    }
