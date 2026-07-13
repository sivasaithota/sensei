"""Immutable market-data capture and admissibility checks."""

from __future__ import annotations

import hashlib
import json
from bisect import bisect_left, bisect_right
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


@dataclass(frozen=True)
class MembershipInterval:
    """A stable instrument's half-open membership interval in a universe."""

    universe: str
    instrument_id: str
    symbol: str
    effective_from: date
    effective_to: date | None = None

    def __post_init__(self) -> None:
        if not self.universe.strip():
            raise ValueError("membership universe must not be empty")
        if not self.instrument_id.strip():
            raise ValueError("membership instrument_id must not be empty")
        if not self.symbol.strip():
            raise ValueError("membership symbol must not be empty")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("membership effective_to must be after effective_from")

    def contains(self, session: date) -> bool:
        return self.effective_from <= session and (
            self.effective_to is None or session < self.effective_to
        )

    def overlaps(self, start: date, end: date) -> bool:
        return self.effective_from <= end and (
            self.effective_to is None or self.effective_to > start
        )

    def identity_payload(self) -> dict[str, str | None]:
        return {
            "universe": self.universe,
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "effective_from": self.effective_from.isoformat(),
            "effective_to": (
                self.effective_to.isoformat() if self.effective_to is not None else None
            ),
        }


@dataclass(frozen=True)
class LineageArtifact:
    role: str
    relative_path: str
    sha256: str
    byte_size: int
    row_count: int

    def identity_payload(self) -> dict[str, str | int]:
        return {
            "role": self.role,
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "byte_size": self.byte_size,
            "row_count": self.row_count,
        }


@dataclass(frozen=True)
class DataLineage:
    catalog_id: str
    issuer: str
    manifest_id: str
    provider: str
    dataset: str
    source_uri: str
    usage_rights: str
    retrieved_at: date
    calendar: str
    timezone: str
    currency: str
    adjustment_policies: tuple[str, ...]
    artifacts: tuple[LineageArtifact, ...]

    def identity_payload(self) -> dict[str, object]:
        return {
            "catalog_id": self.catalog_id,
            "issuer": self.issuer,
            "manifest_id": self.manifest_id,
            "provider": self.provider,
            "dataset": self.dataset,
            "source_uri": self.source_uri,
            "usage_rights": self.usage_rights,
            "retrieved_at": self.retrieved_at.isoformat(),
            "calendar": self.calendar,
            "timezone": self.timezone,
            "currency": self.currency,
            "adjustment_policies": list(self.adjustment_policies),
            "artifacts": [artifact.identity_payload() for artifact in self.artifacts],
        }


@dataclass(frozen=True)
class ValidatedInstrumentData:
    bars: pd.DataFrame
    entry_eligibility: pd.Series


def _direct_capture_lineage(source: str, snapshot_date: date) -> DataLineage:
    manifest_digest = hashlib.sha256(source.encode()).hexdigest()
    return DataLineage(
        catalog_id="direct-capture",
        issuer=source,
        manifest_id=f"sha256:{manifest_digest}",
        provider=source,
        dataset="direct-capture",
        source_uri="direct-capture://in-memory",
        usage_rights="caller-supplied fixture",
        retrieved_at=snapshot_date,
        calendar="unspecified",
        timezone="unspecified",
        currency="unspecified",
        adjustment_policies=("unspecified",),
        artifacts=(),
    )


SNAPSHOT_MATERIALIZER_VERSION = "1.0"
_RUNTIME_HASH_CHUNK_ROWS = 65_536


def _runtime_frame_content_id(frames: Mapping[str, pd.DataFrame]) -> str:
    digest = hashlib.sha256()
    for instrument_id, frame in frames.items():
        digest.update(instrument_id.encode())
        digest.update(repr(tuple(frame.columns)).encode())
        digest.update(repr(tuple(str(dtype) for dtype in frame.dtypes)).encode())
        for start in range(0, len(frame), _RUNTIME_HASH_CHUNK_ROWS):
            chunk = frame.iloc[start : start + _RUNTIME_HASH_CHUNK_ROWS]
            digest.update(
                pd.util.hash_pandas_object(chunk, index=True).values.tobytes()
            )
    return f"sha256:{digest.hexdigest()}"


