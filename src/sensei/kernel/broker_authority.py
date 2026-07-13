"""Authenticated, content-addressed broker snapshots."""

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

from .reconciliation import BrokerSnapshot

_FACT_TYPE = "BrokerSnapshotObserved"


@dataclass(frozen=True)
class BrokerSnapshotEvidence:
    event_id: str
    snapshot_id: str
    issuer_id: str


class BrokerSnapshotAuthority:
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

    def record(
        self,
        snapshot: BrokerSnapshot,
        *,
        signer: HmacFactSigner,
        occurred_at: datetime,
        command_id: str,
    ) -> BrokerSnapshotEvidence:
        if not isinstance(snapshot, BrokerSnapshot):
            raise TypeError("snapshot must be a BrokerSnapshot")
        if signer.issuer_id != self._expected_issuer_id:
            raise ValueError("broker snapshot must come from the configured gateway")
        if not command_id.strip():
            raise ValueError("command_id is required")
        observed_at = _utc(occurred_at)
        if snapshot.captured_at.astimezone(timezone.utc) > observed_at:
            raise ValueError("broker snapshot cannot be observed before capture")
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
            raise ValueError("broker snapshot signer is not trusted")
        event = self._journal.append(
            EventAppend(
                stream_id=(
                    "broker-snapshot:"
                    + snapshot.snapshot_id.removeprefix("broker-snapshot:")
                ),
                event_type="BrokerSnapshotAuthenticated",
                payload={
                    "schema_version": "1.0",
                    "authority": "BROKER_GATEWAY_SNAPSHOT",
                    "issuer_id": signer.issuer_id,
                    "fact": fact,
                    "signature": signature,
                },
                idempotency_key="broker-snapshot:" + _digest(command_id),
                expected_version=0,
                occurred_at=observed_at,
                correlation_id=snapshot.snapshot_id,
            )
        )
        return BrokerSnapshotEvidence(
            event_id=event.event_id,
            snapshot_id=snapshot.snapshot_id,
            issuer_id=signer.issuer_id,
        )

    def verify(
        self,
        event_id: str,
        *,
        snapshot: BrokerSnapshot,
        no_later_than: datetime,
    ) -> bool:
        try:
            cutoff = _utc(no_later_than)
            if not self._journal.verify().ok:
                return False
            event = next(
                item for item in self._journal.read_all() if item.event_id == event_id
            )
            if (
                event.event_type != "BrokerSnapshotAuthenticated"
                or event.schema_version != 1
                or event.correlation_id != snapshot.snapshot_id
                or event.occurred_at > cutoff
                or event.stream_id
                != "broker-snapshot:"
                + snapshot.snapshot_id.removeprefix("broker-snapshot:")
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
                or payload["authority"] != "BROKER_GATEWAY_SNAPSHOT"
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
        except (KeyError, StopIteration, TypeError, ValueError):
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
        raise ValueError("broker snapshot timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)
