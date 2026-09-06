"""Preregistered, chronological strategy-edge validation campaigns."""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import platform
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

import numpy as np
import pandas as pd

from .engine import ROUND_TRIP_COST_PCT, Trade, run_backtest


@dataclass(frozen=True)
class ValidationThresholds:
    """Fixed evidence floors applied uniformly to every strategy."""

    minimum_total_trades: int = 100
    minimum_holdout_trades: int = 30
    minimum_holdout_expectancy_pct: float = 0.30
    minimum_holdout_profit_factor: float = 1.10
    minimum_positive_fold_fraction: float = 0.60

    def __post_init__(self) -> None:
        if self.minimum_total_trades < 1 or self.minimum_holdout_trades < 1:
            raise ValueError("trade-count thresholds must be positive")
        numeric = (
            self.minimum_holdout_expectancy_pct,
            self.minimum_holdout_profit_factor,
            self.minimum_positive_fold_fraction,
        )
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError("validation thresholds must be finite")
        if self.minimum_holdout_profit_factor <= 0:
            raise ValueError("minimum profit factor must be positive")
        if not 0 < self.minimum_positive_fold_fraction <= 1:
            raise ValueError("positive-fold fraction must be in (0, 1]")


@dataclass(frozen=True)
class TradeMetrics:
    trades: int
    hit_rate: float
    expectancy_pct: float
    expectancy_ci95_low_pct: float | None
    expectancy_ci95_high_pct: float | None
    average_win_pct: float
    average_loss_pct: float
    profit_factor: float | None
    worst_trade_pct: float
    return_p05_pct: float
    return_median_pct: float
    return_p95_pct: float
    trade_sequence_max_drawdown_pct: float
    targets: int
    stops: int
    time_exits: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FoldResult:
    name: str
    kind: str
    start: str
    end: str
    metrics: TradeMetrics

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "kind": self.kind,
            "start": self.start,
            "end": self.end,
            "metrics": self.metrics.to_dict(),
        }


@dataclass(frozen=True)
class StrategyValidationResult:
    name: str
    total: TradeMetrics
    folds: tuple[FoldResult, ...]
    verdict: str
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "total": self.total.to_dict(),
            "folds": [fold.to_dict() for fold in self.folds],
            "verdict": self.verdict,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True)
class StrategyValidationCampaignReport:
    generated_at: datetime
    schema_version: str
    campaign_id: str
    input_fingerprint: str
    execution_fingerprint: str
    universe_size: int
    folds: int
    cost_pct: float
    thresholds: ValidationThresholds
    locked_confirmation_consumed: bool
    data_quality_blockers: tuple[str, ...]
    strategies: tuple[StrategyValidationResult, ...]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "schema_version": self.schema_version,
            "campaign_id": self.campaign_id,
            "input_fingerprint": self.input_fingerprint,
            "execution_fingerprint": self.execution_fingerprint,
            "universe_size": self.universe_size,
            "folds": self.folds,
            "cost_pct": self.cost_pct,
            "thresholds": asdict(self.thresholds),
            "locked_confirmation_consumed": self.locked_confirmation_consumed,
            "data_quality_blockers": list(self.data_quality_blockers),
            "strategies": [strategy.to_dict() for strategy in self.strategies],
            "limitations": list(self.limitations),
        }


class LockedConfirmationReuseError(RuntimeError):
    """Raised when one registered confirmation dataset is accessed twice."""


