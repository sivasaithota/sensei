"""Authenticated owner and reconciliation evidence for safety reset."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sensei.operations import (
    EventAppend,
    HmacFactSigner,
    HmacFactVerifier,
    JournalEvent,
    OperationalJournal,
)

from .models import require_timestamp

_EVENT_ID = re.compile(r"event:[0-9a-f]{64}\Z")
_SNAPSHOT_ID = re.compile(r"broker-snapshot:[0-9a-f]{64}\Z")
_RUNTIME_BINDING_FACT_TYPE = "SafetyResetRuntimeBinding"
_SAFETY_STREAM = "safety:global"


@dataclass(frozen=True)
class SafetyHistoryProjection:
    """Fail-closed point-in-time interpretation of the safety stream."""

    latched: bool
    history_valid: bool
    reasons: tuple[tuple[str, str], ...]
    version: int


@dataclass(frozen=True)
class OwnerAuthorization:
    event_id: str
    owner_id: str
    scopes: frozenset[str]
    authenticated_at: datetime
    issuer_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "scopes", frozenset(self.scopes))
        require_timestamp(self.authenticated_at, "authenticated_at")


@dataclass(frozen=True)
class ReconciliationHealth:
    event_id: str
    kernel_event_id: str
    broker_snapshot_event_id: str
    snapshot_id: str
    clean: bool
    issues: tuple[str, ...]
    observed_at: datetime
    issuer_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "issues", tuple(self.issues))
        require_timestamp(self.observed_at, "observed_at")


class SafetyResetAuthority:
    """Mint and verify the two independent capabilities needed for reset."""

    def __init__(
        self,
        journal: OperationalJournal,
        *,
        owner_verifier: HmacFactVerifier,
        reconciliation_verifier: HmacFactVerifier,
        expected_reconciliation_issuer_id: str,
    ) -> None:
        if not expected_reconciliation_issuer_id.strip():
            raise ValueError("expected reconciliation issuer is required")
        self._journal = journal
        self._owner_verifier = owner_verifier
        self._reconciliation_verifier = reconciliation_verifier
        self._expected_reconciliation_issuer_id = (
            expected_reconciliation_issuer_id
        )

    def is_bound_to_journal(self, journal: OperationalJournal) -> bool:
        """Return whether reset evidence uses the exact runtime journal."""

        return self._journal is journal

    def is_bound_to_reconciliation_runtime(
        self,
        *,
        journal: OperationalJournal,
        signer: HmacFactSigner,
    ) -> bool:
        """Check the journal and configured reconciliation signing credential."""

        if self._journal is not journal or not isinstance(signer, HmacFactSigner):
            return False
        if signer.issuer_id != self._expected_reconciliation_issuer_id:
            return False
        fact = {"schema_version": "1.0", "purpose": "composition"}
        signature = signer.sign(
            _RUNTIME_BINDING_FACT_TYPE,
            fact,
        )
        return self._reconciliation_verifier.verify(
            issuer_id=signer.issuer_id,
            fact_type=_RUNTIME_BINDING_FACT_TYPE,
            fact=fact,
            signature=signature,
        )

    def authorize_owner(
        self,
        *,
        owner_id: str,
        scopes: frozenset[str],
        signer: HmacFactSigner,
        occurred_at: datetime,
        command_id: str,
    ) -> OwnerAuthorization:
        if not owner_id.strip() or not command_id.strip():
            raise ValueError("owner_id and command_id are required")
        if signer.issuer_id != owner_id:
            raise ValueError("an owner must sign their own authorization")
        authenticated_at = _utc(occurred_at)
        normalized_scopes = frozenset(scopes)
        fact = {
            "owner_id": owner_id,
            "scopes": sorted(normalized_scopes),
            "authenticated_at": authenticated_at.isoformat(),
        }
        signature = signer.sign("OwnerSafetyResetAuthorized", fact)
        if not self._owner_verifier.verify(
            issuer_id=owner_id,
            fact_type="OwnerSafetyResetAuthorized",
            fact=fact,
            signature=signature,
        ):
            raise ValueError("owner authorization signer is not trusted")
        event = self._journal.append(
            EventAppend(
                stream_id="owner-reset:" + _digest(_canonical(fact)),
                event_type="OwnerSafetyResetAuthorized",
                payload={
                    "schema_version": "1.0",
                    "authority": "OWNER_SAFETY_RESET",
                    "issuer_id": owner_id,
                    "fact": fact,
                    "signature": signature,
                },
                idempotency_key="owner-reset:" + _digest(command_id),
                expected_version=0,
                occurred_at=authenticated_at,
                correlation_id=owner_id,
            )
        )
        return OwnerAuthorization(
            event_id=event.event_id,
            owner_id=owner_id,
            scopes=normalized_scopes,
            authenticated_at=authenticated_at,
            issuer_id=owner_id,
        )

    def attest_reconciliation(
        self,
        *,
        kernel_event_id: str,
        broker_snapshot_event_id: str,
        snapshot_id: str,
        clean: bool,
        issues: tuple[str, ...],
        signer: HmacFactSigner,
        occurred_at: datetime,
        command_id: str,
    ) -> ReconciliationHealth:
        if not isinstance(clean, bool):
            raise TypeError("clean must be a boolean")
        if (
            _EVENT_ID.fullmatch(kernel_event_id) is None
            or _EVENT_ID.fullmatch(broker_snapshot_event_id) is None
            or _SNAPSHOT_ID.fullmatch(snapshot_id) is None
        ):
            raise ValueError("reconciliation evidence identities are invalid")
        if signer.issuer_id != self._expected_reconciliation_issuer_id:
            raise ValueError("reconciliation signer is not the configured issuer")
        if not command_id.strip():
            raise ValueError("command_id is required")
        normalized_issues = tuple(str(issue) for issue in issues)
        if clean is bool(normalized_issues):
            raise ValueError("clean reconciliation and issues are inconsistent")
        observed_at = _utc(occurred_at)
        kernel_event = self._kernel_event(
            kernel_event_id,
            broker_snapshot_event_id=broker_snapshot_event_id,
            snapshot_id=snapshot_id,
            clean=clean,
            issues=normalized_issues,
        )
        if kernel_event.occurred_at > observed_at:
            raise ValueError("reconciliation cannot precede its kernel decision")
        fact = {
            "kernel_event_id": kernel_event_id,
            "broker_snapshot_event_id": broker_snapshot_event_id,
            "snapshot_id": snapshot_id,
            "clean": clean,
            "issues": list(normalized_issues),
            "observed_at": observed_at.isoformat(),
        }
        signature = signer.sign("ReconciliationOutcomeAttested", fact)
        if not self._reconciliation_verifier.verify(
            issuer_id=signer.issuer_id,
            fact_type="ReconciliationOutcomeAttested",
            fact=fact,
            signature=signature,
        ):
            raise ValueError("reconciliation signer is not trusted")
        event = self._journal.append(
            EventAppend(
                stream_id="reconciliation-attestation:" + _digest(kernel_event_id),
                event_type="ReconciliationOutcomeAttested",
                payload={
                    "schema_version": "1.0",
                    "authority": "KERNEL_RECONCILIATION",
                    "issuer_id": signer.issuer_id,
                    "fact": fact,
                    "signature": signature,
                },
                idempotency_key="reconciliation-attestation:" + _digest(command_id),
                expected_version=0,
                occurred_at=observed_at,
                causation_id=kernel_event_id,
                correlation_id=snapshot_id,
            )
        )
        return ReconciliationHealth(
            event_id=event.event_id,
            kernel_event_id=kernel_event_id,
            broker_snapshot_event_id=broker_snapshot_event_id,
            snapshot_id=snapshot_id,
            clean=clean,
            issues=normalized_issues,
            observed_at=observed_at,
            issuer_id=signer.issuer_id,
        )

    def verify_owner(
        self, authorization: OwnerAuthorization, *, no_later_than: datetime
    ) -> bool:
        fact = {
            "owner_id": authorization.owner_id,
            "scopes": sorted(authorization.scopes),
            "authenticated_at": authorization.authenticated_at.astimezone(
                timezone.utc
            ).isoformat(),
        }
        return self._verify_event(
            authorization.event_id,
            event_type="OwnerSafetyResetAuthorized",
            authority="OWNER_SAFETY_RESET",
            issuer_id=authorization.owner_id,
            fact_type="OwnerSafetyResetAuthorized",
            fact=fact,
            verifier=self._owner_verifier,
            no_later_than=no_later_than,
        )

    def verify_reconciliation(
        self, reconciliation: ReconciliationHealth, *, no_later_than: datetime
    ) -> bool:
        fact = {
            "kernel_event_id": reconciliation.kernel_event_id,
            "broker_snapshot_event_id": reconciliation.broker_snapshot_event_id,
            "snapshot_id": reconciliation.snapshot_id,
            "clean": reconciliation.clean,
            "issues": list(reconciliation.issues),
            "observed_at": reconciliation.observed_at.astimezone(
                timezone.utc
            ).isoformat(),
        }
        if not self._verify_event(
            reconciliation.event_id,
            event_type="ReconciliationOutcomeAttested",
            authority="KERNEL_RECONCILIATION",
            issuer_id=self._expected_reconciliation_issuer_id,
            fact_type="ReconciliationOutcomeAttested",
            fact=fact,
            verifier=self._reconciliation_verifier,
            no_later_than=no_later_than,
        ):
            return False
        try:
            self._kernel_event(
                reconciliation.kernel_event_id,
                broker_snapshot_event_id=reconciliation.broker_snapshot_event_id,
                snapshot_id=reconciliation.snapshot_id,
                clean=reconciliation.clean,
                issues=reconciliation.issues,
            )
        except (KeyError, StopIteration, TypeError, ValueError):
            return False
        return True

    def is_latest_reconciliation(self, event_id: str) -> bool:
        events = [
            event
            for event in self._journal.read_all()
            if event.event_type == "ReconciliationOutcomeAttested"
        ]
        return bool(events) and events[-1].event_id == event_id

    def verify_historical_reset(
        self,
        reset_event: JournalEvent,
        *,
        latest_latch: JournalEvent,
        maximum_authorization_age: timedelta,
        maximum_reconciliation_age: timedelta,
        available_events: tuple[JournalEvent, ...],
    ) -> bool:
        """Verify a reset using only evidence that existed at that reset."""

        try:
            if (
                maximum_authorization_age <= timedelta(0)
                or maximum_reconciliation_age <= timedelta(0)
                or not self._journal.verify().ok
            ):
                return False
            indexed = {event.event_id: event for event in available_events}
            recorded_reset = indexed.get(reset_event.event_id)
            recorded_latch = indexed.get(latest_latch.event_id)
            if (
                recorded_reset is None
                or recorded_latch is None
                or recorded_reset.event_hash != reset_event.event_hash
                or recorded_latch.event_hash != latest_latch.event_hash
                or reset_event.stream_id != _SAFETY_STREAM
                or reset_event.event_type != "SafetyReset"
                or reset_event.schema_version != 1
                or latest_latch.stream_id != _SAFETY_STREAM
                or latest_latch.event_type != "SafetyLatched"
                or latest_latch.global_sequence >= reset_event.global_sequence
            ):
                return False
            prior_latches = [
                event
                for event in available_events
                if event.stream_id == _SAFETY_STREAM
                and event.event_type == "SafetyLatched"
                and event.global_sequence < reset_event.global_sequence
            ]
            if (
                not prior_latches
                or prior_latches[-1].event_id != latest_latch.event_id
            ):
                return False

            payload = reset_event.payload
            if set(payload) != {
                "owner_id",
                "owner_authorization_event_id",
                "authenticated_at",
                "reconciliation_observed_at",
                "reconciliation_event_id",
            }:
                return False
            authorization_event = indexed[str(payload["owner_authorization_event_id"])]
            reconciliation_event = indexed[str(payload["reconciliation_event_id"])]
            authorization = self._owner_from_event(authorization_event)
            reconciliation = self._reconciliation_from_event(
                reconciliation_event
            )
            kernel_event = indexed[reconciliation.kernel_event_id]

            if (
                str(payload["owner_id"]) != authorization.owner_id
                or str(payload["authenticated_at"])
                != authorization.authenticated_at.isoformat()
                or str(payload["reconciliation_observed_at"])
                != reconciliation.observed_at.isoformat()
                or authorization.issuer_id != authorization.owner_id
                or "safety:reset" not in authorization.scopes
                or reconciliation.issuer_id
                != self._expected_reconciliation_issuer_id
                or not reconciliation.clean
                or reconciliation.issues
                or not (
                    latest_latch.global_sequence
                    < authorization_event.global_sequence
                    < reset_event.global_sequence
                )
                or not (
                    latest_latch.global_sequence
                    < kernel_event.global_sequence
                    < reconciliation_event.global_sequence
                    < reset_event.global_sequence
                )
                or authorization_event.occurred_at
                != authorization.authenticated_at
                or reconciliation_event.occurred_at
                != reconciliation.observed_at
                or latest_latch.recorded_at > reset_event.recorded_at
                or authorization_event.recorded_at > reset_event.recorded_at
                or reconciliation_event.recorded_at > reset_event.recorded_at
                or kernel_event.recorded_at > reset_event.recorded_at
                or latest_latch.occurred_at > latest_latch.recorded_at
                or authorization.authenticated_at
                > authorization_event.recorded_at
                or reconciliation.observed_at > reconciliation_event.recorded_at
                or kernel_event.occurred_at > kernel_event.recorded_at
                or reset_event.occurred_at > reset_event.recorded_at
                or reset_event.occurred_at < latest_latch.occurred_at
                or authorization.authenticated_at < latest_latch.occurred_at
                or reconciliation.observed_at < latest_latch.occurred_at
                or kernel_event.occurred_at < latest_latch.occurred_at
                or kernel_event.occurred_at > reconciliation.observed_at
                or authorization.authenticated_at > reset_event.occurred_at
                or reconciliation.observed_at > reset_event.occurred_at
                or authorization.authenticated_at > reset_event.recorded_at
                or reconciliation.observed_at > reset_event.recorded_at
                or reset_event.recorded_at - authorization.authenticated_at
                > maximum_authorization_age
                or reset_event.recorded_at - reconciliation.observed_at
                > maximum_reconciliation_age
            ):
                return False
            reconciliations_before_reset = [
                event
                for event in available_events
                if event.event_type == "ReconciliationOutcomeAttested"
                and event.global_sequence < reset_event.global_sequence
            ]
            if (
                not reconciliations_before_reset
                or reconciliations_before_reset[-1].event_id
                != reconciliation.event_id
            ):
                return False
            return self.verify_owner(
                authorization,
                no_later_than=reset_event.occurred_at,
            ) and self.verify_reconciliation(
                reconciliation,
                no_later_than=reset_event.occurred_at,
            )
        except (KeyError, StopIteration, TypeError, ValueError):
            return False

    def _owner_from_event(self, event: JournalEvent) -> OwnerAuthorization:
        payload = event.payload
        if (
            event.event_type != "OwnerSafetyResetAuthorized"
            or event.schema_version != 1
            or set(payload)
            != {
                "schema_version",
                "authority",
                "issuer_id",
                "fact",
                "signature",
            }
            or not isinstance(payload["fact"], Mapping)
        ):
            raise ValueError("owner reset evidence is malformed")
        fact = payload["fact"]
        if set(fact) != {"owner_id", "scopes", "authenticated_at"}:
            raise ValueError("owner reset fact is malformed")
        scopes = fact["scopes"]
        if not isinstance(scopes, (list, tuple)) or not all(
            isinstance(scope, str) for scope in scopes
        ):
            raise TypeError("owner reset scopes are malformed")
        authenticated_at = datetime.fromisoformat(str(fact["authenticated_at"]))
        authorization = OwnerAuthorization(
            event_id=event.event_id,
            owner_id=str(fact["owner_id"]),
            scopes=frozenset(scopes),
            authenticated_at=authenticated_at,
            issuer_id=str(payload["issuer_id"]),
        )
        expected_stream = "owner-reset:" + _digest(_canonical(_plain(fact)))
        if (
            event.stream_id != expected_stream
            or event.occurred_at != authenticated_at
            or event.correlation_id != authorization.owner_id
        ):
            raise ValueError("owner reset event linkage is invalid")
        return authorization

    def _reconciliation_from_event(
        self, event: JournalEvent
    ) -> ReconciliationHealth:
        payload = event.payload
        if (
            event.event_type != "ReconciliationOutcomeAttested"
            or event.schema_version != 1
            or set(payload)
            != {
                "schema_version",
                "authority",
                "issuer_id",
                "fact",
                "signature",
            }
            or not isinstance(payload["fact"], Mapping)
        ):
            raise ValueError("reconciliation evidence is malformed")
        fact = payload["fact"]
        if set(fact) != {
            "kernel_event_id",
            "broker_snapshot_event_id",
            "snapshot_id",
            "clean",
            "issues",
            "observed_at",
        }:
            raise ValueError("reconciliation fact is malformed")
        issues = fact["issues"]
        if (
            not isinstance(fact["clean"], bool)
            or not isinstance(issues, (list, tuple))
            or not all(isinstance(issue, str) for issue in issues)
        ):
            raise TypeError("reconciliation fact values are malformed")
        observed_at = datetime.fromisoformat(str(fact["observed_at"]))
        reconciliation = ReconciliationHealth(
            event_id=event.event_id,
            kernel_event_id=str(fact["kernel_event_id"]),
            broker_snapshot_event_id=str(fact["broker_snapshot_event_id"]),
            snapshot_id=str(fact["snapshot_id"]),
            clean=fact["clean"],
            issues=tuple(issues),
            observed_at=observed_at,
            issuer_id=str(payload["issuer_id"]),
        )
        expected_stream = "reconciliation-attestation:" + _digest(
            reconciliation.kernel_event_id
        )
        if (
            event.stream_id != expected_stream
            or event.occurred_at != observed_at
            or event.causation_id != reconciliation.kernel_event_id
            or event.correlation_id != reconciliation.snapshot_id
        ):
            raise ValueError("reconciliation event linkage is invalid")
        return reconciliation

    def _verify_event(
        self,
        event_id: str,
        *,
        event_type: str,
        authority: str,
        issuer_id: str,
        fact_type: str,
        fact: Mapping[str, object],
        verifier: HmacFactVerifier,
        no_later_than: datetime,
    ) -> bool:
        try:
            cutoff = _utc(no_later_than)
            if not self._journal.verify().ok:
                return False
            event = next(
                item for item in self._journal.read_all() if item.event_id == event_id
            )
            payload = event.payload
            if (
                event.event_type != event_type
                or event.occurred_at > cutoff
                or set(payload)
                != {
                    "schema_version",
                    "authority",
                    "issuer_id",
                    "fact",
                    "signature",
                }
                or payload["schema_version"] != "1.0"
                or payload["authority"] != authority
                or payload["issuer_id"] != issuer_id
                or _canonical(_plain(payload["fact"])) != _canonical(fact)
            ):
                return False
            return verifier.verify(
                issuer_id=issuer_id,
                fact_type=fact_type,
                fact=fact,
                signature=str(payload["signature"]),
            )
        except (KeyError, StopIteration, TypeError, ValueError):
            return False

    def _kernel_event(
        self,
        event_id: str,
        *,
        broker_snapshot_event_id: str,
        snapshot_id: str,
        clean: bool,
        issues: tuple[str, ...],
    ):
        event = next(
            item for item in self._journal.read_all() if item.event_id == event_id
        )
        expected_type = "ReconciliationClean" if clean else "QuarantineRaised"
        if (
            event.stream_id != "kernel:paper"
            or event.event_type != expected_type
            or event.schema_version != 1
            or event.payload.get("snapshot_id") != snapshot_id
            or event.payload.get("broker_snapshot_event_id")
            != broker_snapshot_event_id
            or tuple(event.payload.get("issues", ())) != tuple(issues)
        ):
            raise ValueError("kernel reconciliation event does not match outcome")
        return event


def project_safety_history(
    events: tuple[JournalEvent, ...],
    *,
    reset_authority: SafetyResetAuthority | None,
    maximum_authorization_age: timedelta,
    maximum_reconciliation_age: timedelta,
    journal_integrity_ok: bool,
) -> SafetyHistoryProjection:
    """Project the safety stream without trusting reset event shape alone."""

    safety_events = tuple(
        event for event in events if event.stream_id == _SAFETY_STREAM
    )
    latched = not journal_integrity_ok
    history_valid = journal_integrity_ok
    reasons: list[tuple[str, str]] = []
    latest_latch: JournalEvent | None = None
    if not journal_integrity_ok:
        reasons.append(
            (
                "SAFETY_HISTORY_INVALID",
                "operational journal integrity verification failed",
            )
        )
    for event in safety_events:
        if event.event_type == "SafetyLatched":
            try:
                if event.schema_version != 1 or set(event.payload) != {
                    "reason_code",
                    "detail",
                }:
                    raise ValueError("safety latch payload is malformed")
                reason_code = str(event.payload["reason_code"])
                detail = str(event.payload["detail"])
                if not reason_code.strip():
                    raise ValueError("safety latch reason is blank")
            except (KeyError, TypeError, ValueError):
                history_valid = False
                latched = True
                _add_history_invalid(reasons)
                continue
            latest_latch = event
            latched = True
            reasons.append((reason_code, detail))
        elif event.event_type == "SafetyReset":
            reset_valid = (
                history_valid
                and latched
                and latest_latch is not None
                and reset_authority is not None
                and reset_authority.verify_historical_reset(
                    event,
                    latest_latch=latest_latch,
                    maximum_authorization_age=maximum_authorization_age,
                    maximum_reconciliation_age=maximum_reconciliation_age,
                    available_events=events,
                )
            )
            if reset_valid:
                latched = False
                reasons.clear()
            else:
                history_valid = False
                latched = True
                _add_history_invalid(reasons)
        else:
            history_valid = False
            latched = True
            _add_history_invalid(reasons)
    return SafetyHistoryProjection(
        latched=latched,
        history_valid=history_valid,
        reasons=tuple(reasons),
        version=len(safety_events),
    )


def _add_history_invalid(reasons: list[tuple[str, str]]) -> None:
    if not any(code == "SAFETY_HISTORY_INVALID" for code, _ in reasons):
        reasons.append(
            (
                "SAFETY_HISTORY_INVALID",
                "safety history contains unauthenticated or invalid evidence",
            )
        )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(child) for child in value]
    return value


def _utc(value: datetime) -> datetime:
    require_timestamp(value, "authority timestamp")
    return value.astimezone(timezone.utc)
