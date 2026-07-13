"""Offline materialization of immutable point-in-time market-data snapshots."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date
from io import StringIO
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Protocol

import pandas as pd

from sensei.research.errors import SnapshotIntegrityError
from sensei.research.local_artifacts import (
    inspect_parquet,
    materialize_daily_bars,
    read_regular_file,
)
from sensei.research.market_data import (
    DataLineage,
    LineageArtifact,
    MarketDataSnapshot,
    MembershipInterval,
)

_CONTENT_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SUPPORTED_ADJUSTMENTS = frozenset(
    {"split_adjusted", "split_and_dividend_adjusted"}
)
_MAX_MANIFEST_BYTES = 8_000_000
_MAX_MEMBERSHIP_BYTES = 16_000_000
_MAX_BAR_BYTES = 512_000_000
_MAX_CORPORATE_ACTION_BYTES = 256_000_000
_MAX_CORPORATE_ACTION_CSV_BYTES = 16_000_000
_MAX_INSTRUMENTS = 20_000
_MAX_MEMBERSHIP_ROWS = 500_000
_MAX_TOTAL_COMPRESSED_BYTES = 1_500_000_000
_MAX_TOTAL_DECODED_BYTES = 1_500_000_000
_MAX_TOTAL_ROWS = 10_000_000
_MAX_PARQUET_COLUMNS = 64


@dataclass(frozen=True)
class SnapshotRequest:
    universe: str
    history_start: date
    as_of: date
    frequency: str = "1d"

    def __post_init__(self) -> None:
        if not self.universe.strip():
            raise ValueError("snapshot universe must not be empty")
        if self.history_start > self.as_of:
            raise ValueError("history_start must be on or before as_of")
        if self.frequency != "1d":
            raise ValueError("the research catalog currently supports daily bars only")


class MarketDataCatalog(Protocol):
    def snapshot(self, request: SnapshotRequest) -> MarketDataSnapshot: ...


class ManifestMarketDataCatalog:
    """Read one versioned manifest and its verified local artifacts."""

    def __init__(
        self,
        *,
        manifest_path: Path,
        trusted_issuers: set[str] | frozenset[str] = frozenset(),
        trusted_manifest_ids: set[str] | frozenset[str] = frozenset(),
    ) -> None:
        self._manifest_path = Path(manifest_path)
        self._root = self._manifest_path.parent.resolve()
        self._trusted_issuers = frozenset(trusted_issuers)
        self._trusted_manifest_ids = frozenset(trusted_manifest_ids)
        if any(
            _CONTENT_ID.fullmatch(manifest_id) is None
            for manifest_id in self._trusted_manifest_ids
        ):
            raise ValueError("trusted manifest IDs must be lowercase SHA-256 content IDs")

    def snapshot(self, request: SnapshotRequest) -> MarketDataSnapshot:
        manifest_bytes = read_regular_file(
            self._manifest_path, max_bytes=_MAX_MANIFEST_BYTES
        )
        try:
            manifest = json.loads(
                manifest_bytes, object_pairs_hook=_manifest_object
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SnapshotIntegrityError("manifest must be valid UTF-8 JSON") from exc
        if not isinstance(manifest, dict):
            raise SnapshotIntegrityError("manifest root must be an object")
        _require_equal(manifest, "schema_version", 1)
        manifest_id = _canonical_manifest_id(manifest)

        market = _object(manifest, "market")
        _require_equal(market, "frequency", request.frequency)
        issuer = _text(manifest, "issuer")
        source = _object(manifest, "source")
        retrieved_at = _iso_date(source, "retrieved_at")
        if request.as_of > retrieved_at:
            raise SnapshotIntegrityError(
                "snapshot as-of exceeds the manifest retrieval coverage"
            )

        membership_ref = _artifact_ref(_object(manifest, "membership"))
        if membership_ref.row_count > _MAX_MEMBERSHIP_ROWS:
            raise SnapshotIntegrityError(
                "membership row count exceeds safety limit"
            )
        total_compressed_bytes = membership_ref.byte_size
        total_rows = membership_ref.row_count
        _enforce_budget(
            total_compressed_bytes,
            _MAX_TOTAL_COMPRESSED_BYTES,
            "total compressed bytes",
        )
        _enforce_budget(total_rows, _MAX_TOTAL_ROWS, "total rows")
        membership_bytes = self._verified_artifact(
            membership_ref,
            expected_suffix=".csv",
            max_bytes=_MAX_MEMBERSHIP_BYTES,
        )
        memberships, membership_rows, total_decoded_bytes = _read_memberships(
            membership_bytes,
            expected_rows=membership_ref.row_count,
        )
        _enforce_budget(
            total_decoded_bytes, _MAX_TOTAL_DECODED_BYTES, "total decoded bytes"
        )
        if membership_rows != membership_ref.row_count:
            raise SnapshotIntegrityError(
                "membership row count does not match its manifest"
            )
        _validate_membership_intervals(memberships)
        total_retained_bar_bytes = 0

        relevant = tuple(
            interval
            for interval in memberships
            if interval.universe == request.universe
            and interval.overlaps(request.history_start, request.as_of)
        )
        if not relevant:
            raise SnapshotIntegrityError(
                f"manifest has no membership for universe {request.universe!r} "
                "during the requested period"
            )
        memberships_by_instrument = _group_memberships(relevant)

        instrument_records = _instrument_records(manifest)
        membership_instruments = {
            interval.instrument_id for interval in memberships
        }
        missing = sorted(membership_instruments - set(instrument_records))
        if missing:
            raise SnapshotIntegrityError(
                "membership references instruments absent from the manifest: "
                + ", ".join(missing)
            )
        unreferenced = sorted(set(instrument_records) - membership_instruments)
        if unreferenced:
            raise SnapshotIntegrityError(
                "unreferenced instrument records in manifest: "
                + ", ".join(unreferenced)
            )

        bars_by_instrument: dict[str, pd.DataFrame] = {}
        artifacts = [
            LineageArtifact(
                role="membership",
                relative_path=membership_ref.relative_path,
                sha256=membership_ref.sha256,
                byte_size=membership_ref.byte_size,
                row_count=membership_ref.row_count,
            )
        ]
        artifact_paths = {membership_ref.relative_path}
        adjustment_policies: set[str] = set()
        for instrument_id in sorted(memberships_by_instrument):
            record = instrument_records[instrument_id]
            policy = _text(record, "adjustment_policy")
            if policy not in _SUPPORTED_ADJUSTMENTS:
                raise SnapshotIntegrityError(
                    f"unsupported adjustment policy for {instrument_id}: {policy}"
                )
            adjustment_policies.add(policy)
            bars_ref = _artifact_ref(_object(record, "bars"))
            actions_ref = _optional_actions_ref(record, instrument_id)
            references = (bars_ref,) + (
                (actions_ref,) if actions_ref is not None else ()
            )
            for reference in references:
                if reference.relative_path in artifact_paths:
                    raise SnapshotIntegrityError(
                        f"duplicate artifact path: {reference.relative_path}"
                    )
                artifact_paths.add(reference.relative_path)
            total_compressed_bytes += bars_ref.byte_size + (
                actions_ref.byte_size if actions_ref is not None else 0
            )
            total_rows += bars_ref.row_count + (
                actions_ref.row_count if actions_ref is not None else 0
            )
            _enforce_budget(
                total_compressed_bytes,
                _MAX_TOTAL_COMPRESSED_BYTES,
                "total compressed bytes",
            )
            _enforce_budget(total_rows, _MAX_TOTAL_ROWS, "total rows")
            bars_bytes = self._verified_artifact(
                bars_ref,
                expected_suffix=".parquet",
                max_bytes=_MAX_BAR_BYTES,
            )
            bars_label = f"bar artifact for {instrument_id}"
            materialized = materialize_daily_bars(
                bars_bytes,
                label=bars_label,
                expected_rows=bars_ref.row_count,
                history_start=request.history_start,
                as_of=request.as_of,
                available_working_bytes=(
                    _MAX_TOTAL_DECODED_BYTES - total_decoded_bytes
                ),
                max_columns=_MAX_PARQUET_COLUMNS,
            )
            frame = materialized.frame
            total_decoded_bytes += materialized.retained_bytes
            total_retained_bar_bytes += materialized.retained_bytes
            _enforce_budget(
                total_decoded_bytes + total_retained_bar_bytes,
                _MAX_TOTAL_DECODED_BYTES,
                "snapshot copy working set",
            )
            if frame.empty:
                raise SnapshotIntegrityError(
                    f"bar artifact has no requested sessions for {instrument_id}"
                )
            unmatched = _first_membership_without_matching_bar(
                frame.index,
                memberships_by_instrument[instrument_id],
            )
            if unmatched is not None:
                raise SnapshotIntegrityError(
                    f"membership interval has no matching bars for "
                    f"{instrument_id} from {unmatched.effective_from}"
                )
            bars_by_instrument[instrument_id] = frame
            artifacts.append(
                LineageArtifact(
                    role=f"bars:{instrument_id}",
                    relative_path=bars_ref.relative_path,
                    sha256=bars_ref.sha256,
                    byte_size=bars_ref.byte_size,
                    row_count=bars_ref.row_count,
                )
            )
            if actions_ref is not None:
                suffix = PurePosixPath(actions_ref.relative_path).suffix
                actions_bytes = self._verified_artifact(
                    actions_ref,
                    expected_suffix=suffix,
                    max_bytes=(
                        _MAX_CORPORATE_ACTION_BYTES
                        if suffix == ".parquet"
                        else _MAX_CORPORATE_ACTION_CSV_BYTES
                    ),
                )
                actions_label = f"corporate actions for {instrument_id}"
                if suffix == ".parquet":
                    usage = inspect_parquet(
                        actions_bytes,
                        label=actions_label,
                        expected_rows=actions_ref.row_count,
                    )
                    if usage.column_count > _MAX_PARQUET_COLUMNS:
                        raise SnapshotIntegrityError(
                            f"{actions_label} column count exceeds safety limit"
                        )
                    actions_memory = len(actions_bytes)
                else:
                    actions_memory = _bounded_csv_size(
                        actions_bytes,
                        label=actions_label,
                        expected_rows=actions_ref.row_count,
                    )
                _enforce_budget(
                    total_decoded_bytes + actions_memory,
                    _MAX_TOTAL_DECODED_BYTES,
                    "corporate-action working set",
                )
                artifacts.append(
                    LineageArtifact(
                        role=f"corporate-actions:{instrument_id}",
                        relative_path=actions_ref.relative_path,
                        sha256=actions_ref.sha256,
                        byte_size=actions_ref.byte_size,
                        row_count=actions_ref.row_count,
                    )
                )

        if len(adjustment_policies) != 1:
            raise SnapshotIntegrityError(
                "mixed adjustment policies cannot form one market-data snapshot"
            )

        lineage = DataLineage(
            catalog_id=_text(manifest, "catalog_id"),
            issuer=issuer,
            manifest_id=manifest_id,
            provider=_text(source, "provider"),
            dataset=_text(source, "dataset"),
            source_uri=_text(source, "uri"),
            usage_rights=_text(source, "usage_rights"),
            retrieved_at=retrieved_at,
            calendar=_text(market, "calendar"),
            timezone=_text(market, "timezone"),
            currency=_text(market, "currency"),
            adjustment_policies=tuple(sorted(adjustment_policies)),
            artifacts=tuple(artifacts),
        )
        source_label = f"{lineage.provider}/{lineage.dataset}"
        return MarketDataSnapshot._from_catalog(
            bars_by_instrument=bars_by_instrument,
            history_start=request.history_start,
            as_of=request.as_of,
            universe_as_of=request.as_of,
            point_in_time_universe=(
                issuer in self._trusted_issuers
                and manifest_id in self._trusted_manifest_ids
            ),
            source=source_label,
            memberships_by_instrument=memberships_by_instrument,
            lineage=lineage,
        )

    def _verified_artifact(
        self,
        reference: _ArtifactReference,
        *,
        expected_suffix: str,
        max_bytes: int,
    ) -> bytes:
        if reference.byte_size > max_bytes:
            raise SnapshotIntegrityError(
                f"artifact exceeds safety limit: {reference.relative_path}"
            )
        path = _contained_path(
            self._root, reference.relative_path, expected_suffix=expected_suffix
        )
        content = read_regular_file(path, max_bytes=max_bytes)
        if len(content) != reference.byte_size:
            raise SnapshotIntegrityError(
                f"artifact size does not match manifest: {reference.relative_path}"
            )
        actual = f"sha256:{hashlib.sha256(content).hexdigest()}"
        if actual != reference.sha256:
            raise SnapshotIntegrityError(
                f"artifact hash does not match manifest: {reference.relative_path}"
            )
        return content


@dataclass(frozen=True)
class _ArtifactReference:
    relative_path: str
    sha256: str
    byte_size: int
    row_count: int


def _artifact_ref(value: Mapping[str, Any]) -> _ArtifactReference:
    relative_path = _text(value, "path")
    sha256 = _text(value, "sha256")
    if _CONTENT_ID.fullmatch(sha256) is None:
        raise SnapshotIntegrityError("artifact sha256 must be a lowercase content ID")
    byte_size = _positive_int(value, "bytes")
    row_count = _positive_int(value, "rows")
    return _ArtifactReference(relative_path, sha256, byte_size, row_count)


def _canonical_manifest_id(manifest: Mapping[str, Any]) -> str:
    try:
        canonical = json.dumps(
            manifest,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SnapshotIntegrityError("manifest values must be canonical JSON") from exc
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _manifest_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SnapshotIntegrityError(f"duplicate manifest key: {key}")
        result[key] = value
    return result


def _optional_actions_ref(
    record: Mapping[str, Any], instrument_id: str
) -> _ArtifactReference | None:
    value = record.get("corporate_actions")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise SnapshotIntegrityError(
            f"corporate_actions for {instrument_id} must be an object"
        )
    reference = _artifact_ref(value)
    if PurePosixPath(reference.relative_path).suffix not in {".csv", ".parquet"}:
        raise SnapshotIntegrityError(
            "corporate-action artifacts must be CSV or Parquet"
        )
    return reference


def _enforce_budget(value: int, limit: int, label: str) -> None:
    if value > limit:
        raise SnapshotIntegrityError(f"{label} exceeds safety limit")


def _bounded_csv_size(
    content: bytes,
    *,
    label: str,
    expected_rows: int,
) -> int:
    """Validate a small CSV without constructing an unbounded object table."""

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SnapshotIntegrityError(f"{label} must be valid UTF-8 CSV") from exc

    try:
        reader = csv.reader(StringIO(text, newline=""), strict=True)
        header = next(reader, None)
        if not header or any(not column.strip() for column in header):
            raise SnapshotIntegrityError(f"{label} needs a non-empty header")
        if len(header) > _MAX_PARQUET_COLUMNS:
            raise SnapshotIntegrityError(
                f"{label} column count exceeds safety limit"
            )
        if len(set(header)) != len(header):
            raise SnapshotIntegrityError(f"{label} has duplicate columns")

        row_count = 0
        for row in reader:
            row_count += 1
            if len(row) != len(header):
                raise SnapshotIntegrityError(
                    f"{label} row {reader.line_num} has the wrong column count"
                )
            if row_count > expected_rows:
                raise SnapshotIntegrityError(
                    f"{label} row count exceeds its manifest"
                )
    except csv.Error as exc:
        raise SnapshotIntegrityError(f"cannot read {label} CSV") from exc

    if row_count != expected_rows:
        raise SnapshotIntegrityError(f"{label} row count does not match manifest")

    # StringIO may retain its own decoded buffer while parsing. Count both the
    # decoded string and a conservative second copy toward the aggregate budget.
    return 2 * sys.getsizeof(text)


def _contained_path(root: Path, value: str, *, expected_suffix: str) -> Path:
    if "\\" in value or "\x00" in value:
        raise SnapshotIntegrityError("artifact path contains forbidden characters")
    if any(segment in {"", ".", ".."} for segment in value.split("/")):
        raise SnapshotIntegrityError("artifact path is not a permitted relative path")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.suffix != expected_suffix
    ):
        raise SnapshotIntegrityError("artifact path is not a permitted relative path")
    path = root.joinpath(*relative.parts)
    candidate = root
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise SnapshotIntegrityError("artifact path must not contain a symlink")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise SnapshotIntegrityError(f"artifact does not exist: {value}") from exc
    if resolved.parent != root and root not in resolved.parents:
        raise SnapshotIntegrityError("artifact path escapes the catalog root")
    return path


def _read_memberships(
    content: bytes,
    *,
    expected_rows: int,
) -> tuple[tuple[MembershipInterval, ...], int, int]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SnapshotIntegrityError(
            "membership artifact must be valid UTF-8 CSV"
        ) from exc
    required = (
        "universe",
        "instrument_id",
        "symbol",
        "effective_from",
        "effective_to",
    )
    intervals: list[MembershipInterval] = []
    retained_bytes = 0
    try:
        reader = csv.DictReader(StringIO(text, newline=""), strict=True)
        if tuple(reader.fieldnames or ()) != required:
            raise SnapshotIntegrityError(
                "membership columns must exactly match the version-one schema"
            )
        for row in reader:
            row_number = reader.line_num
            if len(intervals) >= expected_rows:
                raise SnapshotIntegrityError(
                    "membership row count exceeds its manifest"
                )
            if None in row or any(row.get(column) is None for column in required):
                raise SnapshotIntegrityError(
                    f"invalid membership row {row_number}: wrong column count"
                )
            try:
                interval = MembershipInterval(
                    universe=row["universe"],
                    instrument_id=row["instrument_id"],
                    symbol=row["symbol"],
                    effective_from=date.fromisoformat(row["effective_from"]),
                    effective_to=(
                        date.fromisoformat(row["effective_to"])
                        if row["effective_to"]
                        else None
                    ),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise SnapshotIntegrityError(
                    f"invalid membership row {row_number}: {exc}"
                ) from exc
            intervals.append(interval)
            retained_bytes += _membership_interval_size(interval)
            _enforce_budget(
                2 * sys.getsizeof(text)
                + sys.getsizeof(intervals)
                + retained_bytes,
                _MAX_TOTAL_DECODED_BYTES,
                "total decoded bytes",
            )
    except csv.Error as exc:
        raise SnapshotIntegrityError("cannot read membership artifact") from exc

    if len(intervals) != expected_rows:
        raise SnapshotIntegrityError(
            "membership row count does not match its manifest"
        )

    decoded_bytes = (
        2 * sys.getsizeof(text) + sys.getsizeof(intervals) + retained_bytes
    )
    return tuple(intervals), len(intervals), decoded_bytes


def _membership_interval_size(interval: MembershipInterval) -> int:
    values = (
        interval,
        interval.universe,
        interval.instrument_id,
        interval.symbol,
        interval.effective_from,
        interval.effective_to,
    )
    return sum(sys.getsizeof(value) for value in values if value is not None)


def _group_memberships(
    intervals: tuple[MembershipInterval, ...],
) -> dict[str, tuple[MembershipInterval, ...]]:
    grouped: dict[str, list[MembershipInterval]] = {}
    for interval in intervals:
        grouped.setdefault(interval.instrument_id, []).append(interval)
    result: dict[str, tuple[MembershipInterval, ...]] = {}
    for instrument_id, values in sorted(grouped.items()):
        result[instrument_id] = tuple(
            sorted(values, key=lambda item: (item.effective_from, item.effective_to or date.max))
        )
    return result


def _first_membership_without_matching_bar(
    index: pd.DatetimeIndex,
    intervals: tuple[MembershipInterval, ...],
) -> MembershipInterval | None:
    starts = tuple(interval.effective_from for interval in intervals)
    matched = [False] * len(intervals)
    remaining = len(intervals)
    for timestamp in index:
        position = bisect_right(starts, timestamp.date()) - 1
        if position < 0 or matched[position]:
            continue
        if intervals[position].contains(timestamp.date()):
            matched[position] = True
            remaining -= 1
            if remaining == 0:
                return None
    return next(
        (interval for interval, was_matched in zip(intervals, matched) if not was_matched),
        None,
    )


def _validate_membership_intervals(
    intervals: tuple[MembershipInterval, ...],
) -> None:
    grouped: dict[tuple[str, str], list[MembershipInterval]] = {}
    for interval in intervals:
        grouped.setdefault((interval.universe, interval.instrument_id), []).append(
            interval
        )
    for (universe, instrument_id), values in grouped.items():
        ordered = sorted(
            values,
            key=lambda item: (item.effective_from, item.effective_to or date.max),
        )
        for previous, current in zip(ordered, ordered[1:]):
            if previous.effective_to is None or previous.effective_to > current.effective_from:
                raise SnapshotIntegrityError(
                    f"overlapping membership intervals for {instrument_id} "
                    f"in {universe}"
                )


def _instrument_records(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw = manifest.get("instruments")
    if not isinstance(raw, list) or not raw:
        raise SnapshotIntegrityError("manifest instruments must be a non-empty array")
    if len(raw) > _MAX_INSTRUMENTS:
        raise SnapshotIntegrityError("manifest instrument count exceeds safety limit")
    records: dict[str, Mapping[str, Any]] = {}
    paths: set[str] = set()
    for value in raw:
        if not isinstance(value, dict):
            raise SnapshotIntegrityError("each manifest instrument must be an object")
        instrument_id = _text(value, "instrument_id")
        _text(value, "exchange")
        _text(value, "display_symbol")
        if instrument_id in records:
            raise SnapshotIntegrityError(f"duplicate instrument_id: {instrument_id}")
        bars = _object(value, "bars")
        path = _text(bars, "path")
        if path in paths:
            raise SnapshotIntegrityError(f"duplicate bar artifact path: {path}")
        paths.add(path)
        records[instrument_id] = value
    return records


def _object(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    child = value.get(key)
    if not isinstance(child, dict):
        raise SnapshotIntegrityError(f"manifest field {key!r} must be an object")
    return child


def _text(value: Mapping[str, Any], key: str) -> str:
    child = value.get(key)
    if not isinstance(child, str) or not child.strip():
        raise SnapshotIntegrityError(f"manifest field {key!r} must be non-empty text")
    return child


def _positive_int(value: Mapping[str, Any], key: str) -> int:
    child = value.get(key)
    if not isinstance(child, int) or isinstance(child, bool) or child <= 0:
        raise SnapshotIntegrityError(f"manifest field {key!r} must be a positive integer")
    return child


def _iso_date(value: Mapping[str, Any], key: str) -> date:
    try:
        return date.fromisoformat(_text(value, key))
    except ValueError as exc:
        raise SnapshotIntegrityError(
            f"manifest field {key!r} must be an ISO date"
        ) from exc


def _require_equal(value: Mapping[str, Any], key: str, expected: object) -> None:
    if value.get(key) != expected:
        raise SnapshotIntegrityError(
            f"unsupported manifest {key}: expected {expected!r}"
        )
