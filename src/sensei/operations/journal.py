"""Transactional, append-only operational journal."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any

_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}\Z")
_ZERO_HASH = "0" * 64


class JournalConflict(RuntimeError):
    """The expected stream version did not match durable state."""


class JournalIntegrityError(RuntimeError):
    """A durable identity was reused with different content."""


@dataclass(frozen=True)
class EventAppend:
    stream_id: str
    event_type: str
    payload: Mapping[str, Any]
    idempotency_key: str
    expected_version: int
    occurred_at: datetime
    schema_version: int = 1
    causation_id: str | None = None
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("stream_id", self.stream_id),
            ("event_type", self.event_type),
            ("idempotency_key", self.idempotency_key),
        ):
            if _NAME.fullmatch(value) is None:
                raise ValueError(f"{label} is not a valid journal identifier")
        if self.expected_version < 0:
            raise ValueError("expected_version must not be negative")
        if self.schema_version < 1:
            raise ValueError("schema_version must be positive")
        _utc_iso(self.occurred_at)
        _canonical_json(self.payload)


@dataclass(frozen=True)
class JournalEvent:
    global_sequence: int
    stream_id: str
    stream_sequence: int
    event_id: str
    idempotency_key: str
    event_type: str
    payload: Mapping[str, Any]
    schema_version: int
    occurred_at: datetime
    recorded_at: datetime
    causation_id: str | None
    correlation_id: str | None
    previous_global_hash: str
    previous_stream_hash: str
    event_hash: str


@dataclass(frozen=True)
class JournalVerification:
    ok: bool
    events_checked: int
    errors: tuple[str, ...]


@dataclass(frozen=True)
class JournalBackup:
    path: Path
    sha256: str
    events: int
    created_at: datetime


class OperationalJournal:
    """Own ordered event identity, idempotency, and optimistic concurrency."""

    def __init__(
        self,
        path: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._initialize()

    def append(self, command: EventAppend) -> JournalEvent:
        payload_json = _canonical_json(command.payload)
        command_json = _canonical_json(
            {
                "stream_id": command.stream_id,
                "event_type": command.event_type,
                "payload": json.loads(payload_json),
                "occurred_at": _utc_iso(command.occurred_at),
                "schema_version": command.schema_version,
                "causation_id": command.causation_id,
                "correlation_id": command.correlation_id,
            }
        )
        command_hash = _sha256(command_json)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM journal_events WHERE idempotency_key = ?",
                (command.idempotency_key,),
            ).fetchone()
            if existing is not None:
                if existing["command_hash"] != command_hash:
                    raise JournalIntegrityError(
                        "idempotency key was reused with different content"
                    )
                connection.commit()
                return _event_from_row(existing)

            stream_head = connection.execute(
                """
                SELECT stream_sequence, event_hash
                FROM journal_events
                WHERE stream_id = ?
                ORDER BY stream_sequence DESC
                LIMIT 1
                """,
                (command.stream_id,),
            ).fetchone()
            actual_version = (
                int(stream_head["stream_sequence"]) if stream_head is not None else 0
            )
            if actual_version != command.expected_version:
                raise JournalConflict(
                    f"stream {command.stream_id!r} is at version {actual_version}; "
                    f"expected {command.expected_version}"
                )

            global_head = connection.execute(
                """
                SELECT global_sequence, event_hash
                FROM journal_events
                ORDER BY global_sequence DESC
                LIMIT 1
                """
            ).fetchone()
            global_sequence = (
                int(global_head["global_sequence"]) + 1
                if global_head is not None
                else 1
            )
            stream_sequence = actual_version + 1
            previous_global_hash = (
                str(global_head["event_hash"])
                if global_head is not None
                else _ZERO_HASH
            )
            previous_stream_hash = (
                str(stream_head["event_hash"])
                if stream_head is not None
                else _ZERO_HASH
            )
            recorded_at = self._clock()
            material = _canonical_json(
                {
                    "global_sequence": global_sequence,
                    "stream_id": command.stream_id,
                    "stream_sequence": stream_sequence,
                    "idempotency_key": command.idempotency_key,
                    "event_type": command.event_type,
                    "payload": json.loads(payload_json),
                    "schema_version": command.schema_version,
                    "occurred_at": _utc_iso(command.occurred_at),
                    "recorded_at": _utc_iso(recorded_at),
                    "causation_id": command.causation_id,
                    "correlation_id": command.correlation_id,
                    "previous_global_hash": previous_global_hash,
                    "previous_stream_hash": previous_stream_hash,
                }
            )
            event_hash = _sha256(material)
            event_id = f"event:{event_hash}"
            connection.execute(
                """
                INSERT INTO journal_events (
                    global_sequence, stream_id, stream_sequence, event_id,
                    idempotency_key, event_type, payload_json, schema_version,
                    occurred_at, recorded_at, causation_id, correlation_id,
                    previous_global_hash, previous_stream_hash, event_hash,
                    command_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    global_sequence,
                    command.stream_id,
                    stream_sequence,
                    event_id,
                    command.idempotency_key,
                    command.event_type,
                    payload_json,
                    command.schema_version,
                    _utc_iso(command.occurred_at),
                    _utc_iso(recorded_at),
                    command.causation_id,
                    command.correlation_id,
                    previous_global_hash,
                    previous_stream_hash,
                    event_hash,
                    command_hash,
                ),
            )
            row = connection.execute(
                "SELECT * FROM journal_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            connection.commit()
            return _event_from_row(row)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def read_stream(self, stream_id: str) -> tuple[JournalEvent, ...]:
        if _NAME.fullmatch(stream_id) is None:
            raise ValueError("stream_id is not a valid journal identifier")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM journal_events
                WHERE stream_id = ?
                ORDER BY stream_sequence
                """,
                (stream_id,),
            ).fetchall()
        return tuple(_event_from_row(row) for row in rows)

    def read_all(self) -> tuple[JournalEvent, ...]:
        """Return the immutable global event sequence."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM journal_events ORDER BY global_sequence"
            ).fetchall()
        return tuple(_event_from_row(row) for row in rows)

    def verify(self) -> JournalVerification:
        """Verify global and per-stream ordering and cryptographic hash chains."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM journal_events ORDER BY global_sequence"
            ).fetchall()

        errors: list[str] = []
        previous_global_hash = _ZERO_HASH
        stream_heads: dict[str, tuple[int, str]] = {}
        for expected_global_sequence, row in enumerate(rows, start=1):
            global_sequence = int(row["global_sequence"])
            stream_id = str(row["stream_id"])
            stream_sequence = int(row["stream_sequence"])
            prior_stream_sequence, prior_stream_hash = stream_heads.get(
                stream_id, (0, _ZERO_HASH)
            )
            if global_sequence != expected_global_sequence:
                errors.append(
                    f"global sequence {global_sequence} followed "
                    f"{expected_global_sequence - 1}"
                )
            if stream_sequence != prior_stream_sequence + 1:
                errors.append(
                    f"stream {stream_id!r} sequence {stream_sequence} followed "
                    f"{prior_stream_sequence}"
                )
            if row["previous_global_hash"] != previous_global_hash:
                errors.append(f"global hash link is broken at {global_sequence}")
            if row["previous_stream_hash"] != prior_stream_hash:
                errors.append(
                    f"stream hash link is broken at {stream_id}:{stream_sequence}"
                )

            material = _canonical_json(
                {
                    "global_sequence": global_sequence,
                    "stream_id": stream_id,
                    "stream_sequence": stream_sequence,
                    "idempotency_key": row["idempotency_key"],
                    "event_type": row["event_type"],
                    "payload": json.loads(row["payload_json"]),
                    "schema_version": int(row["schema_version"]),
                    "occurred_at": row["occurred_at"],
                    "recorded_at": row["recorded_at"],
                    "causation_id": row["causation_id"],
                    "correlation_id": row["correlation_id"],
                    "previous_global_hash": row["previous_global_hash"],
                    "previous_stream_hash": row["previous_stream_hash"],
                }
            )
            calculated_hash = _sha256(material)
            if row["event_hash"] != calculated_hash:
                errors.append(f"event hash is invalid at {global_sequence}")
            if row["event_id"] != f"event:{calculated_hash}":
                errors.append(f"event identity is invalid at {global_sequence}")

            previous_global_hash = str(row["event_hash"])
            stream_heads[stream_id] = (stream_sequence, str(row["event_hash"]))

        return JournalVerification(
            ok=not errors,
            events_checked=len(rows),
            errors=tuple(errors),
        )

    def backup_to(self, destination: Path) -> JournalBackup:
        """Create a consistent SQLite backup after verifying the source journal."""

        destination = Path(destination)
        if destination.exists():
            raise FileExistsError(destination)
        verification = self.verify()
        if not verification.ok:
            raise JournalIntegrityError(
                "cannot back up a journal with failed integrity verification"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = self._connect()
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        copied = OperationalJournal(destination)
        copied_verification = copied.verify()
        if not copied_verification.ok:
            destination.unlink(missing_ok=True)
            raise JournalIntegrityError("new journal backup failed verification")
        created_at = self._clock()
        _utc_iso(created_at)
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        return JournalBackup(
            path=destination,
            sha256=f"sha256:{digest}",
            events=copied_verification.events_checked,
            created_at=created_at,
        )

    @classmethod
    def restore_from(
        cls, backup_path: Path, destination: Path
    ) -> OperationalJournal:
        """Restore into a new path and reject any unverified result."""

        backup_path = Path(backup_path)
        destination = Path(destination)
        if destination.exists():
            raise FileExistsError(destination)
        if not backup_path.is_file():
            raise FileNotFoundError(backup_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally:
            target.close()
            source.close()
        restored = cls(destination)
        verification = restored.verify()
        if not verification.ok:
            destination.unlink(missing_ok=True)
            raise JournalIntegrityError("restored journal failed verification")
        return restored

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._path,
            timeout=5,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS journal_events (
                    global_sequence INTEGER PRIMARY KEY,
                    stream_id TEXT NOT NULL,
                    stream_sequence INTEGER NOT NULL,
                    event_id TEXT NOT NULL UNIQUE,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    occurred_at TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    causation_id TEXT,
                    correlation_id TEXT,
                    previous_global_hash TEXT NOT NULL,
                    previous_stream_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE,
                    command_hash TEXT NOT NULL,
                    UNIQUE(stream_id, stream_sequence)
                );

                CREATE TRIGGER IF NOT EXISTS journal_events_no_update
                BEFORE UPDATE ON journal_events
                BEGIN
                    SELECT RAISE(ABORT, 'journal events are append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS journal_events_no_delete
                BEFORE DELETE ON journal_events
                BEGIN
                    SELECT RAISE(ABORT, 'journal events are append-only');
                END;
                """
            )
        finally:
            connection.close()


def _event_from_row(row: sqlite3.Row) -> JournalEvent:
    payload = _freeze_json(json.loads(row["payload_json"]))
    return JournalEvent(
        global_sequence=int(row["global_sequence"]),
        stream_id=str(row["stream_id"]),
        stream_sequence=int(row["stream_sequence"]),
        event_id=str(row["event_id"]),
        idempotency_key=str(row["idempotency_key"]),
        event_type=str(row["event_type"]),
        payload=payload,
        schema_version=int(row["schema_version"]),
        occurred_at=datetime.fromisoformat(row["occurred_at"]),
        recorded_at=datetime.fromisoformat(row["recorded_at"]),
        causation_id=row["causation_id"],
        correlation_id=row["correlation_id"],
        previous_global_hash=str(row["previous_global_hash"]),
        previous_stream_hash=str(row["previous_stream_hash"]),
        event_hash=str(row["event_hash"]),
    )


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType(
            {str(key): _freeze_json(child) for key, child in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(child) for child in value)
    return value


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("journal payload must be canonical JSON") from exc


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("journal timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()
