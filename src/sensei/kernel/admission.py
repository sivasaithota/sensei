"""Authenticated admission boundary in front of the paper execution kernel."""

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
from sensei.portfolio_risk import TradeIntent

_FACT_TYPE = "PaperIntentAdmissionAuthorized"
_EVENT_ID = re.compile(r"event:[0-9a-f]{64}\Z")
_APPROVAL_ID = re.compile(r"approval:[0-9a-f]{64}\Z")
_CLAIM_ID = re.compile(r"claim:[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class KernelAdmissionAuthorization:
    event_id: str
    admission_id: str
    intent_id: str
    issuer_id: str


class KernelAdmissionAuthority:
    """Issue and verify a signed paper-only capability for one exact intent."""

    def __init__(
        self,
        journal: OperationalJournal,
        verifier: HmacFactVerifier,
    ) -> None:
        self._journal = journal
        self._verifier = verifier

    def issue(
        self,
        intent: TradeIntent,
        *,
        lineage_id: str,
        trace_attestation_event_id: str,
        lifecycle_event_id: str,
        health_event_id: str,
        committee_event_id: str,
        committee_approval_id: str,
        verdict_evidence_event_ids: tuple[str, ...],
        provenance_claim_ids: tuple[str, ...],
        signer: HmacFactSigner,
        occurred_at: datetime,
        command_id: str,
    ) -> KernelAdmissionAuthorization:
        if not isinstance(intent, TradeIntent):
            raise TypeError("intent must be a TradeIntent")
        if not lineage_id.strip() or not command_id.strip():
            raise ValueError("lineage_id and command_id are required")
        evidence_ids = (
            trace_attestation_event_id,
            lifecycle_event_id,
            health_event_id,
            committee_event_id,
            *verdict_evidence_event_ids,
        )
        if (
            len(verdict_evidence_event_ids) != 4
            or len(set(verdict_evidence_event_ids)) != 4
            or any(_EVENT_ID.fullmatch(value) is None for value in evidence_ids)
        ):
            raise ValueError("admission requires exact durable governance evidence")
        if _APPROVAL_ID.fullmatch(committee_approval_id) is None:
            raise ValueError("committee_approval_id must be content-addressed")
        if (
            not provenance_claim_ids
            or len(set(provenance_claim_ids)) != len(provenance_claim_ids)
            or any(_CLAIM_ID.fullmatch(value) is None for value in provenance_claim_ids)
        ):
            raise ValueError("admission requires content-addressed provenance claims")

        issued_at = _utc(occurred_at)
        fact = _fact(
            intent,
            lineage_id=lineage_id,
            trace_attestation_event_id=trace_attestation_event_id,
            lifecycle_event_id=lifecycle_event_id,
            health_event_id=health_event_id,
            committee_event_id=committee_event_id,
            committee_approval_id=committee_approval_id,
            verdict_evidence_event_ids=verdict_evidence_event_ids,
            provenance_claim_ids=provenance_claim_ids,
            issued_at=issued_at,
        )
        signature = signer.sign(_FACT_TYPE, fact)
        if not self._verifier.verify(
            issuer_id=signer.issuer_id,
            fact_type=_FACT_TYPE,
            fact=fact,
            signature=signature,
        ):
            raise ValueError("paper admission signer is not a trusted issuer")
        admission_id = f"admission:{_digest(_canonical(fact))}"
        event = self._journal.append(
            EventAppend(
                stream_id=(
                    "kernel-admission:"
                    + intent.intent_id.removeprefix("intent:")
                ),
                event_type=_FACT_TYPE,
                payload={
                    "schema_version": "1.0",
                    "authority": "PAPER_KERNEL_ADMISSION",
                    "admission_id": admission_id,
                    "issuer_id": signer.issuer_id,
                    "fact": fact,
                    "signature": signature,
                },
                idempotency_key="kernel-admission:" + _digest(command_id),
                expected_version=0,
                occurred_at=issued_at,
                correlation_id=intent.intent_id,
            )
        )
        return KernelAdmissionAuthorization(
            event_id=event.event_id,
            admission_id=admission_id,
            intent_id=intent.intent_id,
            issuer_id=signer.issuer_id,
        )

    def verify(
        self,
        event_id: str,
        *,
        intent: TradeIntent,
        no_later_than: datetime,
    ) -> bool:
        try:
            cutoff = _utc(no_later_than)
            if not self._journal.verify().ok:
                return False
            event = next(
                item for item in self._journal.read_all() if item.event_id == event_id
            )
            expected_stream = (
                "kernel-admission:" + intent.intent_id.removeprefix("intent:")
            )
            if (
                event.event_type != _FACT_TYPE
                or event.schema_version != 1
                or event.correlation_id != intent.intent_id
                or event.stream_id != expected_stream
                or event.occurred_at > cutoff
            ):
                return False
            payload = event.payload
            if set(payload) != {
                "schema_version",
                "authority",
                "admission_id",
                "issuer_id",
                "fact",
                "signature",
            }:
                return False
            if (
                payload["schema_version"] != "1.0"
                or payload["authority"] != "PAPER_KERNEL_ADMISSION"
            ):
                return False
            fact = _plain(payload["fact"])
            if not isinstance(fact, dict) or set(fact) != {
                "execution_mode",
                "intent",
                "lineage_id",
                "trace_attestation_event_id",
                "lifecycle_event_id",
                "health_event_id",
                "committee_event_id",
                "committee_approval_id",
                "verdict_evidence_event_ids",
                "provenance_claim_ids",
                "issued_at",
            }:
                return False
            if (
                fact["execution_mode"] != "paper"
                or _canonical(fact["intent"]) != _canonical(intent.to_payload())
                or fact["issued_at"] != event.occurred_at.isoformat()
            ):
                return False
            admission_id = f"admission:{_digest(_canonical(fact))}"
            if payload["admission_id"] != admission_id:
                return False
            return self._verifier.verify(
                issuer_id=str(payload["issuer_id"]),
                fact_type=_FACT_TYPE,
                fact=fact,
                signature=str(payload["signature"]),
            )
        except (KeyError, StopIteration, TypeError, ValueError):
            return False


def _fact(
    intent: TradeIntent,
    *,
    lineage_id: str,
    trace_attestation_event_id: str,
    lifecycle_event_id: str,
    health_event_id: str,
    committee_event_id: str,
    committee_approval_id: str,
    verdict_evidence_event_ids: tuple[str, ...],
    provenance_claim_ids: tuple[str, ...],
    issued_at: datetime,
) -> dict[str, object]:
    return {
        "execution_mode": "paper",
        "intent": intent.to_payload(),
        "lineage_id": lineage_id,
        "trace_attestation_event_id": trace_attestation_event_id,
        "lifecycle_event_id": lifecycle_event_id,
        "health_event_id": health_event_id,
        "committee_event_id": committee_event_id,
        "committee_approval_id": committee_approval_id,
        "verdict_evidence_event_ids": list(verdict_evidence_event_ids),
        "provenance_claim_ids": sorted(provenance_claim_ids),
        "issued_at": _utc(issued_at).isoformat(),
    }


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
        raise ValueError("admission timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)
