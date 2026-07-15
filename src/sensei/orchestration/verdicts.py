"""Authenticated evidence emitted independently by each committee role."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from sensei.agents.thesis import TradeThesis, Verdict
from sensei.operations import (
    EventAppend,
    HmacFactSigner,
    HmacFactVerifier,
    OperationalJournal,
)

FACT_TYPE = "TradeCommitteeVerdictProduced"
EXPECTED_COMMITTEE = (
    ("L1", "risk-officer"),
    ("L2", "devils-advocate"),
    ("L3", "compliance"),
    ("L4", "orchestrator"),
)


@dataclass(frozen=True)
class CommitteeVerdictEvidence:
    event_id: str
    thesis_id: str
    level: str
    agent: str
    issuer_id: str


class CommitteeVerdictAuthority:
    """Require every L1-L4 producer to authenticate its own verdict."""

    def __init__(
        self,
        journal: OperationalJournal,
        verifier: HmacFactVerifier,
    ) -> None:
        self._journal = journal
        self._verifier = verifier

    def is_bound_to_journal(self, journal: OperationalJournal) -> bool:
        """Return whether committee evidence uses the runtime journal."""

        return self._journal is journal

    def record(
        self,
        thesis: TradeThesis,
        verdict: Verdict,
        *,
        signer: HmacFactSigner,
        occurred_at: datetime,
        command_id: str,
    ) -> CommitteeVerdictEvidence:
        if not isinstance(thesis, TradeThesis) or not isinstance(verdict, Verdict):
            raise TypeError("thesis and verdict must use committee domain models")
        if (verdict.level, verdict.agent) not in EXPECTED_COMMITTEE:
            raise ValueError("verdict does not occupy a recognized committee seat")
        if signer.issuer_id != verdict.agent:
            raise ValueError("each role must sign its own committee verdict")
        if not command_id.strip():
            raise ValueError("command_id is required")
        produced_at = _utc(occurred_at)
        if _utc(verdict.checked_at) > produced_at:
            raise ValueError("verdict cannot be attested before it was checked")
        fact = _fact(thesis, verdict, produced_at)
        signature = signer.sign(FACT_TYPE, fact)
        if not self._verifier.verify(
            issuer_id=signer.issuer_id,
            fact_type=FACT_TYPE,
            fact=fact,
            signature=signature,
        ):
            raise ValueError("committee signer is not a trusted issuer")

        event = self._journal.append(
            EventAppend(
                stream_id=_stream_id(fact),
                event_type=FACT_TYPE,
                payload={
                    "schema_version": "1.0",
                    "authority": "COMMITTEE_ROLE_VERDICT",
                    "issuer_id": signer.issuer_id,
                    "fact": fact,
                    "signature": signature,
                },
                idempotency_key="verdict-attestation:" + _digest(command_id),
                expected_version=0,
                occurred_at=produced_at,
                correlation_id=thesis.id,
            )
        )
        return CommitteeVerdictEvidence(
            event_id=event.event_id,
            thesis_id=thesis.id,
            level=verdict.level,
            agent=verdict.agent,
            issuer_id=signer.issuer_id,
        )

    def verify(
        self,
        event_id: str,
        *,
        thesis: TradeThesis,
        verdict: Verdict,
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
                event.event_type != FACT_TYPE
                or event.schema_version != 1
                or event.correlation_id != thesis.id
                or event.occurred_at > cutoff
                or _utc(verdict.checked_at) > event.occurred_at
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
                or payload["authority"] != "COMMITTEE_ROLE_VERDICT"
                or payload["issuer_id"] != verdict.agent
            ):
                return False
            expected_fact = _fact(thesis, verdict, event.occurred_at)
            if _canonical(_plain(payload["fact"])) != _canonical(expected_fact):
                return False
            if event.stream_id != _stream_id(expected_fact):
                return False
            return self._verifier.verify(
                issuer_id=str(payload["issuer_id"]),
                fact_type=FACT_TYPE,
                fact=expected_fact,
                signature=str(payload["signature"]),
            )
        except (KeyError, StopIteration, TypeError, ValueError):
            return False


def _fact(
    thesis: TradeThesis,
    verdict: Verdict,
    produced_at: datetime,
) -> dict[str, object]:
    return {
        "thesis": thesis.model_dump(mode="json"),
        "verdict": verdict.model_dump(mode="json"),
        "produced_at": _utc(produced_at).isoformat(),
    }


def _stream_id(fact: Mapping[str, object]) -> str:
    return f"verdict-attestation:{_digest(_canonical(fact))}"


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
        raise ValueError("committee timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)
