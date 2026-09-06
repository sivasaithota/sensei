"""Versioned portfolio diagnostics; these reports never authorize trading.

Run with ``python -m sensei.research.stock_evaluation --help``. All supplied
history is development data. Benchmark inputs must include the preceding
session and must not be forward-filled across missing sessions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from sensei.backtest.portfolio_campaign import PortfolioCampaignConfig, PortfolioCampaignReport, run_portfolio_campaign


@dataclass(frozen=True)
class EvaluationProtocol:
    version: str = "stock-portfolio-evaluation-v1"
    maximum_drawdown_pct: float | None = None
    minimum_sessions: int = 252
    minimum_trades: int = 30
    bootstrap_block_sessions: int = 20
    bootstrap_samples: int = 2000
    confidence: float = 0.90
    random_seed: int = 20260906

    def __post_init__(self):
        if self.maximum_drawdown_pct is not None and (
            isinstance(self.maximum_drawdown_pct, bool)
            or not 0 < self.maximum_drawdown_pct <= 100
        ):
            raise ValueError("maximum drawdown must be greater than zero and at most 100 percent")
        for value in (self.minimum_sessions, self.minimum_trades, self.bootstrap_block_sessions, self.bootstrap_samples):
            if type(value) is not int or value < 1:
                raise ValueError("sample and block counts must be positive integers")
        if not 0 < self.confidence < 1:
            raise ValueError("confidence must be between zero and one")


def audit_stock_data(frames: Mapping[str, pd.DataFrame]) -> dict:
    """Inspect content without filtering away poorly covered securities."""
    issues = []
    summaries = {}
    required = {"open", "high", "low", "close", "volume"}
    for symbol, frame in sorted(frames.items()):
        if frame.empty or not isinstance(frame.index, pd.DatetimeIndex) or frame.index.has_duplicates or not required <= set(frame):
            issues.append(f"{symbol}:invalid_schema_or_calendar")
            continue
        values = frame[list(required)].astype(float)
        finite = np.isfinite(values.to_numpy()).all()
        invalid = (not finite or (frame[["open", "high", "low", "close"]] <= 0).any(axis=None)
                   or (frame.volume < 0).any()
                   or (frame.high + frame.high.abs() * 1e-8 < frame[["open", "close", "low"]].max(axis=1)).any()
                   or (frame.low - frame.low.abs() * 1e-8 > frame[["open", "close", "high"]].min(axis=1)).any())
        if invalid:
            issues.append(f"{symbol}:invalid_ohlcv")
        jumps = int((frame.sort_index().close.pct_change(fill_method=None).abs() > 0.30).sum())
        if jumps:
            issues.append(f"{symbol}:large_price_changes_require_action_review")
        summaries[symbol] = {"rows": len(frame), "first": str(frame.index.min().date()),
                             "last": str(frame.index.max().date()), "large_daily_changes": jumps}
    if not frames:
        issues.append("empty_universe")
    return {
        "status": "DATA_BLOCKED",
        "content_issues": issues,
        "external_evidence_missing": [
            "verified historical universe membership including removals and delistings",
            "verified corporate-action and executable-price treatment",
            "exchange-session calendar and per-instrument coverage provenance",
        ],
        "instruments": summaries,
        "note": "Content checks do not certify provenance. No security is removed by this audit.",
    }


def _bootstrap_excess(excess: np.ndarray, protocol: EvaluationProtocol) -> list[float]:
    """Circular moving-block interval for annualized mean daily excess.

    This is descriptive dependence-aware uncertainty, not an untouched test,
    selection-bias correction, or a forecast. No independent-trade assumption.
    """
    rng = np.random.default_rng(protocol.random_seed)
    n = len(excess)
    block = min(protocol.bootstrap_block_sessions, n)
    draws = []
    for _ in range(protocol.bootstrap_samples):
        starts = rng.integers(0, n, size=math.ceil(n / block))
        indexes = ((starts[:, None] + np.arange(block)) % n).ravel()[:n]
        draws.append(float(excess[indexes].mean() * 252 * 100))
    tail = (1 - protocol.confidence) / 2
    return [round(float(v), 4) for v in np.quantile(draws, [tail, 1 - tail])]


def evaluate_stock_portfolio(*, campaign: PortfolioCampaignReport,
                             protocol: EvaluationProtocol,
                             data_audit: dict,
                             benchmark: pd.Series | None = None,
                             benchmark_name: str = "unspecified") -> dict:
    if not campaign.equity_curve:
        raise ValueError("evaluation requires at least one session")
    dates = pd.DatetimeIndex([point.session for point in campaign.equity_curve])
    equity = np.array([campaign.config.capital] + [point.equity for point in campaign.equity_curve])
    if not np.isfinite(equity).all() or (equity <= 0).any():
        raise ValueError("evaluation requires positive finite equity")
    daily = equity[1:] / equity[:-1] - 1
    n = len(daily)
    underwater = longest = 0
    for value, peak in zip(equity[1:], np.maximum.accumulate(equity)[1:], strict=True):
        underwater = underwater + 1 if value < peak else 0
        longest = max(longest, underwater)
    benchmark_issues = []
    comparison = None
    benchmark_digest = None
    if benchmark is None:
        benchmark_issues.append("benchmark_missing")
    elif (not isinstance(benchmark.index, pd.DatetimeIndex) or benchmark.index.has_duplicates
          or not np.isfinite(benchmark.to_numpy(dtype=float)).all() or (benchmark <= 0).any()):
        benchmark_issues.append("benchmark_invalid")
    else:
        benchmark = benchmark.sort_index()
        benchmark_digest = hashlib.sha256(pd.util.hash_pandas_object(benchmark, index=True).values.tobytes()).hexdigest()
        predecessor = pd.Timestamp(campaign.preceding_session) if campaign.preceding_session else None
        # Require the benchmark calendar and portfolio calendar to agree;
        # otherwise hidden skipped market sessions could bias daily metrics.
        benchmark_window = benchmark.loc[(benchmark.index >= dates[0]) & (benchmark.index <= dates[-1])]
        prior_benchmark_dates = benchmark.index[benchmark.index < dates[0]]
        if (predecessor is None or prior_benchmark_dates.empty or prior_benchmark_dates[-1] != predecessor
                or not benchmark_window.index.equals(dates)):
            benchmark_issues.append("benchmark_calendar_mismatch_or_missing_prior_session")
        else:
            levels = np.r_[float(benchmark.loc[predecessor]), benchmark_window.to_numpy(dtype=float)]
            returns = levels[1:] / levels[:-1] - 1
            interval = _bootstrap_excess(daily - returns, protocol)
            comparison = {
                "name": benchmark_name,
                "return_pct": round((levels[-1] / levels[0] - 1) * 100, 4),
                "cagr_pct": round(((levels[-1] / levels[0]) ** (252 / n) - 1) * 100, 4),
                "excess_total_return_percentage_points": round(campaign.return_pct - (levels[-1] / levels[0] - 1) * 100, 4),
                "annualized_mean_daily_excess_pct": round(float((daily - returns).mean() * 252 * 100), 4),
                "annualized_mean_daily_excess_interval_pct": interval,
                "interval_method": "circular moving blocks; exploratory, no multiple-testing correction",
            }
    reasons = []
    if protocol.maximum_drawdown_pct is None:
        reasons.append("account_drawdown_limit_unspecified")
    if n < protocol.minimum_sessions or len(campaign.trades) < protocol.minimum_trades:
        reasons.append("insufficient_observations")
    if campaign.open_positions:
        reasons.append("unliquidated_positions")
    reasons.extend(benchmark_issues)
    if reasons:
        economics = "INCONCLUSIVE"
    elif campaign.max_drawdown_pct > protocol.maximum_drawdown_pct:
        economics = "OUTSIDE_RISK_BUDGET"
    elif comparison["annualized_mean_daily_excess_interval_pct"][0] <= 0 or campaign.return_pct <= 0:
        economics = "NO_CLEAR_NET_EDGE"
    else:
        economics = "PROMISING_DEVELOPMENT_RESULT"
    trades = campaign.trades
    identity = {"campaign": campaign.experiment_id, "protocol": asdict(protocol),
                "benchmark_digest": benchmark_digest, "benchmark_name": benchmark_name,
                "data_audit": data_audit}
    return {
        "evaluation_id": "sha256:" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(),
        "protocol": asdict(protocol), "campaign": campaign.to_dict(),
        "data": data_audit, "benchmark": comparison,
        "economics": {"verdict": economics, "limitations": reasons,
                      "cagr_pct": round(((equity[-1] / equity[0]) ** (252 / n) - 1) * 100, 4),
                      "longest_underwater_sessions": longest,
                      "completed_trades": len(trades),
                      "total_realized_costs_inr": round(sum(t.costs for t in trades), 2),
                      "median_trade_net_pnl_inr": float(np.median([t.net_pnl for t in trades])) if trades else None},
        "cost_interpretation": "Current delivery schedule is a current-cost counterfactual, not historical tax reconstruction. DP is per simulated sale; same-day sales are conservatively charged. Entry slippage is explicit; gap stops fill at the open without additional exit slippage.",
        "authority": "RESEARCH_ONLY", "can_trade": False,
        "holdout_is_untouched": False,
        "decision": "DATA_BLOCKED" if data_audit.get("status") != "VERIFIED" else "RESEARCH_ONLY",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prices", type=Path, default=Path("data/prices"))
    parser.add_argument("--benchmark", type=Path, help="Parquet with DatetimeIndex and close; include prior session")
    parser.add_argument("--benchmark-name", default="unspecified")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--strategy", default="momentum_breakout_55")
    parser.add_argument("--max-drawdown", type=float)
    parser.add_argument("--entry-slippage-bps", type=float, default=10)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    from sensei.backtest.playbook import all_strategies
    from sensei.research.exposure import record_development_frames

    available = all_strategies()
    if args.strategy not in available:
        parser.error(f"unknown strategy: {args.strategy}")
    frames = {path.stem: pd.read_parquet(path).sort_index() for path in sorted(args.prices.glob("*.parquet"))}
    record_development_frames(frames, campaign_id="stock-portfolio-evaluation-v1")
    audit = audit_stock_data(frames)
    protocol = EvaluationProtocol(maximum_drawdown_pct=args.max_drawdown)
    # Structural problems block simulation instead of silently excluding names.
    if any("invalid" in issue or issue == "empty_universe" for issue in audit["content_issues"]):
        payload = {"data": audit, "decision": "DATA_BLOCKED", "authority": "RESEARCH_ONLY", "can_trade": False}
    else:
        campaign = run_portfolio_campaign(
            frames=frames, strategies={args.strategy: available[args.strategy]},
            config=PortfolioCampaignConfig(cost_model="current_delivery_schedule", liquidate_at_end=True,
                max_positions_per_strategy=5, entry_slippage_bps=args.entry_slippage_bps),
            evaluation_start=pd.Timestamp(args.start), evaluation_end=pd.Timestamp(args.end),
        )
        benchmark = pd.read_parquet(args.benchmark)["close"] if args.benchmark else None
        payload = evaluate_stock_portfolio(campaign=campaign, protocol=protocol,
            data_audit=audit, benchmark=benchmark, benchmark_name=args.benchmark_name)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({key: payload[key] for key in ("decision", "authority", "can_trade")}))


if __name__ == "__main__":
    main()
