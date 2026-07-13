import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from sensei.agents.thesis import (
    ApprovalRecord,
    Direction,
    PlaybookCitation,
    TradeThesis,
    Verdict,
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
    TransitionRequest,
)
from sensei.kernel import (
    KernelAdmissionAuthority,
    RecordingPaperGateway,
    TradingKernel,
)
from sensei.learning.episodes import TradeEpisodeJournal
from sensei.operations.health import HealthAssessmentInput, OperationsMonitor
from sensei.operations import (
    ComponentState,
    EventAppend,
    HmacFactSigner,
    HmacFactVerifier,
    OperationalJournal,
    OperationsControlPlane,
)
from sensei.orchestration import CommitteeVerdictAuthority, TradeCommitteeGate
from sensei.orchestration.intents import ExecutableQuote, TradeIntentFactory
from sensei.orchestration.paper import (
    GovernedPaperCoordinator,
    PaperAdmissionRejected,
)
from sensei.portfolio_risk import (
    AccountSnapshot,
    PortfolioRisk,
    RiskLimits,
    SafetyControl,
)
from sensei.provenance import (
    ClaimProposal,
    PlainTextAdapter,
    ProvenanceCorpus,
    SourceCitation,
    SourceKind,
    SourceMetadata,
)
from sensei.strategy import (
    DecisionTraceAuthority,
    PlanEvaluationRequest,
    StrategyPlanEngine,
)
from tests.test_strategy_plan import hammer_bars, hammer_follow_through_plan


UTC = timezone.utc
SIGNAL_TIME = datetime(2025, 1, 9, 16, 0, tzinfo=UTC)
QUOTE_TIME = datetime(2025, 1, 10, 9, 15, tzinfo=UTC)
LINEAGE = "hammer-follow-through"
DECISION_SNAPSHOT = "snapshot:" + "a" * 64
HISTORIAN_SECRET = b"historian-fixture-secret-at-least-32-bytes"
ADMISSION_SECRET = b"paper-admission-fixture-secret-at-least-32b"
COMMITTEE_SECRETS = {
    "risk-officer": b"risk-officer-fixture-secret-at-least-32",
    "devils-advocate": b"devils-advocate-fixture-secret-at-least-32",
    "compliance": b"compliance-fixture-secret-at-least-32b",
    "orchestrator": b"orchestrator-fixture-secret-at-least-32b",
}
OPERATIONS_SECRETS = {
    component: f"{component}-paper-fixture-secret-at-least-32".encode()
    for component in ("market-data", "paper-gateway", "reconciliation")
}
MONITOR_SECRET = b"operations-monitor-paper-fixture-secret-32b"


