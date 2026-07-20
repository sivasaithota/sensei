"""Upstream preparation of signed surveillance truth for an entry session."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from sensei.operations import EventAppend, OperationalJournal
from sensei.runtime.activation import (
    NseSurveillanceRefresher,
    SurveillanceSourceUnavailable,
)

from .scheduling import (
    ScheduledTask,
    SchedulerLedger,
    SchedulerTaskKind,
    SchedulerTaskState,
)


@dataclass(frozen=True)
class SurveillancePreflightResult:
    trading_date: date
    ready: bool
    symbols: int
    event_id: str
    source_session: date
    source_report_type: str
    source_content_sha256: str


@dataclass(frozen=True)
class SurveillancePreflightEvidence:
    trading_date: date
    snapshot_sha256: str
    symbols: int
    event_id: str
    task_id: str
    source_session: date
    source_report_type: str
    source_content_sha256: str


class SurveillancePreflightSession:
    """Fetch, retry, sign and journal one date-bound surveillance snapshot."""

    def __init__(
        self,
        *,
        journal: OperationalJournal,
        destination: Path,
        issuer_id: str,
        secret: bytes,
        fetch=None,
        maximum_attempts: int = 3,
        retry_backoff_seconds: float = 1.0,
        sleep=None,
    ) -> None:
        options = {
            "destination": destination,
            "issuer_id": issuer_id,
            "secret": secret,
            "fetch": fetch,
            "maximum_attempts": maximum_attempts,
            "retry_backoff_seconds": retry_backoff_seconds,
        }
        if sleep is not None:
            options["sleep"] = sleep
        self._journal = journal
        self._destination = Path(destination)
        self._refresher = NseSurveillanceRefresher(**options)

    def prepare(
        self,
        *,
        trading_date: date,
        observed_at: datetime,
        command_id: str,
    ) -> SurveillancePreflightResult:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if not command_id.strip():
            raise ValueError("command_id is required")
        digest = hashlib.sha256(command_id.encode()).hexdigest()
        stream = f"surveillance-preflight:{digest}"
        started = self._journal.append(
            EventAppend(
                stream_id=stream,
                event_type="SurveillancePreflightStarted",
                payload={
                    "schema_version": "1.0",
                    "trading_date": trading_date.isoformat(),
                    "authority": "TRUST_INPUT_PREPARATION_ONLY",
                },
                idempotency_key=f"surveillance-preflight-start:{digest}",
                expected_version=0,
                occurred_at=observed_at,
                correlation_id=command_id,
            )
        )
        try:
            refresh = self._refresher.refresh_result(
                session=trading_date,
                observed_at=observed_at,
            )
        except SurveillanceSourceUnavailable as exc:
            self._journal.append(
                EventAppend(
                    stream_id=stream,
                    event_type="SurveillancePreflightFailed",
                    payload={
                        "schema_version": "1.0",
                        "trading_date": trading_date.isoformat(),
                        "attempts": [
                            {
                                "source_session": failure.source_session.isoformat(),
                                "report_type": failure.report_type,
                                "attempt": failure.attempt,
                                "category": failure.category,
                            }
                            for failure in exc.attempts
                        ],
                        "can_authorize_trading": False,
                    },
                    idempotency_key=f"surveillance-preflight-failed:{digest}",
                    expected_version=1,
                    occurred_at=observed_at,
                    causation_id=started.event_id,
                    correlation_id=command_id,
                )
            )
            raise
        stages = refresh.stages
        source_session = refresh.source.source_session
        source_report_type = refresh.source.report_type
        source_content_sha256 = refresh.source.content_sha256
        snapshot_sha256 = hashlib.sha256(self._destination.read_bytes()).hexdigest()
        completed = self._journal.append(
            EventAppend(
                stream_id=stream,
                event_type="SurveillancePreflightCompleted",
                payload={
                    "schema_version": "1.0",
                    "trading_date": trading_date.isoformat(),
                    "symbols": len(stages),
                    "snapshot_sha256": snapshot_sha256,
                    "source_session": source_session.isoformat(),
                    "source_report_type": source_report_type,
                    "source_content_sha256": source_content_sha256,
                    "snapshot_ready": True,
                    "can_authorize_trading": False,
                },
                idempotency_key=f"surveillance-preflight-complete:{digest}",
                expected_version=1,
                occurred_at=observed_at,
                causation_id=started.event_id,
                correlation_id=command_id,
            )
        )
        return SurveillancePreflightResult(
            trading_date=trading_date,
            ready=True,
            symbols=len(stages),
            event_id=completed.event_id,
            source_session=source_session,
            source_report_type=source_report_type,
            source_content_sha256=source_content_sha256,
        )


def completed_surveillance_preflight(
    *,
    journal: OperationalJournal,
    snapshot_path: Path,
    trading_date: date,
    base_policy_version: str,
) -> SurveillancePreflightEvidence | None:
    """Resolve exact snapshot evidence only after its scheduler task completed."""

    try:
        snapshot_sha256 = hashlib.sha256(Path(snapshot_path).read_bytes()).hexdigest()
    except OSError:
        return None
    ledger = SchedulerLedger(journal)
    expected_prefix = base_policy_version + ":surveillance-"
    for event in reversed(journal.read_all()):
        if event.event_type != "SurveillancePreflightCompleted":
            continue
        if event.payload.get("trading_date") != trading_date.isoformat():
            continue
        if event.payload.get("snapshot_sha256") != snapshot_sha256:
            continue
        task_id = event.correlation_id
        if task_id is None:
            continue
        record = ledger.record(task_id)
        if record is None or record.state is not SchedulerTaskState.COMPLETED:
            continue
        task = record.task
        if (
            task.kind is not SchedulerTaskKind.SURVEILLANCE_PREFLIGHT
            or task.trading_date != trading_date
            or not task.policy_version.startswith(expected_prefix)
            or "SURVEILLANCE_PREFLIGHT_READY" not in record.reason_codes
        ):
            continue
        symbols = event.payload.get("symbols")
        if isinstance(symbols, bool) or not isinstance(symbols, int) or symbols < 1:
            continue
        source_report_type = event.payload.get("source_report_type")
        source_content_sha256 = event.payload.get("source_content_sha256")
        try:
            source_session = date.fromisoformat(event.payload["source_session"])
        except (KeyError, TypeError, ValueError):
            continue
        if (
            source_report_type not in {"REG1_IND", "REG_IND"}
            or not isinstance(source_content_sha256, str)
            or len(source_content_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in source_content_sha256
            )
            or source_session >= trading_date
            or trading_date - source_session > date.resolution * 7
        ):
            continue
        return SurveillancePreflightEvidence(
            trading_date=trading_date,
            snapshot_sha256=snapshot_sha256,
            symbols=symbols,
            event_id=event.event_id,
            task_id=task_id,
            source_session=source_session,
            source_report_type=source_report_type,
            source_content_sha256=source_content_sha256,
        )
    return None


def require_surveillance_preflight(
    *,
    journal_path: Path,
    snapshot_path: Path,
    entry_task: ScheduledTask,
) -> SurveillancePreflightEvidence:
    journal = OperationalJournal.open_read_only(journal_path)
    evidence = completed_surveillance_preflight(
        journal=journal,
        snapshot_path=snapshot_path,
        trading_date=entry_task.trading_date,
        base_policy_version=entry_task.policy_version,
    )
    if evidence is None:
        raise SurveillanceSourceUnavailable(
            "surveillance snapshot lacks a completed matching preflight task"
        )
    return evidence


__all__ = [
    "SurveillancePreflightEvidence",
    "SurveillancePreflightResult",
    "SurveillancePreflightSession",
    "completed_surveillance_preflight",
    "require_surveillance_preflight",
]
