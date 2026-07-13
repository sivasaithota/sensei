from datetime import datetime, timezone

import pytest

from sensei.governance.lifecycle import (
    Authority,
    AuthorityRole,
    EvidenceKind,
    EvidenceRef,
    InvalidLifecycleTransition,
    LifecycleStage,
    OwnerAuthorityRequired,
    ReadinessEvidenceMissing,
    StrategyAlreadyActive,
    StrategyLifecycle,
    TerminalLifecycleState,
    TransitionRequest,
    UnauthorizedTransition,
    UntrustedReadinessEvidence,
)
from sensei.operations.journal import JournalConflict, OperationalJournal


NOW = datetime(2026, 7, 13, 11, 0, tzinfo=timezone.utc)
PROPOSER = Authority(actor_id="research-agent-7", role=AuthorityRole.PROPOSER)
GOVERNOR = Authority(actor_id="research-governor-1", role=AuthorityRole.GOVERNOR)
OWNER = Authority(
    actor_id="human-owner-1",
    role=AuthorityRole.OWNER,
    approval_ref="approval:owner-console-100",
)
SAFETY = Authority(actor_id="risk-daemon-1", role=AuthorityRole.SAFETY)
TRUSTED_ACTOR_ROLES = {
    PROPOSER.actor_id: frozenset({AuthorityRole.PROPOSER}),
    GOVERNOR.actor_id: frozenset({AuthorityRole.GOVERNOR}),
    OWNER.actor_id: frozenset({AuthorityRole.OWNER}),
    SAFETY.actor_id: frozenset({AuthorityRole.SAFETY}),
}


def evidence(kind: EvidenceKind, suffix: str) -> EvidenceRef:
    return EvidenceRef(kind=kind, ref_id=f"evidence:{suffix}")


def shadow_readiness_evidence() -> tuple[EvidenceRef, ...]:
    return (
        evidence(EvidenceKind.SHADOW_READINESS, "shadow-ready"),
        evidence(EvidenceKind.CONFORMANCE_DOSSIER, "plan-conformance"),
        evidence(EvidenceKind.LOCKED_CONFIRMATION, "locked-confirmation"),
    )


def request(
    target: LifecycleStage,
    *,
    revision: int,
    command: str,
    authority: Authority,
    evidence_refs: tuple[EvidenceRef, ...] = (),
    plan_version_id: str = "plan:hammer:v1",
    lineage_id: str = "hammer-follow-through",
) -> TransitionRequest:
    return TransitionRequest(
        lineage_id=lineage_id,
        plan_version_id=plan_version_id,
        target_stage=target,
        evidence_refs=evidence_refs,
        authority=authority,
        expected_revision=revision,
        command_id=command,
        occurred_at=NOW,
    )


def progress_to_canary(
    lifecycle: StrategyLifecycle,
    *,
    start_revision: int = 0,
    plan_version_id: str = "plan:hammer:v1",
) -> int:
    stages = (
        (LifecycleStage.PROPOSED, PROPOSER, ()),
        (
            LifecycleStage.EXAMINED,
            GOVERNOR,
            (evidence(EvidenceKind.EXAMINATION_DOSSIER, "examined"),),
        ),
        (
            LifecycleStage.SHADOW,
            GOVERNOR,
            shadow_readiness_evidence(),
        ),
        (
            LifecycleStage.PAPER,
            GOVERNOR,
            (evidence(EvidenceKind.SHADOW_TRIAL, "shadow-trial"),),
        ),
        (
            LifecycleStage.CANARY,
            OWNER,
            (
                evidence(EvidenceKind.PAPER_TRIAL, "paper-trial"),
                evidence(EvidenceKind.RISK_READINESS, "risk-ready"),
                evidence(EvidenceKind.OPERATIONS_READINESS, "ops-ready"),
            ),
        ),
    )
    revision = start_revision
    for target, authority, refs in stages:
        revision += 1
        record = lifecycle.transition(
            request(
                target,
                revision=revision - 1,
                command=f"{plan_version_id}-{target.value}",
                authority=authority,
                evidence_refs=refs,
                plan_version_id=plan_version_id,
            )
        )
        assert record.lineage_revision == revision
    return revision


