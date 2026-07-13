"""Read-only import of legacy JSON facts into the operational journal.

Legacy state is evidence about what the old prototype observed or attempted.
It is never lifecycle evidence, an execution instruction, or accounting truth.
The importer consequently has one output only: non-authoritative events in the
shared append-only journal.  It never rewrites, moves, or annotates source files.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from sensei.operations.journal import EventAppend, OperationalJournal

_STREAM = "legacy:imports"


class LegacyFileKind(str, Enum):
    AUDIT = "audit"
    SUBMISSIONS = "submissions"
    PENDING = "pending"
    PAPER_POSITIONS = "paper_positions"
    PAPER_CLOSED = "paper_closed"
    LEDGER = "ledger"


@dataclass(frozen=True)
class LegacySource:
    """One caller-selected source; there are deliberately no live defaults."""

    label: str
    kind: LegacyFileKind
    path: Path

    def __post_init__(self) -> None:
        label = self.label.strip()
        if not label:
            raise ValueError("legacy source label must not be blank")
        if not isinstance(self.kind, LegacyFileKind):
            raise ValueError("legacy source kind must be a LegacyFileKind")
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "path", Path(self.path))


@dataclass(frozen=True)
class LegacyImportManifest:
    sources: tuple[LegacySource, ...]

    def __post_init__(self) -> None:
        if not self.sources:
            raise ValueError("legacy import manifest must contain at least one source")
        labels = tuple(source.label for source in self.sources)
        if len(labels) != len(set(labels)):
            raise ValueError("legacy source labels must be unique")


@dataclass(frozen=True)
class LegacyImportSummary:
    imported_facts: int
    previously_imported_facts: int
    missing_sources: tuple[str, ...]
    event_ids: tuple[str, ...]


@dataclass(frozen=True)
class _SourceRecord:
    index: int
    parsed: Any | None
    record_bytes: bytes
    parse_status: str


class LegacyImporter:
    """Capture source-preserving historical facts without granting authority."""

    def __init__(self, journal: OperationalJournal) -> None:
        self._journal = journal

    def import_manifest(
        self,
        manifest: LegacyImportManifest,
        *,
        imported_at: datetime,
    ) -> LegacyImportSummary:
        if imported_at.tzinfo is None or imported_at.utcoffset() is None:
            raise ValueError("imported_at must be timezone-aware")

        existing = {
            event.idempotency_key: event
            for event in self._journal.read_stream(_STREAM)
        }
        imported = 0
        previously_imported = 0
        missing: list[str] = []
        event_ids: list[str] = []

        for source in manifest.sources:
            facts, is_missing = self._facts(source)
            if is_missing:
                missing.append(source.label)
            for payload in facts:
                fact_digest = _digest_json(payload)
                idempotency_key = f"legacy:{fact_digest}"
                already = existing.get(idempotency_key)
                if already is not None:
                    previously_imported += 1
                    event_ids.append(already.event_id)
                    continue

                events = self._journal.read_stream(_STREAM)
                event = self._journal.append(
                    EventAppend(
                        stream_id=_STREAM,
                        event_type="LegacyFactImported",
                        payload=payload,
                        idempotency_key=idempotency_key,
                        expected_version=len(events),
                        occurred_at=imported_at,
                        correlation_id=f"legacy:{fact_digest}",
                    )
                )
                existing[idempotency_key] = event
                imported += 1
                event_ids.append(event.event_id)

        return LegacyImportSummary(
            imported_facts=imported,
            previously_imported_facts=previously_imported,
            missing_sources=tuple(missing),
            event_ids=tuple(event_ids),
        )

    def _facts(
        self,
        source: LegacySource,
    ) -> tuple[tuple[dict[str, Any], ...], bool]:
        if not source.path.exists():
            return (
                (
                    _base_payload(
                        source=source,
                        source_sha256=None,
                        record_index=0,
                        record_sha256=None,
                        fact_type="missing_source",
                        parse_status="MISSING",
                        evidence_status="MISSING",
                        missing_evidence=("source_bytes",),
                    ),
                ),
                True,
            )
        if not source.path.is_file():
            raise ValueError(f"legacy source is not a regular file: {source.path}")

        # This is the sole source read.  No source file handle is ever opened in
        # write mode, and source bytes are hashed before parsing.
        source_bytes = source.path.read_bytes()
        source_sha256 = _digest_bytes(source_bytes)
        records = _records(source, source_bytes)
        if not records:
            return (
                (
                    _base_payload(
                        source=source,
                        source_sha256=source_sha256,
                        record_index=0,
                        record_sha256=_digest_bytes(b""),
                        fact_type="empty_source",
                        parse_status="EMPTY",
                        evidence_status="MISSING",
                        missing_evidence=("legacy_record",),
                    ),
                ),
                False,
            )

        payloads = tuple(
            _payload_for_record(source, source_sha256, record)
            for record in records
        )
        return payloads, False


def _records(source: LegacySource, source_bytes: bytes) -> tuple[_SourceRecord, ...]:
    line_oriented = source.kind in {
        LegacyFileKind.AUDIT,
        LegacyFileKind.PAPER_CLOSED,
        LegacyFileKind.LEDGER,
    } or source.path.suffix.lower() == ".jsonl"
    if line_oriented:
        records: list[_SourceRecord] = []
        for line in source_bytes.splitlines():
            if not line.strip():
                continue
            parsed, status = _parse_json(line)
            records.append(
                _SourceRecord(
                    index=len(records),
                    parsed=parsed,
                    record_bytes=line,
                    parse_status=status,
                )
            )
        return tuple(records)

    parsed, status = _parse_json(source_bytes)
    if status == "INVALID":
        return (
            _SourceRecord(
                index=0,
                parsed=None,
                record_bytes=source_bytes,
                parse_status=status,
            ),
        )

    values: list[Any]
    if isinstance(parsed, list):
        values = parsed
    elif (
        source.kind is LegacyFileKind.SUBMISSIONS
        and isinstance(parsed, Mapping)
        and isinstance(parsed.get("submissions"), list)
    ):
        values = list(parsed["submissions"])
    else:
        values = [parsed]
    return tuple(
        _SourceRecord(
            index=index,
            parsed=value,
            record_bytes=_canonical_json(value).encode("utf-8"),
            parse_status="VALID",
        )
        for index, value in enumerate(values)
    )


def _payload_for_record(
    source: LegacySource,
    source_sha256: str,
    record: _SourceRecord,
) -> dict[str, Any]:
    record_sha256 = _digest_bytes(record.record_bytes)
    if record.parse_status != "VALID":
        return _base_payload(
            source=source,
            source_sha256=source_sha256,
            record_index=record.index,
            record_sha256=record_sha256,
            fact_type="unparseable_record",
            parse_status="INVALID",
            evidence_status="MISSING",
            missing_evidence=("parseable_legacy_record", "thesis_content"),
        )

    thesis = _extract_thesis(source.kind, record.parsed)
    thesis_fingerprint = _digest_json(thesis) if thesis is not None else None
    thesis_id = _legacy_thesis_id(record.parsed, thesis)
    missing_evidence = [
        "canonical_strategy_plan_id",
        "source_claim_ids",
        "point_in_time_snapshot_id",
    ]
    if thesis is None:
        missing_evidence.append("thesis_content")
        evidence_status = "MISSING"
    elif not _has_legacy_evidence(thesis):
        missing_evidence.append("legacy_thesis_evidence")
        evidence_status = "MISSING"
    else:
        evidence_status = "PARTIAL"

    payload = _base_payload(
        source=source,
        source_sha256=source_sha256,
        record_index=record.index,
        record_sha256=record_sha256,
        fact_type=_fact_type(source.kind, record.parsed),
        parse_status="VALID",
        evidence_status=evidence_status,
        missing_evidence=tuple(missing_evidence),
    )
    payload.update(
        {
            "record": record.parsed,
            "legacy_thesis_id": thesis_id,
            "thesis_fingerprint": (
                f"sha256:{thesis_fingerprint}" if thesis_fingerprint else None
            ),
        }
    )
    return payload


def _base_payload(
    *,
    source: LegacySource,
    source_sha256: str | None,
    record_index: int,
    record_sha256: str | None,
    fact_type: str,
    parse_status: str,
    evidence_status: str,
    missing_evidence: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "source_label": source.label,
        "source_kind": source.kind.value,
        "source_path": str(source.path),
        "source_sha256": source_sha256,
        "record_index": record_index,
        "record_sha256": record_sha256,
        "fact_type": fact_type,
        "parse_status": parse_status,
        "evidence_status": evidence_status,
        "missing_evidence": list(missing_evidence),
        "authority": "HISTORICAL_FACT_ONLY",
        "can_authorize_lifecycle": False,
        "can_authorize_trading": False,
    }


def _parse_json(raw: bytes) -> tuple[Any | None, str]:
    try:
        decoded = raw.decode("utf-8")
        parsed = json.loads(
            decoded,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"invalid JSON constant {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None, "INVALID"
    return parsed, "VALID"


def _extract_thesis(kind: LegacyFileKind, value: Any) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    direct = value.get("thesis")
    if isinstance(direct, Mapping):
        return direct
    approval = value.get("record")
    if isinstance(approval, Mapping):
        nested = approval.get("thesis")
        if isinstance(nested, Mapping):
            return nested
    if kind is LegacyFileKind.SUBMISSIONS and _looks_like_thesis(value):
        return value
    return None


def _looks_like_thesis(value: Mapping[str, Any]) -> bool:
    return bool(value.get("id")) and any(
        key in value
        for key in ("symbol", "entry_zone_low", "stop_loss", "narrative")
    )


def _legacy_thesis_id(
    record: Any,
    thesis: Mapping[str, Any] | None,
) -> str | None:
    if thesis is not None and thesis.get("id") is not None:
        return str(thesis["id"])
    if isinstance(record, Mapping) and record.get("thesis_id") is not None:
        return str(record["thesis_id"])
    return None


def _has_legacy_evidence(thesis: Mapping[str, Any]) -> bool:
    evidence = thesis.get("evidence")
    return isinstance(evidence, list) and bool(evidence) and all(
        isinstance(item, str) and bool(item.strip()) for item in evidence
    )


def _fact_type(kind: LegacyFileKind, value: Any) -> str:
    if kind is LegacyFileKind.AUDIT and isinstance(value, Mapping):
        event = value.get("event")
        if isinstance(event, str) and event.strip():
            return event.strip()
        return "audit_record"
    return {
        LegacyFileKind.AUDIT: "audit_record",
        LegacyFileKind.SUBMISSIONS: "thesis_submitted",
        LegacyFileKind.PENDING: "pending_order",
        LegacyFileKind.PAPER_POSITIONS: "paper_positions_snapshot",
        LegacyFileKind.PAPER_CLOSED: "paper_trade_closed",
        LegacyFileKind.LEDGER: "legacy_ledger_observation",
    }[kind]


def _digest_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _digest_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
