"""Durable component heartbeats and derived operational readiness."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping as AbcMapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Mapping

from sensei.operations.journal import EventAppend, OperationalJournal
from sensei.operations.authority import HmacFactSigner, HmacFactVerifier

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

    def __init__(
        self,
        journal: OperationalJournal,
        verifier: HmacFactVerifier,
    ) -> None:
        self._journal = journal
        self._verifier = verifier

    def record_heartbeat(
        self,
        *,
        component: str,
        state: ComponentState,
        occurred_at: datetime,
        command_id: str,
        detail: str,
        signer: HmacFactSigner,
    ) -> ComponentHeartbeat:
        if _COMPONENT.fullmatch(component) is None:
            raise ValueError("component must be a lowercase hyphenated identifier")
        if not isinstance(state, ComponentState):
            raise ValueError("state must be a ComponentState")
        _aware("occurred_at", occurred_at)
        if not command_id.strip():
            raise ValueError("command_id is required")
        if signer.issuer_id != component:
            raise ValueError("a component must sign its own heartbeat")
        observed_at = occurred_at.astimezone(timezone.utc)
        fact = {
            "component": component,
            "state": state.value,
            "detail": detail,
            "observed_at": observed_at.isoformat(),
        }
        signature = signer.sign("ComponentHeartbeatObserved", fact)
        if not self._verifier.verify(
            issuer_id=signer.issuer_id,
            fact_type="ComponentHeartbeatObserved",
            fact=fact,
            signature=signature,
        ):
            raise ValueError("component heartbeat signer is not trusted")
        stream = _component_stream(component)
        events = self._journal.read_stream(stream)
        event = self._journal.append(
            EventAppend(
                stream_id=stream,
                event_type="ComponentHeartbeatRecorded",
                payload={
                    "schema_version": "1.0",
                    "authority": "COMPONENT_HEARTBEAT",
                    "issuer_id": signer.issuer_id,
                    "fact": fact,
                    "signature": signature,
                },
                idempotency_key=_command_key("heartbeat", command_id),
                expected_version=len(events),
                occurred_at=observed_at,
                correlation_id=component,
            )
        )
        return ComponentHeartbeat(
            component=component,
            state=state,
            occurred_at=observed_at,
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
        reasons, evidence = self._derive(
            required_components,
            now=now,
            events=self._journal.read_all(),
            journal_integrity_ok=verification.ok,
        )

        ready = not reasons
        events = self._journal.read_stream(_READINESS_STREAM)
        event = self._journal.append(
            EventAppend(
                stream_id=_READINESS_STREAM,
                event_type="OperationsReadinessAssessed",
                payload={
                    "ready": ready,
                    "required_components": _component_ages(required_components),
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

    def verify_readiness(
        self,
        readiness: OperationsReadiness,
        *,
        required_components: Mapping[str, timedelta],
        no_later_than: datetime,
    ) -> bool:
        """Recompute a durable readiness decision from authenticated heartbeats."""

        try:
            _aware("no_later_than", no_later_than)
            verification = self._journal.verify()
            if not verification.ok:
                return False
            event = next(
                item
                for item in self._journal.read_all()
                if item.event_id == readiness.event_id
            )
            if (
                event.event_type != "OperationsReadinessAssessed"
                or event.schema_version != 1
                or event.occurred_at != readiness.assessed_at
                or event.occurred_at > no_later_than
            ):
                return False
            payload = event.payload
            if set(payload) != {
                "ready",
                "required_components",
                "reason_codes",
                "evidence_event_ids",
                "journal_integrity_ok",
            }:
                return False
            if _plain(payload["required_components"]) != _component_ages(
                required_components
            ):
                return False
            prior_events = tuple(
                item
                for item in self._journal.read_all()
                if item.global_sequence < event.global_sequence
            )
            reasons, evidence = self._derive(
                required_components,
                now=event.occurred_at,
                events=prior_events,
                journal_integrity_ok=True,
            )
            ready = not reasons
            return (
                payload["ready"] is ready
                and tuple(payload["reason_codes"]) == tuple(reasons)
                and tuple(payload["evidence_event_ids"]) == tuple(evidence)
                and payload["journal_integrity_ok"] is True
                and readiness.ready is ready
                and readiness.reason_codes == tuple(reasons)
                and readiness.evidence_event_ids == tuple(evidence)
            )
        except (KeyError, StopIteration, TypeError, ValueError):
            return False

    def _derive(
        self,
        required_components: Mapping[str, timedelta],
        *,
        now: datetime,
        events: tuple[object, ...],
        journal_integrity_ok: bool,
    ) -> tuple[list[str], list[str]]:
        reasons: list[str] = []
        if not journal_integrity_ok:
            reasons.append("JOURNAL_INTEGRITY_FAILED")
        heartbeats: dict[str, object] = {}
        for event in events:
            if event.event_type != "ComponentHeartbeatRecorded":
                continue
            fact = event.payload.get("fact")
            component = (
                str(fact.get("component"))
                if isinstance(fact, AbcMapping)
                else ""
            )
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
            if not self._verify_heartbeat(event, component):
                reasons.append(f"{code}_UNAUTHENTICATED")
                continue
            age = now - event.occurred_at
            if age < timedelta(0):
                reasons.append(f"{code}_FUTURE")
            elif age > required_components[component]:
                reasons.append(f"{code}_STALE")
            state = str(event.payload["fact"]["state"])
            if state != ComponentState.HEALTHY.value:
                reasons.append(f"{code}_{state}")
        return reasons, evidence

    def _verify_heartbeat(self, event, component: str) -> bool:
        try:
            payload = event.payload
            if set(payload) != {
                "schema_version",
                "authority",
                "issuer_id",
                "fact",
                "signature",
            }:
                return False
            if (
                payload["schema_version"] != "1.0"
                or payload["authority"] != "COMPONENT_HEARTBEAT"
                or payload["issuer_id"] != component
            ):
                return False
            fact = _plain(payload["fact"])
            expected = {
                "component": component,
                "state": str(fact["state"]),
                "detail": str(fact["detail"]),
                "observed_at": event.occurred_at.isoformat(),
            }
            if _canonical(fact) != _canonical(expected):
                return False
            ComponentState(str(fact["state"]))
            return self._verifier.verify(
                issuer_id=component,
                fact_type="ComponentHeartbeatObserved",
                fact=expected,
                signature=str(payload["signature"]),
            )
        except (KeyError, TypeError, ValueError):
            return False


def _component_stream(component: str) -> str:
    digest = hashlib.sha256(component.encode("utf-8")).hexdigest()
    return f"operations-heartbeat:{digest}"


def _command_key(namespace: str, command_id: str) -> str:
    digest = hashlib.sha256(command_id.encode("utf-8")).hexdigest()
    return f"{namespace}:{digest}"


def _component_ages(
    required_components: Mapping[str, timedelta],
) -> dict[str, int]:
    return {
        component: int(maximum_age.total_seconds() * 1_000_000)
        for component, maximum_age in sorted(required_components.items())
    }


def _aware(label: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _plain(value: object) -> object:
    if isinstance(value, AbcMapping):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(child) for child in value]
    return value


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
