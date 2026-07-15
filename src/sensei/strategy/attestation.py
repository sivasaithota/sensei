"""Durable authority for exact strategy decision traces."""

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

from .models import PlanDecisionTrace

_FACT_TYPE = "PlanDecisionTraceProduced"
_SNAPSHOT_ID = re.compile(r"snapshot:[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class DecisionTraceAttestation:
    """Durable identity proving who produced a trace and for which data."""

    event_id: str
    trace_id: str
    market_snapshot_id: str
    issuer_id: str


class DecisionTraceAuthority:
    """Record and verify signed traces against an independently trusted issuer."""

    def __init__(
        self,
        journal: OperationalJournal,
        verifier: HmacFactVerifier,
    ) -> None:
        self._journal = journal
        self._verifier = verifier

    def is_bound_to_journal(self, journal: OperationalJournal) -> bool:
        """Return whether trace attestations use the runtime journal."""

        return self._journal is journal

    def record(
        self,
        trace: PlanDecisionTrace,
        *,
        market_snapshot_id: str,
        signer: HmacFactSigner,
        occurred_at: datetime,
        command_id: str,
    ) -> DecisionTraceAttestation:
        if not isinstance(trace, PlanDecisionTrace):
            raise TypeError("trace must be a PlanDecisionTrace")
        _validate_snapshot_id(market_snapshot_id)
        if not command_id.strip():
            raise ValueError("command_id is required")
        produced_at = _utc(occurred_at)
        fact = _fact(trace, market_snapshot_id, produced_at)
        signature = signer.sign(_FACT_TYPE, fact)
        if not self._verifier.verify(
            issuer_id=signer.issuer_id,
            fact_type=_FACT_TYPE,
            fact=fact,
            signature=signature,
        ):
            raise ValueError("decision trace signer is not a trusted issuer")

        event = self._journal.append(
            EventAppend(
                stream_id=_stream_id(trace.trace_id, market_snapshot_id),
                event_type=_FACT_TYPE,
                payload={
                    "schema_version": "1.0",
                    "authority": "STRATEGY_DECISION_TRACE",
                    "issuer_id": signer.issuer_id,
                    "fact": fact,
                    "signature": signature,
                },
                idempotency_key="trace-attestation:" + _digest(command_id),
                expected_version=0,
                occurred_at=produced_at,
                correlation_id=trace.trace_id,
            )
        )
        return DecisionTraceAttestation(
            event_id=event.event_id,
            trace_id=trace.trace_id,
            market_snapshot_id=market_snapshot_id,
            issuer_id=signer.issuer_id,
        )

    def verify(
        self,
        event_id: str,
        *,
        trace: PlanDecisionTrace,
        market_snapshot_id: str,
        no_later_than: datetime,
    ) -> bool:
        """Fail closed unless an intact event authenticates the exact inputs."""

        try:
            _validate_snapshot_id(market_snapshot_id)
            cutoff = _utc(no_later_than)
            if not self._journal.verify().ok:
                return False
            event = next(
                event
                for event in self._journal.read_all()
                if event.event_id == event_id
            )
            if (
                event.event_type != _FACT_TYPE
                or event.schema_version != 1
                or event.correlation_id != trace.trace_id
                or event.occurred_at > cutoff
                or event.stream_id
                != _stream_id(trace.trace_id, market_snapshot_id)
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
                or payload["authority"] != "STRATEGY_DECISION_TRACE"
            ):
                return False
            expected_fact = _fact(trace, market_snapshot_id, event.occurred_at)
            if _canonical(_plain(payload["fact"])) != _canonical(expected_fact):
                return False
            return self._verifier.verify(
                issuer_id=str(payload["issuer_id"]),
                fact_type=_FACT_TYPE,
                fact=expected_fact,
                signature=str(payload["signature"]),
            )
        except (KeyError, StopIteration, TypeError, ValueError):
            return False


def _fact(
    trace: PlanDecisionTrace,
    market_snapshot_id: str,
    produced_at: datetime,
) -> dict[str, object]:
    return {
        "trace_id": trace.trace_id,
        "trace": trace.model_dump(mode="json"),
        "market_snapshot_id": market_snapshot_id,
        "produced_at": _utc(produced_at).isoformat(),
    }


def _stream_id(trace_id: str, market_snapshot_id: str) -> str:
    identity = f"{trace_id}|{market_snapshot_id}"
    return f"trace-attestation:{_digest(identity)}"


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


def _validate_snapshot_id(value: str) -> None:
    if not isinstance(value, str) or _SNAPSHOT_ID.fullmatch(value) is None:
        raise ValueError("market_snapshot_id must be content-addressed")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("authority timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)
