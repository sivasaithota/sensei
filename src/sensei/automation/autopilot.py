"""Unattended lifecycle progression backed only by verified stage dossiers.

The autopilot owns no research judgment.  It proposes exact catalogued plans,
collects already-issued independent dossiers, and applies the lifecycle's
normal transition API.  It deliberately stops at PAPER; capital-bearing stages
remain owner decisions.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from sensei.governance.evidence import DossierOutcome, StageDossierRegistry
from sensei.governance.lifecycle import (
    Authority,
    AuthorityRole,
    EvidenceRef,
    LifecycleStage,
    StrategyLifecycle,
    TransitionRequest,
    required_evidence_for,
)
from sensei.operations import OperationalJournal
from sensei.strategy import StrategyPlanCatalog, StrategyPlanRecord


class EvidenceAvailabilityState(StrEnum):
    READY = "READY"
    WAITING = "WAITING"
    FAILED = "FAILED"


@dataclass(frozen=True)
class EvidenceAvailability:
    state: EvidenceAvailabilityState
    evidence_refs: tuple[EvidenceRef, ...] = ()
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        refs = tuple(self.evidence_refs)
        reasons = tuple(self.reason_codes)
        if len(set(refs)) != len(refs):
            raise ValueError("evidence references must be unique")
        if len(set(reasons)) != len(reasons) or any(
            not isinstance(reason, str) or not reason.strip() for reason in reasons
        ):
            raise ValueError("reason codes must be unique nonblank text")
        if self.state is EvidenceAvailabilityState.READY:
            if not refs or reasons:
                raise ValueError("ready evidence requires references and no reasons")
        elif refs or not reasons:
            raise ValueError("non-ready evidence requires reasons and no references")
        object.__setattr__(self, "evidence_refs", refs)
        object.__setattr__(self, "reason_codes", reasons)


class LifecycleEvidenceProvider(Protocol):
    def evidence_for(
        self,
        record: StrategyPlanRecord,
        target_stage: LifecycleStage,
    ) -> EvidenceAvailability: ...


class ExistingDossierEvidenceProvider:
    """Select the newest trusted dossier for every exact required kind."""

    def __init__(
        self,
        journal: OperationalJournal,
        registry: StageDossierRegistry,
    ) -> None:
        if not registry.is_bound_to_journal(journal):
            raise ValueError("dossier provider and registry must share one journal")
        self._journal = journal
        self._registry = registry

    def is_bound_to_journal(self, journal: OperationalJournal) -> bool:
        return self._journal is journal and self._registry.is_bound_to_journal(
            journal
        )

    def evidence_for(
        self,
        record: StrategyPlanRecord,
        target_stage: LifecycleStage,
    ) -> EvidenceAvailability:
        required = required_evidence_for(target_stage)
        if not required:
            raise ValueError("the requested lifecycle stage needs no evidence")
        if not self._journal.verify().ok:
            return EvidenceAvailability(
                EvidenceAvailabilityState.FAILED,
                reason_codes=("JOURNAL_INTEGRITY_FAILED",),
            )

        newest = {}
        for event in self._journal.read_all():
            if event.event_type != "StageDossierIssued":
                continue
            payload = event.payload
            if (
                payload.get("lineage_id") != record.lineage_id
                or payload.get("plan_version_id") != record.plan_id
            ):
                continue
            try:
                dossier = self._registry.get(str(payload["dossier_id"]))
            except Exception:
                return EvidenceAvailability(
                    EvidenceAvailabilityState.FAILED,
                    reason_codes=("STAGE_DOSSIER_INVALID",),
                )
            if dossier is None or dossier.evidence_kind not in required:
                continue
            prior = newest.get(dossier.evidence_kind)
            if (
                prior is None
                or dossier.journal_global_sequence
                > prior.journal_global_sequence
            ):
                newest[dossier.evidence_kind] = dossier

        reasons: list[str] = []
        refs: list[EvidenceRef] = []
        for kind in sorted(required, key=lambda value: value.value):
            dossier = newest.get(kind)
            code = kind.value.upper()
            if dossier is None:
                reasons.append(f"{code}_MISSING")
            elif dossier.outcome is DossierOutcome.FAILED:
                reasons.append(f"{code}_FAILED")
            elif dossier.outcome is DossierOutcome.INCONCLUSIVE:
                reasons.append(f"{code}_INCONCLUSIVE")
            else:
                refs.append(dossier.evidence_ref)

        if reasons:
            failed = any(
                reason.endswith(("_FAILED", "_INCONCLUSIVE"))
                or reason in {"JOURNAL_INTEGRITY_FAILED", "STAGE_DOSSIER_INVALID"}
                for reason in reasons
            )
            return EvidenceAvailability(
                (
                    EvidenceAvailabilityState.FAILED
                    if failed
                    else EvidenceAvailabilityState.WAITING
                ),
                reason_codes=tuple(reasons),
            )
        return EvidenceAvailability(
            EvidenceAvailabilityState.READY,
            evidence_refs=tuple(refs),
        )


class StrategyAutomationState(StrEnum):
    PROGRESSED = "PROGRESSED"
    WAITING_EVIDENCE = "WAITING_EVIDENCE"
    EVIDENCE_FAILED = "EVIDENCE_FAILED"
    PAPER_READY = "PAPER_READY"
    OWNER_CONTROLLED = "OWNER_CONTROLLED"
    TERMINAL = "TERMINAL"


@dataclass(frozen=True)
class StrategyAutomationResult:
    plan_id: str
    lineage_id: str
    stage: LifecycleStage
    state: StrategyAutomationState
    reason_codes: tuple[str, ...] = ()
    lifecycle_event_id: str | None = None


@dataclass(frozen=True)
class StrategyAutomationReport:
    assessed_at: datetime
    results: tuple[StrategyAutomationResult, ...]

    @property
    def paper_plan_ids(self) -> tuple[str, ...]:
        return tuple(
            result.plan_id
            for result in self.results
            if result.stage is LifecycleStage.PAPER
        )


_NEXT_AUTOMATED_STAGE = {
    LifecycleStage.PROPOSED: LifecycleStage.EXAMINED,
    LifecycleStage.EXAMINED: LifecycleStage.SHADOW,
    LifecycleStage.SHADOW: LifecycleStage.PAPER,
}
_TERMINAL_STAGES = frozenset(
    {
        LifecycleStage.QUARANTINED,
        LifecycleStage.REJECTED,
        LifecycleStage.RETIRED,
        LifecycleStage.ROLLED_BACK,
    }
)


class StrategyAutopilot:
    """Apply at most one evidence-bearing promotion per plan and poll."""

    def __init__(
        self,
        *,
        catalog: StrategyPlanCatalog,
        lifecycle: StrategyLifecycle,
        evidence_provider: LifecycleEvidenceProvider,
        proposer: Authority,
        governor: Authority,
    ) -> None:
        if proposer.role is not AuthorityRole.PROPOSER:
            raise ValueError("autopilot proposer needs the proposer authority role")
        if governor.role is not AuthorityRole.GOVERNOR:
            raise ValueError("autopilot governor needs the governor authority role")
        if proposer.actor_id == governor.actor_id:
            raise ValueError("strategy proposer and governor must be independent")
        if not isinstance(catalog, StrategyPlanCatalog):
            raise TypeError("catalog must be a StrategyPlanCatalog")
        if not isinstance(lifecycle, StrategyLifecycle):
            raise TypeError("lifecycle must be a StrategyLifecycle")
        self._catalog = catalog
        self._lifecycle = lifecycle
        self._evidence_provider = evidence_provider
        self._proposer = proposer
        self._governor = governor

    def reconcile(
        self,
        *,
        now: datetime,
        command_id: str,
    ) -> StrategyAutomationReport:
        _aware(now)
        if not command_id.strip():
            raise ValueError("command_id is required")
        results = tuple(
            self._reconcile_plan(record, now=now, command_id=command_id)
            for record in self._catalog.list()
        )
        return StrategyAutomationReport(assessed_at=now, results=results)

    def _reconcile_plan(
        self,
        record: StrategyPlanRecord,
        *,
        now: datetime,
        command_id: str,
    ) -> StrategyAutomationResult:
        view = self._lifecycle.view(record.lineage_id)
        try:
            stage = view.stage_for(record.plan_id)
        except KeyError:
            proposed = self._lifecycle.transition(
                TransitionRequest(
                    lineage_id=record.lineage_id,
                    plan_version_id=record.plan_id,
                    target_stage=LifecycleStage.PROPOSED,
                    evidence_refs=(),
                    authority=self._proposer,
                    expected_revision=view.revision,
                    command_id=_transition_command(
                        command_id, record.plan_id, LifecycleStage.PROPOSED
                    ),
                    occurred_at=now,
                )
            )
            stage = proposed.stage
            view = self._lifecycle.view(record.lineage_id)

        if stage is LifecycleStage.PAPER:
            return StrategyAutomationResult(
                plan_id=record.plan_id,
                lineage_id=record.lineage_id,
                stage=stage,
                state=StrategyAutomationState.PAPER_READY,
            )
        if stage in {LifecycleStage.CANARY, LifecycleStage.ACTIVE}:
            return StrategyAutomationResult(
                plan_id=record.plan_id,
                lineage_id=record.lineage_id,
                stage=stage,
                state=StrategyAutomationState.OWNER_CONTROLLED,
                reason_codes=("OWNER_AUTHORITY_REQUIRED",),
            )
        if stage in _TERMINAL_STAGES:
            return StrategyAutomationResult(
                plan_id=record.plan_id,
                lineage_id=record.lineage_id,
                stage=stage,
                state=StrategyAutomationState.TERMINAL,
                reason_codes=(f"STRATEGY_{stage.value.upper()}",),
            )

        target = _NEXT_AUTOMATED_STAGE[stage]
        availability = self._evidence_provider.evidence_for(record, target)
        if availability.state is not EvidenceAvailabilityState.READY:
            return StrategyAutomationResult(
                plan_id=record.plan_id,
                lineage_id=record.lineage_id,
                stage=stage,
                state=(
                    StrategyAutomationState.WAITING_EVIDENCE
                    if availability.state is EvidenceAvailabilityState.WAITING
                    else StrategyAutomationState.EVIDENCE_FAILED
                ),
                reason_codes=availability.reason_codes,
            )

        transitioned = self._lifecycle.transition(
            TransitionRequest(
                lineage_id=record.lineage_id,
                plan_version_id=record.plan_id,
                target_stage=target,
                evidence_refs=availability.evidence_refs,
                authority=self._governor,
                expected_revision=view.revision,
                command_id=_transition_command(command_id, record.plan_id, target),
                occurred_at=now,
            )
        )
        return StrategyAutomationResult(
            plan_id=record.plan_id,
            lineage_id=record.lineage_id,
            stage=target,
            state=(
                StrategyAutomationState.PAPER_READY
                if target is LifecycleStage.PAPER
                else StrategyAutomationState.PROGRESSED
            ),
            lifecycle_event_id=transitioned.event_id,
        )


def _transition_command(
    poll_command_id: str,
    plan_id: str,
    stage: LifecycleStage,
) -> str:
    material = f"{poll_command_id}|{plan_id}|{stage.value}"
    return "strategy-autopilot:" + hashlib.sha256(material.encode()).hexdigest()


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("autopilot time must be timezone-aware")