def governed_system(tmp_path, *, stop_at: LifecycleStage = LifecycleStage.PAPER):
    journal = OperationalJournal(tmp_path / "sensei.sqlite3")
    provenance = ProvenanceCorpus(journal, tmp_path / "provenance")
    research_text = "A hammer followed by strength can define a bounded swing setup."
    research_path = tmp_path / "hammer-research.txt"
    research_path.write_text(research_text, encoding="utf-8")
    source = provenance.ingest(
        PlainTextAdapter().adapt(
            research_path,
            SourceMetadata(
                title="Hammer follow-through research fixture",
                canonical_uri="fixture://hammer-follow-through",
                source_kind=SourceKind.TEXT_DOCUMENT,
                edition="1",
                usage_rights="test fixture",
                retrieved_at=SIGNAL_TIME - timedelta(days=10),
            ),
        ),
        occurred_at=SIGNAL_TIME - timedelta(days=9),
        command_id="ingest-hammer-research",
    )
    segment = source.segments[0]
    claim = provenance.record_claim(
        ClaimProposal(
            statement="Hammer follow-through is a research hypothesis.",
            citations=(
                SourceCitation(
                    source_id=source.source_id,
                    segment_id=segment.segment_id,
                    locator_kind=segment.locator_kind,
                    start=0,
                    end=len(segment.text),
                    quote_sha256=(
                        "sha256:"
                        + hashlib.sha256(segment.text.encode("utf-8")).hexdigest()
                    ),
                ),
            ),
            producer_id="researcher-1",
            extraction_method_id="fixture-manual:v1",
        ),
        occurred_at=SIGNAL_TIME - timedelta(days=8),
        command_id="claim-hammer-research",
    )
    plan = hammer_follow_through_plan(source_claim_id=claim.claim_id)
    bars = hammer_bars()
    trace = StrategyPlanEngine().evaluate(
        PlanEvaluationRequest(
            plan=plan,
            instrument_id="NSE:TEST",
            bars=bars,
            evaluation_session=bars.index[-1].date(),
        )
    )
    trace_authority = DecisionTraceAuthority(
        journal,
        HmacFactVerifier({"historian-1": HISTORIAN_SECRET}),
    )
    trace_attestation = trace_authority.record(
        trace,
        market_snapshot_id=DECISION_SNAPSHOT,
        signer=HmacFactSigner("historian-1", HISTORIAN_SECRET),
        occurred_at=SIGNAL_TIME,
        command_id="attest-paper-trace",
    )
    dossiers = StageDossierRegistry(
        journal,
        trusted_issuer_ids=frozenset({"governance-service-1"}),
        trusted_producers_by_kind={
            kind: frozenset({f"fixture:{kind.value}"}) for kind in EvidenceKind
        },
    )
    lifecycle = StrategyLifecycle(
        journal,
        evidence_verifier=dossiers.verify_transition,
        trusted_actor_roles={
            "researcher-1": frozenset({AuthorityRole.PROPOSER}),
            "governor-1": frozenset({AuthorityRole.GOVERNOR}),
        },
    )
    governor = Authority("governor-1", AuthorityRole.GOVERNOR)
    proposer = Authority("researcher-1", AuthorityRole.PROPOSER)
    stages: tuple[tuple[LifecycleStage, Authority, tuple[EvidenceKind, ...]], ...] = (
        (LifecycleStage.PROPOSED, proposer, ()),
        (
            LifecycleStage.EXAMINED,
            governor,
            (EvidenceKind.EXAMINATION_DOSSIER,),
        ),
        (
            LifecycleStage.SHADOW,
            governor,
            (
                EvidenceKind.SHADOW_READINESS,
                EvidenceKind.CONFORMANCE_DOSSIER,
                EvidenceKind.LOCKED_CONFIRMATION,
            ),
        ),
        (
            LifecycleStage.PAPER,
            governor,
            (EvidenceKind.SHADOW_TRIAL,),
        ),
    )
    revision = 0
    for stage, authority, kinds in stages:
        transition_time = SIGNAL_TIME - timedelta(days=4 - revision)
        refs = []
        for kind in kinds:
            producer_id = f"fixture:{kind.value}"
            evidence = StageEvidenceEnvelope(
                lineage_id=LINEAGE,
                plan_version_id=plan.plan_id,
                evidence_kind=kind,
                producer_id=producer_id,
                outcome=DossierOutcome.PASSED,
                artifact_content_id=(
                    "sha256:"
                    + hashlib.sha256(
                        f"{plan.plan_id}:{kind.value}".encode("utf-8")
                    ).hexdigest()
                ),
            )
            support = journal.append(
                EventAppend(
                    stream_id=f"support:paper-fixture:{kind.value}",
                    event_type="StageEvidenceProduced",
                    payload=evidence.to_payload(),
                    idempotency_key=f"support-paper-fixture-{kind.value}",
                    expected_version=0,
                    occurred_at=transition_time - timedelta(minutes=2),
                )
            )
            refs.append(
                dossiers.issue(
                    StageDossierIssue(
                        lineage_id=LINEAGE,
                        plan_version_id=plan.plan_id,
                        evidence_kind=kind,
                        supporting_event_ids=(support.event_id,),
                        issuer_id="governance-service-1",
                        producer_id=producer_id,
                        issued_at=transition_time - timedelta(minutes=1),
                        outcome=DossierOutcome.PASSED,
                    )
                ).evidence_ref
            )
        lifecycle.transition(
            TransitionRequest(
                lineage_id=LINEAGE,
                plan_version_id=plan.plan_id,
                target_stage=stage,
                evidence_refs=tuple(refs),
                authority=authority,
                expected_revision=revision,
                command_id=f"lifecycle-{stage.value}",
                occurred_at=transition_time,
            )
        )
        revision += 1
        if stage is stop_at:
            break

    required_components = {
        component: timedelta(minutes=1) for component in OPERATIONS_SECRETS
    }
    control_plane = OperationsControlPlane(
        journal, HmacFactVerifier(OPERATIONS_SECRETS)
    )
    for component in required_components:
        control_plane.record_heartbeat(
            component=component,
            state=ComponentState.HEALTHY,
            occurred_at=QUOTE_TIME,
            command_id=f"paper-heartbeat-{component}",
            detail="paper fixture ready",
            signer=HmacFactSigner(component, OPERATIONS_SECRETS[component]),
        )
    readiness = control_plane.assess_readiness(
        required_components=required_components,
        now=QUOTE_TIME,
        command_id="readiness-paper-admission",
    )
    operations_monitor = OperationsMonitor(
        journal,
        control_plane=control_plane,
        required_components=required_components,
        maximum_readiness_age=timedelta(minutes=2),
        signer=HmacFactSigner("operations-monitor", MONITOR_SECRET),
        verifier=HmacFactVerifier({"operations-monitor": MONITOR_SECRET}),
    )
    health = operations_monitor.assess(
        HealthAssessmentInput(now=QUOTE_TIME, readiness=readiness),
        command_id="health-paper-admission",
    )
    limits = RiskLimits(
        max_total_notional_paise=10_000_000,
        max_position_notional_paise=2_000_000,
        max_risk_per_trade_paise=100_000,
        max_total_risk_paise=500_000,
        max_open_positions=5,
        snapshot_max_age=timedelta(minutes=2),
        max_daily_loss_paise=500_000,
        max_weekly_loss_paise=1_000_000,
        max_drawdown_bps=2_000,
    )
    risk = PortfolioRisk(journal, limits)
    safety = SafetyControl(journal)
    gateway = RecordingPaperGateway()
    admission_authority = KernelAdmissionAuthority(
        journal,
        HmacFactVerifier({"paper-admission": ADMISSION_SECRET}),
    )
    kernel = TradingKernel(
        journal,
        risk,
        safety,
        gateway,
        admission_authority=admission_authority,
    )
    intent_factory = TradeIntentFactory(
        limits, maximum_quote_age=timedelta(minutes=1)
    )
    committee_authority = CommitteeVerdictAuthority(
        journal,
        HmacFactVerifier(COMMITTEE_SECRETS),
    )
    coordinator = GovernedPaperCoordinator(
        journal=journal,
        lifecycle=lifecycle,
        intent_factory=intent_factory,
        episodes=TradeEpisodeJournal(journal),
        kernel=kernel,
        safety=safety,
        committee_gate=TradeCommitteeGate(journal, committee_authority),
        decision_trace_authority=trace_authority,
        admission_authority=admission_authority,
        admission_signer=HmacFactSigner("paper-admission", ADMISSION_SECRET),
        operations_monitor=operations_monitor,
        provenance=provenance,
    )
    quote = ExecutableQuote(
        instrument_id="NSE:TEST",
        snapshot_id="snapshot:quote-1",
        worst_entry_price_paise=10_000,
        observed_at=QUOTE_TIME,
    )
    account = AccountSnapshot(
        available_cash_paise=10_000_000,
        marked_equity_paise=10_000_000,
        high_water_mark_paise=10_000_000,
        day_pnl_paise=0,
        week_pnl_paise=0,
        positions=(),
        included_reservation_ids=(),
        reconciled=True,
        captured_at=QUOTE_TIME,
    )
    sizing = intent_factory.build(
        plan=plan,
        trace=trace,
        quote=quote,
        account_snapshot=account,
        now=QUOTE_TIME + timedelta(seconds=10),
    )
    assert trace.exit_intent is not None
    intent = sizing.intent
    approval = ApprovalRecord(
        thesis=TradeThesis(
            id="TH-PAPER-FIXTURE-1",
            created_at=QUOTE_TIME + timedelta(seconds=1),
            symbol=intent.instrument_id,
            direction=Direction.BUY,
            entry_zone_low=intent.limit_price_paise / 100,
            entry_zone_high=intent.limit_price_paise / 100,
            quantity=intent.quantity,
            stop_loss=intent.stop_price_paise / 100,
            targets=[intent.target_price_paise / 100],
            time_horizon_days=trace.exit_intent.max_hold_sessions,
            invalidation="The exact plan invalidates or the stop is reached.",
            evidence=[claim.claim_id],
            playbook_citations=[
                PlaybookCitation(
                    strategy=plan.plan_id,
                    oos_expectancy_pct=1.0,
                    oos_hit_rate=0.45,
                    oos_trades=100,
                )
            ],
            narrative="Follow-through plan with bounded downside.",
        ),
        verdicts=[
            Verdict(
                level=level,
                agent=agent,
                approved=True,
                reasoning="The exact intent passed this independent gate.",
                checked_at=QUOTE_TIME + timedelta(seconds=index),
            )
            for index, (level, agent) in enumerate(
                (
                    ("L1", "risk-officer"),
                    ("L2", "devils-advocate"),
                    ("L3", "compliance"),
                    ("L4", "orchestrator"),
                ),
                start=2,
            )
        ],
    )
    verdict_evidence_event_ids = tuple(
        committee_authority.record(
            approval.thesis,
            verdict,
            signer=HmacFactSigner(
                verdict.agent, COMMITTEE_SECRETS[verdict.agent]
            ),
            occurred_at=verdict.checked_at,
            command_id=f"attest-paper-{verdict.level}",
        ).event_id
        for verdict in approval.verdicts
    )
    return (
        coordinator,
        plan,
        trace,
        quote,
        account,
        health,
        approval,
        gateway,
        journal,
        trace_attestation.event_id,
        verdict_evidence_event_ids,
        kernel,
    )


