import sqlite3
import hashlib
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from sensei.governance.evidence import (
    DossierError,
    DossierIntegrityError,
    DossierOutcome,
    MissingSupportingEvent,
    StageEvidenceEnvelope,
    StageDossierIssue,
    StageDossierRegistry,
)
from sensei.governance.lifecycle import (
    Authority,
    AuthorityRole,
    EvidenceKind,
    EvidenceRef,
    LifecycleStage,
    StrategyLifecycle,
    TransitionRequest,
)
from sensei.operations.journal import EventAppend, OperationalJournal


NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
LINEAGE = "hammer-follow-through"
PLAN = "plan:hammer:v1"
GOVERNOR = Authority("governor-1", AuthorityRole.GOVERNOR)
OWNER = Authority("owner-1", AuthorityRole.OWNER, "approval:owner-1")
PROPOSER = Authority("researcher-1", AuthorityRole.PROPOSER)
TRUSTED_ACTOR_ROLES = {
    PROPOSER.actor_id: frozenset({AuthorityRole.PROPOSER}),
    GOVERNOR.actor_id: frozenset({AuthorityRole.GOVERNOR}),
    OWNER.actor_id: frozenset({AuthorityRole.OWNER}),
}
TRUSTED_ISSUERS = frozenset({"governance-service-1"})
TRUSTED_PRODUCERS_BY_KIND = {
    EvidenceKind.EXAMINATION_DOSSIER: frozenset(
        {
            "research-examiner-1",
            "examiner-contract-1",
            "producer:passed-exam",
            "producer:failed-exam",
            "producer:examined-integration",
            "governor-1",
            "examiner-1",
        }
    ),
    EvidenceKind.SHADOW_READINESS: frozenset(
        {"producer:shadow-shadow_readiness"}
    ),
    EvidenceKind.CONFORMANCE_DOSSIER: frozenset(
        {
            "producer:only-conformance",
            "producer:shadow-conformance_dossier",
        }
    ),
    EvidenceKind.LOCKED_CONFIRMATION: frozenset(
        {"producer:shadow-locked_confirmation"}
    ),
    EvidenceKind.SHADOW_TRIAL: frozenset({"producer:paper-integration"}),
    EvidenceKind.PAPER_TRIAL: frozenset({"producer:canary-paper_trial"}),
    EvidenceKind.RISK_READINESS: frozenset(
        {"producer:canary-risk_readiness", "producer:active-risk_readiness"}
    ),
    EvidenceKind.OPERATIONS_READINESS: frozenset(
        {
            "producer:canary-operations_readiness",
            "producer:active-operations_readiness",
        }
    ),
    EvidenceKind.CANARY_TRIAL: frozenset({"producer:active-canary_trial"}),
}


def trusted_registry(journal: OperationalJournal) -> StageDossierRegistry:
    return StageDossierRegistry(
        journal,
        trusted_issuer_ids=TRUSTED_ISSUERS,
        trusted_producers_by_kind=TRUSTED_PRODUCERS_BY_KIND,
    )


def supporting_event(
    journal: OperationalJournal,
    name: str,
    *,
    kind: EvidenceKind = EvidenceKind.EXAMINATION_DOSSIER,
    producer_id: str | None = None,
    outcome: DossierOutcome = DossierOutcome.PASSED,
    lineage_id: str = LINEAGE,
    plan_version_id: str = PLAN,
    event_type: str = "StageEvidenceProduced",
):
    producer = producer_id or f"producer:{name}"
    envelope = StageEvidenceEnvelope(
        lineage_id=lineage_id,
        plan_version_id=plan_version_id,
        evidence_kind=kind,
        producer_id=producer,
        outcome=outcome,
        artifact_content_id=(
            "sha256:" + hashlib.sha256(name.encode("utf-8")).hexdigest()
        ),
    )
    return journal.append(
        EventAppend(
            stream_id=f"support:{name}",
            event_type=event_type,
            payload=envelope.to_payload(),
            idempotency_key=f"support-{name}",
            expected_version=0,
            occurred_at=NOW,
        )
    )


def issue_dossier(
    registry: StageDossierRegistry,
    journal: OperationalJournal,
    kind: EvidenceKind,
    name: str,
    *,
    lineage_id: str = LINEAGE,
    plan_version_id: str = PLAN,
    outcome: DossierOutcome = DossierOutcome.PASSED,
):
    producer_id = f"producer:{name}"
    support = supporting_event(
        journal,
        name,
        kind=kind,
        producer_id=producer_id,
        outcome=outcome,
        lineage_id=lineage_id,
        plan_version_id=plan_version_id,
    )
    return registry.issue(
        StageDossierIssue(
            lineage_id=lineage_id,
            plan_version_id=plan_version_id,
            evidence_kind=kind,
            supporting_event_ids=(support.event_id,),
            issuer_id="governance-service-1",
            producer_id=producer_id,
            issued_at=NOW,
            outcome=outcome,
        )
    )