def _snapshot_content_id(
    *,
    instrument_ids: tuple[str, ...],
    history_start: date,
    as_of: date,
    universe_as_of: date,
    point_in_time_universe: bool,
    source: str,
    memberships: Mapping[str, tuple[MembershipInterval, ...]],
    lineage: DataLineage,
    fixture_frame_content_id: str | None,
) -> str:
    metadata = {
        "materializer_version": SNAPSHOT_MATERIALIZER_VERSION,
        "history_start": history_start.isoformat(),
        "as_of": as_of.isoformat(),
        "universe_as_of": universe_as_of.isoformat(),
        "point_in_time_universe": point_in_time_universe,
        "source": source,
        "frequency": "1d",
        "instrument_ids": list(instrument_ids),
        "memberships": {
            instrument_id: [interval.identity_payload() for interval in intervals]
            for instrument_id, intervals in memberships.items()
        },
        "lineage": lineage.identity_payload(),
    }
    if fixture_frame_content_id is not None:
        metadata["fixture_frame_content_id"] = fixture_frame_content_id
    canonical = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


@dataclass(frozen=True, init=False)
class MarketDataSnapshot:
    history_start: date
    as_of: date
    universe_as_of: date
    point_in_time_universe: bool
    source: str
    snapshot_id: str
    lineage: DataLineage
    frequency: Literal["1d"] = "1d"
    __bars_by_instrument: Mapping[str, pd.DataFrame] = field(
        default_factory=dict, repr=False, compare=False
    )
    __memberships_by_instrument: Mapping[str, tuple[MembershipInterval, ...]] = field(
        default_factory=dict, repr=False, compare=False
    )
    __runtime_frame_content_id: str = field(default="", repr=False, compare=False)

    @classmethod
    def _from_catalog(
        cls,
        *,
        bars_by_instrument: Mapping[str, pd.DataFrame],
        history_start: date,
        as_of: date,
        universe_as_of: date,
        point_in_time_universe: bool,
        source: str,
        memberships_by_instrument: Mapping[str, tuple[MembershipInterval, ...]],
        lineage: DataLineage,
    ) -> MarketDataSnapshot:
        return cls._capture(
            bars_by_instrument=bars_by_instrument,
            history_start=history_start,
            as_of=as_of,
            universe_as_of=universe_as_of,
            point_in_time_universe=point_in_time_universe,
            source=source,
            memberships_by_instrument=memberships_by_instrument,
            lineage=lineage,
            copy_frames=False,
        )

    @classmethod
    def _for_testing(
        cls,
        *,
        bars_by_instrument: Mapping[str, pd.DataFrame],
        history_start: date = date.min,
        as_of: date,
        universe_as_of: date,
        point_in_time_universe: bool,
        source: str,
        memberships_by_instrument: Mapping[
            str, tuple[MembershipInterval, ...]
        ]
        | None = None,
    ) -> MarketDataSnapshot:
        return cls._capture(
            bars_by_instrument=bars_by_instrument,
            history_start=history_start,
            as_of=as_of,
            universe_as_of=universe_as_of,
            point_in_time_universe=point_in_time_universe,
            source=source,
            memberships_by_instrument=memberships_by_instrument,
            lineage=_direct_capture_lineage(source, as_of),
            copy_frames=True,
        )

    @classmethod
    def _capture(
        cls,
        *,
        bars_by_instrument: Mapping[str, pd.DataFrame],
        history_start: date,
        as_of: date,
        universe_as_of: date,
        point_in_time_universe: bool,
        source: str,
        memberships_by_instrument: Mapping[
            str, tuple[MembershipInterval, ...]
        ]
        | None,
        lineage: DataLineage,
        copy_frames: bool,
    ) -> MarketDataSnapshot:
        if not bars_by_instrument:
            raise ValueError("a market data snapshot needs at least one symbol")
        if not source.strip():
            raise ValueError("market data source must not be empty")
        if history_start > as_of:
            raise ValueError("snapshot history_start must not be after as_of")

        captured = {
            instrument_id: frame.copy(deep=True) if copy_frames else frame
            for instrument_id, frame in sorted(bars_by_instrument.items())
        }
        captured_memberships = _capture_memberships(
            tuple(captured), memberships_by_instrument
        )
        runtime_frame_content_id = _runtime_frame_content_id(captured)
        snapshot = object.__new__(cls)
        object.__setattr__(snapshot, "history_start", history_start)
        object.__setattr__(snapshot, "as_of", as_of)
        object.__setattr__(snapshot, "universe_as_of", universe_as_of)
        object.__setattr__(snapshot, "point_in_time_universe", point_in_time_universe)
        object.__setattr__(snapshot, "source", source)
        object.__setattr__(snapshot, "lineage", lineage)
        object.__setattr__(snapshot, "frequency", "1d")
        object.__setattr__(
            snapshot,
            "snapshot_id",
            _snapshot_content_id(
                instrument_ids=tuple(captured),
                history_start=history_start,
                as_of=as_of,
                universe_as_of=universe_as_of,
                point_in_time_universe=point_in_time_universe,
                source=source,
                memberships=captured_memberships,
                lineage=lineage,
                fixture_frame_content_id=(
                    runtime_frame_content_id if not lineage.artifacts else None
                ),
            ),
        )
        object.__setattr__(
            snapshot,
            "_MarketDataSnapshot__bars_by_instrument",
            MappingProxyType(captured),
        )
        object.__setattr__(
            snapshot,
            "_MarketDataSnapshot__memberships_by_instrument",
            MappingProxyType(captured_memberships),
        )
        object.__setattr__(
            snapshot,
            "_MarketDataSnapshot__runtime_frame_content_id",
            runtime_frame_content_id,
        )
        return snapshot

    @property
    def symbols(self) -> tuple[str, ...]:
        result: list[str] = []
        for instrument_id in self.instrument_ids:
            intervals = self.__memberships_by_instrument[instrument_id]
            active = next(
                (
                    interval
                    for interval in intervals
                    if interval.contains(self.as_of)
                ),
                intervals[-1],
            )
            result.append(active.symbol)
        return tuple(result)

    @property
    def instrument_ids(self) -> tuple[str, ...]:
        return tuple(self.__bars_by_instrument)

    def membership_intervals(
        self, instrument_id: str
    ) -> tuple[MembershipInterval, ...]:
        try:
            return self.__memberships_by_instrument[instrument_id]
        except KeyError as exc:
            raise KeyError(f"unknown instrument_id: {instrument_id}") from exc

    def frame(self, instrument_id: str) -> pd.DataFrame:
        try:
            return self._verified_frame_copies()[instrument_id]
        except KeyError as exc:
            raise KeyError(f"unknown instrument_id: {instrument_id}") from exc

    def entry_eligible_on(self, instrument_id: str, session: date) -> bool:
        return any(
            interval.contains(session)
            for interval in self.membership_intervals(instrument_id)
        )

    def validated_frames(
        self, protocol: ExaminationProtocol
    ) -> tuple[dict[str, ValidatedInstrumentData], tuple[EvidenceIssue, ...]]:
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
        issues.extend(
            _universe_coverage_issues(
                self.__memberships_by_instrument,
                protocol,
            )
        )

        valid_frames: dict[str, ValidatedInstrumentData] = {}
        for instrument_id, frame in frames.items():
            intervals = self.__memberships_by_instrument[instrument_id]
            frame_issues = _validate_frame(instrument_id, frame, as_of=self.as_of)
            entry_eligibility: pd.Series | None = None
            if not frame_issues:
                entry_eligibility = _entry_eligibility(frame.index, intervals)
                frame_issues.extend(
                    _coverage_issues(
                        instrument_id,
                        intervals,
                        entry_eligibility,
                        protocol,
                    )
                )
            issues.extend(frame_issues)
            if not frame_issues and entry_eligibility is not None:
                valid_frames[instrument_id] = ValidatedInstrumentData(
                    bars=frame,
                    entry_eligibility=entry_eligibility,
                )
        return valid_frames, tuple(issues)

    def _verified_frame_copies(self) -> dict[str, pd.DataFrame]:
        runtime_frame_content_id = _runtime_frame_content_id(
            self.__bars_by_instrument
        )
        if runtime_frame_content_id != self.__runtime_frame_content_id:
            raise ValueError("market data snapshot content changed after capture")
        current_id = _snapshot_content_id(
            instrument_ids=tuple(self.__bars_by_instrument),
            history_start=self.history_start,
            as_of=self.as_of,
            universe_as_of=self.universe_as_of,
            point_in_time_universe=self.point_in_time_universe,
            source=self.source,
            memberships=self.__memberships_by_instrument,
            lineage=self.lineage,
            fixture_frame_content_id=(
                runtime_frame_content_id if not self.lineage.artifacts else None
            ),
        )
        if current_id != self.snapshot_id:
            raise ValueError("market data snapshot content changed after capture")
        return {
            instrument_id: frame.copy(deep=True)
            for instrument_id, frame in self.__bars_by_instrument.items()
        }