def test_governed_paper_admission_connects_lifecycle_trace_episode_and_kernel(tmp_path):
    (
        coordinator,
        plan,
        trace,
        quote,
        account,
        health,
        approval,
        gateway,
        journal,
        trace_event_id,
        verdict_event_ids,
        _,
    ) = governed_system(tmp_path)
    arguments = dict(
        lineage_id=LINEAGE,
        plan=plan,
        trace=trace,
        quote=quote,
        account_snapshot=account,
        operational_health=health,
        signal_observed_at=SIGNAL_TIME,
        now=QUOTE_TIME + timedelta(seconds=10),
        command_id="paper-admit-1",
        approval_record=approval,
        decision_market_snapshot_id=DECISION_SNAPSHOT,
        trace_attestation_event_id=trace_event_id,
        verdict_evidence_event_ids=verdict_event_ids,
    )

    accepted = coordinator.accept(**arguments)
    repeated = coordinator.accept(**arguments)

    assert repeated == accepted
    assert accepted.intent.strategy_plan_id == plan.plan_id
    assert accepted.episode.plan_version_id == plan.plan_id
    assert accepted.episode.intent_id == accepted.intent.intent_id
    assert accepted.committee_approval_id.startswith("approval:")
    assert accepted.thesis_id == approval.thesis.id
    assert len(accepted.episode.linked_event_ids) >= 1
    assert gateway.commands == ()  # acceptance has no broker side effect
    assert any(
        event.event_type == "TradeIntentAccepted"
        for event in journal.read_stream("kernel:paper")
    )


