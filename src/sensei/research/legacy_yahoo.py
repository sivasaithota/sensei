"""Read-only adapter for the bot's legacy Yahoo/current-constituent store."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import date
from io import StringIO
from pathlib import Path

import pandas as pd

from sensei.research.catalog import SnapshotRequest
from sensei.research.errors import SnapshotIntegrityError
from sensei.research.local_artifacts import (
    materialize_daily_bars,
    read_regular_file,
)
from sensei.research.market_data import (
    DataLineage,
    LineageArtifact,
    MarketDataSnapshot,
    MembershipInterval,
)

_MAX_UNIVERSE_BYTES = 16_000_000
_MAX_BAR_BYTES = 512_000_000
_MAX_INSTRUMENTS = 20_000
_MAX_TOTAL_COMPRESSED_BYTES = 1_500_000_000
_MAX_TOTAL_DECODED_BYTES = 1_500_000_000
_MAX_TOTAL_ROWS = 10_000_000
_MAX_PARQUET_COLUMNS = 64


class LegacyYahooCurrentConstituentCatalog:
    """Expose existing local files without ever claiming point-in-time quality."""

    def __init__(
        self,
        *,
        universe_file: Path,
        prices_dir: Path,
        universe_as_of: date,
        universe: str,
    ) -> None:
        if not universe.strip():
            raise ValueError("legacy catalog universe must not be empty")
        self._universe_file = Path(universe_file)
        self._prices_dir = Path(prices_dir)
        self._universe_as_of = universe_as_of
        self._universe = universe

    def snapshot(self, request: SnapshotRequest) -> MarketDataSnapshot:
        if request.universe != self._universe:
            raise SnapshotIntegrityError(
                f"legacy catalog is bound to named universe {self._universe!r}"
            )
        universe_bytes = read_regular_file(
            self._universe_file, max_bytes=_MAX_UNIVERSE_BYTES
        )
        try:
            universe_text = universe_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise SnapshotIntegrityError(
                "legacy universe must be valid UTF-8 CSV"
            ) from exc
        required = {"symbol", "isin"}
        records: list[tuple[str, str]] = []
        seen_symbols: set[str] = set()
        seen_instruments: set[str] = set()
        retained_bytes = 0
        try:
            reader = csv.DictReader(
                StringIO(universe_text, newline=""), strict=True
            )
            fieldnames = tuple(reader.fieldnames or ())
            if not required.issubset(fieldnames):
                raise SnapshotIntegrityError(
                    "legacy universe needs symbol and isin columns"
                )
            if len(fieldnames) > _MAX_PARQUET_COLUMNS:
                raise SnapshotIntegrityError(
                    "legacy universe column count exceeds safety limit"
                )
            if len(set(fieldnames)) != len(fieldnames):
                raise SnapshotIntegrityError(
                    "legacy universe has duplicate columns"
                )
            for row in reader:
                row_number = reader.line_num
                if None in row or any(value is None for value in row.values()):
                    raise SnapshotIntegrityError(
                        f"legacy universe row {row_number} has the wrong column count"
                    )
                symbol = row["symbol"].strip()
                instrument_id = row["isin"].strip()
                if not symbol or not instrument_id:
                    raise SnapshotIntegrityError(
                        f"legacy universe row {row_number} has an empty symbol or isin"
                    )
                if symbol in seen_symbols or instrument_id in seen_instruments:
                    raise SnapshotIntegrityError(
                        f"legacy universe row {row_number} duplicates a symbol or isin"
                    )
                if len(records) >= _MAX_INSTRUMENTS:
                    raise SnapshotIntegrityError(
                        "legacy universe instrument count exceeds safety limit"
                    )
                seen_symbols.add(symbol)
                seen_instruments.add(instrument_id)
                records.append((instrument_id, symbol))
                retained_bytes += sys.getsizeof(instrument_id) + sys.getsizeof(symbol)
        except csv.Error as exc:
            raise SnapshotIntegrityError(
                "cannot read the legacy universe file"
            ) from exc
        if not records:
            raise SnapshotIntegrityError("legacy universe must not be empty")

        universe_row_count = len(records)
        universe_decoded_bytes = (
            2 * sys.getsizeof(universe_text)
            + sys.getsizeof(records)
            + retained_bytes
        )
        if universe_decoded_bytes > _MAX_TOTAL_DECODED_BYTES:
            raise SnapshotIntegrityError(
                "legacy total decoded bytes exceeds safety limit"
            )

        if not self._prices_dir.is_dir():
            raise SnapshotIntegrityError("legacy prices directory does not exist")
        price_paths = {path.stem: path for path in self._prices_dir.glob("*.parquet")}
        expected_symbols = {symbol for _, symbol in records}
        missing = sorted(expected_symbols - set(price_paths))
        unexpected = sorted(set(price_paths) - expected_symbols)
        if missing or unexpected:
            details = []
            if missing:
                details.append("missing=" + ",".join(missing))
            if unexpected:
                details.append("unexpected=" + ",".join(unexpected))
            raise SnapshotIntegrityError(
                "legacy universe and price files disagree: " + "; ".join(details)
            )
        total_compressed_bytes = len(universe_bytes)
        total_rows = universe_row_count
        total_decoded_bytes = universe_decoded_bytes
        total_retained_bar_bytes = 0

        bars_by_instrument: dict[str, pd.DataFrame] = {}
        memberships: dict[str, tuple[MembershipInterval, ...]] = {}
        artifacts = [
            _lineage_artifact(
                role="current-membership",
                relative_path=self._universe_file.name,
                content=universe_bytes,
                row_count=universe_row_count,
            )
        ]
        for instrument_id, symbol in sorted(records):
            content = read_regular_file(
                price_paths[symbol], max_bytes=_MAX_BAR_BYTES
            )
            total_compressed_bytes += len(content)
            if total_compressed_bytes > _MAX_TOTAL_COMPRESSED_BYTES:
                raise SnapshotIntegrityError(
                    "legacy total compressed bytes exceeds safety limit"
                )
            label = f"legacy bars for {symbol}"
            materialized = materialize_daily_bars(
                content,
                label=label,
                expected_rows=None,
                history_start=request.history_start,
                as_of=request.as_of,
                available_working_bytes=(
                    _MAX_TOTAL_DECODED_BYTES - total_decoded_bytes
                ),
                max_columns=_MAX_PARQUET_COLUMNS,
            )
            total_rows += materialized.artifact_rows
            if total_rows > _MAX_TOTAL_ROWS:
                raise SnapshotIntegrityError("legacy total rows exceeds safety limit")
            total_decoded_bytes += materialized.retained_bytes
            total_retained_bar_bytes += materialized.retained_bytes
            if (
                total_decoded_bytes + total_retained_bar_bytes
                > _MAX_TOTAL_DECODED_BYTES
            ):
                raise SnapshotIntegrityError(
                    "legacy snapshot copy working set exceeds safety limit"
                )
            frame = materialized.frame
            artifact_row_count = materialized.artifact_rows
            if frame.empty:
                raise SnapshotIntegrityError(
                    f"legacy bars have no requested sessions for {symbol}"
                )
            bars_by_instrument[instrument_id] = frame
            memberships[instrument_id] = (
                MembershipInterval(
                    universe=request.universe,
                    instrument_id=instrument_id,
                    symbol=symbol,
                    effective_from=date.min,
                ),
            )
            artifacts.append(
                _lineage_artifact(
                    role=f"bars:{instrument_id}",
                    relative_path=f"prices/{symbol}.parquet",
                    content=content,
                    row_count=artifact_row_count,
                )
            )

        identity = {
            "adapter": "legacy-yahoo-current-constituents/1",
            "universe_as_of": self._universe_as_of.isoformat(),
            "artifacts": [artifact.identity_payload() for artifact in artifacts],
        }
        manifest_id = "sha256:" + hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        lineage = DataLineage(
            catalog_id="legacy-yahoo-current-constituents",
            issuer="local-unverified",
            manifest_id=manifest_id,
            provider="Yahoo Finance",
            dataset="current-constituent backfill",
            source_uri="local://legacy-yahoo-current-constituents",
            usage_rights="unknown; compatibility use only",
            retrieved_at=self._universe_as_of,
            calendar="XNSE-assumed",
            timezone="Asia/Kolkata",
            currency="INR",
            adjustment_policies=("yahoo-auto-adjust-unspecified",),
            artifacts=tuple(artifacts),
        )
        return MarketDataSnapshot._from_catalog(
            bars_by_instrument=bars_by_instrument,
            history_start=request.history_start,
            as_of=request.as_of,
            universe_as_of=self._universe_as_of,
            point_in_time_universe=False,
            source="Yahoo Finance/current-constituent backfill",
            memberships_by_instrument=memberships,
            lineage=lineage,
        )


def _lineage_artifact(
    *, role: str, relative_path: str, content: bytes, row_count: int
) -> LineageArtifact:
    return LineageArtifact(
        role=role,
        relative_path=relative_path,
        sha256=f"sha256:{hashlib.sha256(content).hexdigest()}",
        byte_size=len(content),
        row_count=row_count,
    )
