"""Fail-closed operational health assessment with durable evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from sensei.operations.journal import EventAppend, OperationalJournal


class HealthState(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    HALTED = "HALTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class HealthAssessmentInput:
    now: datetime
    market_data_watermark: datetime | None
    broker_snapshot_at: datetime | None
    last_reconciliation_at: datetime | None
    maximum_market_data_age: timedelta
    maximum_broker_age: timedelta
    maximum_reconciliation_age: timedelta
    session_active: bool
    safety_latched: bool
    unprotected_quantity: int
    unknown_broker_objects: int

    def __post_init__(self) -> None:
        _aware("now", self.now)
        for label, value in (
            ("market_data_watermark", self.market_data_watermark),
            ("broker_snapshot_at", self.broker_snapshot_at),
            ("last_reconciliation_at", self.last_reconciliation_at),
        ):
            if value is not None:
                _aware(label, value)
                if value > self.now:
                    raise ValueError(f"{label} cannot be in the future")
        for label, value in (
            ("maximum_market_data_age", self.maximum_market_data_age),
            ("maximum_broker_age", self.maximum_broker_age),
            ("maximum_reconciliation_age", self.maximum_reconciliation_age),
        ):
            if value <= timedelta(0):
                raise ValueError(f"{label} must be positive")
        if self.unprotected_quantity < 0 or self.unknown_broker_objects < 0:
            raise ValueError("operational counts must not be negative")


@dataclass(frozen=True)
class OperationalHealth:
    state: HealthState
    assessed_at: datetime
    reason_codes: tuple[str, ...]
    new_entries_allowed: bool
    protective_actions_allowed: bool
    event_id: str


class OperationsMonitor:
    def __init__(self, journal: OperationalJournal) -> None:
        self._journal = journal

    def assess(
        self, facts: HealthAssessmentInput, *, command_id: str
    ) -> OperationalHealth:
        reasons: list[str] = []
        missing = False
        halted = False
        degraded = False

        if facts.safety_latched:
            reasons.append("SAFETY_LATCHED")
            halted = True
        if facts.unprotected_quantity:
            reasons.append("UNPROTECTED_EXPOSURE")
            halted = True
        if facts.unknown_broker_objects:
            reasons.append("UNKNOWN_BROKER_OBJECTS")
            halted = True

        checks = (
            (
                "MARKET_DATA",
                facts.market_data_watermark,
                facts.maximum_market_data_age,
            ),
            ("BROKER_SNAPSHOT", facts.broker_snapshot_at, facts.maximum_broker_age),
            (
                "RECONCILIATION",
                facts.last_reconciliation_at,
                facts.maximum_reconciliation_age,
            ),
        )
        for name, timestamp, maximum_age in checks:
            if timestamp is None:
                reasons.append(f"{name}_MISSING")
                missing = True
                continue
            if facts.now - timestamp > maximum_age:
                reasons.append(f"{name}_STALE")
                if name == "MARKET_DATA" and not facts.session_active:
                    degraded = True
                else:
                    halted = True

        if halted:
            state = HealthState.HALTED
        elif missing:
            state = HealthState.UNKNOWN
        elif degraded:
            state = HealthState.DEGRADED
        else:
            state = HealthState.HEALTHY

        events = self._journal.read_stream("operations:health")
        event = self._journal.append(
            EventAppend(
                stream_id="operations:health",
                event_type="OperationalHealthAssessed",
                payload={
                    "state": state.value,
                    "reason_codes": reasons,
                    "new_entries_allowed": state is HealthState.HEALTHY,
                    "protective_actions_allowed": True,
                },
                idempotency_key=command_id,
                expected_version=len(events),
                occurred_at=facts.now,
            )
        )
        return OperationalHealth(
            state=state,
            assessed_at=facts.now,
            reason_codes=tuple(reasons),
            new_entries_allowed=state is HealthState.HEALTHY,
            protective_actions_allowed=True,
            event_id=event.event_id,
        )


def _aware(label: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
