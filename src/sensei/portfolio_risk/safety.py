"""Durable, latched safety control independent of strategy judgment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sensei.operations.journal import EventAppend, OperationalJournal

from .models import require_timestamp
from .safety_authority import (
    OwnerAuthorization,
    ReconciliationHealth,
    SafetyResetAuthority,
)

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


class SafetyControl:
    def __init__(
        self,
        journal: OperationalJournal,
        *,
        reset_authority: SafetyResetAuthority | None = None,
        maximum_authorization_age: timedelta = timedelta(minutes=5),
        maximum_reconciliation_age: timedelta = timedelta(minutes=2),
    ) -> None:
        if maximum_authorization_age <= timedelta(0):
            raise ValueError("maximum_authorization_age must be positive")
        if maximum_reconciliation_age <= timedelta(0):
            raise ValueError("maximum_reconciliation_age must be positive")
        self._journal = journal
        self._reset_authority = reset_authority
        self._maximum_authorization_age = maximum_authorization_age
        self._maximum_reconciliation_age = maximum_reconciliation_age

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
            self._reset_authority is None
            or not self._reset_authority.verify_owner(
                authorization, no_later_than=occurred_at
            )
            or "safety:reset" not in authorization.scopes
        ):
            raise SafetyResetRejected("valid owner authorization is required")
        if (
            not self._reset_authority.verify_reconciliation(
                reconciliation, no_later_than=occurred_at
            )
            or not self._reset_authority.is_latest_reconciliation(
                reconciliation.event_id
            )
            or not reconciliation.clean
        ):
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
        if (
            latest_latch is not None
            and authorization.authenticated_at < latest_latch.occurred_at
        ):
            raise SafetyResetRejected(
                "owner authorization must be newer than the safety latch"
            )
        if authorization.authenticated_at > occurred_at:
            raise SafetyResetRejected("owner authorization cannot be in the future")
        if reconciliation.observed_at > occurred_at:
            raise SafetyResetRejected("reconciliation cannot be in the future")
        if occurred_at - authorization.authenticated_at > self._maximum_authorization_age:
            raise SafetyResetRejected("owner authorization is stale")
        if occurred_at - reconciliation.observed_at > self._maximum_reconciliation_age:
            raise SafetyResetRejected("clean reconciliation is stale")
        self._journal.append(
            EventAppend(
                stream_id=_STREAM,
                event_type="SafetyReset",
                payload={
                    "owner_id": authorization.owner_id,
                    "owner_authorization_event_id": authorization.event_id,
                    "authenticated_at": authorization.authenticated_at.isoformat(),
                    "reconciliation_observed_at": reconciliation.observed_at.isoformat(),
                    "reconciliation_event_id": reconciliation.event_id,
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
