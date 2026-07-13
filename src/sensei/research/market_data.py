"""Immutable market-data capture and admissibility checks."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType
from typing import Literal, Mapping

import numpy as np
import pandas as pd

from sensei.research.models import (
    EvidenceIssue,
    EvidenceIssueCode,
    ExaminationProtocol,
)


def _snapshot_content_id(
    *,
    frames: Mapping[str, pd.DataFrame],
    as_of: date,
    universe_as_of: date,
    point_in_time_universe: bool,
    source: str,
) -> str:
    digest = hashlib.sha256()
    metadata = {
        "as_of": as_of.isoformat(),
        "universe_as_of": universe_as_of.isoformat(),
        "point_in_time_universe": point_in_time_universe,
        "source": source,
        "frequency": "1d",
        "symbols": list(frames),
    }
    digest.update(json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode())
    for symbol, frame in frames.items():
        digest.update(symbol.encode())
        digest.update(repr(tuple(frame.columns)).encode())
        digest.update(repr(tuple(str(dtype) for dtype in frame.dtypes)).encode())
        digest.update(pd.util.hash_pandas_object(frame, index=True).values.tobytes())
    return f"sha256:{digest.hexdigest()}"


@dataclass(frozen=True, init=False)
class MarketDataSnapshot:
    as_of: date
    universe_as_of: date
    point_in_time_universe: bool
    source: str
    snapshot_id: str
    frequency: Literal["1d"] = "1d"
    __bars_by_symbol: Mapping[str, pd.DataFrame] = field(
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
        snapshot = object.__new__(cls)
        object.__setattr__(snapshot, "as_of", as_of)
        object.__setattr__(snapshot, "universe_as_of", universe_as_of)
        object.__setattr__(snapshot, "point_in_time_universe", point_in_time_universe)
        object.__setattr__(snapshot, "source", source)
        object.__setattr__(snapshot, "frequency", "1d")
        object.__setattr__(
            snapshot,
            "snapshot_id",
            _snapshot_content_id(
                frames=captured,
                as_of=as_of,
                universe_as_of=universe_as_of,
                point_in_time_universe=point_in_time_universe,
                source=source,
            ),
        )
        object.__setattr__(
            snapshot,
            "_MarketDataSnapshot__bars_by_symbol",
            MappingProxyType(captured),
        )
        return snapshot

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(self.__bars_by_symbol)

    def validated_frames(
        self, protocol: ExaminationProtocol
    ) -> tuple[dict[str, pd.DataFrame], tuple[EvidenceIssue, ...]]:
        frames = self._verified_frame_copies()
        issues: list[EvidenceIssue] = []
        if not self.point_in_time_universe:
            issues.append(
                EvidenceIssue(
                    code=EvidenceIssueCode.UNIVERSE_NOT_POINT_IN_TIME,
                    detail=(
                        "The snapshot does not prove point-in-time universe membership; "
                        "survivorship bias can invalidate the evidence."
                    ),
                )
            )

        valid_frames: dict[str, pd.DataFrame] = {}
        for symbol, frame in frames.items():
            frame_issues = _validate_frame(symbol, frame, as_of=self.as_of)
            if not frame_issues:
                frame_issues.extend(_coverage_issues(symbol, frame, protocol))
            issues.extend(frame_issues)
            if not frame_issues:
                valid_frames[symbol] = frame
        return valid_frames, tuple(issues)

    def _verified_frame_copies(self) -> dict[str, pd.DataFrame]:
        current_id = _snapshot_content_id(
            frames=self.__bars_by_symbol,
            as_of=self.as_of,
            universe_as_of=self.universe_as_of,
            point_in_time_universe=self.point_in_time_universe,
            source=self.source,
        )
        if current_id != self.snapshot_id:
            raise ValueError("market data snapshot content changed after capture")
        return {
            symbol: frame.copy(deep=True)
            for symbol, frame in self.__bars_by_symbol.items()
        }


def _coverage_issues(
    symbol: str, frame: pd.DataFrame, protocol: ExaminationProtocol
) -> list[EvidenceIssue]:
    for fold in protocol.folds:
        sessions = sum(
            fold.start <= timestamp.date() <= fold.end for timestamp in frame.index
        )
        if sessions < protocol.min_sessions_per_fold:
            return [
                EvidenceIssue(
                    code=EvidenceIssueCode.INSUFFICIENT_FOLD_COVERAGE,
                    symbol=symbol,
                    detail=(
                        f"Fold {fold.name!r} has {sessions} sessions; "
                        f"the protocol requires {protocol.min_sessions_per_fold}."
                    ),
                )
            ]
    return []


def _validate_frame(
    symbol: str, frame: pd.DataFrame, *, as_of: date
) -> list[EvidenceIssue]:
    required = ("open", "high", "low", "close", "volume")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        return [
            EvidenceIssue(
                code=EvidenceIssueCode.MISSING_COLUMNS,
                symbol=symbol,
                detail=f"Required columns are missing: {', '.join(missing)}.",
            )
        ]
    if not isinstance(frame.index, pd.DatetimeIndex):
        return [
            EvidenceIssue(
                code=EvidenceIssueCode.INVALID_INDEX,
                symbol=symbol,
                detail="Bars must use a DatetimeIndex.",
            )
        ]
    if frame.empty:
        return [
            EvidenceIssue(
                code=EvidenceIssueCode.EMPTY,
                symbol=symbol,
                detail="The symbol has no bars.",
            )
        ]
    if not frame.index.is_monotonic_increasing or not frame.index.is_unique:
        return [
            EvidenceIssue(
                code=EvidenceIssueCode.INVALID_INDEX,
                symbol=symbol,
                detail="Bar sessions must be strictly increasing and unique.",
            )
        ]
    if any(timestamp.date() > as_of for timestamp in frame.index):
        return [
            EvidenceIssue(
                code=EvidenceIssueCode.AFTER_SNAPSHOT_AS_OF,
                symbol=symbol,
                detail="The frame contains a session after the snapshot as-of date.",
            )
        ]

    try:
        values = frame.loc[:, required].to_numpy(dtype=float)
    except (TypeError, ValueError):
        return [
            EvidenceIssue(
                code=EvidenceIssueCode.NON_NUMERIC,
                symbol=symbol,
                detail="OHLCV values must be numeric.",
            )
        ]
    if not np.isfinite(values).all():
        return [
            EvidenceIssue(
                code=EvidenceIssueCode.NON_FINITE,
                symbol=symbol,
                detail="OHLCV values must be finite.",
            )
        ]

    o, h, l, c, volume = (frame[column].to_numpy(dtype=float) for column in required)
    if (np.column_stack((o, h, l, c)) <= 0).any():
        return [
            EvidenceIssue(
                code=EvidenceIssueCode.NON_POSITIVE_PRICE,
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
                code=EvidenceIssueCode.INVALID_OHLC,
                symbol=symbol,
                detail="High/low does not contain the session's open and close.",
            )
        ]
    if (volume < 0).any():
        return [
            EvidenceIssue(
                code=EvidenceIssueCode.NEGATIVE_VOLUME,
                symbol=symbol,
                detail="Volume must not be negative.",
            )
        ]
    return []
