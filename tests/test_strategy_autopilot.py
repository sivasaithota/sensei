import hashlib
from datetime import datetime, timezone

from sensei.automation.autopilot import (
    ExistingDossierEvidenceProvider,
    StrategyAutopilot,
    StrategyAutomationState,
)
from sensei.governance.evidence import (
    DossierOutcome,
    StageDossierIssue,
    StageDossierRegistry,
    StageEvidenceEnvelope,
)
from sensei.governance.lifecycle import (
    Authority,
    AuthorityRole,
    EvidenceKind,
    LifecycleStage,
    StrategyLifecycle,
    required_evidence_for,
)
from sensei.operations import EventAppend, OperationalJournal
from sensei.strategy import StrategyPlanCatalog
from tests.test_strategy_plan import hammer_follow_through_plan


NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
LINEAGE = "hammer-follow-through"
PROPOSER = Authority("strategy-proposer", AuthorityRole.PROPOSER)
GOVERNOR = Authority("strategy-governor", AuthorityRole.GOVERNOR)
ISSUER = "governance-dossier-service"


def _system(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    plan = hammer_follow_through_plan()
    catalog = StrategyPlanCatalog(journal)
    catalog.register(
        lineage_id=LINEAGE,
        plan=plan,
        source_rule_name="hammer_follow_through",
        occurred_at=NOW,
        command_id="register-plan",
    )
    producers = {
        kind: frozenset({f"producer:{kind.value}"}) for kind in EvidenceKind
    }
    dossiers = StageDossierRegistry(
        journal,
        trusted_issuer_ids=frozenset({ISSUER}),
        trusted_producers_by_kind=producers,
    )
    lifecycle = StrategyLifecycle(
        journal,
        evidence_verifier=dossiers.verify_transition,
        trusted_actor_roles={
            PROPOSER.actor_id: frozenset({AuthorityRole.PROPOSER}),
            GOVERNOR.actor_id: frozenset({AuthorityRole.GOVERNOR}),
        },
    )
    autopilot = StrategyAutopilot(
        catalog=catalog,
        lifecycle=lifecycle,
        evidence_provider=ExistingDossierEvidenceProvider(journal, dossiers),
        proposer=PROPOSER,
        governor=GOVERNOR,
    )
    return journal, plan, dossiers, lifecycle, autopilot


def _issue_stage_evidence(journal, dossiers, plan, target):
    refs = []
    for kind in sorted(required_evidence_for(target), key=lambda item: item.value):
        producer = f"producer:{kind.value}"
        digest = hashlib.sha256(
            f"{plan.plan_id}:{kind.value}".encode("utf-8")
        ).hexdigest()
        envelope = StageEvidenceEnvelope(
            lineage_id=LINEAGE,
            plan_version_id=plan.plan_id,
            evidence_kind=kind,
            producer_id=producer,
            outcome=DossierOutcome.PASSED,
            artifact_content_id=f"sha256:{digest}",
        )
        support = journal.append(
            EventAppend(
                stream_id=f"autopilot-support:{digest}",
                event_type="StageEvidenceProduced",
                payload=envelope.to_payload(),
                idempotency_key=f"autopilot-support:{digest}",
                expected_version=0,
                occurred_at=NOW,
            )
        )
        refs.append(
            dossiers.issue(
                StageDossierIssue(
                    lineage_id=LINEAGE,
                    plan_version_id=plan.plan_id,
                    evidence_kind=kind,
                    supporting_event_ids=(support.event_id,),
                    issuer_id=ISSUER,
                    producer_id=producer,
                    issued_at=NOW,
                    outcome=DossierOutcome.PASSED,
                )
            ).evidence_ref
        )
    return tuple(refs)


def test_autopilot_proposes_then_waits_for_real_examination_evidence(tmp_path):
    _, plan, _, lifecycle, autopilot = _system(tmp_path)

    report = autopilot.reconcile(now=NOW, command_id="poll-1")

    assert report.results[0].state is StrategyAutomationState.WAITING_EVIDENCE
    assert report.results[0].stage is LifecycleStage.PROPOSED
    assert report.results[0].reason_codes == (
        "EXAMINATION_DOSSIER_MISSING",
    )
    assert lifecycle.view(LINEAGE).stage_for(plan.plan_id) is LifecycleStage.PROPOSED


def test_autopilot_advances_to_paper_but_never_canary_without_owner(tmp_path):
    journal, plan, dossiers, lifecycle, autopilot = _system(tmp_path)
    first = autopilot.reconcile(now=NOW, command_id="poll-propose")
    assert first.results[0].stage is LifecycleStage.PROPOSED

    _issue_stage_evidence(journal, dossiers, plan, LifecycleStage.EXAMINED)
    examined = autopilot.reconcile(now=NOW, command_id="poll-examined")
    assert examined.results[0].stage is LifecycleStage.EXAMINED

    _issue_stage_evidence(journal, dossiers, plan, LifecycleStage.SHADOW)
    shadow = autopilot.reconcile(now=NOW, command_id="poll-shadow")
    assert shadow.results[0].stage is LifecycleStage.SHADOW

    _issue_stage_evidence(journal, dossiers, plan, LifecycleStage.PAPER)
    paper = autopilot.reconcile(now=NOW, command_id="poll-paper")
    replay = autopilot.reconcile(now=NOW, command_id="poll-paper-replay")

    assert paper.results[0].state is StrategyAutomationState.PAPER_READY
    assert paper.results[0].stage is LifecycleStage.PAPER
    assert replay.results[0].state is StrategyAutomationState.PAPER_READY
    assert lifecycle.view(LINEAGE).stage_for(plan.plan_id) is LifecycleStage.PAPER
    assert journal.verify().ok is True


def test_autopilot_rejects_same_actor_as_proposer_and_governor(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    catalog = StrategyPlanCatalog(journal)
    dossiers = StageDossierRegistry(
        journal,
        trusted_issuer_ids=frozenset({ISSUER}),
        trusted_producers_by_kind={
            EvidenceKind.EXAMINATION_DOSSIER: frozenset(
                {"producer:examination_dossier"}
            )
        },
    )
    lifecycle = StrategyLifecycle(
        journal,
        evidence_verifier=dossiers.verify_transition,
        trusted_actor_roles={
            "same-machine": frozenset(
                {AuthorityRole.PROPOSER, AuthorityRole.GOVERNOR}
            )
        },
    )

    try:
        StrategyAutopilot(
            catalog=catalog,
            lifecycle=lifecycle,
            evidence_provider=ExistingDossierEvidenceProvider(journal, dossiers),
            proposer=Authority("same-machine", AuthorityRole.PROPOSER),
            governor=Authority("same-machine", AuthorityRole.GOVERNOR),
        )
    except ValueError as exc:
        assert "independent" in str(exc)
    else:
        raise AssertionError("autopilot accepted one actor in both authority roles")
