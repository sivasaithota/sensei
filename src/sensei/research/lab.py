"""Research lab orchestration for Coach hypotheses.

The lab turns a research-only mistake hypothesis plus an executable candidate
rule into preregistered examination evidence. It never promotes a strategy or
changes the active playbook.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from sensei.learning.outcomes import MistakeHypothesis
from sensei.operations.journal import EventAppend, OperationalJournal
from sensei.research.artifacts import ImmutableEvidenceStore
from sensei.research.examiner import ExaminationRequest, ResearchExaminer
from sensei.research.market_data import MarketDataSnapshot
from sensei.research.models import (
    EvidenceDossier,
    ExaminationProtocol,
    HypothesisVersion,
    Recommendation,
    content_id,
)
from sensei.research.registry import (
    ExperimentDeclaration,
    ExperimentPhase,
    ExperimentRegistry,
    RegisteredExperiment,
)

_STREAM_SUFFIX = re.compile(r"[A-Za-z0-9_.:-]{1,64}\Z")


@dataclass(frozen=True)
class ResearchLabCandidate:
    coach_hypothesis: MistakeHypothesis
    hypothesis: HypothesisVersion
    snapshot: MarketDataSnapshot
    protocol: ExaminationProtocol
    data_policy_id: str
    minimum_effect_size: float
    minimum_confidence_lower_bound: float
    familywise_alpha: float

    def __post_init__(self) -> None:
        if not self.data_policy_id.strip():
            raise ValueError("data_policy_id is required")

    @property
    def campaign_id(self) -> str:
        return f"coach:{self.coach_hypothesis.scope.scope_id}"

    @property
    def variant_id(self) -> str:
        return content_id(
            {
                "coach_hypothesis_id": self.coach_hypothesis.hypothesis_id,
                "candidate": self.hypothesis.identity_payload(),
                "snapshot_id": self.snapshot.snapshot_id,
                "protocol_id": self.protocol.protocol_id,
            }
        )

    @property
    def plan_content_hash(self) -> str:
        return content_id(self.hypothesis.identity_payload())

    @property
    def plan_version_id(self) -> str:
        return f"{self.hypothesis.hypothesis_id}:v{self.hypothesis.version}"

    def with_hypothesis(self, hypothesis: HypothesisVersion) -> ResearchLabCandidate:
        return replace(self, hypothesis=hypothesis)

    def with_coach_hypothesis(
        self, coach_hypothesis: MistakeHypothesis
    ) -> ResearchLabCandidate:
        return replace(self, coach_hypothesis=coach_hypothesis)


@dataclass(frozen=True)
class ResearchLabResult:
    registration: RegisteredExperiment
    dossier: EvidenceDossier
    event_id: str
    shadow_eligible: bool
    playbook_changed: bool = False


@dataclass(frozen=True)
class _LabGate:
    recommendation: Recommendation
    shadow_eligible: bool
    effect_size: float | None
    confidence_lower_bound: float | None
    reasons: tuple[str, ...]


class ResearchBacktestLab:
    """Validate and examine Coach-derived research candidates."""

    def __init__(
        self,
        journal: OperationalJournal,
        *,
        artifact_dir: Path | None = None,
        examiner: ResearchExaminer | None = None,
    ) -> None:
        self._journal = journal
        self._registry = ExperimentRegistry(journal)
        self._examiner = examiner or ResearchExaminer()
        self._artifact_store = (
            ImmutableEvidenceStore(artifact_dir) if artifact_dir is not None else None
        )

    def run(
        self,
        candidate: ResearchLabCandidate,
        *,
        command_id: str,
        occurred_at: datetime,
    ) -> ResearchLabResult:
        _validate_candidate(candidate)
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        if not command_id.strip():
            raise ValueError("command_id is required")

        campaign = self._registry.campaign(candidate.campaign_id)
        registration = self._registry.preregister(
            ExperimentDeclaration(
                campaign_id=candidate.campaign_id,
                variant_id=candidate.variant_id,
                plan_version_id=candidate.plan_version_id,
                plan_content_hash=candidate.plan_content_hash,
                protocol_id=candidate.protocol.protocol_id,
                data_policy_id=candidate.data_policy_id,
                phase=ExperimentPhase.DISCOVERY,
                minimum_effect_size=candidate.minimum_effect_size,
                minimum_confidence_lower_bound=(
                    candidate.minimum_confidence_lower_bound
                ),
                discovery_snapshot_id=candidate.snapshot.snapshot_id,
                familywise_alpha=candidate.familywise_alpha,
                expected_campaign_revision=campaign.revision,
                command_id=f"{command_id}:register",
                occurred_at=occurred_at,
            )
        )
        dossier = self._examiner.examine(
            ExaminationRequest(
                hypothesis=candidate.hypothesis,
                snapshot=candidate.snapshot,
                protocol=candidate.protocol,
            )
        )
        gate = _lab_gate(candidate, dossier)
        artifact_recorded = False
        if self._artifact_store is not None:
            self._artifact_store.record(dossier)
            artifact_recorded = True
        stream = _lab_stream(candidate.coach_hypothesis)
        events = self._journal.read_stream(stream)
        payload = _result_payload(
            candidate,
            registration,
            dossier,
            gate,
            artifact_recorded=artifact_recorded,
        )
        event = self._journal.append(
            EventAppend(
                stream_id=stream,
                event_type="ResearchLabDossierRecorded",
                payload=payload,
                idempotency_key=_result_key(registration.registration_id),
                expected_version=len(events),
                occurred_at=occurred_at,
                correlation_id=registration.registration_id,
            )
        )
        return ResearchLabResult(
            registration=registration,
            dossier=dossier,
            event_id=event.event_id,
            shadow_eligible=gate.shadow_eligible,
            playbook_changed=False,
        )


def _validate_candidate(candidate: ResearchLabCandidate) -> None:
    coach = candidate.coach_hypothesis
    if coach.authority != "RESEARCH_ONLY":
        raise ValueError("Coach hypotheses must remain research-only")
    if not coach.requires_examination:
        raise ValueError("Coach hypotheses must require examination")
    if coach.can_veto_trades:
        raise ValueError("Coach hypotheses cannot veto trades")
    if not coach.evidence_episode_ids:
        raise ValueError("Coach hypotheses require episode evidence")


def _result_payload(
    candidate: ResearchLabCandidate,
    registration: RegisteredExperiment,
    dossier: EvidenceDossier,
    gate: _LabGate,
    *,
    artifact_recorded: bool,
) -> dict[str, Any]:
    aggregate = dossier.aggregate.model_dump(mode="json")
    return {
        "lab_result_id": content_id(
            {
                "registration_id": registration.registration_id,
                "experiment_id": dossier.experiment_id,
                "coach_hypothesis_id": candidate.coach_hypothesis.hypothesis_id,
            }
        ),
        "authority": "RESEARCH_ONLY",
        "coach_hypothesis_id": candidate.coach_hypothesis.hypothesis_id,
        "coach_scope_id": candidate.coach_hypothesis.scope.scope_id,
        "evidence_episode_ids": list(
            candidate.coach_hypothesis.evidence_episode_ids
        ),
        "candidate_hypothesis_id": candidate.hypothesis.hypothesis_id,
        "candidate_hypothesis_version": candidate.hypothesis.version,
        "registration_id": registration.registration_id,
        "campaign_id": registration.campaign_id,
        "trial_number": registration.trial_number,
        "experiment_id": dossier.experiment_id,
        "artifact_recorded": artifact_recorded,
        "snapshot_id": dossier.snapshot_id,
        "protocol_id": dossier.protocol_id,
        "status": dossier.status.value,
        "examiner_recommendation": dossier.recommendation.value,
        "recommendation": gate.recommendation.value,
        "shadow_eligible": gate.shadow_eligible,
        "effect_size": gate.effect_size,
        "minimum_effect_size": registration.minimum_effect_size,
        "confidence_lower_bound": gate.confidence_lower_bound,
        "minimum_confidence_lower_bound": (
            registration.minimum_confidence_lower_bound
        ),
        "playbook_changed": False,
        "aggregate": aggregate,
        "issues": [issue.model_dump(mode="json") for issue in dossier.issues],
        "warnings": [
            warning.model_dump(mode="json") for warning in dossier.warnings
        ],
        "reasons": list(dossier.reasons + gate.reasons),
    }


def _lab_gate(
    candidate: ResearchLabCandidate,
    dossier: EvidenceDossier,
) -> _LabGate:
    if dossier.recommendation is not Recommendation.ELIGIBLE_FOR_SHADOW:
        return _LabGate(
            recommendation=dossier.recommendation,
            shadow_eligible=False,
            effect_size=dossier.aggregate.expectancy_pct,
            confidence_lower_bound=None,
            reasons=(),
        )

    effect_size = dossier.aggregate.expectancy_pct
    if effect_size is None or effect_size < candidate.minimum_effect_size:
        return _LabGate(
            recommendation=Recommendation.REJECT,
            shadow_eligible=False,
            effect_size=effect_size,
            confidence_lower_bound=None,
            reasons=(
                "The lab effect size failed the preregistered minimum effect gate.",
            ),
        )
    if candidate.minimum_confidence_lower_bound > 0:
        return _LabGate(
            recommendation=Recommendation.NEEDS_MORE_EVIDENCE,
            shadow_eligible=False,
            effect_size=effect_size,
            confidence_lower_bound=None,
            reasons=(
                "The examiner does not estimate a confidence lower bound for "
                "discovery lab evidence.",
            ),
        )
    return _LabGate(
        recommendation=Recommendation.ELIGIBLE_FOR_SHADOW,
        shadow_eligible=True,
        effect_size=effect_size,
        confidence_lower_bound=None,
        reasons=(),
    )


def _lab_stream(coach_hypothesis: MistakeHypothesis) -> str:
    hypothesis_id = coach_hypothesis.hypothesis_id.removeprefix("hypothesis:")
    if _STREAM_SUFFIX.fullmatch(hypothesis_id) is not None:
        return f"research_lab:{hypothesis_id}"
    return (
        "research_lab:"
        + content_id(coach_hypothesis.hypothesis_id).removeprefix("sha256:")
    )


def _result_key(registration_id: str) -> str:
    return f"research-lab:{content_id(registration_id).removeprefix('sha256:')}"