def _capture_memberships(
    instrument_ids: tuple[str, ...],
    memberships: Mapping[str, tuple[MembershipInterval, ...]] | None,
) -> dict[str, tuple[MembershipInterval, ...]]:
    if memberships is None:
        return {
            instrument_id: (
                MembershipInterval(
                    universe="direct-capture",
                    instrument_id=instrument_id,
                    symbol=instrument_id,
                    effective_from=date.min,
                ),
            )
            for instrument_id in instrument_ids
        }

    if set(memberships) != set(instrument_ids):
        raise ValueError("membership instruments must exactly match captured bars")
    captured: dict[str, tuple[MembershipInterval, ...]] = {}
    for instrument_id in sorted(instrument_ids):
        intervals = tuple(
            sorted(
                memberships[instrument_id],
                key=lambda interval: (
                    interval.effective_from,
                    interval.effective_to or date.max,
                    interval.symbol,
                ),
            )
        )
        if not intervals:
            raise ValueError(f"{instrument_id} has no membership intervals")
        for interval in intervals:
            if interval.instrument_id != instrument_id:
                raise ValueError("membership interval instrument_id does not match key")
        for previous, current in zip(intervals, intervals[1:]):
            if previous.effective_to is None or previous.effective_to > current.effective_from:
                raise ValueError(f"{instrument_id} has overlapping membership intervals")
        captured[instrument_id] = intervals
    return captured