def transition_request(
    target: LifecycleStage,
    revision: int,
    refs: tuple[EvidenceRef, ...],
    authority: Authority,
) -> TransitionRequest:
    return TransitionRequest(
        lineage_id=LINEAGE,
        plan_version_id=PLAN,
        target_stage=target,
        evidence_refs=refs,
        authority=authority,
        expected_revision=revision,
        command_id=f"transition-{target.value}",
        occurred_at=NOW,
    )


def test_stage_dossier_is_content_addressed_durable_and_idempotent(tmp_path):
    journal = OperationalJournal(tmp_path / "sensei.sqlite3")
    registry = trusted_registry(journal)
    support = supporting_event(
        journal,
        "examined",
        kind=EvidenceKind.EXAMINATION_DOSSIER,
        producer_id="research-examiner-1",
    )
    issue = StageDossierIssue(
        lineage_id=LINEAGE,
        plan_version_id=PLAN,
        evidence_kind=EvidenceKind.EXAMINATION_DOSSIER,
        supporting_event_ids=(support.event_id,),
        issuer_id="governance-service-1",
        producer_id="research-examiner-1",
        issued_at=NOW,
        outcome=DossierOutcome.PASSED,
    )

    first = registry.issue(issue)
    repeated = trusted_registry(journal).issue(issue)

    assert first == repeated
    assert first.dossier_id.startswith("dossier:")
    assert first.evidence_ref == EvidenceRef(
        EvidenceKind.EXAMINATION_DOSSIER, first.dossier_id
    )
    assert first.supporting_event_ids == (support.event_id,)
    assert journal.verify().ok is True

    with pytest.raises(MissingSupportingEvent, match="not found"):
        registry.issue(
            replace(
                issue,
                supporting_event_ids=("event:" + "0" * 64,),
            )
        )

    with pytest.raises(ValueError, match="independent"):
        StageDossierIssue(
            lineage_id=LINEAGE,
            plan_version_id=PLAN,
            evidence_kind=EvidenceKind.EXAMINATION_DOSSIER,
            supporting_event_ids=(support.event_id,),
            issuer_id="same-actor",
            producer_id="same-actor",
            issued_at=NOW,
            outcome=DossierOutcome.PASSED,
        )


def test_dossier_authorities_are_explicitly_trusted_and_role_stable(tmp_path):
    journal = OperationalJournal(tmp_path / "sensei.sqlite3")
    registry = trusted_registry(journal)
    support = supporting_event(
        journal,
        "authority-contract",
        producer_id="research-examiner-1",
    )
    base = StageDossierIssue(
        lineage_id=LINEAGE,
        plan_version_id=PLAN,
        evidence_kind=EvidenceKind.EXAMINATION_DOSSIER,
        supporting_event_ids=(support.event_id,),
        issuer_id="governance-service-1",
        producer_id="research-examiner-1",
        issued_at=NOW,
        outcome=DossierOutcome.PASSED,
    )

    with pytest.raises(DossierError, match="untrusted dossier issuer"):
        registry.issue(replace(base, issuer_id="invented-issuer"))
    with pytest.raises(DossierError, match="untrusted producer"):
        registry.issue(replace(base, producer_id="invented-producer"))
    with pytest.raises(DossierError, match="untrusted dossier issuer"):
        registry.issue(
            replace(
                base,
                issuer_id="research-examiner-1",
                producer_id="examiner-contract-1",
            )
        )
    with pytest.raises(ValueError, match="disjoint"):
        StageDossierRegistry(
            journal,
            trusted_issuer_ids=TRUSTED_ISSUERS,
            trusted_producers_by_kind={
                EvidenceKind.EXAMINATION_DOSSIER: TRUSTED_ISSUERS
            },
        )


