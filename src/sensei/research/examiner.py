"""Deterministic examination of a fixed strategy hypothesis.

The Research Examiner owns evidence production, not strategy promotion. Its
result is always quarantined and can recommend at most a shadow trial.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from sensei.backtest.rulespec import RuleSpec, compile_spec

EXAMINER_VERSION = "1.0"


def _content_id(payload: object) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


@dataclass(frozen=True)
class HypothesisVersion:
    hypothesis_id: str
    version: int
    strategy: RuleSpec
    source_claim_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.hypothesis_id.strip():
            raise ValueError("hypothesis_id must not be empty")
        if self.version < 1:
            raise ValueError("hypothesis version must be positive")
        if not self.source_claim_ids:
            raise ValueError("at least one source claim is required")

    def identity_payload(self) -> dict:
        return {
            "hypothesis_id": self.hypothesis_id,
            "version": self.version,
            "strategy": self.strategy.model_dump(mode="json"),
            "source_claim_ids": list(self.source_claim_ids),
        }


@dataclass(frozen=True)
class MarketDataSnapshot:
    as_of: date
    universe_as_of: date
    point_in_time_universe: bool
    source: str
    snapshot_id: str
    frequency: Literal["1d"] = "1d"
    _bars_by_symbol: Mapping[str, pd.DataFrame] = field(
        default_factory=dict, repr=False, compare=False
    )

    @classmethod
    def capture(
        cls,
        *,
        bars_by_symbol: Mapping[str, pd.DataFrame],
        as_of: date,
        universe_as_of: date,
        point_in_time_universe: bool,
        source: str,
    ) -> MarketDataSnapshot:
        if not bars_by_symbol:
            raise ValueError("a market data snapshot needs at least one symbol")
        if not source.strip():
            raise ValueError("market data source must not be empty")

        captured = {
            symbol: frame.copy(deep=True)
            for symbol, frame in sorted(bars_by_symbol.items())
        }
        digest = hashlib.sha256()
        metadata = {
            "as_of": as_of.isoformat(),
            "universe_as_of": universe_as_of.isoformat(),
            "point_in_time_universe": point_in_time_universe,
            "source": source,
            "frequency": "1d",
            "symbols": list(captured),
        }
        digest.update(
            json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
        )
        for symbol, frame in captured.items():
            digest.update(symbol.encode())
            digest.update(repr(tuple(frame.columns)).encode())
            digest.update(repr(tuple(str(dtype) for dtype in frame.dtypes)).encode())
            digest.update(pd.util.hash_pandas_object(frame, index=True).values.tobytes())

        return cls(
            as_of=as_of,
            universe_as_of=universe_as_of,
            point_in_time_universe=point_in_time_universe,
            source=source,
            snapshot_id=f"sha256:{digest.hexdigest()}",
            _bars_by_symbol=MappingProxyType(captured),
        )

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(self._bars_by_symbol)


@dataclass(frozen=True)
class EvaluationFold:
    name: str
    start: date
    end: date

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("fold name must not be empty")
        if self.start > self.end:
            raise ValueError("fold start must not be after its end")

    def identity_payload(self) -> dict:
        return {"name": self.name, "start": self.start.isoformat(), "end": self.end.isoformat()}


@dataclass(frozen=True)
class ExaminationProtocol:
    name: str
    version: int
    folds: tuple[EvaluationFold, ...]
    min_trades: int
    min_symbols: int
    min_expectancy_pct: float
    round_trip_cost_pct: float = 0.25
    min_hit_rate: float | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("protocol name must not be empty")
        if self.version < 1:
            raise ValueError("protocol version must be positive")
        if not self.folds:
            raise ValueError("at least one evaluation fold is required")
        if self.min_trades < 1 or self.min_symbols < 1:
            raise ValueError("evidence minimums must be positive")
        if self.round_trip_cost_pct < 0:
            raise ValueError("round-trip cost must not be negative")
        if self.min_hit_rate is not None and not 0 <= self.min_hit_rate <= 1:
            raise ValueError("minimum hit rate must be between zero and one")
        previous_end: date | None = None
        for fold in self.folds:
            if previous_end is not None and fold.start <= previous_end:
                raise ValueError("evaluation folds must be chronological and non-overlapping")
            previous_end = fold.end

    def identity_payload(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "folds": [fold.identity_payload() for fold in self.folds],
            "min_trades": self.min_trades,
            "min_symbols": self.min_symbols,
            "min_expectancy_pct": self.min_expectancy_pct,
            "round_trip_cost_pct": self.round_trip_cost_pct,
            "min_hit_rate": self.min_hit_rate,
        }

    @property
    def protocol_id(self) -> str:
        return _content_id(self.identity_payload())


@dataclass(frozen=True)
class ExaminationRequest:
    hypothesis: HypothesisVersion
    snapshot: MarketDataSnapshot
    protocol: ExaminationProtocol


class DossierStatus(str, Enum):
    QUARANTINED = "quarantined"


class Recommendation(str, Enum):
    REJECT = "reject"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"
    ELIGIBLE_FOR_SHADOW = "eligible_for_shadow"


class EvidenceSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    trades: int
    symbols_with_trades: int
    hit_rate: float | None
    expectancy_pct: float | None
    avg_win_pct: float | None
    avg_loss_pct: float | None
    worst_trade_pct: float | None
    stop_exits: int
    target_exits: int
    time_exits: int


class FoldEvidence(EvidenceSummary):
    name: str
    window_start: date
    window_end: date
    censored_trades: int


class EvidenceIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    detail: str
    symbol: str | None = None


class EvidenceDossier(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    examiner_version: Literal["1.0"] = "1.0"
    experiment_id: str
    hypothesis_id: str
    hypothesis_version: int
    strategy_name: str
    snapshot_id: str
    protocol_id: str
    status: DossierStatus
    recommendation: Recommendation
    folds: tuple[FoldEvidence, ...]
    aggregate: EvidenceSummary
    censored_trades: int
    issues: tuple[EvidenceIssue, ...]
    reasons: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class _Trade:
    symbol: str
    ret_pct: float
    exit_reason: Literal["stop", "target", "time"]


def _validate_frame(
    symbol: str, frame: pd.DataFrame, *, as_of: date
) -> list[EvidenceIssue]:
    required = ("open", "high", "low", "close", "volume")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        return [
            EvidenceIssue(
                code="bars.missing_columns",
                symbol=symbol,
                detail=f"Required columns are missing: {', '.join(missing)}.",
            )
        ]
    if not isinstance(frame.index, pd.DatetimeIndex):
        return [
            EvidenceIssue(
                code="bars.invalid_index",
                symbol=symbol,
                detail="Bars must use a DatetimeIndex.",
            )
        ]
    if frame.empty:
        return [
            EvidenceIssue(
                code="bars.empty",
                symbol=symbol,
                detail="The symbol has no bars.",
            )
        ]
    if not frame.index.is_monotonic_increasing or not frame.index.is_unique:
        return [
            EvidenceIssue(
                code="bars.invalid_index",
                symbol=symbol,
                detail="Bar sessions must be strictly increasing and unique.",
            )
        ]
    if any(timestamp.date() > as_of for timestamp in frame.index):
        return [
            EvidenceIssue(
                code="bars.after_snapshot_as_of",
                symbol=symbol,
                detail="The frame contains a session after the snapshot as-of date.",
            )
        ]

    try:
        values = frame.loc[:, required].to_numpy(dtype=float)
    except (TypeError, ValueError):
        return [
            EvidenceIssue(
                code="bars.non_numeric",
                symbol=symbol,
                detail="OHLCV values must be numeric.",
            )
        ]
    if not np.isfinite(values).all():
        return [
            EvidenceIssue(
                code="bars.non_finite",
                symbol=symbol,
                detail="OHLCV values must be finite.",
            )
        ]

    o, h, l, c, volume = (frame[column].to_numpy(dtype=float) for column in required)
    if (np.column_stack((o, h, l, c)) <= 0).any():
        return [
            EvidenceIssue(
                code="bars.non_positive_price",
                symbol=symbol,
                detail="Every OHLC price must be positive.",
            )
        ]
    invalid_range = (h < np.maximum.reduce((o, c, l))) | (
        l > np.minimum.reduce((o, c, h))
    )
    if invalid_range.any():
        return [
            EvidenceIssue(
                code="bars.invalid_ohlc",
                symbol=symbol,
                detail="High/low does not contain the session's open and close.",
            )
        ]
    if (volume < 0).any():
        return [
            EvidenceIssue(
                code="bars.negative_volume",
                symbol=symbol,
                detail="Volume must not be negative.",
            )
        ]
    return []


def _simulate_fold(
    symbol: str,
    frame: pd.DataFrame,
    signals: pd.Series,
    fold: EvaluationFold,
    strategy: RuleSpec,
    cost_pct: float,
) -> tuple[list[_Trade], int]:
    dates = frame.index
    opens = frame["open"].to_numpy(dtype=float)
    highs = frame["high"].to_numpy(dtype=float)
    lows = frame["low"].to_numpy(dtype=float)
    closes = frame["close"].to_numpy(dtype=float)
    signal_values = signals.fillna(False).to_numpy(dtype=bool)
    trades: list[_Trade] = []
    censored_trades = 0

    i = 0
    while i < len(frame) - 1:
        signal_day = dates[i].date()
        if not signal_values[i] or signal_day < fold.start or signal_day > fold.end:
            i += 1
            continue

        entry_index = i + 1
        if dates[entry_index].date() > fold.end:
            censored_trades += 1
            break
        entry = opens[entry_index]
        stop = entry * (1 - strategy.stop_pct / 100)
        target = entry * (1 + strategy.target_pct / 100)
        last_hold_index = entry_index + strategy.max_hold_days - 1
        last_available_index = min(last_hold_index, len(frame) - 1)
        exit_index: int | None = None
        exit_price: float | None = None
        exit_reason: Literal["stop", "target", "time"] | None = None

        for j in range(entry_index, last_available_index + 1):
            if dates[j].date() > fold.end:
                break
            if opens[j] <= stop:
                exit_index, exit_price, exit_reason = j, opens[j], "stop"
                break
            if opens[j] >= target:
                exit_index, exit_price, exit_reason = j, target, "target"
                break
            if lows[j] <= stop:
                exit_index, exit_price, exit_reason = j, stop, "stop"
                break
            if highs[j] >= target:
                exit_index, exit_price, exit_reason = j, target, "target"
                break

        if exit_index is None:
            if last_hold_index >= len(frame) or dates[last_hold_index].date() > fold.end:
                censored_trades += 1
                break
            exit_index, exit_price, exit_reason = (
                last_hold_index,
                closes[last_hold_index],
                "time",
            )

        ret_pct = (float(exit_price) / float(entry) - 1) * 100 - cost_pct
        trades.append(_Trade(symbol=symbol, ret_pct=ret_pct, exit_reason=exit_reason))
        i = exit_index + 1

    return trades, censored_trades


def _summarize(trades: list[_Trade]) -> EvidenceSummary:
    if not trades:
        return EvidenceSummary(
            trades=0,
            symbols_with_trades=0,
            hit_rate=None,
            expectancy_pct=None,
            avg_win_pct=None,
            avg_loss_pct=None,
            worst_trade_pct=None,
            stop_exits=0,
            target_exits=0,
            time_exits=0,
        )
    returns = np.array([trade.ret_pct for trade in trades])
    wins = returns[returns > 0]
    losses = returns[returns <= 0]
    return EvidenceSummary(
        trades=len(trades),
        symbols_with_trades=len({trade.symbol for trade in trades}),
        hit_rate=round(float(np.mean(returns > 0)), 6),
        expectancy_pct=round(float(np.mean(returns)), 6),
        avg_win_pct=round(float(np.mean(wins)), 6) if len(wins) else None,
        avg_loss_pct=round(float(np.mean(losses)), 6) if len(losses) else None,
        worst_trade_pct=round(float(np.min(returns)), 6),
        stop_exits=sum(trade.exit_reason == "stop" for trade in trades),
        target_exits=sum(trade.exit_reason == "target" for trade in trades),
        time_exits=sum(trade.exit_reason == "time" for trade in trades),
    )


class ResearchExaminer:
    """Produce evidence for a hypothesis without promotion side effects."""

    def __init__(
        self,
        *,
        artifact_dir: Path | None = None,
        reserved_strategy_names: Collection[str] = (),
    ) -> None:
        self._artifact_dir = artifact_dir
        self._reserved_strategy_names = frozenset(reserved_strategy_names)

    def examine(self, request: ExaminationRequest) -> EvidenceDossier:
        if any(fold.end > request.snapshot.as_of for fold in request.protocol.folds):
            raise ValueError("evaluation folds must end on or before the snapshot as-of")
        identity = {
            "examiner_version": EXAMINER_VERSION,
            "hypothesis": request.hypothesis.identity_payload(),
            "snapshot_id": request.snapshot.snapshot_id,
            "protocol": request.protocol.identity_payload(),
        }
        signal_fn = compile_spec(request.hypothesis.strategy)
        fold_evidence: list[FoldEvidence] = []
        all_trades: list[_Trade] = []
        total_censored = 0
        issues: list[EvidenceIssue] = []
        if request.hypothesis.strategy.name in self._reserved_strategy_names:
            issues.append(
                EvidenceIssue(
                    code="strategy.name_collision",
                    detail=(
                        "The candidate name collides with an existing strategy; "
                        "names are not strategy identity."
                    ),
                )
            )
        if not request.snapshot.point_in_time_universe:
            issues.append(
                EvidenceIssue(
                    code="universe.not_point_in_time",
                    detail=(
                        "The snapshot does not prove point-in-time universe membership; "
                        "survivorship bias can invalidate the evidence."
                    ),
                )
            )
        valid_frames: dict[str, pd.DataFrame] = {}
        for symbol, frame in request.snapshot._bars_by_symbol.items():
            frame_issues = _validate_frame(symbol, frame, as_of=request.snapshot.as_of)
            issues.extend(frame_issues)
            if not frame_issues:
                valid_frames[symbol] = frame

        for fold in request.protocol.folds:
            fold_trades: list[_Trade] = []
            fold_censored = 0
            for symbol, frame in valid_frames.items():
                signals = signal_fn(frame)
                symbol_trades, symbol_censored = _simulate_fold(
                    symbol,
                    frame,
                    signals,
                    fold,
                    request.hypothesis.strategy,
                    request.protocol.round_trip_cost_pct,
                )
                fold_trades.extend(symbol_trades)
                fold_censored += symbol_censored
            summary = _summarize(fold_trades)
            fold_evidence.append(
                FoldEvidence(
                    name=fold.name,
                    window_start=fold.start,
                    window_end=fold.end,
                    censored_trades=fold_censored,
                    **summary.model_dump(),
                )
            )
            all_trades.extend(fold_trades)
            total_censored += fold_censored

        aggregate = _summarize(all_trades)
        insufficient = (
            aggregate.trades < request.protocol.min_trades
            or aggregate.symbols_with_trades < request.protocol.min_symbols
        )
        if issues:
            recommendation = Recommendation.NEEDS_MORE_EVIDENCE
            reasons = ("Snapshot integrity must pass before shadow eligibility.",)
        elif insufficient:
            recommendation = Recommendation.NEEDS_MORE_EVIDENCE
            reasons = ("The examined sample does not meet the protocol's evidence minimums.",)
        else:
            failed_expectancy = (
                aggregate.expectancy_pct is None
                or aggregate.expectancy_pct < request.protocol.min_expectancy_pct
            )
            failed_hit_rate = (
                request.protocol.min_hit_rate is not None
                and (
                    aggregate.hit_rate is None
                    or aggregate.hit_rate < request.protocol.min_hit_rate
                )
            )
            if failed_expectancy or failed_hit_rate:
                recommendation = Recommendation.REJECT
                reasons = ("The evidence fails at least one configured performance threshold.",)
            else:
                recommendation = Recommendation.ELIGIBLE_FOR_SHADOW
                reasons = ("The evidence clears the foundation protocol for a shadow trial only.",)

        dossier = EvidenceDossier(
            experiment_id=_content_id(identity),
            hypothesis_id=request.hypothesis.hypothesis_id,
            hypothesis_version=request.hypothesis.version,
            strategy_name=request.hypothesis.strategy.name,
            snapshot_id=request.snapshot.snapshot_id,
            protocol_id=request.protocol.protocol_id,
            status=DossierStatus.QUARANTINED,
            recommendation=recommendation,
            folds=tuple(fold_evidence),
            aggregate=aggregate,
            censored_trades=total_censored,
            issues=tuple(issues),
            reasons=reasons,
            limitations=(
                "Portfolio cash, concurrency, drawdown, and correlation were not simulated.",
                "Regime dependence was not examined.",
                "Multiple-hypothesis and parameter-selection bias were not corrected.",
                "Daily bars do not validate an intraday strategy.",
            ),
        )
        if self._artifact_dir is not None:
            self._persist(dossier)
        return dossier

    def _persist(self, dossier: EvidenceDossier) -> None:
        artifact_dir = Path(self._artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        digest = dossier.experiment_id.removeprefix("sha256:")
        destination = artifact_dir / f"{digest}.json"
        payload = (dossier.model_dump_json(indent=2) + "\n").encode()

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=artifact_dir, delete=False) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            try:
                os.link(temporary_path, destination)
            except FileExistsError:
                if destination.read_bytes() != payload:
                    raise RuntimeError(
                        f"experiment artifact collision or corruption: {destination}"
                    )
            else:
                destination.chmod(0o444)
                directory_fd = os.open(artifact_dir, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
