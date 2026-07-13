"""Durable, latched safety control independent of strategy judgment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sensei.operations.journal import EventAppend, OperationalJournal

from .models import require_timestamp

_STREAM = "safety:global"


class SafetyAction(StrEnum):
    ENTRY = "ENTRY"
    PROTECTION = "PROTECTION"
    CANCEL_ENTRY = "CANCEL_ENTRY"


class SafetyBlocked(RuntimeError):
    pass


class SafetyResetRejected(RuntimeError):
    pass


@dataclass(frozen=True)
class SafetyReason:
    reason_code: str
    detail: str


@dataclass(frozen=True)
class SafetyState:
    latched: bool
    reasons: tuple[SafetyReason, ...]
    version: int


@dataclass(frozen=True)
class OwnerAuthorization:
    owner_id: str
    scopes: frozenset[str]
    authenticated_at: datetime
    authenticated: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "scopes", frozenset(self.scopes))
        if not self.owner_id.strip():
            raise ValueError("owner_id must not be blank")
        require_timestamp(self.authenticated_at, "authenticated_at")


@dataclass(frozen=True)
class ReconciliationHealth:
    clean: bool
    observed_at: datetime
    detail: str = ""

    def __post_init__(self) -> None:
        require_timestamp(self.observed_at, "observed_at")


class SafetyControl:
    def __init__(self, journal: OperationalJournal) -> None:
        self._journal = journal

    def latch(
        self,
        *,
        reason_code: str,
        detail: str,
        occurred_at: datetime,
        idempotency_key: str,
    ) -> SafetyState:
        require_timestamp(occurred_at, "occurred_at")
        if not reason_code.strip():
            raise ValueError("reason_code must not be blank")
        events = self._journal.read_stream(_STREAM)
        self._journal.append(
            EventAppend(
                stream_id=_STREAM,
                event_type="SafetyLatched",
                payload={"reason_code": reason_code, "detail": detail},
                idempotency_key=idempotency_key,
                expected_version=len(events),
                occurred_at=occurred_at,
            )
        )
        return self.state()

    def reset(
        self,
        authorization: OwnerAuthorization,
        reconciliation: ReconciliationHealth,
        *,
        occurred_at: datetime,
        idempotency_key: str,
    ) -> SafetyState:
        require_timestamp(occurred_at, "occurred_at")
        if (
            not authorization.authenticated
            or "safety:reset" not in authorization.scopes
        ):
            raise SafetyResetRejected("valid owner authorization is required")
        if not reconciliation.clean:
            raise SafetyResetRejected("a clean reconciliation is required")
        events = self._journal.read_stream(_STREAM)
        latest_latch = next(
            (
                event
                for event in reversed(events)
                if event.event_type == "SafetyLatched"
            ),
            None,
        )
        if (
            latest_latch is not None
            and reconciliation.observed_at < latest_latch.occurred_at
        ):
            raise SafetyResetRejected(
                "clean reconciliation must be newer than the safety latch"
            )
        if authorization.authenticated_at > occurred_at:
            raise SafetyResetRejected("owner authorization cannot be in the future")
        if reconciliation.observed_at > occurred_at:
            raise SafetyResetRejected("reconciliation cannot be in the future")
        self._journal.append(
            EventAppend(
                stream_id=_STREAM,
                event_type="SafetyReset",
                payload={
                    "owner_id": authorization.owner_id,
                    "authenticated_at": authorization.authenticated_at.isoformat(),
                    "reconciliation_observed_at": reconciliation.observed_at.isoformat(),
                },
                idempotency_key=idempotency_key,
                expected_version=len(events),
                occurred_at=occurred_at,
            )
        )
        return self.state()

    def state(self) -> SafetyState:
        latched = False
        reasons: list[SafetyReason] = []
        events = self._journal.read_stream(_STREAM)
        for event in events:
            if event.event_type == "SafetyLatched":
                latched = True
                reasons.append(
                    SafetyReason(
                        reason_code=str(event.payload["reason_code"]),
                        detail=str(event.payload["detail"]),
                    )
                )
            elif event.event_type == "SafetyReset":
                latched = False
                reasons.clear()
        return SafetyState(latched=latched, reasons=tuple(reasons), version=len(events))

    def assert_allowed(self, action: SafetyAction) -> None:
        action = SafetyAction(action)
        if action is not SafetyAction.ENTRY:
            return
        state = self.state()
        if state.latched:
            codes = ", ".join(reason.reason_code for reason in state.reasons)
            raise SafetyBlocked(f"new entry blocked by latched safety: {codes}")
