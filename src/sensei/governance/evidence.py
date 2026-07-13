"""Content-addressed stage dossiers backed by the Operational Journal."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from sensei.governance.lifecycle import (
    EvidenceKind,
    EvidenceRef,
    TransitionRequest,
    required_evidence_for,
)
from sensei.operations.journal import EventAppend, JournalEvent, OperationalJournal

_EVENT_ID = re.compile(r"event:[0-9a-f]{64}\Z")
_DOSSIER_ID = re.compile(r"dossier:[0-9a-f]{64}\Z")
_SCHEMA_VERSION = "1.0"
_PAYLOAD_KEYS = frozenset(
    {
        "schema_version",
        "dossier_id",
        "lineage_id",
        "plan_version_id",
        "evidence_kind",
        "supporting_event_ids",
        "issuer_id",
        "producer_id",
        "issued_at",
        "outcome",
    }
)


class DossierOutcome(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


class DossierError(RuntimeError):
    """Base error for stage-dossier issuance and reconstruction."""


class DossierIntegrityError(DossierError):
    """The journal or a dossier failed content-integrity checks."""


class MissingSupportingEvent(DossierError):
    """A dossier cited a journal event that does not exist."""


@dataclass(frozen=True)
class StageDossierIssue:
    lineage_id: str
    plan_version_id: str
    evidence_kind: EvidenceKind
    supporting_event_ids: tuple[str, ...]
    issuer_id: str
    producer_id: str
    issued_at: datetime
    outcome: DossierOutcome

    def __post_init__(self) -> None:
        for label, value in (
            ("lineage_id", self.lineage_id),
            ("plan_version_id", self.plan_version_id),
            ("issuer_id", self.issuer_id),
            ("producer_id", self.producer_id),
        ):
            if not value.strip():
                raise ValueError(f"{label} must not be empty")
        if not isinstance(self.evidence_kind, EvidenceKind):
            raise ValueError("evidence_kind must be an EvidenceKind")
        if not isinstance(self.outcome, DossierOutcome):
            raise ValueError("outcome must be a DossierOutcome")
        if self.issued_at.tzinfo is None or self.issued_at.utcoffset() is None:
            raise ValueError("issued_at must be timezone-aware")
        event_ids = tuple(self.supporting_event_ids)
        if not event_ids:
            raise ValueError("at least one supporting journal event is required")
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("supporting_event_ids must not contain duplicates")
        if any(_EVENT_ID.fullmatch(event_id) is None for event_id in event_ids):
            raise ValueError("supporting_event_ids must be content-addressed event IDs")
        object.__setattr__(self, "supporting_event_ids", tuple(sorted(event_ids)))

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "lineage_id": self.lineage_id,
            "plan_version_id": self.plan_version_id,
            "evidence_kind": self.evidence_kind.value,
            "supporting_event_ids": list(self.supporting_event_ids),
            "issuer_id": self.issuer_id,
            "producer_id": self.producer_id,
            "issued_at": _utc_iso(self.issued_at),
            "outcome": self.outcome.value,
        }


@dataclass(frozen=True)
class StageDossier:
    dossier_id: str
    lineage_id: str
    plan_version_id: str
    evidence_kind: EvidenceKind
    supporting_event_ids: tuple[str, ...]
    issuer_id: str
    producer_id: str
    issued_at: datetime
    outcome: DossierOutcome
    journal_event_id: str
    journal_global_sequence: int

    @property
    def evidence_ref(self) -> EvidenceRef:
        return EvidenceRef(kind=self.evidence_kind, ref_id=self.dossier_id)


class StageDossierRegistry:
    """Issue and verify immutable evidence dossiers for lifecycle transitions."""

    def __init__(self, journal: OperationalJournal) -> None:
        self._journal = journal

    def issue(self, request: StageDossierIssue) -> StageDossier:
        events = self._clean_events()
        events_by_id = {event.event_id: event for event in events}
        missing = tuple(
            event_id
            for event_id in request.supporting_event_ids
            if event_id not in events_by_id
        )
        if missing:
            raise MissingSupportingEvent(
                "supporting journal event not found: " + ", ".join(missing)
            )

        identity = request.identity_payload()
        dossier_id = _content_id(identity)
        event = self._journal.append(
            EventAppend(
                stream_id="stage-dossier:" + dossier_id.removeprefix("dossier:"),
                event_type="StageDossierIssued",
                payload={**identity, "dossier_id": dossier_id},
                idempotency_key=(
                    "issue-dossier:" + dossier_id.removeprefix("dossier:")
                ),
                expected_version=0,
                occurred_at=request.issued_at,
                correlation_id=dossier_id,
            )
        )
        events_by_id[event.event_id] = event
        return _dossier_from_event(event, events_by_id)

    def get(self, dossier_id: str) -> StageDossier | None:
        if _DOSSIER_ID.fullmatch(dossier_id) is None:
            raise ValueError("dossier_id must be a content-addressed dossier ID")
        events = self._clean_events()
        events_by_id = {event.event_id: event for event in events}
        matches = tuple(
            event
            for event in events
            if event.event_type == "StageDossierIssued"
            and event.payload.get("dossier_id") == dossier_id
        )
        if len(matches) > 1:
            raise DossierIntegrityError("duplicate stage dossier identity")
        return _dossier_from_event(matches[0], events_by_id) if matches else None

    def verify_transition(self, request: TransitionRequest) -> bool:
        """Return literal trust for the exact plan, kinds, and passed dossiers."""

        try:
            return self._verify_transition(request)
        except Exception:
            return False

    def _verify_transition(self, request: TransitionRequest) -> bool:
        required = required_evidence_for(request.target_stage)
        supplied = {ref.kind for ref in request.evidence_refs}
        if not required.issubset(supplied):
            return False

        events = self._clean_events()
        events_by_id = {event.event_id: event for event in events}
        dossiers: dict[str, StageDossier] = {}
        for event in events:
            if event.event_type != "StageDossierIssued":
                continue
            dossier = _dossier_from_event(event, events_by_id)
            if dossier.dossier_id in dossiers:
                return False
            dossiers[dossier.dossier_id] = dossier

        for ref in request.evidence_refs:
            dossier = dossiers.get(ref.ref_id)
            if dossier is None:
                return False
            if (
                dossier.lineage_id != request.lineage_id
                or dossier.plan_version_id != request.plan_version_id
                or dossier.evidence_kind is not ref.kind
                or dossier.outcome is not DossierOutcome.PASSED
            ):
                return False
        return True

    def _clean_events(self) -> tuple[JournalEvent, ...]:
        verification = self._journal.verify()
        if not verification.ok:
            detail = "; ".join(verification.errors) or "unknown error"
            raise DossierIntegrityError(
                f"operational journal integrity verification failed: {detail}"
            )
        return self._journal.read_all()


def _dossier_from_event(
    event: JournalEvent,
    events_by_id: Mapping[str, JournalEvent],
) -> StageDossier:
    if event.event_type != "StageDossierIssued":
        raise DossierIntegrityError("journal event is not a stage dossier")
    payload = event.payload
    if frozenset(payload) != _PAYLOAD_KEYS:
        raise DossierIntegrityError("stage dossier payload shape is invalid")
    try:
        issue = StageDossierIssue(
            lineage_id=str(payload["lineage_id"]),
            plan_version_id=str(payload["plan_version_id"]),
            evidence_kind=EvidenceKind(str(payload["evidence_kind"])),
            supporting_event_ids=tuple(
                str(event_id) for event_id in payload["supporting_event_ids"]
            ),
            issuer_id=str(payload["issuer_id"]),
            producer_id=str(payload["producer_id"]),
            issued_at=datetime.fromisoformat(str(payload["issued_at"])),
            outcome=DossierOutcome(str(payload["outcome"])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DossierIntegrityError("stage dossier content is invalid") from exc
    if payload["schema_version"] != _SCHEMA_VERSION:
        raise DossierIntegrityError("unsupported stage dossier schema")
    dossier_id = str(payload["dossier_id"])
    if dossier_id != _content_id(issue.identity_payload()):
        raise DossierIntegrityError("stage dossier content identity is invalid")
    if event.occurred_at != issue.issued_at:
        raise DossierIntegrityError("stage dossier event time does not match issued_at")
    for support_id in issue.supporting_event_ids:
        support = events_by_id.get(support_id)
        if support is None:
            raise MissingSupportingEvent(
                f"supporting journal event not found: {support_id}"
            )
        if support.global_sequence >= event.global_sequence:
            raise DossierIntegrityError(
                "supporting events must precede stage dossier issuance"
            )
    return StageDossier(
        dossier_id=dossier_id,
        lineage_id=issue.lineage_id,
        plan_version_id=issue.plan_version_id,
        evidence_kind=issue.evidence_kind,
        supporting_event_ids=issue.supporting_event_ids,
        issuer_id=issue.issuer_id,
        producer_id=issue.producer_id,
        issued_at=issue.issued_at,
        outcome=issue.outcome,
        journal_event_id=event.event_id,
        journal_global_sequence=event.global_sequence,
    )


def _content_id(payload: object) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return "dossier:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()
