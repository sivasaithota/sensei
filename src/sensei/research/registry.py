"""Pre-registration and locked-confirmation governance for research campaigns."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from sensei.operations.journal import (
    EventAppend,
    JournalConflict,
    JournalEvent,
    JournalIntegrityError,
    OperationalJournal,
)

_CONTENT_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")


class ExperimentPhase(str, Enum):
    DISCOVERY = "discovery"
    CONFIRMATION = "confirmation"


class DependenceMethod(str, Enum):
    """Accepted uncertainty methods that account for dependent observations."""

    PURGED_WALK_FORWARD_FOLDS = "purged_walk_forward_folds"
    MOVING_BLOCK_BOOTSTRAP = "moving_block_bootstrap"
    CLUSTER_ROBUST = "cluster_robust"


class CampaignLocked(RuntimeError):
    """The campaign cannot accept more variants after confirmation begins."""


class ConfirmationAlreadyConsumed(RuntimeError):
    """The opaque holdout for this registration has already been accessed."""


@dataclass(frozen=True)
class ResolvedHoldout:
    """A server-resolved snapshot and its in-process examination material."""

    snapshot_id: str
    material: Any

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip():
            raise ValueError("snapshot_id must not be empty")


@dataclass(frozen=True)
class ConfirmationEvidence:
    evidence_ref: str
    p_value: float
    protocol_passed: bool
    dependence_method: DependenceMethod
    independent_unit_count: int
    effect_size: float
    confidence_lower_bound: float

    def __post_init__(self) -> None:
        if not self.evidence_ref.strip():
            raise ValueError("evidence_ref must not be empty")
        if not math.isfinite(self.p_value) or not 0 <= self.p_value <= 1:
            raise ValueError("p_value must be finite and between zero and one")
        if not isinstance(self.protocol_passed, bool):
            raise ValueError("protocol_passed must be a bool")
        if not isinstance(self.dependence_method, DependenceMethod):
            raise ValueError("dependence_method must be an accepted DependenceMethod")
        if type(self.independent_unit_count) is not int:
            raise ValueError("independent_unit_count must be an integer")
        if self.independent_unit_count < 2:
            raise ValueError("independent_unit_count must be at least two")
        for label, value in (
            ("effect_size", self.effect_size),
            ("confidence_lower_bound", self.confidence_lower_bound),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{label} must be finite")
        if self.confidence_lower_bound > self.effect_size:
            raise ValueError("confidence_lower_bound must not exceed effect_size")


@dataclass(frozen=True)
class ConfirmationRequest:
    campaign_id: str
    registration_id: str
    expected_campaign_revision: int
    command_id: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        for label, value in (
            ("campaign_id", self.campaign_id),
            ("registration_id", self.registration_id),
            ("command_id", self.command_id),
        ):
            if not value.strip():
                raise ValueError(f"{label} must not be empty")
        if self.expected_campaign_revision < 0:
            raise ValueError("expected_campaign_revision must not be negative")


@dataclass(frozen=True)
class ConfirmationResult:
    registration_id: str
    campaign_id: str
    evidence_ref: str
    snapshot_id: str
    campaign_trial_count: int
    familywise_alpha: float
    adjusted_alpha: float
    p_value: float
    protocol_passed: bool
    dependence_method: DependenceMethod
    independent_unit_count: int
    effect_size: float
    confidence_lower_bound: float
    minimum_effect_size: float
    minimum_confidence_lower_bound: float
    passed: bool
    burn_event_id: str
    completion_event_id: str
    campaign_revision: int


@dataclass(frozen=True)
class ExperimentDeclaration:
    campaign_id: str
    variant_id: str
    plan_version_id: str
    plan_content_hash: str
    protocol_id: str
    data_policy_id: str
    phase: ExperimentPhase
    minimum_effect_size: float
    minimum_confidence_lower_bound: float
    familywise_alpha: float
    expected_campaign_revision: int
    command_id: str
    occurred_at: datetime
    discovery_snapshot_id: str | None = None
    confirmation_holdout_policy_id: str | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("campaign_id", self.campaign_id),
            ("variant_id", self.variant_id),
            ("plan_version_id", self.plan_version_id),
            ("protocol_id", self.protocol_id),
            ("data_policy_id", self.data_policy_id),
            ("command_id", self.command_id),
        ):
            if not value.strip():
                raise ValueError(f"{label} must not be empty")
        if _CONTENT_HASH.fullmatch(self.plan_content_hash) is None:
            raise ValueError("plan_content_hash must be a lowercase sha256 identity")
        if not isinstance(self.phase, ExperimentPhase):
            raise ValueError("phase must be an ExperimentPhase")
        if (
            not math.isfinite(self.familywise_alpha)
            or not 0 < self.familywise_alpha <= 1
        ):
            raise ValueError("familywise_alpha must be finite and between zero and one")
        for label, value in (
            ("minimum_effect_size", self.minimum_effect_size),
            (
                "minimum_confidence_lower_bound",
                self.minimum_confidence_lower_bound,
            ),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{label} must be finite")
        if self.expected_campaign_revision < 0:
            raise ValueError("expected_campaign_revision must not be negative")
        if self.phase is ExperimentPhase.DISCOVERY:
            if not (self.discovery_snapshot_id or "").strip():
                raise ValueError("discovery registration requires a snapshot")
            if self.confirmation_holdout_policy_id is not None:
                raise ValueError(
                    "discovery registration cannot name a confirmation holdout"
                )
        else:
            if self.discovery_snapshot_id is not None:
                raise ValueError(
                    "confirmation registration cannot accept a caller snapshot"
                )
            if not (self.confirmation_holdout_policy_id or "").strip():
                raise ValueError(
                    "confirmation registration requires an opaque holdout policy"
                )

    def identity_payload(self) -> dict[str, object]:
        return {
            "campaign_id": self.campaign_id,
            "variant_id": self.variant_id,
            "plan_version_id": self.plan_version_id,
            "plan_content_hash": self.plan_content_hash,
            "protocol_id": self.protocol_id,
            "data_policy_id": self.data_policy_id,
            "phase": self.phase.value,
            "minimum_effect_size": self.minimum_effect_size,
            "minimum_confidence_lower_bound": self.minimum_confidence_lower_bound,
            "familywise_alpha": self.familywise_alpha,
            "discovery_snapshot_id": self.discovery_snapshot_id,
            "confirmation_holdout_policy_id": self.confirmation_holdout_policy_id,
        }


@dataclass(frozen=True)
class RegisteredExperiment:
    registration_id: str
    campaign_id: str
    variant_id: str
    plan_version_id: str
    plan_content_hash: str
    protocol_id: str
    data_policy_id: str
    phase: ExperimentPhase
    minimum_effect_size: float
    minimum_confidence_lower_bound: float
    familywise_alpha: float
    discovery_snapshot_id: str | None
    confirmation_holdout_policy_id: str | None
    trial_number: int
    campaign_revision: int
    registered_at: datetime
    event_id: str


@dataclass(frozen=True)
class CampaignView:
    campaign_id: str
    registrations: tuple[RegisteredExperiment, ...]
    revision: int
    confirmation_started: bool

    @property
    def trial_count(self) -> int:
        return len(self.registrations)


class ExperimentRegistry:
    """Own immutable campaign registrations and their trial count."""

    def __init__(
        self,
        journal: OperationalJournal,
        *,
        confirmation_resolver: Callable[[str], ResolvedHoldout] | None = None,
        confirmation_examiner: Callable[
            [RegisteredExperiment, Any], ConfirmationEvidence
        ]
        | None = None,
    ) -> None:
        self._journal = journal
        self._confirmation_resolver = confirmation_resolver
        self._confirmation_examiner = confirmation_examiner

    def preregister(self, declaration: ExperimentDeclaration) -> RegisteredExperiment:
        campaign = self.campaign(declaration.campaign_id)
        registration_id = _content_id(declaration.identity_payload(), "experiment")
        existing = next(
            (
                item
                for item in campaign.registrations
                if item.registration_id == registration_id
            ),
            None,
        )
        if existing is not None:
            return existing
        if campaign.confirmation_started:
            raise CampaignLocked(
                "campaign registrations are sealed once confirmation access begins"
            )
        if campaign.registrations and not math.isclose(
            campaign.registrations[0].familywise_alpha,
            declaration.familywise_alpha,
        ):
            raise ValueError(
                "all registrations in a campaign must use one familywise alpha"
            )

        trial_number = campaign.trial_count + 1
        payload = {
            **declaration.identity_payload(),
            "registration_id": registration_id,
            "trial_number": trial_number,
        }
        event = self._journal.append(
            EventAppend(
                stream_id=_campaign_stream(declaration.campaign_id),
                event_type="ExperimentRegistered",
                payload=payload,
                idempotency_key=_command_key(declaration.command_id),
                expected_version=declaration.expected_campaign_revision,
                occurred_at=declaration.occurred_at,
                correlation_id=registration_id,
            )
        )
        return _registered_from_event(
            event.payload,
            event.occurred_at,
            event.event_id,
            event.stream_sequence,
        )

    def confirm(self, request: ConfirmationRequest) -> ConfirmationResult:
        """Consume one opaque holdout, then examine it with campaign correction."""

        events = self._journal.read_stream(_campaign_stream(request.campaign_id))
        campaign = self.campaign(request.campaign_id)
        registration = next(
            (
                item
                for item in campaign.registrations
                if item.registration_id == request.registration_id
            ),
            None,
        )
        if registration is None:
            raise KeyError(f"unknown registration {request.registration_id!r}")
        if registration.phase is not ExperimentPhase.CONFIRMATION:
            raise ValueError("only a confirmation registration can consume a holdout")
        consumed = next(
            (
                event
                for event in events
                if event.event_type == "ConfirmationAccessConsumed"
                and event.payload["registration_id"] == request.registration_id
            ),
            None,
        )
        if consumed is not None:
            if consumed.payload.get("command_id") == request.command_id:
                exact_retry = (
                    consumed.payload.get("expected_campaign_revision")
                    == request.expected_campaign_revision
                    and consumed.occurred_at == request.occurred_at
                )
                if not exact_retry:
                    raise JournalIntegrityError(
                        "confirmation command_id was reused with different content"
                    )
                completed = next(
                    (
                        event
                        for event in events
                        if event.event_type == "LockedConfirmationCompleted"
                        and event.payload["burn_event_id"] == consumed.event_id
                    ),
                    None,
                )
                if completed is not None:
                    return _confirmation_result_from_event(completed)
            raise ConfirmationAlreadyConsumed(
                "confirmation access was already consumed for this registration"
            )
        if self._confirmation_resolver is None or self._confirmation_examiner is None:
            raise RuntimeError("confirmation resolver and examiner must be configured")

        adjusted_alpha = registration.familywise_alpha / campaign.trial_count
        burn = self._journal.append(
            EventAppend(
                stream_id=_campaign_stream(request.campaign_id),
                event_type="ConfirmationAccessConsumed",
                payload={
                    "campaign_id": request.campaign_id,
                    "registration_id": request.registration_id,
                    "campaign_trial_count": campaign.trial_count,
                    "familywise_alpha": registration.familywise_alpha,
                    "adjusted_alpha": adjusted_alpha,
                    "command_id": request.command_id,
                    "expected_campaign_revision": request.expected_campaign_revision,
                },
                idempotency_key=_command_key(request.command_id),
                expected_version=request.expected_campaign_revision,
                occurred_at=request.occurred_at,
                correlation_id=request.registration_id,
            )
        )

        # This resolution is intentionally after the durable burn above. A resolver
        # failure leaves the one-use opportunity consumed.
        holdout = self._confirmation_resolver(
            registration.confirmation_holdout_policy_id or ""
        )
        evidence = self._confirmation_examiner(registration, holdout.material)
        passed = (
            evidence.protocol_passed
            and evidence.p_value <= adjusted_alpha
            and evidence.effect_size >= registration.minimum_effect_size
            and evidence.confidence_lower_bound
            >= registration.minimum_confidence_lower_bound
        )
        completion_payload = {
            "campaign_id": request.campaign_id,
            "registration_id": request.registration_id,
            "evidence_ref": evidence.evidence_ref,
            "snapshot_id": holdout.snapshot_id,
            "campaign_trial_count": campaign.trial_count,
            "familywise_alpha": registration.familywise_alpha,
            "adjusted_alpha": adjusted_alpha,
            "p_value": evidence.p_value,
            "protocol_passed": evidence.protocol_passed,
            "dependence_method": evidence.dependence_method.value,
            "independent_unit_count": evidence.independent_unit_count,
            "effect_size": evidence.effect_size,
            "confidence_lower_bound": evidence.confidence_lower_bound,
            "minimum_effect_size": registration.minimum_effect_size,
            "minimum_confidence_lower_bound": (
                registration.minimum_confidence_lower_bound
            ),
            "passed": passed,
            "burn_event_id": burn.event_id,
        }
        expected_completion_revision = burn.stream_sequence
        while True:
            try:
                completion = self._journal.append(
                    EventAppend(
                        stream_id=_campaign_stream(request.campaign_id),
                        event_type="LockedConfirmationCompleted",
                        payload=completion_payload,
                        idempotency_key=_confirmation_result_key(
                            request.registration_id
                        ),
                        expected_version=expected_completion_revision,
                        occurred_at=request.occurred_at,
                        causation_id=burn.event_id,
                        correlation_id=request.registration_id,
                    )
                )
                break
            except JournalConflict:
                # Confirmation burns for other pre-registered variants may commit
                # while this examiner runs. Registrations are already sealed, so
                # retrying only advances over a finite set of immutable events.
                latest = self._journal.read_stream(
                    _campaign_stream(request.campaign_id)
                )
                expected_completion_revision = latest[-1].stream_sequence
        return _confirmation_result_from_event(completion)

    def campaign(self, campaign_id: str) -> CampaignView:
        if not campaign_id.strip():
            raise ValueError("campaign_id must not be empty")
        events = self._journal.read_stream(_campaign_stream(campaign_id))
        registrations = tuple(
            _registered_from_event(
                event.payload,
                event.occurred_at,
                event.event_id,
                event.stream_sequence,
            )
            for event in events
            if event.event_type == "ExperimentRegistered"
        )
        return CampaignView(
            campaign_id=campaign_id,
            registrations=registrations,
            revision=events[-1].stream_sequence if events else 0,
            confirmation_started=any(
                event.event_type == "ConfirmationAccessConsumed" for event in events
            ),
        )


def _registered_from_event(
    payload: Mapping[str, Any],
    occurred_at: datetime,
    event_id: str,
    campaign_revision: int,
) -> RegisteredExperiment:
    return RegisteredExperiment(
        registration_id=str(payload["registration_id"]),
        campaign_id=str(payload["campaign_id"]),
        variant_id=str(payload["variant_id"]),
        plan_version_id=str(payload["plan_version_id"]),
        plan_content_hash=str(payload["plan_content_hash"]),
        protocol_id=str(payload["protocol_id"]),
        data_policy_id=str(payload["data_policy_id"]),
        phase=ExperimentPhase(str(payload["phase"])),
        minimum_effect_size=float(payload["minimum_effect_size"]),
        minimum_confidence_lower_bound=float(
            payload["minimum_confidence_lower_bound"]
        ),
        familywise_alpha=float(payload["familywise_alpha"]),
        discovery_snapshot_id=(
            str(payload["discovery_snapshot_id"])
            if payload["discovery_snapshot_id"] is not None
            else None
        ),
        confirmation_holdout_policy_id=(
            str(payload["confirmation_holdout_policy_id"])
            if payload["confirmation_holdout_policy_id"] is not None
            else None
        ),
        trial_number=int(payload["trial_number"]),
        campaign_revision=campaign_revision,
        registered_at=occurred_at,
        event_id=event_id,
    )


def _confirmation_result_from_event(event: JournalEvent) -> ConfirmationResult:
    payload = event.payload
    return ConfirmationResult(
        registration_id=str(payload["registration_id"]),
        campaign_id=str(payload["campaign_id"]),
        evidence_ref=str(payload["evidence_ref"]),
        snapshot_id=str(payload["snapshot_id"]),
        campaign_trial_count=int(payload["campaign_trial_count"]),
        familywise_alpha=float(payload["familywise_alpha"]),
        adjusted_alpha=float(payload["adjusted_alpha"]),
        p_value=float(payload["p_value"]),
        protocol_passed=bool(payload["protocol_passed"]),
        dependence_method=DependenceMethod(str(payload["dependence_method"])),
        independent_unit_count=int(payload["independent_unit_count"]),
        effect_size=float(payload["effect_size"]),
        confidence_lower_bound=float(payload["confidence_lower_bound"]),
        minimum_effect_size=float(payload["minimum_effect_size"]),
        minimum_confidence_lower_bound=float(
            payload["minimum_confidence_lower_bound"]
        ),
        passed=bool(payload["passed"]),
        burn_event_id=str(payload["burn_event_id"]),
        completion_event_id=event.event_id,
        campaign_revision=event.stream_sequence,
    )


def _campaign_stream(campaign_id: str) -> str:
    return "campaign:" + hashlib.sha256(campaign_id.encode("utf-8")).hexdigest()


def _command_key(command_id: str) -> str:
    return "command:" + hashlib.sha256(command_id.encode("utf-8")).hexdigest()


def _confirmation_result_key(registration_id: str) -> str:
    return "confirmation-result:" + hashlib.sha256(
        registration_id.encode("utf-8")
    ).hexdigest()


def _content_id(payload: object, namespace: str) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return namespace + ":" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