@pytest.mark.parametrize(
    "mismatch",
    ("event_type", "lineage", "plan", "kind", "producer", "outcome"),
)
def test_dossier_rejects_support_that_does_not_match_its_typed_contract(
    tmp_path, mismatch
):
    journal = OperationalJournal(tmp_path / "sensei.sqlite3")
    registry = trusted_registry(journal)
    expected_producer = "examiner-contract-1"
    support = supporting_event(
        journal,
        f"mismatch-{mismatch}",
        event_type=(
            "UntypedArtifactRecorded"
            if mismatch == "event_type"
            else "StageEvidenceProduced"
        ),
        lineage_id="other-lineage" if mismatch == "lineage" else LINEAGE,
        plan_version_id="plan:other" if mismatch == "plan" else PLAN,
        kind=(
            EvidenceKind.SHADOW_TRIAL
            if mismatch == "kind"
            else EvidenceKind.EXAMINATION_DOSSIER
        ),
        producer_id=(
            "other-producer" if mismatch == "producer" else expected_producer
        ),
        outcome=(
            DossierOutcome.FAILED
            if mismatch == "outcome"
            else DossierOutcome.PASSED
        ),
    )
    issue = StageDossierIssue(
        lineage_id=LINEAGE,
        plan_version_id=PLAN,
        evidence_kind=EvidenceKind.EXAMINATION_DOSSIER,
        supporting_event_ids=(support.event_id,),
        issuer_id="governance-service-1",
        producer_id=expected_producer,
        issued_at=NOW,
        outcome=DossierOutcome.PASSED,
    )

    with pytest.raises(DossierIntegrityError, match="support"):
        registry.issue(issue)


def test_verifier_rejects_wrong_plan_kind_missing_failed_and_tampered_refs(tmp_path):
    journal = OperationalJournal(tmp_path / "sensei.sqlite3")
    registry = trusted_registry(journal)
    passed = issue_dossier(
        registry, journal, EvidenceKind.EXAMINATION_DOSSIER, "passed-exam"
    )
    request = transition_request(
        LifecycleStage.EXAMINED,
        1,
        (passed.evidence_ref,),
        GOVERNOR,
    )

    assert registry.verify_transition(request) is True
    assert (
        registry.verify_transition(replace(request, plan_version_id="plan:other"))
        is False
    )
    assert (
        registry.verify_transition(replace(request, lineage_id="other-lineage"))
        is False
    )
    assert registry.verify_transition(
        replace(
            request,
            evidence_refs=(
                EvidenceRef(EvidenceKind.SHADOW_READINESS, passed.dossier_id),
            ),
        )
    ) is False
    assert registry.verify_transition(
        replace(
            request,
            evidence_refs=(
                EvidenceRef(EvidenceKind.EXAMINATION_DOSSIER, "dossier:" + "0" * 64),
            ),
        )
    ) is False

    failed = issue_dossier(
        registry,
        journal,
        EvidenceKind.EXAMINATION_DOSSIER,
        "failed-exam",
        outcome=DossierOutcome.FAILED,
    )
    assert registry.verify_transition(
        replace(request, evidence_refs=(failed.evidence_ref,))
    ) is False

    support = supporting_event(
        journal,
        "forged-support",
        kind=EvidenceKind.EXAMINATION_DOSSIER,
        producer_id="forged-producer",
    )
    forged_id = "dossier:" + "f" * 64
    journal.append(
        EventAppend(
            stream_id="stage-dossier:forged",
            event_type="StageDossierIssued",
            payload={
                "dossier_id": forged_id,
                "lineage_id": LINEAGE,
                "plan_version_id": PLAN,
                "evidence_kind": EvidenceKind.EXAMINATION_DOSSIER.value,
                "supporting_event_ids": [support.event_id],
                "issuer_id": "forged-issuer",
                "producer_id": "forged-producer",
                "issued_at": NOW.isoformat(),
                "outcome": DossierOutcome.PASSED.value,
            },
            idempotency_key="forged-dossier-event",
            expected_version=0,
            occurred_at=NOW,
        )
    )
    assert registry.verify_transition(
        replace(
            request,
            evidence_refs=(
                EvidenceRef(EvidenceKind.EXAMINATION_DOSSIER, forged_id),
            ),
        )
    ) is False

    conformance = issue_dossier(
        registry,
        journal,
        EvidenceKind.CONFORMANCE_DOSSIER,
        "only-conformance",
    )
    incomplete_shadow = transition_request(
        LifecycleStage.SHADOW,
        2,
        (conformance.evidence_ref,),
        GOVERNOR,
    )
    assert registry.verify_transition(incomplete_shadow) is False