def active_evidence() -> tuple[EvidenceRef, ...]:
    return (
        evidence(EvidenceKind.CANARY_TRIAL, "canary-trial"),
        evidence(EvidenceKind.RISK_READINESS, "risk-ready-active"),
        evidence(EvidenceKind.OPERATIONS_READINESS, "ops-ready-active"),
    )


def test_lifecycle_requires_every_stage_owner_authority_and_readiness(tmp_path):
    path = tmp_path / "sensei.sqlite3"
    lifecycle = StrategyLifecycle(
        OperationalJournal(path),
        evidence_verifier=lambda _request: True,
        trusted_actor_roles=TRUSTED_ACTOR_ROLES,
    )
    revision = 0

    for target, authority, refs in (
        (LifecycleStage.PROPOSED, PROPOSER, ()),
        (
            LifecycleStage.EXAMINED,
            GOVERNOR,
            (evidence(EvidenceKind.EXAMINATION_DOSSIER, "examined"),),
        ),
        (
            LifecycleStage.SHADOW,
            GOVERNOR,
            shadow_readiness_evidence(),
        ),
        (
            LifecycleStage.PAPER,
            GOVERNOR,
            (evidence(EvidenceKind.SHADOW_TRIAL, "shadow-trial"),),
        ),
    ):
        record = lifecycle.transition(
            request(
                target,
                revision=revision,
                command=f"transition-{target.value}",
                authority=authority,
                evidence_refs=refs,
            )
        )
        revision = record.lineage_revision

    canary_readiness = (
        evidence(EvidenceKind.PAPER_TRIAL, "paper-trial"),
        evidence(EvidenceKind.RISK_READINESS, "risk-ready"),
        evidence(EvidenceKind.OPERATIONS_READINESS, "ops-ready"),
    )
    with pytest.raises(OwnerAuthorityRequired, match="owner"):
        lifecycle.transition(
            request(
                LifecycleStage.CANARY,
                revision=revision,
                command="agent-cannot-authorize-capital",
                authority=GOVERNOR,
                evidence_refs=canary_readiness,
            )
        )
    with pytest.raises(ReadinessEvidenceMissing, match="operations_readiness"):
        lifecycle.transition(
            request(
                LifecycleStage.CANARY,
                revision=revision,
                command="owner-missing-readiness",
                authority=OWNER,
                evidence_refs=canary_readiness[:-1],
            )
        )

    canary = lifecycle.transition(
        request(
            LifecycleStage.CANARY,
            revision=revision,
            command="owner-authorizes-canary",
            authority=OWNER,
            evidence_refs=canary_readiness,
        )
    )
    active = lifecycle.transition(
        request(
            LifecycleStage.ACTIVE,
            revision=canary.lineage_revision,
            command="owner-authorizes-active",
            authority=OWNER,
            evidence_refs=active_evidence(),
        )
    )

    assert active.previous_stage is LifecycleStage.CANARY
    assert active.stage is LifecycleStage.ACTIVE
    assert active.evidence_refs == active_evidence()
    rebuilt = StrategyLifecycle(OperationalJournal(path)).view(
        "hammer-follow-through"
    )
    assert rebuilt.active_plan_version_id == "plan:hammer:v1"
    assert rebuilt.stage_for("plan:hammer:v1") is LifecycleStage.ACTIVE
    assert rebuilt.revision == 6


def test_lifecycle_rejects_skips_and_stale_expected_revisions(tmp_path):
    lifecycle = StrategyLifecycle(
        OperationalJournal(tmp_path / "sensei.sqlite3"),
        evidence_verifier=lambda _request: True,
        trusted_actor_roles=TRUSTED_ACTOR_ROLES,
    )
    lifecycle.transition(
        request(
            LifecycleStage.PROPOSED,
            revision=0,
            command="propose",
            authority=PROPOSER,
        )
    )

    with pytest.raises(InvalidLifecycleTransition, match="proposed.*paper"):
        lifecycle.transition(
            request(
                LifecycleStage.PAPER,
                revision=1,
                command="skip-examination",
                authority=GOVERNOR,
                evidence_refs=(evidence(EvidenceKind.SHADOW_TRIAL, "unearned"),),
            )
        )

    with pytest.raises(JournalConflict, match="expected 0"):
        lifecycle.transition(
            request(
                LifecycleStage.EXAMINED,
                revision=0,
                command="stale-examined",
                authority=GOVERNOR,
                evidence_refs=(
                    evidence(EvidenceKind.EXAMINATION_DOSSIER, "dossier"),
                ),
            )
        )