def test_governed_paper_admission_rejects_shadow_only_plan(tmp_path):
    (
        coordinator,
        plan,
        trace,
        quote,
        account,
        health,
        approval,
        _,
        _,
        trace_event_id,
        verdict_event_ids,
        _,
    ) = governed_system(tmp_path, stop_at=LifecycleStage.SHADOW)
    with pytest.raises(PaperAdmissionRejected, match="paper stage"):
        coordinator.accept(
            lineage_id=LINEAGE,
            plan=plan,
            trace=trace,
            quote=quote,
            account_snapshot=account,
            operational_health=health,
            signal_observed_at=SIGNAL_TIME,
            now=QUOTE_TIME,
            command_id="paper-admit-too-early",
            approval_record=approval,
            decision_market_snapshot_id=DECISION_SNAPSHOT,
            trace_attestation_event_id=trace_event_id,
            verdict_evidence_event_ids=verdict_event_ids,
        )


def test_governed_paper_admission_rejects_any_committee_veto(tmp_path):
    (
        coordinator,
        plan,
        trace,
        quote,
        account,
        health,
        approval,
        gateway,
        journal,
        trace_event_id,
        verdict_event_ids,
        _,
    ) = governed_system(tmp_path)
    vetoed_verdicts = list(approval.verdicts)
    vetoed_verdicts[1] = vetoed_verdicts[1].model_copy(
        update={"approved": False, "reasoning": "Risk/reward is not acceptable."}
    )
    vetoed = approval.model_copy(update={"verdicts": vetoed_verdicts})

    with pytest.raises(PaperAdmissionRejected, match="four approved"):
        coordinator.accept(
            lineage_id=LINEAGE,
            plan=plan,
            trace=trace,
            quote=quote,
            account_snapshot=account,
            operational_health=health,
            signal_observed_at=SIGNAL_TIME,
            now=QUOTE_TIME + timedelta(seconds=10),
            command_id="paper-admit-vetoed",
            approval_record=vetoed,
            decision_market_snapshot_id=DECISION_SNAPSHOT,
            trace_attestation_event_id=trace_event_id,
            verdict_evidence_event_ids=verdict_event_ids,
        )

    assert gateway.commands == ()
    assert not any(
        event.event_type == "TradeIntentAccepted"
        for event in journal.read_stream("kernel:paper")
    )
