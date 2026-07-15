"""Authenticated, content-addressed account snapshots."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from sensei.operations import (
    EventAppend,
    HmacFactSigner,
    HmacFactVerifier,
    OperationalJournal,
)

from .models import AccountSnapshot

_FACT_TYPE = "AccountSnapshotObserved"


@dataclass(frozen=True)
class AccountSnapshotEvidence:
    event_id: str
    snapshot_id: str
    issuer_id: str


class AccountSnapshotAuthority:
    """Record and verify exact account truth from one configured adapter."""

    def __init__(
        self,
        journal: OperationalJournal,
        verifier: HmacFactVerifier,
        *,
        expected_issuer_id: str,
    ) -> None:
        if not expected_issuer_id.strip():
            raise ValueError("expected_issuer_id is required")
        self._journal = journal
        self._verifier = verifier
        self._expected_issuer_id = expected_issuer_id

    def is_bound_to_journal(self, journal: OperationalJournal) -> bool:
        """Return whether evidence is read from the exact runtime journal."""

        return self._journal is journal

    def record(
        self,
        snapshot: AccountSnapshot,
        *,
        signer: HmacFactSigner,
        occurred_at: datetime,
        command_id: str,
    ) -> AccountSnapshotEvidence:
        if not isinstance(snapshot, AccountSnapshot):
            raise TypeError("snapshot must be an AccountSnapshot")
        if not snapshot.has_valid_identity():
            raise ValueError("account snapshot content identity is invalid")
        if signer.issuer_id != self._expected_issuer_id:
            raise ValueError(
                "account snapshot must come from the configured account adapter"
            )
        if not command_id.strip():
            raise ValueError("command_id is required")
        observed_at = _utc(occurred_at)
        if snapshot.captured_at.astimezone(timezone.utc) > observed_at:
            raise ValueError("account snapshot cannot be observed before capture")
        fact = {
            "snapshot": snapshot.to_payload(),
            "observed_at": observed_at.isoformat(),
        }
        signature = signer.sign(_FACT_TYPE, fact)
        if not self._verifier.verify(
            issuer_id=signer.issuer_id,
            fact_type=_FACT_TYPE,
            fact=fact,
            signature=signature,
        ):
            raise ValueError("account snapshot signer is not trusted")
        event = self._journal.append(
            EventAppend(
                stream_id=(
                    "account-snapshot:"
                    + snapshot.snapshot_id.removeprefix("snapshot:")
                ),
                event_type="AccountSnapshotAuthenticated",
                payload={
                    "schema_version": "1.0",
                    "authority": "ACCOUNT_SNAPSHOT_SOURCE",
                    "issuer_id": signer.issuer_id,
                    "fact": fact,
                    "signature": signature,
                },
                idempotency_key="account-snapshot:" + _digest(command_id),
                expected_version=0,
                occurred_at=observed_at,
                correlation_id=snapshot.snapshot_id,
            )
        )
        return AccountSnapshotEvidence(
            event_id=event.event_id,
            snapshot_id=snapshot.snapshot_id,
            issuer_id=signer.issuer_id,
        )

    def verify(
        self,
        event_id: str,
        *,
        snapshot: AccountSnapshot,
        no_later_than: datetime,
    ) -> bool:
        try:
            cutoff = _utc(no_later_than)
            if not snapshot.has_valid_identity() or not self._journal.verify().ok:
                return False
            event = next(
                item for item in self._journal.read_all() if item.event_id == event_id
            )
            if (
                event.event_type != "AccountSnapshotAuthenticated"
                or event.schema_version != 1
                or event.correlation_id != snapshot.snapshot_id
                or event.occurred_at > cutoff
                or snapshot.captured_at.astimezone(timezone.utc) > event.occurred_at
                or event.stream_id
                != "account-snapshot:"
                + snapshot.snapshot_id.removeprefix("snapshot:")
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
                payload["schema_version"] != "1.0"
                or payload["authority"] != "ACCOUNT_SNAPSHOT_SOURCE"
                or payload["issuer_id"] != self._expected_issuer_id
            ):
                return False
            expected_fact = {
                "snapshot": snapshot.to_payload(),
                "observed_at": event.occurred_at.isoformat(),
            }
            if _canonical(_plain(payload["fact"])) != _canonical(expected_fact):
                return False
            return self._verifier.verify(
                issuer_id=self._expected_issuer_id,
                fact_type=_FACT_TYPE,
                fact=expected_fact,
                signature=str(payload["signature"]),
            )
        except (AttributeError, KeyError, StopIteration, TypeError, ValueError):
            return False


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
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("account snapshot timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)
