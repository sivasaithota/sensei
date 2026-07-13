"""Audited, fail-closed lifecycle for immutable strategy plan versions."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType

from sensei.operations.journal import (
    EventAppend,
    JournalEvent,
    JournalIntegrityError,
    OperationalJournal,
)


class LifecycleStage(str, Enum):
    PROPOSED = "proposed"
    EXAMINED = "examined"
    SHADOW = "shadow"
    PAPER = "paper"
    CANARY = "canary"
    ACTIVE = "active"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"
    RETIRED = "retired"
    ROLLED_BACK = "rolled_back"


class AuthorityRole(str, Enum):
    PROPOSER = "proposer"
    GOVERNOR = "governor"
    OWNER = "owner"
    SAFETY = "safety"


class EvidenceKind(str, Enum):
    EXAMINATION_DOSSIER = "examination_dossier"
    SHADOW_READINESS = "shadow_readiness"
    CONFORMANCE_DOSSIER = "conformance_dossier"
    LOCKED_CONFIRMATION = "locked_confirmation"
    SHADOW_TRIAL = "shadow_trial"
    PAPER_TRIAL = "paper_trial"
    RISK_READINESS = "risk_readiness"
    OPERATIONS_READINESS = "operations_readiness"
    CANARY_TRIAL = "canary_trial"
    SAFETY_EVENT = "safety_event"
    ROLLBACK_DECISION = "rollback_decision"
    GOVERNANCE_DECISION = "governance_decision"
    RETIREMENT_DECISION = "retirement_decision"


class InvalidLifecycleTransition(RuntimeError):
    """The requested transition does not follow the governed path."""


class TerminalLifecycleState(InvalidLifecycleTransition):
    """A terminal or safety state cannot be revived in place."""


class UnauthorizedTransition(PermissionError):
    """The supplied authority role cannot make this transition."""


class OwnerAuthorityRequired(UnauthorizedTransition):
    """Capital-bearing lifecycle stages require explicit owner authority."""


class ReadinessEvidenceMissing(RuntimeError):
    """A stage dossier is missing one or more required evidence kinds."""


class StrategyAlreadyActive(RuntimeError):
    """Another plan version in the same lineage is active."""


class UntrustedReadinessEvidence(RuntimeError):
    """Required stage evidence could not be independently verified."""


@dataclass(frozen=True)
class Authority:
    actor_id: str
    role: AuthorityRole
    approval_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.actor_id.strip():
            raise ValueError("actor_id must not be empty")
        if not isinstance(self.role, AuthorityRole):
            raise ValueError("role must be an AuthorityRole")
        if self.role is AuthorityRole.OWNER and not (self.approval_ref or "").strip():
            raise ValueError("owner authority requires an explicit approval_ref")


@dataclass(frozen=True)
class EvidenceRef:
    kind: EvidenceKind
    ref_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EvidenceKind):
            raise ValueError("kind must be an EvidenceKind")
        if not self.ref_id.strip():
            raise ValueError("evidence ref_id must not be empty")


@dataclass(frozen=True)
class TransitionRequest:
    lineage_id: str
    plan_version_id: str
    target_stage: LifecycleStage
    evidence_refs: tuple[EvidenceRef, ...]
    authority: Authority
    expected_revision: int
    command_id: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        for label, value in (
            ("lineage_id", self.lineage_id),
            ("plan_version_id", self.plan_version_id),
            ("command_id", self.command_id),
        ):
            if not value.strip():
                raise ValueError(f"{label} must not be empty")
        if not isinstance(self.target_stage, LifecycleStage):
            raise ValueError("target_stage must be a LifecycleStage")
        if self.expected_revision < 0:
            raise ValueError("expected_revision must not be negative")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("evidence_refs must not contain duplicates")


@dataclass(frozen=True)
class LifecycleRecord:
    lineage_id: str
    plan_version_id: str
    previous_stage: LifecycleStage | None
    stage: LifecycleStage
    evidence_refs: tuple[EvidenceRef, ...]
    authority: Authority
    lineage_revision: int
    event_id: str
    occurred_at: datetime


@dataclass(frozen=True)
class PlanLifecycleState:
    plan_version_id: str
    stage: LifecycleStage
    last_record: LifecycleRecord


@dataclass(frozen=True)
class LifecycleView:
    lineage_id: str
    plans: tuple[PlanLifecycleState, ...]
    revision: int

    def stage_for(self, plan_version_id: str) -> LifecycleStage:
        for plan in self.plans:
            if plan.plan_version_id == plan_version_id:
                return plan.stage
        raise KeyError(f"unknown plan version {plan_version_id!r}")

    @property
    def active_plan_version_id(self) -> str | None:
        active = tuple(
            plan.plan_version_id
            for plan in self.plans
            if plan.stage is LifecycleStage.ACTIVE
        )
        if len(active) > 1:
            raise JournalIntegrityError("lineage contains more than one active plan")
        return active[0] if active else None


_TERMINAL_STAGES = frozenset(
    {
        LifecycleStage.QUARANTINED,
        LifecycleStage.REJECTED,
        LifecycleStage.RETIRED,
        LifecycleStage.ROLLED_BACK,
    }
)

_PROMOTION_STAGES = frozenset(
    {
        LifecycleStage.EXAMINED,
        LifecycleStage.SHADOW,
        LifecycleStage.PAPER,
        LifecycleStage.CANARY,
        LifecycleStage.ACTIVE,
    }
)

_NEXT_STAGE: Mapping[LifecycleStage, LifecycleStage] = {
    LifecycleStage.PROPOSED: LifecycleStage.EXAMINED,
    LifecycleStage.EXAMINED: LifecycleStage.SHADOW,
    LifecycleStage.SHADOW: LifecycleStage.PAPER,
    LifecycleStage.PAPER: LifecycleStage.CANARY,
    LifecycleStage.CANARY: LifecycleStage.ACTIVE,
}

_REQUIRED_EVIDENCE: Mapping[LifecycleStage, frozenset[EvidenceKind]] = {
    LifecycleStage.PROPOSED: frozenset(),
    LifecycleStage.EXAMINED: frozenset({EvidenceKind.EXAMINATION_DOSSIER}),
    LifecycleStage.SHADOW: frozenset(
        {
            EvidenceKind.SHADOW_READINESS,
            EvidenceKind.CONFORMANCE_DOSSIER,
            EvidenceKind.LOCKED_CONFIRMATION,
        }
    ),
    LifecycleStage.PAPER: frozenset({EvidenceKind.SHADOW_TRIAL}),
    LifecycleStage.CANARY: frozenset(
        {
            EvidenceKind.PAPER_TRIAL,
            EvidenceKind.RISK_READINESS,
            EvidenceKind.OPERATIONS_READINESS,
        }
    ),
    LifecycleStage.ACTIVE: frozenset(
        {
            EvidenceKind.CANARY_TRIAL,
            EvidenceKind.RISK_READINESS,
            EvidenceKind.OPERATIONS_READINESS,
        }
    ),
    LifecycleStage.QUARANTINED: frozenset({EvidenceKind.SAFETY_EVENT}),
    LifecycleStage.REJECTED: frozenset({EvidenceKind.GOVERNANCE_DECISION}),
    LifecycleStage.RETIRED: frozenset({EvidenceKind.RETIREMENT_DECISION}),
    LifecycleStage.ROLLED_BACK: frozenset({EvidenceKind.ROLLBACK_DECISION}),
}


class StrategyLifecycle:
    """Transition plan versions without activating or executing orders."""

    def __init__(
        self,
        journal: OperationalJournal,
        *,
        evidence_verifier: Callable[[TransitionRequest], bool] | None = None,
        trusted_actor_roles: Mapping[str, Collection[AuthorityRole]] | None = None,
    ) -> None:
        self._journal = journal
        self._evidence_verifier = evidence_verifier
        self._trusted_actor_roles = _freeze_trusted_actor_roles(trusted_actor_roles)

    def transition(self, request: TransitionRequest) -> LifecycleRecord:
        events = self._events(request.lineage_id)
        repeated = _repeated_command(events, request)
        if repeated is not None:
            return repeated
        self._verify_trusted_authority(request.authority)
        view = _view_from_events(request.lineage_id, events)
        current = next(
            (
                plan.stage
                for plan in view.plans
                if plan.plan_version_id == request.plan_version_id
            ),
            None,
        )
        _validate_path(current, request.target_stage)
        _validate_promoter_independence(events, request)
        _validate_authority(request.target_stage, request.authority)
        _validate_evidence(request.target_stage, request.evidence_refs)
        if (
            request.target_stage is LifecycleStage.ACTIVE
            and view.active_plan_version_id is not None
            and view.active_plan_version_id != request.plan_version_id
        ):
            raise StrategyAlreadyActive(
                f"{view.active_plan_version_id} is already active for this lineage"
            )
        if required_evidence_for(request.target_stage):
            self._verify_required_evidence(request)

        event = self._journal.append(
            EventAppend(
                stream_id=_lineage_stream(request.lineage_id),
                event_type="StrategyLifecycleTransitioned",
                payload=_event_payload(request, current),
                idempotency_key=_command_key(request.command_id),
                expected_version=request.expected_revision,
                occurred_at=request.occurred_at,
                correlation_id=request.plan_version_id,
            )
        )
        return _record_from_event(event)

    def view(self, lineage_id: str) -> LifecycleView:
        if not lineage_id.strip():
            raise ValueError("lineage_id must not be empty")
        return _view_from_events(lineage_id, self._events(lineage_id))

    def _events(self, lineage_id: str) -> tuple[JournalEvent, ...]:
        return self._journal.read_stream(_lineage_stream(lineage_id))

    def _verify_trusted_authority(self, authority: Authority) -> None:
        if self._trusted_actor_roles is None:
            raise UnauthorizedTransition(
                "a trusted actor-role registry is required for lifecycle transitions"
            )
        roles = self._trusted_actor_roles.get(authority.actor_id, frozenset())
        if authority.role not in roles:
            raise UnauthorizedTransition(
                f"actor {authority.actor_id!r} is not trusted for role "
                f"{authority.role.value}"
            )

    def _verify_required_evidence(self, request: TransitionRequest) -> None:
        if self._evidence_verifier is None:
            raise UntrustedReadinessEvidence(
                "evidence-bearing transitions require independently verified evidence"
            )
        try:
            trusted = self._evidence_verifier(request)
        except Exception as exc:
            raise UntrustedReadinessEvidence(
                "stage evidence verification failed closed"
            ) from exc
        if trusted is not True:
            raise UntrustedReadinessEvidence(
                "evidence-bearing transitions require independently verified evidence"
            )


def _validate_path(
    current: LifecycleStage | None,
    target: LifecycleStage,
) -> None:
    if current is None:
        if target is not LifecycleStage.PROPOSED:
            raise InvalidLifecycleTransition(
                f"an unregistered plan cannot transition directly to {target.value}"
            )
        return
    if current in _TERMINAL_STAGES:
        raise TerminalLifecycleState(
            f"a plan in terminal state {current.value} cannot transition "
            f"to {target.value}"
        )
    if target is LifecycleStage.QUARANTINED:
        return
    if target is LifecycleStage.REJECTED and current in {
        LifecycleStage.PROPOSED,
        LifecycleStage.EXAMINED,
        LifecycleStage.SHADOW,
    }:
        return
    if target is LifecycleStage.ROLLED_BACK and current in {
        LifecycleStage.CANARY,
        LifecycleStage.ACTIVE,
    }:
        return
    if target is LifecycleStage.RETIRED and current is LifecycleStage.ACTIVE:
        return
    expected = _NEXT_STAGE.get(current)
    if target is not expected:
        raise InvalidLifecycleTransition(
            f"invalid lifecycle transition from {current.value} to {target.value}"
        )


def _validate_promoter_independence(
    events: tuple[JournalEvent, ...],
    request: TransitionRequest,
) -> None:
    if request.target_stage not in _PROMOTION_STAGES:
        return
    proposer_id = next(
        (
            record.authority.actor_id
            for event in events
            if event.event_type == "StrategyLifecycleTransitioned"
            for record in (_record_from_event(event),)
            if record.plan_version_id == request.plan_version_id
            and record.stage is LifecycleStage.PROPOSED
        ),
        None,
    )
    if proposer_id is None:
        raise JournalIntegrityError(
            "strategy plan has no durable proposer identity"
        )
    if proposer_id == request.authority.actor_id:
        raise UnauthorizedTransition(
            "the plan proposer cannot authorize a later promotion for the same plan"
        )


def _validate_authority(target: LifecycleStage, authority: Authority) -> None:
    if target in {LifecycleStage.CANARY, LifecycleStage.ACTIVE}:
        if authority.role is not AuthorityRole.OWNER:
            raise OwnerAuthorityRequired(
                f"explicit owner authority is required for {target.value}"
            )
        return
    if target is LifecycleStage.PROPOSED:
        allowed = {AuthorityRole.PROPOSER, AuthorityRole.GOVERNOR, AuthorityRole.OWNER}
    elif target in {LifecycleStage.QUARANTINED, LifecycleStage.ROLLED_BACK}:
        allowed = {AuthorityRole.SAFETY, AuthorityRole.OWNER}
    elif target is LifecycleStage.RETIRED:
        allowed = {AuthorityRole.OWNER}
    else:
        allowed = {AuthorityRole.GOVERNOR, AuthorityRole.OWNER}
    if authority.role not in allowed:
        raise UnauthorizedTransition(
            f"{authority.role.value} cannot authorize transition to {target.value}"
        )


def _validate_evidence(
    target: LifecycleStage,
    evidence_refs: tuple[EvidenceRef, ...],
) -> None:
    supplied = {ref.kind for ref in evidence_refs}
    missing = _REQUIRED_EVIDENCE[target] - supplied
    if missing:
        names = ", ".join(sorted(kind.value for kind in missing))
        raise ReadinessEvidenceMissing(
            f"transition to {target.value} is missing evidence: {names}"
        )


def required_evidence_for(stage: LifecycleStage) -> frozenset[EvidenceKind]:
    """Return the dossier kinds required to enter a lifecycle stage."""

    if not isinstance(stage, LifecycleStage):
        raise ValueError("stage must be a LifecycleStage")
    return _REQUIRED_EVIDENCE[stage]


def _view_from_events(
    lineage_id: str,
    events: tuple[JournalEvent, ...],
) -> LifecycleView:
    plans: dict[str, PlanLifecycleState] = {}
    for event in events:
        if event.event_type != "StrategyLifecycleTransitioned":
            continue
        record = _record_from_event(event)
        plans[record.plan_version_id] = PlanLifecycleState(
            plan_version_id=record.plan_version_id,
            stage=record.stage,
            last_record=record,
        )
    view = LifecycleView(
        lineage_id=lineage_id,
        plans=tuple(plans.values()),
        revision=events[-1].stream_sequence if events else 0,
    )
    view.active_plan_version_id
    return view


def _event_payload(
    request: TransitionRequest,
    previous_stage: LifecycleStage | None,
) -> dict[str, object]:
    return {
        "lineage_id": request.lineage_id,
        "plan_version_id": request.plan_version_id,
        "previous_stage": previous_stage.value if previous_stage is not None else None,
        "target_stage": request.target_stage.value,
        "evidence_refs": [
            {"kind": ref.kind.value, "ref_id": ref.ref_id}
            for ref in request.evidence_refs
        ],
        "authority": {
            "actor_id": request.authority.actor_id,
            "role": request.authority.role.value,
            "approval_ref": request.authority.approval_ref,
        },
        "command_id": request.command_id,
    }


def _record_from_event(event: JournalEvent) -> LifecycleRecord:
    payload = event.payload
    previous = payload["previous_stage"]
    authority = payload["authority"]
    return LifecycleRecord(
        lineage_id=str(payload["lineage_id"]),
        plan_version_id=str(payload["plan_version_id"]),
        previous_stage=(
            LifecycleStage(str(previous)) if previous is not None else None
        ),
        stage=LifecycleStage(str(payload["target_stage"])),
        evidence_refs=tuple(
            EvidenceRef(
                kind=EvidenceKind(str(item["kind"])),
                ref_id=str(item["ref_id"]),
            )
            for item in payload["evidence_refs"]
        ),
        authority=Authority(
            actor_id=str(authority["actor_id"]),
            role=AuthorityRole(str(authority["role"])),
            approval_ref=(
                str(authority["approval_ref"])
                if authority["approval_ref"] is not None
                else None
            ),
        ),
        lineage_revision=event.stream_sequence,
        event_id=event.event_id,
        occurred_at=event.occurred_at,
    )


def _repeated_command(
    events: tuple[JournalEvent, ...],
    request: TransitionRequest,
) -> LifecycleRecord | None:
    for event in events:
        if event.event_type != "StrategyLifecycleTransitioned":
            continue
        if event.payload["command_id"] != request.command_id:
            continue
        record = _record_from_event(event)
        if (
            record.lineage_id != request.lineage_id
            or record.plan_version_id != request.plan_version_id
            or record.stage is not request.target_stage
            or record.evidence_refs != request.evidence_refs
            or record.authority != request.authority
            or record.occurred_at != request.occurred_at
        ):
            raise JournalIntegrityError(
                "command_id was reused for a different lifecycle transition"
            )
        return record
    return None


def _lineage_stream(lineage_id: str) -> str:
    return "strategy-lineage:" + hashlib.sha256(
        lineage_id.encode("utf-8")
    ).hexdigest()


def _command_key(command_id: str) -> str:
    return "command:" + hashlib.sha256(command_id.encode("utf-8")).hexdigest()


def _freeze_trusted_actor_roles(
    configured: Mapping[str, Collection[AuthorityRole]] | None,
) -> Mapping[str, frozenset[AuthorityRole]] | None:
    if configured is None:
        return None
    frozen: dict[str, frozenset[AuthorityRole]] = {}
    for actor_id, configured_roles in configured.items():
        if not isinstance(actor_id, str) or not actor_id.strip():
            raise ValueError("trusted actor IDs must be non-empty strings")
        if isinstance(configured_roles, (str, bytes, AuthorityRole)):
            raise ValueError("trusted actor roles must be a collection")
        roles = frozenset(configured_roles)
        if any(not isinstance(role, AuthorityRole) for role in roles):
            raise ValueError("trusted actor roles must contain AuthorityRole values")
        frozen[actor_id] = roles
    return MappingProxyType(frozen)