def test_transition_authority_cannot_be_the_dossier_producer(tmp_path):
    journal = OperationalJournal(tmp_path / "sensei.sqlite3")
    registry = trusted_registry(journal)
    support = supporting_event(
        journal,
        "governor-produced",
        kind=EvidenceKind.EXAMINATION_DOSSIER,
        producer_id=GOVERNOR.actor_id,
    )
    dossier = registry.issue(
        StageDossierIssue(
            lineage_id=LINEAGE,
            plan_version_id=PLAN,
            evidence_kind=EvidenceKind.EXAMINATION_DOSSIER,
            supporting_event_ids=(support.event_id,),
            issuer_id="governance-service-1",
            producer_id=GOVERNOR.actor_id,
            issued_at=NOW,
            outcome=DossierOutcome.PASSED,
        )
    )

    assert registry.verify_transition(
        transition_request(
            LifecycleStage.EXAMINED,
            1,
            (dossier.evidence_ref,),
            GOVERNOR,
        )
    ) is False


def test_lifecycle_reaches_paper_and_capital_stages_through_durable_dossiers(
    tmp_path,
):
    journal = OperationalJournal(tmp_path / "sensei.sqlite3")
    registry = trusted_registry(journal)
    lifecycle = StrategyLifecycle(
        journal,
        evidence_verifier=registry.verify_transition,
        trusted_actor_roles=TRUSTED_ACTOR_ROLES,
    )
    proposed = lifecycle.transition(
        transition_request(LifecycleStage.PROPOSED, 0, (), PROPOSER)
    )

    examined_ref = issue_dossier(
        registry, journal, EvidenceKind.EXAMINATION_DOSSIER, "examined-integration"
    ).evidence_ref
    examined = lifecycle.transition(
        transition_request(
            LifecycleStage.EXAMINED,
            proposed.lineage_revision,
            (examined_ref,),
            GOVERNOR,
        )
    )

    shadow_refs = tuple(
        issue_dossier(registry, journal, kind, f"shadow-{kind.value}").evidence_ref
        for kind in (
            EvidenceKind.SHADOW_READINESS,
            EvidenceKind.CONFORMANCE_DOSSIER,
            EvidenceKind.LOCKED_CONFIRMATION,
        )
    )
    shadow = lifecycle.transition(
        transition_request(
            LifecycleStage.SHADOW,
            examined.lineage_revision,
            shadow_refs,
            GOVERNOR,
        )
    )

    paper_ref = issue_dossier(
        registry, journal, EvidenceKind.SHADOW_TRIAL, "paper-integration"
    ).evidence_ref
    paper = lifecycle.transition(
        transition_request(
            LifecycleStage.PAPER,
            shadow.lineage_revision,
            (paper_ref,),
            GOVERNOR,
        )
    )
    assert paper.stage is LifecycleStage.PAPER

    canary_refs = tuple(
        issue_dossier(registry, journal, kind, f"canary-{kind.value}").evidence_ref
        for kind in (
            EvidenceKind.PAPER_TRIAL,
            EvidenceKind.RISK_READINESS,
            EvidenceKind.OPERATIONS_READINESS,
        )
    )
    canary = lifecycle.transition(
        transition_request(
            LifecycleStage.CANARY,
            paper.lineage_revision,
            canary_refs,
            OWNER,
        )
    )

    active_refs = tuple(
        issue_dossier(registry, journal, kind, f"active-{kind.value}").evidence_ref
        for kind in (
            EvidenceKind.CANARY_TRIAL,
            EvidenceKind.RISK_READINESS,
            EvidenceKind.OPERATIONS_READINESS,
        )
    )
    active = lifecycle.transition(
        transition_request(
            LifecycleStage.ACTIVE,
            canary.lineage_revision,
            active_refs,
            OWNER,
        )
    )

    assert active.stage is LifecycleStage.ACTIVE
    assert journal.verify().ok is True


def test_dossier_issuance_fails_when_journal_integrity_is_broken(tmp_path):
    path = tmp_path / "sensei.sqlite3"
    journal = OperationalJournal(path)
    support = supporting_event(
        journal,
        "will-be-tampered",
        kind=EvidenceKind.EXAMINATION_DOSSIER,
        producer_id="examiner-1",
    )
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER journal_events_no_update")
        connection.execute(
            "UPDATE journal_events SET payload_json = ? WHERE event_id = ?",
            ('{"artifact":"tampered"}', support.event_id),
        )

    registry = trusted_registry(journal)
    with pytest.raises(DossierIntegrityError, match="integrity"):
        registry.issue(
            StageDossierIssue(
                lineage_id=LINEAGE,
                plan_version_id=PLAN,
                evidence_kind=EvidenceKind.EXAMINATION_DOSSIER,
                supporting_event_ids=(support.event_id,),
                issuer_id="governance-service-1",
                producer_id="examiner-1",
                issued_at=NOW,
                outcome=DossierOutcome.PASSED,
            )
        )