def _coverage_issues(
    instrument_id: str,
    intervals: tuple[MembershipInterval, ...],
    entry_eligibility: pd.Series,
    protocol: ExaminationProtocol,
) -> list[EvidenceIssue]:
    eligible_dates = tuple(
        timestamp.date()
        for timestamp, is_eligible in zip(
            entry_eligibility.index,
            entry_eligibility.to_numpy(dtype=bool),
        )
        if is_eligible
    )
    for fold in protocol.folds:
        if not _intervals_overlap(intervals, fold.start, fold.end):
            continue
        sessions = (
            bisect_right(eligible_dates, fold.end)
            - bisect_left(eligible_dates, fold.start)
        )
        if sessions < protocol.min_sessions_per_fold:
            return [
                EvidenceIssue(
                    code=EvidenceIssueCode.INSUFFICIENT_FOLD_COVERAGE,
                    symbol=instrument_id,
                    detail=(
                        f"Fold {fold.name!r} has {sessions} sessions; "
                        f"the protocol requires {protocol.min_sessions_per_fold}."
                    ),
                )
            ]
    return []


def _entry_eligibility(
    index: pd.DatetimeIndex,
    intervals: tuple[MembershipInterval, ...],
) -> pd.Series:
    values = np.zeros(len(index), dtype=bool)
    interval_position = 0
    for row_position, timestamp in enumerate(index):
        session = timestamp.date()
        while interval_position < len(intervals):
            effective_to = intervals[interval_position].effective_to
            if effective_to is None or session < effective_to:
                break
            interval_position += 1
        if interval_position == len(intervals):
            break
        interval = intervals[interval_position]
        values[row_position] = interval.contains(session)
    return pd.Series(values, index=index, dtype=bool)


def _intervals_overlap(
    intervals: tuple[MembershipInterval, ...],
    start: date,
    end: date,
) -> bool:
    position = bisect_right(
        intervals,
        end,
        key=lambda interval: interval.effective_from,
    ) - 1
    return position >= 0 and intervals[position].overlaps(start, end)


def _universe_coverage_issues(
    memberships: Mapping[str, tuple[MembershipInterval, ...]],
    protocol: ExaminationProtocol,
) -> list[EvidenceIssue]:
    issues: list[EvidenceIssue] = []
    for fold in protocol.folds:
        if any(
            _intervals_overlap(intervals, fold.start, fold.end)
            for intervals in memberships.values()
        ):
            continue
        issues.append(
            EvidenceIssue(
                code=EvidenceIssueCode.INSUFFICIENT_FOLD_COVERAGE,
                detail=(
                    f"Fold {fold.name!r} has no point-in-time universe membership; "
                    "the fold cannot produce admissible evidence."
                ),
            )
        )
    return issues


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
    session_dates = pd.Index(frame.index.date)
    if (
        not frame.index.is_monotonic_increasing
        or not frame.index.is_unique
        or not session_dates.is_unique
    ):
        return [
            EvidenceIssue(
                code=EvidenceIssueCode.INVALID_INDEX,
                symbol=symbol,
                detail=(
                    "Daily bars must have one strictly increasing row per "
                    "market session."
                ),
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