class LockedConfirmationLedger:
    """Durable one-use boundary for preregistered confirmation access."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def preregister(self, campaign_id: str, *, registered_at: datetime) -> None:
        entries = self._read()
        if any(entry.get("campaign_id") == campaign_id for entry in entries):
            raise LockedConfirmationReuseError(
                f"locked confirmation already accessed: {campaign_id}"
            )
        entries.append({
            "campaign_id": campaign_id,
            "registered_at": registered_at.astimezone(timezone.utc).isoformat(),
            "status": "REGISTERED",
        })
        self._write(entries)

    def consume(
        self, campaign_id: str, *, consumed_at: datetime, status: str,
    ) -> None:
        if status not in {"COMPLETED", "FAILED_CONSUMED"}:
            raise ValueError("locked confirmation terminal status is invalid")
        entries = self._read()
        entry = next(
            (item for item in entries if item.get("campaign_id") == campaign_id),
            None,
        )
        if entry is None or entry.get("status") != "REGISTERED":
            raise LockedConfirmationReuseError(
                f"locked confirmation is not registered: {campaign_id}"
            )
        entry["status"] = status
        entry["consumed_at"] = consumed_at.astimezone(timezone.utc).isoformat()
        self._write(entries)

    def _read(self) -> list[dict[str, object]]:
        if not self._path.exists():
            return []
        value = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise ValueError("locked confirmation ledger must contain a list")
        return [dict(item) for item in value]

    def _write(self, entries: list[dict[str, object]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(entries, indent=2, sort_keys=True), encoding="utf-8"
        )
        temporary.replace(self._path)


def run_validation_campaign(
    *,
    frames: Mapping[str, pd.DataFrame],
    strategies: Mapping[str, Mapping[str, object]],
    folds: int = 5,
    cost_pct: float = ROUND_TRIP_COST_PCT,
    thresholds: ValidationThresholds | None = None,
    generated_at: datetime | None = None,
    progress: Callable[[str], None] | None = None,
    historical_membership_available: bool = False,
    locked_confirmation_consumed: bool = False,
    provenance: Mapping[str, str] | None = None,
) -> StrategyValidationCampaignReport:
    """Evaluate fixed strategies over chronological folds and one locked fold."""

    if folds < 3:
        raise ValueError("at least three folds are required")
    if not frames:
        raise ValueError("campaign universe must not be empty")
    if not strategies:
        raise ValueError("campaign strategies must not be empty")
    if not math.isfinite(cost_pct) or cost_pct < 0:
        raise ValueError("cost_pct must be finite and non-negative")
    policy = thresholds or ValidationThresholds()
    normalized = {
        str(symbol): _normalize_frame(frame)
        for symbol, frame in sorted(frames.items())
    }
    sessions = pd.DatetimeIndex(sorted({
        timestamp.normalize()
        for frame in normalized.values()
        for timestamp in frame.index
    }))
    if len(sessions) < folds:
        raise ValueError("not enough sessions for the requested folds")
    partitions = tuple(pd.DatetimeIndex(part) for part in np.array_split(sessions, folds))
    fold_descriptors = _fold_descriptors(folds, locked_confirmation_consumed)
    discontinuities = _price_discontinuities(normalized)
    data_quality_blockers = []
    if not historical_membership_available:
        data_quality_blockers.append("HISTORICAL_UNIVERSE_MEMBERSHIP_UNAVAILABLE")
    if discontinuities:
        data_quality_blockers.append(
            f"UNRESOLVED_PRICE_DISCONTINUITIES:{len(discontinuities)}:"
            + ",".join(discontinuities[:10])
        )
    results = []
    for name, spec in sorted(strategies.items()):
        if progress is not None:
            progress(name)
        trades = _strategy_trades(
            name=name,
            spec=spec,
            frames=normalized,
            cost_pct=cost_pct,
        )
        fold_results = []
        assigned: list[Trade] = []
        for index, partition in enumerate(partitions):
            start, end = partition[0], partition[-1]
            selected = [
                trade for trade in trades
                if start <= trade.entry_date.normalize() <= end
            ]
            assigned.extend(selected)
            fold_results.append(FoldResult(
                name=fold_descriptors[index][0],
                kind=fold_descriptors[index][1],
                start=start.date().isoformat(),
                end=end.date().isoformat(),
                metrics=_metrics(selected),
            ))
        total = _metrics(assigned)
        verdict, reasons = _verdict(
            total, tuple(fold_results), policy,
            data_quality_blocked=bool(data_quality_blockers),
        )
        results.append(StrategyValidationResult(
            name=name,
            total=total,
            folds=tuple(fold_results),
            verdict=verdict,
            reason_codes=reasons,
        ))
    campaign_id, input_fingerprint, execution_fingerprint = _campaign_id(
        normalized=normalized,
        strategies=strategies,
        sessions=sessions,
        folds=folds,
        cost_pct=cost_pct,
        policy=policy,
        historical_membership_available=historical_membership_available,
        locked_confirmation_consumed=locked_confirmation_consumed,
        provenance=provenance or {},
    )
    return StrategyValidationCampaignReport(
        generated_at=generated_at or datetime.now(timezone.utc),
        schema_version="1.0",
        campaign_id=campaign_id,
        input_fingerprint=input_fingerprint,
        execution_fingerprint=execution_fingerprint,
        universe_size=len(normalized),
        folds=folds,
        cost_pct=cost_pct,
        thresholds=policy,
        locked_confirmation_consumed=locked_confirmation_consumed,
        data_quality_blockers=tuple(data_quality_blockers),
        strategies=tuple(results),
        limitations=(
            "Current stored universe membership is survivorship-biased.",
            "Adjusted vendor OHLCV may contain revision and corporate-action risk.",
            "Per-strategy signal tests do not model portfolio concurrency or agent operations.",
            "Trade-sequence drawdown is not a capital-weighted portfolio drawdown.",
            ("The final chronological fold is consumed locked confirmation."
             if locked_confirmation_consumed else
             "The final chronological fold is a reusable holdout, not locked confirmation."),
        ),
    )


def validation_campaign_id(
    *, frames: Mapping[str, pd.DataFrame],
    strategies: Mapping[str, Mapping[str, object]], folds: int,
    cost_pct: float, thresholds: ValidationThresholds | None = None,
    historical_membership_available: bool = False,
    locked_confirmation_consumed: bool = False,
    provenance: Mapping[str, str] | None = None,
) -> str:
    """Compute the exact evidence identity before outcome access."""

    normalized = {
        str(symbol): _normalize_frame(frame)
        for symbol, frame in sorted(frames.items())
    }
    sessions = pd.DatetimeIndex(sorted({
        timestamp.normalize()
        for frame in normalized.values()
        for timestamp in frame.index
    }))
    return _campaign_id(
        normalized=normalized,
        strategies=strategies,
        sessions=sessions,
        folds=folds,
        cost_pct=cost_pct,
        policy=thresholds or ValidationThresholds(),
        historical_membership_available=historical_membership_available,
        locked_confirmation_consumed=locked_confirmation_consumed,
        provenance=provenance or {},
    )[0]


def _campaign_id(
    *, normalized: Mapping[str, pd.DataFrame],
    strategies: Mapping[str, Mapping[str, object]], sessions: pd.DatetimeIndex,
    folds: int, cost_pct: float, policy: ValidationThresholds,
    historical_membership_available: bool,
    locked_confirmation_consumed: bool,
    provenance: Mapping[str, str],
) -> tuple[str, str, str]:
    input_fingerprint = _input_fingerprint(normalized, strategies)
    execution_fingerprint = _execution_fingerprint(provenance)
    identity = {
        "input_fingerprint": input_fingerprint,
        "execution_fingerprint": execution_fingerprint,
        "symbols": tuple(normalized),
        "sessions": (sessions[0].isoformat(), sessions[-1].isoformat()),
        "strategies": tuple(sorted(strategies)),
        "folds": folds,
        "cost_pct": cost_pct,
        "thresholds": asdict(policy),
        "historical_membership_available": historical_membership_available,
        "locked_confirmation_consumed": locked_confirmation_consumed,
    }
    campaign_id = "campaign:" + hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return campaign_id, input_fingerprint, execution_fingerprint


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close", "volume"}
    if not isinstance(frame, pd.DataFrame) or not required <= set(frame.columns):
        raise ValueError("each frame requires OHLCV columns")
    result = frame.loc[:, sorted(required)].copy()
    result.index = pd.to_datetime(result.index)
    result = result[~result.index.duplicated(keep="last")].sort_index()
    if result.empty:
        raise ValueError("price frames must not be empty")
    return result


def _input_fingerprint(
    frames: Mapping[str, pd.DataFrame],
    strategies: Mapping[str, Mapping[str, object]],
) -> str:
    digest = hashlib.sha256()
    for symbol, frame in frames.items():
        digest.update(symbol.encode())
        digest.update("|".join(map(str, frame.columns)).encode())
        digest.update(pd.util.hash_pandas_object(frame, index=True).values.tobytes())
    for name, spec in sorted(strategies.items()):
        digest.update(name.encode())
        for field in ("stop_pct", "target_pct", "max_hold_days"):
            digest.update(f"{field}:{spec[field]}".encode())
        function = spec.get("fn")
        try:
            source = inspect.getsource(function)  # type: ignore[arg-type]
        except (OSError, TypeError):
            source = repr(function)
        digest.update(source.encode())
    return "sha256:" + digest.hexdigest()


def _execution_fingerprint(provenance: Mapping[str, str]) -> str:
    from sensei.backtest import daily_execution

    material = {
        "daily_execution_source": inspect.getsource(daily_execution),
        "campaign_source": inspect.getsource(run_validation_campaign),
        "metrics_source": inspect.getsource(_metrics),
        "verdict_source": inspect.getsource(_verdict),
        "backtest_source": inspect.getsource(run_backtest),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "provenance": dict(sorted(provenance.items())),
    }
    return "sha256:" + hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _price_discontinuities(
    frames: Mapping[str, pd.DataFrame],
) -> tuple[str, ...]:
    flagged = []
    for symbol, frame in frames.items():
        prior_close = frame["close"].shift(1)
        ratio = frame["open"] / prior_close
        for timestamp in frame.index[(ratio < 0.5) | (ratio > 2.0)]:
            flagged.append(f"{symbol}:{timestamp.date().isoformat()}")
    return tuple(sorted(flagged))


def _strategy_trades(
    *, name: str, spec: Mapping[str, object],
    frames: Mapping[str, pd.DataFrame], cost_pct: float,
) -> list[Trade]:
    signal_fn = spec.get("fn")
    if not callable(signal_fn):
        raise TypeError(f"strategy {name!r} has no callable signal function")
    trades = []
    for symbol, frame in frames.items():
        result = run_backtest(
            frame,
            signal_fn,  # type: ignore[arg-type]
            strategy=name,
            symbol=symbol,
            stop_pct=float(spec["stop_pct"]),
            target_pct=float(spec["target_pct"]),
            max_hold_days=int(spec["max_hold_days"]),
            cost_pct=cost_pct,
        )
        trades.extend(result.trades)
    return sorted(trades, key=lambda trade: (trade.entry_date, trade.symbol))


def _metrics(trades: list[Trade]) -> TradeMetrics:
    if not trades:
        return TradeMetrics(
            0, 0.0, 0.0, None, None, 0.0, 0.0, None,
            0.0, 0.0, 0.0, 0.0, 0.0, 0, 0, 0,
        )
    returns = np.asarray([trade.ret_pct for trade in trades], dtype=float)
    wins = returns[returns > 0]
    losses = returns[returns <= 0]
    expectancy = float(returns.mean())
    residuals = pd.Series(
        returns - expectancy,
        index=pd.DatetimeIndex([trade.entry_date for trade in trades]),
    )
    cluster_scores = residuals.groupby(level=0).sum().to_numpy()
    if len(cluster_scores) > 1:
        variance = (
            len(cluster_scores) / (len(cluster_scores) - 1)
            * float(np.square(cluster_scores).sum())
            / len(returns) ** 2
        )
        margin = 1.96 * math.sqrt(variance)
        ci_low, ci_high = expectancy - margin, expectancy + margin
    else:
        ci_low = ci_high = None
    gross_loss = abs(float(losses.sum()))
    profit_factor = float(wins.sum()) / gross_loss if gross_loss else None
    equity = np.cumprod(1 + returns / 100)
    peaks = np.maximum.accumulate(np.concatenate(([1.0], equity)))[1:]
    drawdown = float(((peaks - equity) / peaks).max() * 100)
    reasons = [trade.exit_reason for trade in trades]
    return TradeMetrics(
        trades=len(trades),
        hit_rate=round(float(np.mean(returns > 0)), 6),
        expectancy_pct=round(expectancy, 6),
        expectancy_ci95_low_pct=round(ci_low, 6) if ci_low is not None else None,
        expectancy_ci95_high_pct=round(ci_high, 6) if ci_high is not None else None,
        average_win_pct=round(float(wins.mean()), 6) if len(wins) else 0.0,
        average_loss_pct=round(float(losses.mean()), 6) if len(losses) else 0.0,
        profit_factor=round(profit_factor, 6) if profit_factor is not None else None,
        worst_trade_pct=round(float(returns.min()), 6),
        return_p05_pct=round(float(np.quantile(returns, 0.05)), 6),
        return_median_pct=round(float(np.median(returns)), 6),
        return_p95_pct=round(float(np.quantile(returns, 0.95)), 6),
        trade_sequence_max_drawdown_pct=round(drawdown, 6),
        targets=reasons.count("target"),
        stops=sum(reason in {"stop", "stop_gap"} for reason in reasons),
        time_exits=reasons.count("time"),
    )


def _verdict(
    total: TradeMetrics,
    folds: tuple[FoldResult, ...],
    policy: ValidationThresholds,
    *, data_quality_blocked: bool,
) -> tuple[str, tuple[str, ...]]:
    holdout = folds[-1].metrics
    reasons = []
    if total.trades < policy.minimum_total_trades:
        reasons.append("INSUFFICIENT_TOTAL_TRADES")
    if holdout.trades < policy.minimum_holdout_trades:
        reasons.append("INSUFFICIENT_HOLDOUT_TRADES")
    if reasons:
        if data_quality_blocked:
            reasons.append("DATA_QUALITY_BLOCKED")
        return "INCONCLUSIVE", tuple(reasons)
    if holdout.expectancy_pct < policy.minimum_holdout_expectancy_pct:
        reasons.append("HOLDOUT_EXPECTANCY_BELOW_THRESHOLD")
    effective_pf = holdout.profit_factor if holdout.profit_factor is not None else math.inf
    if effective_pf < policy.minimum_holdout_profit_factor:
        reasons.append("HOLDOUT_PROFIT_FACTOR_BELOW_THRESHOLD")
    positive = sum(fold.metrics.expectancy_pct > 0 for fold in folds) / len(folds)
    if positive < policy.minimum_positive_fold_fraction:
        reasons.append("POSITIVE_FOLD_FRACTION_BELOW_THRESHOLD")
    if total.expectancy_ci95_low_pct is None or total.expectancy_ci95_low_pct <= 0:
        reasons.append("OVERALL_EXPECTANCY_NOT_DISTINGUISHABLE_FROM_ZERO")
    if data_quality_blocked:
        reasons.append("DATA_QUALITY_BLOCKED")
        return (
            "PRELIMINARY_PROMISING_DATA_BLOCKED" if len(reasons) == 1
            else "DATA_QUALITY_BLOCKED",
            tuple(reasons),
        )
    return ("NOT_VALIDATED", tuple(reasons)) if reasons else ("PROMISING", ())


def _fold_descriptors(
    folds: int, locked: bool,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (("locked-confirmation", "locked-confirmation") if locked
         else ("holdout", "holdout")) if index == folds - 1
        else ("validation", "validation") if index == folds - 2
        else (f"development-{index + 1}", "development")
        for index in range(folds)
    )


__all__ = [
    "LockedConfirmationLedger",
    "LockedConfirmationReuseError",
    "StrategyValidationCampaignReport",
    "ValidationThresholds",
    "run_validation_campaign",
    "validation_campaign_id",
]
