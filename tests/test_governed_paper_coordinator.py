from datetime import datetime, timedelta, timezone

import pytest

from sensei.governance.evidence import (
    DossierOutcome,
    StageDossierIssue,
    StageDossierRegistry,
)
from sensei.governance.lifecycle import (
    Authority,
    AuthorityRole,
    EvidenceKind,
    LifecycleStage,
    StrategyLifecycle,
    TransitionRequest,
)
from sensei.kernel import RecordingPaperGateway, TradingKernel
from sensei.learning.episodes import TradeEpisodeJournal
from sensei.operations.health import HealthAssessmentInput, OperationsMonitor
from sensei.operations.journal import EventAppend, OperationalJournal
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
from sensei.strategy import PlanEvaluationRequest, StrategyPlanEngine
from tests.test_strategy_plan import hammer_bars, hammer_follow_through_plan


UTC = timezone.utc
SIGNAL_TIME = datetime(2025, 1, 9, 16, 0, tzinfo=UTC)
QUOTE_TIME = datetime(2025, 1, 10, 9, 15, tzinfo=UTC)
LINEAGE = "hammer-follow-through"


def governed_system(tmp_path, *, stop_at: LifecycleStage = LifecycleStage.PAPER):
    journal = OperationalJournal(tmp_path / "sensei.sqlite3")
    plan = hammer_follow_through_plan()
    bars = hammer_bars()
    trace = StrategyPlanEngine().evaluate(
        PlanEvaluationRequest(
            plan=plan,
            instrument_id="NSE:TEST",
            bars=bars,
            evaluation_session=bars.index[-1].date(),
        )
    )
    dossiers = StageDossierRegistry(journal)
    lifecycle = StrategyLifecycle(
        journal,
        evidence_verifier=dossiers.verify_transition,
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
            support = journal.append(
                EventAppend(
                    stream_id=f"support:paper-fixture:{kind.value}",
                    event_type="StageEvidenceProduced",
                    payload={"kind": kind.value, "passed": True},
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
                        producer_id=f"fixture:{kind.value}",
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

    health = OperationsMonitor(journal).assess(
        HealthAssessmentInput(
            now=QUOTE_TIME,
            market_data_watermark=QUOTE_TIME,
            broker_snapshot_at=QUOTE_TIME,
            last_reconciliation_at=QUOTE_TIME,
            maximum_market_data_age=timedelta(minutes=1),
            maximum_broker_age=timedelta(minutes=1),
            maximum_reconciliation_age=timedelta(minutes=1),
            session_active=True,
            safety_latched=False,
            unprotected_quantity=0,
            unknown_broker_objects=0,
        ),
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
    kernel = TradingKernel(journal, risk, safety, gateway)
    coordinator = GovernedPaperCoordinator(
        journal=journal,
        lifecycle=lifecycle,
        intent_factory=TradeIntentFactory(
            limits, maximum_quote_age=timedelta(minutes=1)
        ),
        episodes=TradeEpisodeJournal(journal),
        kernel=kernel,
        safety=safety,
    )
    quote = ExecutableQuote(
        instrument_id="NSE:TEST",
        snapshot_id="snapshot:quote-1",
        worst_entry_price_paise=10_000,
        observed_at=QUOTE_TIME,
    )
    account = AccountSnapshot(
        snapshot_id="snapshot:account-1",
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
    return coordinator, plan, trace, quote, account, health, gateway, journal


def test_governed_paper_admission_connects_lifecycle_trace_episode_and_kernel(tmp_path):
    coordinator, plan, trace, quote, account, health, gateway, journal = (
        governed_system(tmp_path)
    )
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
    )

    accepted = coordinator.accept(**arguments)
    repeated = coordinator.accept(**arguments)

    assert repeated == accepted
    assert accepted.intent.strategy_plan_id == plan.plan_id
    assert accepted.episode.plan_version_id == plan.plan_id
    assert accepted.episode.intent_id == accepted.intent.intent_id
    assert len(accepted.episode.linked_event_ids) >= 1
    assert gateway.commands == ()  # acceptance has no broker side effect
    assert any(
        event.event_type == "TradeIntentAccepted"
        for event in journal.read_stream("kernel:paper")
    )


def test_governed_paper_admission_rejects_shadow_only_plan(tmp_path):
    coordinator, plan, trace, quote, account, health, _, _ = governed_system(
        tmp_path, stop_at=LifecycleStage.SHADOW
    )
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
        )
