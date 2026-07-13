"""Bounded, read-only loading of local research artifacts."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as parquet

from sensei.research.errors import SnapshotIntegrityError


@dataclass(frozen=True)
class ParquetResourceUsage:
    row_count: int
    column_count: int
    decoded_bytes: int


@dataclass(frozen=True)
class MaterializedBars:
    frame: pd.DataFrame
    artifact_rows: int
    retained_bytes: int


_BAR_COLUMNS = ("open", "high", "low", "close", "volume")
_MAX_FIELD_NAME_LENGTH = 128
_MAX_PARQUET_ROW_GROUPS = 4_096
_PARQUET_THRIFT_LIMIT = 1_000_000
_FRAME_OVERHEAD_BYTES = 64_000
_MATERIALIZATION_OVERHEAD_BYTES = 1_000_000


def read_regular_file(path: Path, *, max_bytes: int) -> bytes:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
    except OSError as exc:
        raise SnapshotIntegrityError(f"cannot open catalog artifact: {path.name}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise SnapshotIntegrityError("catalog artifacts must be regular files")
        if metadata.st_size > max_bytes:
            raise SnapshotIntegrityError(
                f"catalog artifact exceeds safety limit: {path.name}"
            )
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            content = handle.read(metadata.st_size + 1)
        if len(content) != metadata.st_size:
            raise SnapshotIntegrityError("catalog artifact changed while it was read")
        after = os.fstat(descriptor)
        before_identity = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
        )
        after_identity = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        )
        if before_identity != after_identity:
            raise SnapshotIntegrityError("catalog artifact changed while it was read")
        return content
    finally:
        os.close(descriptor)


def inspect_parquet(
    content: bytes, *, label: str, expected_rows: int | None = None
) -> ParquetResourceUsage:
    reader = _parquet_reader(content, label=label)
    metadata = reader.metadata
    if expected_rows is not None and metadata.num_rows != expected_rows:
        raise SnapshotIntegrityError(f"row count does not match manifest for {label}")
    decoded_bytes = sum(
        metadata.row_group(index).total_byte_size
        for index in range(metadata.num_row_groups)
    )
    return ParquetResourceUsage(
        row_count=metadata.num_rows,
        column_count=metadata.num_columns,
        decoded_bytes=decoded_bytes,
    )


def materialize_daily_bars(
    content: bytes,
    *,
    label: str,
    expected_rows: int | None,
    history_start: date,
    as_of: date,
    available_working_bytes: int,
    max_columns: int,
) -> MaterializedBars:
    """Preflight and decode one fixed-width daily-bar artifact within a budget."""

    reader = _parquet_reader(content, label=label)
    metadata = reader.metadata
    if expected_rows is not None and metadata.num_rows != expected_rows:
        raise SnapshotIntegrityError(f"row count does not match manifest for {label}")
    schema = reader.schema_arrow
    if metadata.num_columns > max_columns or len(schema) > max_columns:
        raise SnapshotIntegrityError(f"{label} column count exceeds safety limit")
    if metadata.num_columns != len(schema):
        raise SnapshotIntegrityError(f"{label} must use a flat fixed-width schema")

    names = tuple(field.name for field in schema)
    if len(set(names)) != len(names):
        raise SnapshotIntegrityError(f"{label} has duplicate columns")
    if any(not name or len(name) > _MAX_FIELD_NAME_LENGTH for name in names):
        raise SnapshotIntegrityError(f"{label} has an invalid field name")
    missing = tuple(column for column in _BAR_COLUMNS if column not in names)
    if missing:
        raise SnapshotIntegrityError(
            f"{label} is missing required bar columns: {', '.join(missing)}"
        )

    for column in _BAR_COLUMNS:
        field_type = schema.field(column).type
        if not (
            pa.types.is_integer(field_type) or pa.types.is_floating(field_type)
        ):
            raise SnapshotIntegrityError(
                f"{label} bar column {column!r} must be fixed-width numeric"
            )
    if any(not _is_permitted_fixed_width(field.type) for field in schema):
        raise SnapshotIntegrityError(
            f"{label} must contain only permitted fixed-width columns"
        )

    timestamp_fields = tuple(
        field.name for field in schema if pa.types.is_timestamp(field.type)
    )
    if len(timestamp_fields) != 1:
        raise SnapshotIntegrityError(
            f"{label} needs exactly one fixed-width timestamp index"
        )
    index_name = timestamp_fields[0]
    selected_columns = names
    frame_bound = _fixed_width_frame_bound(
        metadata.num_rows, len(selected_columns)
    )
    encoded_page_bytes = sum(
        metadata.row_group(index).total_byte_size
        for index in range(metadata.num_row_groups)
    )
    peak_bound = (
        len(content)
        + encoded_page_bytes
        + 3 * frame_bound
        + 16 * metadata.num_rows
        + _MATERIALIZATION_OVERHEAD_BYTES
    )
    if peak_bound > available_working_bytes:
        raise SnapshotIntegrityError(
            f"{label} exceeds the working-memory safety limit before decode"
        )

    table = _read_bar_table(reader, columns=selected_columns, label=label)
    try:
        frame = table.to_pandas(
            use_threads=False,
            ignore_metadata=True,
            split_blocks=True,
            self_destruct=True,
        )
    except Exception as exc:
        raise SnapshotIntegrityError(f"cannot materialize {label}") from exc
    if len(frame) != metadata.num_rows:
        raise SnapshotIntegrityError(f"decoded row count changed for {label}")
    try:
        frame.index = pd.DatetimeIndex(frame.pop(index_name), name=None)
    except (KeyError, TypeError, ValueError) as exc:
        raise SnapshotIntegrityError(f"{label} has an invalid timestamp index") from exc
    full_frame_bytes = int(frame.memory_usage(index=True, deep=True).sum())
    if full_frame_bytes > frame_bound:
        raise SnapshotIntegrityError(
            f"{label} exceeded its fixed-width preflight bound"
        )

    in_window = (
        (frame.index.date >= history_start)
        & (frame.index.date <= as_of)
    )
    if not in_window.all():
        frame = frame.loc[in_window].copy(deep=True)
    retained_bound = _fixed_width_frame_bound(len(frame), len(selected_columns))
    retained_bytes = int(frame.memory_usage(index=True, deep=True).sum())
    if retained_bytes > retained_bound:
        raise SnapshotIntegrityError(
            f"{label} exceeded its retained fixed-width bound"
        )
    return MaterializedBars(
        frame=frame,
        artifact_rows=metadata.num_rows,
        retained_bytes=retained_bound,
    )


def _parquet_reader(content: bytes, *, label: str) -> parquet.ParquetFile:
    try:
        reader = parquet.ParquetFile(
            pa.BufferReader(content),
            pre_buffer=False,
            thrift_string_size_limit=_PARQUET_THRIFT_LIMIT,
            thrift_container_size_limit=_PARQUET_THRIFT_LIMIT,
            arrow_extensions_enabled=False,
        )
    except Exception as exc:
        raise SnapshotIntegrityError(f"cannot inspect {label}") from exc
    if reader.metadata.num_row_groups > _MAX_PARQUET_ROW_GROUPS:
        raise SnapshotIntegrityError(
            f"{label} row-group count exceeds safety limit"
        )
    return reader


def _read_bar_table(
    reader: parquet.ParquetFile,
    *,
    columns: tuple[str, ...],
    label: str,
) -> pa.Table:
    try:
        return reader.read(
            columns=list(columns),
            use_threads=False,
            use_pandas_metadata=False,
        )
    except Exception as exc:
        raise SnapshotIntegrityError(f"cannot decode {label}") from exc


def _is_permitted_fixed_width(value: pa.DataType) -> bool:
    return (
        pa.types.is_integer(value)
        or pa.types.is_floating(value)
        or pa.types.is_timestamp(value)
    )


def _fixed_width_frame_bound(rows: int, fields: int) -> int:
    null_bitmaps = ((rows + 7) // 8) * fields
    return _FRAME_OVERHEAD_BYTES + rows * 8 * fields + null_bitmaps
