"""Fail-closed health derived only from authenticated operational evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from sensei.operations.authority import HmacFactSigner, HmacFactVerifier
from sensei.operations.control_plane import (
    OperationsControlPlane,
    OperationsReadiness,
)
from sensei.operations.journal import EventAppend, OperationalJournal


class HealthState(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    HALTED = "HALTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class HealthAssessmentInput:
    now: datetime
    readiness: OperationsReadiness

    def __post_init__(self) -> None:
        _aware("now", self.now)
        if not isinstance(self.readiness, OperationsReadiness):
            raise TypeError("readiness must be an OperationsReadiness decision")


@dataclass(frozen=True)
class OperationalHealth:
    state: HealthState
    assessed_at: datetime
    reason_codes: tuple[str, ...]
    new_entries_allowed: bool
    protective_actions_allowed: bool
    readiness_event_id: str
    readiness_evidence_event_ids: tuple[str, ...]
    event_id: str


class OperationsMonitor:
    """Derive and authenticate health; caller booleans are never accepted."""

    def __init__(
        self,
        journal: OperationalJournal,
        *,
        control_plane: OperationsControlPlane,
        required_components: Mapping[str, timedelta],
        maximum_readiness_age: timedelta,
        signer: HmacFactSigner,
        verifier: HmacFactVerifier,
    ) -> None:
        if not required_components:
            raise ValueError("health requires at least one operational component")
        if any(age <= timedelta(0) for age in required_components.values()):
            raise ValueError("component maximum ages must be positive")
        if maximum_readiness_age <= timedelta(0):
            raise ValueError("maximum_readiness_age must be positive")
        self._journal = journal
        self._control_plane = control_plane
        self._required_components = dict(required_components)
        self._maximum_readiness_age = maximum_readiness_age
        self._signer = signer
        self._verifier = verifier

    def assess(
        self, facts: HealthAssessmentInput, *, command_id: str
    ) -> OperationalHealth:
        if not command_id.strip():
            raise ValueError("command_id is required")
        now = facts.now.astimezone(timezone.utc)
        readiness = facts.readiness
        readiness_valid = self._control_plane.verify_readiness(
            readiness,
            required_components=self._required_components,
            no_later_than=now,
        )
        state, reasons = self._derive(
            readiness,
            readiness_valid=readiness_valid,
            now=now,
            safety_latched=_safety_latched(self._journal.read_all()),
        )
        fact = _fact(state, reasons, readiness, now)
        signature = self._signer.sign("OperationalHealthDerived", fact)
        if not self._verifier.verify(
            issuer_id=self._signer.issuer_id,
            fact_type="OperationalHealthDerived",
            fact=fact,
            signature=signature,
        ):
            raise ValueError("operations monitor signer is not trusted")
        events = self._journal.read_stream("operations:health")
        event = self._journal.append(
            EventAppend(
                stream_id="operations:health",
                event_type="OperationalHealthAssessed",
                payload={
                    "schema_version": "2.0",
                    "authority": "AUTHENTICATED_OPERATIONS_MONITOR",
                    "issuer_id": self._signer.issuer_id,
                    "fact": fact,
                    "signature": signature,
                },
                idempotency_key="health:" + _digest(command_id),
                expected_version=len(events),
                occurred_at=now,
                causation_id=readiness.event_id,
            )
        )
        return _health_from_fact(fact, event.event_id)

    def verify(
        self,
        health: OperationalHealth,
        *,
        no_later_than: datetime,
    ) -> bool:
        """Verify the signature and independently reproduce the health result."""

        try:
            _aware("no_later_than", no_later_than)
            verification = self._journal.verify()
            if not verification.ok:
                return False
            event = next(
                item
                for item in self._journal.read_all()
                if item.event_id == health.event_id
            )
            if (
                event.event_type != "OperationalHealthAssessed"
                or event.schema_version != 1
                or event.occurred_at != health.assessed_at
                or event.occurred_at > no_later_than
            ):
                return False
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
                payload["schema_version"] != "2.0"
                or payload["authority"]
                != "AUTHENTICATED_OPERATIONS_MONITOR"
                or payload["issuer_id"] != self._signer.issuer_id
            ):
                return False
            fact = _plain(payload["fact"])
            readiness = _readiness_from_fact(fact)
            readiness_valid = self._control_plane.verify_readiness(
                readiness,
                required_components=self._required_components,
                no_later_than=event.occurred_at,
            )
            prior_events = tuple(
                item
                for item in self._journal.read_all()
                if item.global_sequence < event.global_sequence
            )
            state, reasons = self._derive(
                readiness,
                readiness_valid=readiness_valid,
                now=event.occurred_at,
                safety_latched=_safety_latched(prior_events),
            )
            expected_fact = _fact(state, reasons, readiness, event.occurred_at)
            if _canonical(fact) != _canonical(expected_fact):
                return False
            if _health_from_fact(expected_fact, event.event_id) != health:
                return False
            return self._verifier.verify(
                issuer_id=str(payload["issuer_id"]),
                fact_type="OperationalHealthDerived",
                fact=expected_fact,
                signature=str(payload["signature"]),
            )
        except (KeyError, StopIteration, TypeError, ValueError):
            return False

    def _derive(
        self,
        readiness: OperationsReadiness,
        *,
        readiness_valid: bool,
        now: datetime,
        safety_latched: bool,
    ) -> tuple[HealthState, tuple[str, ...]]:
        reasons: list[str] = []
        if not readiness_valid:
            reasons.append("READINESS_EVIDENCE_INVALID")
            state = HealthState.UNKNOWN
        else:
            age = now - readiness.assessed_at
            if age < timedelta(0):
                reasons.append("READINESS_FUTURE")
                state = HealthState.UNKNOWN
            elif age > self._maximum_readiness_age:
                reasons.append("READINESS_STALE")
                state = HealthState.HALTED
            elif not readiness.ready:
                reasons.extend(readiness.reason_codes)
                state = (
                    HealthState.UNKNOWN
                    if any(
                        reason.endswith("_MISSING")
                        or reason == "JOURNAL_INTEGRITY_FAILED"
                        for reason in reasons
                    )
                    else HealthState.HALTED
                )
            else:
                state = HealthState.HEALTHY
        if safety_latched:
            reasons.append("SAFETY_LATCHED")
            state = HealthState.HALTED
        return state, tuple(reasons)


def _fact(
    state: HealthState,
    reasons: tuple[str, ...],
    readiness: OperationsReadiness,
    assessed_at: datetime,
) -> dict[str, object]:
    return {
        "state": state.value,
        "reason_codes": list(reasons),
        "new_entries_allowed": state is HealthState.HEALTHY,
        "protective_actions_allowed": True,
        "assessed_at": assessed_at.astimezone(timezone.utc).isoformat(),
        "readiness": {
            "event_id": readiness.event_id,
            "ready": readiness.ready,
            "assessed_at": readiness.assessed_at.astimezone(timezone.utc).isoformat(),
            "reason_codes": list(readiness.reason_codes),
            "evidence_event_ids": list(readiness.evidence_event_ids),
        },
    }


def _health_from_fact(
    fact: Mapping[str, object], event_id: str
) -> OperationalHealth:
    readiness = fact["readiness"]
    if not isinstance(readiness, Mapping):
        raise TypeError("health readiness fact is invalid")
    return OperationalHealth(
        state=HealthState(str(fact["state"])),
        assessed_at=datetime.fromisoformat(str(fact["assessed_at"])),
        reason_codes=tuple(str(value) for value in fact["reason_codes"]),
        new_entries_allowed=bool(fact["new_entries_allowed"]),
        protective_actions_allowed=bool(fact["protective_actions_allowed"]),
        readiness_event_id=str(readiness["event_id"]),
        readiness_evidence_event_ids=tuple(
            str(value) for value in readiness["evidence_event_ids"]
        ),
        event_id=event_id,
    )


def _readiness_from_fact(fact: Mapping[str, object]) -> OperationsReadiness:
    readiness = fact["readiness"]
    if not isinstance(readiness, Mapping):
        raise TypeError("health readiness fact is invalid")
    return OperationsReadiness(
        ready=bool(readiness["ready"]),
        assessed_at=datetime.fromisoformat(str(readiness["assessed_at"])),
        reason_codes=tuple(str(value) for value in readiness["reason_codes"]),
        evidence_event_ids=tuple(
            str(value) for value in readiness["evidence_event_ids"]
        ),
        event_id=str(readiness["event_id"]),
    )


def _safety_latched(events: tuple[object, ...]) -> bool:
    latched = False
    for event in events:
        if event.event_type == "SafetyLatched":
            latched = True
        elif event.event_type == "SafetyReset":
            latched = False
    return latched


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
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


def _aware(label: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
