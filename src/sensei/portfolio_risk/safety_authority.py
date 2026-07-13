"""Authenticated owner and reconciliation evidence for safety reset."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from sensei.operations import (
    EventAppend,
    HmacFactSigner,
    HmacFactVerifier,
    OperationalJournal,
)

from .models import require_timestamp

_EVENT_ID = re.compile(r"event:[0-9a-f]{64}\Z")
_SNAPSHOT_ID = re.compile(r"broker-snapshot:[0-9a-f]{64}\Z")


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
            event.event_type != expected_type
            or event.payload.get("snapshot_id") != snapshot_id
            or event.payload.get("broker_snapshot_event_id")
            != broker_snapshot_event_id
            or tuple(event.payload.get("issues", ())) != tuple(issues)
        ):
            raise ValueError("kernel reconciliation event does not match outcome")
        return event


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