def test_lineage_allows_only_one_active_version_and_rollback_is_terminal(tmp_path):
    lifecycle = StrategyLifecycle(
        OperationalJournal(tmp_path / "sensei.sqlite3"),
        evidence_verifier=lambda _request: True,
        trusted_actor_roles=TRUSTED_ACTOR_ROLES,
    )
    revision = progress_to_canary(lifecycle)
    v1_active = lifecycle.transition(
        request(
            LifecycleStage.ACTIVE,
            revision=revision,
            command="activate-v1",
            authority=OWNER,
            evidence_refs=active_evidence(),
        )
    )
    revision = progress_to_canary(
        lifecycle,
        start_revision=v1_active.lineage_revision,
        plan_version_id="plan:hammer:v2",
    )

    with pytest.raises(StrategyAlreadyActive, match="plan:hammer:v1"):
        lifecycle.transition(
            request(
                LifecycleStage.ACTIVE,
                revision=revision,
                command="activate-v2-too-early",
                authority=OWNER,
                evidence_refs=active_evidence(),
                plan_version_id="plan:hammer:v2",
            )
        )

    rolled_back = lifecycle.transition(
        request(
            LifecycleStage.ROLLED_BACK,
            revision=revision,
            command="risk-rolls-back-v1",
            authority=SAFETY,
            evidence_refs=(
                evidence(EvidenceKind.ROLLBACK_DECISION, "incident-55"),
            ),
        )
    )
    assert rolled_back.stage is LifecycleStage.ROLLED_BACK

    activated_v2 = lifecycle.transition(
        request(
            LifecycleStage.ACTIVE,
            revision=rolled_back.lineage_revision,
            command="activate-v2-after-rollback",
            authority=OWNER,
            evidence_refs=active_evidence(),
            plan_version_id="plan:hammer:v2",
        )
    )
    assert activated_v2.stage is LifecycleStage.ACTIVE

    with pytest.raises(TerminalLifecycleState, match="rolled_back"):
        lifecycle.transition(
            request(
                LifecycleStage.ACTIVE,
                revision=activated_v2.lineage_revision,
                command="cannot-revive-v1",
                authority=OWNER,
                evidence_refs=active_evidence(),
            )
        )


def test_quarantine_fails_closed_and_cannot_be_reopened(tmp_path):
    lifecycle = StrategyLifecycle(
        OperationalJournal(tmp_path / "sensei.sqlite3"),
        evidence_verifier=lambda _request: True,
        trusted_actor_roles=TRUSTED_ACTOR_ROLES,
    )
    lifecycle.transition(
        request(
            LifecycleStage.PROPOSED,
            revision=0,
            command="propose-for-quarantine",
            authority=PROPOSER,
        )
    )
    quarantined = lifecycle.transition(
        request(
            LifecycleStage.QUARANTINED,
            revision=1,
            command="quarantine-on-data-lineage-failure",
            authority=SAFETY,
            evidence_refs=(
                evidence(EvidenceKind.SAFETY_EVENT, "lineage-failure"),
            ),
        )
    )

    assert quarantined.stage is LifecycleStage.QUARANTINED
    with pytest.raises(TerminalLifecycleState, match="quarantined"):
        lifecycle.transition(
            request(
                LifecycleStage.EXAMINED,
                revision=2,
                command="cannot-reopen-quarantined",
                authority=GOVERNOR,
                evidence_refs=(
                    evidence(EvidenceKind.EXAMINATION_DOSSIER, "later-dossier"),
                ),
            )
        )


