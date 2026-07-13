"""Durable component heartbeats and derived operational readiness."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Mapping

from sensei.operations.journal import EventAppend, OperationalJournal

_COMPONENT = re.compile(r"[a-z][a-z0-9-]{1,62}\Z")
_READINESS_STREAM = "operations:readiness"


class ComponentState(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    HALTED = "HALTED"


@dataclass(frozen=True)
class ComponentHeartbeat:
    component: str
    state: ComponentState
    occurred_at: datetime
    detail: str
    event_id: str


@dataclass(frozen=True)
class OperationsReadiness:
    ready: bool
    assessed_at: datetime
    reason_codes: tuple[str, ...]
    evidence_event_ids: tuple[str, ...]
    event_id: str


class OperationsControlPlane:
    """Own readiness evidence; prose or caller booleans are not accepted."""

    def __init__(self, journal: OperationalJournal) -> None:
        self._journal = journal

    def record_heartbeat(
        self,
        *,
        component: str,
        state: ComponentState,
        occurred_at: datetime,
        command_id: str,
        detail: str,
    ) -> ComponentHeartbeat:
        if _COMPONENT.fullmatch(component) is None:
            raise ValueError("component must be a lowercase hyphenated identifier")
        if not isinstance(state, ComponentState):
            raise ValueError("state must be a ComponentState")
        _aware("occurred_at", occurred_at)
        if not command_id.strip():
            raise ValueError("command_id is required")
        stream = _component_stream(component)
        events = self._journal.read_stream(stream)
        event = self._journal.append(
            EventAppend(
                stream_id=stream,
                event_type="ComponentHeartbeatRecorded",
                payload={
                    "component": component,
                    "state": state.value,
                    "detail": detail,
                },
                idempotency_key=_command_key("heartbeat", command_id),
                expected_version=len(events),
                occurred_at=occurred_at,
                correlation_id=component,
            )
        )
        return ComponentHeartbeat(
            component=component,
            state=state,
            occurred_at=occurred_at,
            detail=detail,
            event_id=event.event_id,
        )

    def assess_readiness(
        self,
        *,
        required_components: Mapping[str, timedelta],
        now: datetime,
        command_id: str,
    ) -> OperationsReadiness:
        _aware("now", now)
        if not required_components:
            raise ValueError("at least one required component is needed")
        for component, maximum_age in required_components.items():
            if _COMPONENT.fullmatch(component) is None:
                raise ValueError("required component identifier is invalid")
            if maximum_age <= timedelta(0):
                raise ValueError("component maximum ages must be positive")

        verification = self._journal.verify()
        reasons: list[str] = []
        if not verification.ok:
            reasons.append("JOURNAL_INTEGRITY_FAILED")
        heartbeats: dict[str, object] = {}
        for event in self._journal.read_all():
            if event.event_type != "ComponentHeartbeatRecorded":
                continue
            component = str(event.payload["component"])
            if component in required_components:
                heartbeats[component] = event

        evidence: list[str] = []
        for component in sorted(required_components):
            code = component.upper()
            event = heartbeats.get(component)
            if event is None:
                reasons.append(f"{code}_MISSING")
                continue
            evidence.append(event.event_id)
            age = now - event.occurred_at
            if age < timedelta(0):
                reasons.append(f"{code}_FUTURE")
            elif age > required_components[component]:
                reasons.append(f"{code}_STALE")
            state = str(event.payload["state"])
            if state != ComponentState.HEALTHY.value:
                reasons.append(f"{code}_{state}")

        ready = not reasons
        events = self._journal.read_stream(_READINESS_STREAM)
        event = self._journal.append(
            EventAppend(
                stream_id=_READINESS_STREAM,
                event_type="OperationsReadinessAssessed",
                payload={
                    "ready": ready,
                    "required_components": sorted(required_components),
                    "reason_codes": reasons,
                    "evidence_event_ids": evidence,
                    "journal_integrity_ok": verification.ok,
                },
                idempotency_key=_command_key("readiness", command_id),
                expected_version=len(events),
                occurred_at=now,
            )
        )
        return OperationsReadiness(
            ready=ready,
            assessed_at=now,
            reason_codes=tuple(reasons),
            evidence_event_ids=tuple(evidence),
            event_id=event.event_id,
        )


def _component_stream(component: str) -> str:
    digest = hashlib.sha256(component.encode("utf-8")).hexdigest()
    return f"operations-heartbeat:{digest}"


def _command_key(namespace: str, command_id: str) -> str:
    digest = hashlib.sha256(command_id.encode("utf-8")).hexdigest()
    return f"{namespace}:{digest}"


def _aware(label: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
