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
_ARTIFACT_CONTENT_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
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
_SUPPORT_PAYLOAD_KEYS = frozenset(
    {
        "schema_version",
        "lineage_id",
        "plan_version_id",
        "evidence_kind",
        "producer_id",
        "outcome",
        "artifact_content_id",
    }
)


class DossierOutcome(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class StageEvidenceEnvelope:
    """Typed content contract for evidence that may support a stage dossier."""

    lineage_id: str
    plan_version_id: str
    evidence_kind: EvidenceKind
    producer_id: str
    outcome: DossierOutcome
    artifact_content_id: str

    def __post_init__(self) -> None:
        for label, value in (
            ("lineage_id", self.lineage_id),
            ("plan_version_id", self.plan_version_id),
            ("producer_id", self.producer_id),
        ):
            if not value.strip():
                raise ValueError(f"{label} must not be empty")
        if not isinstance(self.evidence_kind, EvidenceKind):
            raise ValueError("evidence_kind must be an EvidenceKind")
        if not isinstance(self.outcome, DossierOutcome):
            raise ValueError("outcome must be a DossierOutcome")
        if _ARTIFACT_CONTENT_ID.fullmatch(self.artifact_content_id) is None:
            raise ValueError("artifact_content_id must be a lowercase sha256 identity")

    def to_payload(self) -> dict[str, str]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "lineage_id": self.lineage_id,
            "plan_version_id": self.plan_version_id,
            "evidence_kind": self.evidence_kind.value,
            "producer_id": self.producer_id,
            "outcome": self.outcome.value,
            "artifact_content_id": self.artifact_content_id,
        }


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
        if self.issuer_id == self.producer_id:
            raise ValueError("dossier issuer and producer must be independent")
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

    def __init__(
        self,
        journal: OperationalJournal,
        *,
        trusted_issuer_ids: frozenset[str],
        trusted_producers_by_kind: Mapping[EvidenceKind, frozenset[str]],
    ) -> None:
        self._journal = journal
        if not trusted_issuer_ids or any(
            not isinstance(actor_id, str) or not actor_id.strip()
            for actor_id in trusted_issuer_ids
        ):
            raise ValueError("trusted_issuer_ids must contain named actors")
        normalized: dict[EvidenceKind, frozenset[str]] = {}
        for kind, producer_ids in trusted_producers_by_kind.items():
            if not isinstance(kind, EvidenceKind):
                raise ValueError("trusted producer keys must be EvidenceKind values")
            producers = frozenset(producer_ids)
            if not producers or any(
                not isinstance(actor_id, str) or not actor_id.strip()
                for actor_id in producers
            ):
                raise ValueError(
                    "trusted producer sets must contain named actors"
                )
            normalized[kind] = producers
        all_producers = (
            frozenset().union(*normalized.values())
            if normalized
            else frozenset()
        )
        if trusted_issuer_ids & all_producers:
            raise ValueError("dossier issuers and evidence producers must be disjoint")
        self._trusted_issuer_ids = frozenset(trusted_issuer_ids)
        self._trusted_producers_by_kind = normalized

    def issue(self, request: StageDossierIssue) -> StageDossier:
        self._require_trusted_issue(request)
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
        for support_id in request.supporting_event_ids:
            _validate_support_event(events_by_id[support_id], request)

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
        dossier = _dossier_from_event(event, events_by_id)
        self._require_trusted_dossier(dossier)
        return dossier

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
        if not matches:
            return None
        dossier = _dossier_from_event(matches[0], events_by_id)
        self._require_trusted_dossier(dossier)
        return dossier

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
            self._require_trusted_dossier(dossier)
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
                or dossier.producer_id == request.authority.actor_id
            ):
                return False
        return True

    def _require_trusted_issue(self, issue: StageDossierIssue) -> None:
        if issue.issuer_id not in self._trusted_issuer_ids:
            raise DossierError(f"untrusted dossier issuer {issue.issuer_id!r}")
        allowed = self._trusted_producers_by_kind.get(
            issue.evidence_kind, frozenset()
        )
        if issue.producer_id not in allowed:
            raise DossierError(
                f"untrusted producer {issue.producer_id!r} "
                f"for {issue.evidence_kind.value}"
            )

    def _require_trusted_dossier(self, dossier: StageDossier) -> None:
        if dossier.issuer_id not in self._trusted_issuer_ids:
            raise DossierIntegrityError(
                f"dossier names untrusted issuer {dossier.issuer_id!r}"
            )
        allowed = self._trusted_producers_by_kind.get(
            dossier.evidence_kind, frozenset()
        )
        if dossier.producer_id not in allowed:
            raise DossierIntegrityError(
                f"dossier names untrusted producer {dossier.producer_id!r}"
            )

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
        _validate_support_event(support, issue)
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


def _validate_support_event(
    event: JournalEvent,
    dossier: StageDossierIssue,
) -> None:
    try:
        evidence = _stage_evidence_from_event(event)
    except (TypeError, ValueError, KeyError) as exc:
        raise DossierIntegrityError(
            "supporting event does not satisfy the StageEvidenceProduced contract"
        ) from exc
    if (
        evidence.lineage_id != dossier.lineage_id
        or evidence.plan_version_id != dossier.plan_version_id
        or evidence.evidence_kind is not dossier.evidence_kind
        or evidence.producer_id != dossier.producer_id
        or evidence.outcome is not dossier.outcome
    ):
        raise DossierIntegrityError(
            "supporting evidence does not match the dossier's exact contract"
        )
    if event.occurred_at > dossier.issued_at:
        raise DossierIntegrityError(
            "supporting evidence must precede dossier issuance"
        )


def _stage_evidence_from_event(event: JournalEvent) -> StageEvidenceEnvelope:
    if event.event_type != "StageEvidenceProduced":
        raise ValueError("supporting event has the wrong type")
    payload = event.payload
    if frozenset(payload) != _SUPPORT_PAYLOAD_KEYS:
        raise ValueError("supporting event payload shape is invalid")
    if payload["schema_version"] != _SCHEMA_VERSION:
        raise ValueError("supporting event schema is unsupported")
    return StageEvidenceEnvelope(
        lineage_id=str(payload["lineage_id"]),
        plan_version_id=str(payload["plan_version_id"]),
        evidence_kind=EvidenceKind(str(payload["evidence_kind"])),
        producer_id=str(payload["producer_id"]),
        outcome=DossierOutcome(str(payload["outcome"])),
        artifact_content_id=str(payload["artifact_content_id"]),
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