def test_shadow_requires_conformance_and_locked_confirmation_dossiers(tmp_path):
    lifecycle = StrategyLifecycle(
        OperationalJournal(tmp_path / "sensei.sqlite3"),
        evidence_verifier=lambda _request: True,
        trusted_actor_roles=TRUSTED_ACTOR_ROLES,
    )
    lifecycle.transition(
        request(
            LifecycleStage.PROPOSED,
            revision=0,
            command="propose-before-shadow-gate",
            authority=PROPOSER,
        )
    )
    lifecycle.transition(
        request(
            LifecycleStage.EXAMINED,
            revision=1,
            command="examine-before-shadow-gate",
            authority=GOVERNOR,
            evidence_refs=(
                evidence(EvidenceKind.EXAMINATION_DOSSIER, "examined-shadow-gate"),
            ),
        )
    )

    with pytest.raises(
        ReadinessEvidenceMissing,
        match="conformance_dossier.*locked_confirmation",
    ):
        lifecycle.transition(
            request(
                LifecycleStage.SHADOW,
                revision=2,
                command="shadow-without-conformance",
                authority=GOVERNOR,
                evidence_refs=(
                    evidence(EvidenceKind.SHADOW_READINESS, "only-readiness"),
                ),
            )
        )


@pytest.mark.parametrize(
    "verifier",
    (None, lambda _request: False),
    ids=("missing-verifier", "untrusted-evidence"),
)
def test_evidence_bearing_stages_fail_closed_without_verified_dossiers(
    tmp_path, verifier
):
    lifecycle = StrategyLifecycle(
        OperationalJournal(tmp_path / "sensei.sqlite3"),
        evidence_verifier=verifier,
        trusted_actor_roles=TRUSTED_ACTOR_ROLES,
    )
    proposed = lifecycle.transition(
        request(
            LifecycleStage.PROPOSED,
            revision=0,
            command="default-fail-proposed",
            authority=PROPOSER,
        )
    )
    assert proposed.stage is LifecycleStage.PROPOSED

    with pytest.raises(UntrustedReadinessEvidence, match="verified"):
        lifecycle.transition(
            request(
                LifecycleStage.EXAMINED,
                revision=proposed.lineage_revision,
                command="cannot-trust-typed-examination-ref",
                authority=GOVERNOR,
                evidence_refs=(
                    evidence(
                        EvidenceKind.EXAMINATION_DOSSIER,
                        "caller-typed-default-fail",
                    ),
                ),
            )
        )


def test_authority_roles_are_resolved_from_trusted_configuration(tmp_path):
    journal = OperationalJournal(tmp_path / "sensei.sqlite3")
    unconfigured = StrategyLifecycle(journal)
    with pytest.raises(UnauthorizedTransition, match="trusted"):
        unconfigured.transition(
            request(
                LifecycleStage.PROPOSED,
                revision=0,
                command="untrusted-proposer",
                authority=PROPOSER,
            )
        )

    configured = StrategyLifecycle(
        journal,
        trusted_actor_roles=TRUSTED_ACTOR_ROLES,
    )
    relabeled = Authority(PROPOSER.actor_id, AuthorityRole.GOVERNOR)
    with pytest.raises(UnauthorizedTransition, match="role"):
        configured.transition(
            request(
                LifecycleStage.PROPOSED,
                revision=0,
                command="caller-relabeled-role",
                authority=relabeled,
            )
        )


def test_plan_proposer_cannot_promote_the_same_plan(tmp_path):
    self_promoter = Authority(PROPOSER.actor_id, AuthorityRole.GOVERNOR)
    lifecycle = StrategyLifecycle(
        OperationalJournal(tmp_path / "sensei.sqlite3"),
        evidence_verifier=lambda _request: True,
        trusted_actor_roles={
            PROPOSER.actor_id: frozenset(
                {AuthorityRole.PROPOSER, AuthorityRole.GOVERNOR}
            )
        },
    )
    proposed = lifecycle.transition(
        request(
            LifecycleStage.PROPOSED,
            revision=0,
            command="self-proposed",
            authority=PROPOSER,
        )
    )

    with pytest.raises(UnauthorizedTransition, match="proposer"):
        lifecycle.transition(
            request(
                LifecycleStage.EXAMINED,
                revision=proposed.lineage_revision,
                command="self-promoted",
                authority=self_promoter,
                evidence_refs=(
                    evidence(EvidenceKind.EXAMINATION_DOSSIER, "self-promotion"),
                ),
            )
        )
