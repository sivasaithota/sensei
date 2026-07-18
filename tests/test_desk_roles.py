from datetime import timedelta

from sensei.learning.outcomes import OutcomeLearner
from sensei.operations import HmacFactSigner, HmacFactVerifier, OperationalJournal
from sensei.orchestration import (
    AnalystBrief,
    ApprovalChainCommittee,
    CommitteeInputs,
    CommitteeReviewContext,
    EarningsReporter,
    EventBrief,
    GovernedAnalyst,
    HistoricalDecision,
    HistoricalRequest,
    MarketMood,
    OutcomeCoach,
    StrategyEvidenceStats,
    StrategyHistorian,
    IntentBuildResult,
)
from sensei.portfolio_risk import TradeIntent
from sensei.orchestration.verdicts import CommitteeVerdictAuthority
from sensei.risk.rails import PortfolioState
from sensei.strategy import (
    DecisionTraceAuthority,
    PlanEvaluationRequest,
    StrategyPlanEngine,
)
from tests.test_strategy_plan import hammer_bars, hammer_follow_through_plan
from tests.test_trade_committee_gate import NOW, SECRETS, _approval
from tests.test_trade_episodes_learning import complete_episode_for_learning


HISTORIAN_SECRET = b"historian-role-test-secret-at-least-32-bytes"


def test_historian_evaluates_and_attests_exact_strategy_trace(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    authority = DecisionTraceAuthority(
        journal,
        HmacFactVerifier({"historian": HISTORIAN_SECRET}),
    )
    bars = hammer_bars()
    role = StrategyHistorian(
        StrategyPlanEngine(),
        authority,
        HmacFactSigner("historian", HISTORIAN_SECRET),
    )

    result = role.evaluate(
        HistoricalRequest(
            plan=hammer_follow_through_plan(),
            instrument_id="NSE:TEST",
            bars=bars,
            evaluation_session=bars.index[-1].date(),
            market_snapshot_id="snapshot:" + "a" * 64,
            occurred_at=NOW,
            command_id="historian-role-1",
        )
    )

    assert result.trace.action.value == "enter_long"
    assert authority.verify(
        result.trace_attestation_event_id,
        trace=result.trace,
        market_snapshot_id="snapshot:" + "a" * 64,
        no_later_than=NOW,
    )


def test_governed_analyst_cannot_change_candidate_numbers_or_claims():
    plan = hammer_follow_through_plan(source_claim_id="claim:" + "c" * 64)
    bars = hammer_bars()
    trace = StrategyPlanEngine().evaluate(
        PlanEvaluationRequest(
            plan=plan,
            instrument_id="NSE:TEST",
            bars=bars,
            evaluation_session=bars.index[-1].date(),
        )
    )
    intent = TradeIntent(
        strategy_plan_id=plan.plan_id,
        decision_trace_id=trace.trace_id,
        market_snapshot_id="snapshot:quote",
        account_snapshot_id="snapshot:account",
        instrument_id="NSE:TEST",
        quantity=7,
        limit_price_paise=10_000,
        stop_price_paise=9_500,
        target_price_paise=11_000,
        created_at=NOW,
    )
    candidate = IntentBuildResult(
        intent=intent,
        market_snapshot_id=intent.market_snapshot_id,
        account_snapshot_id=intent.account_snapshot_id,
        portfolio_value_paise=100_000,
        risk_budget_paise=1_000,
        position_budget_paise=10_000,
        binding_capacity="PLAN_POSITION_CAP",
    )
    thesis = GovernedAnalyst().draft(
        AnalystBrief(
            plan=plan,
            candidate=candidate,
            history=HistoricalDecision(trace, "event:" + "1" * 64),
            events=EventBrief("NSE:TEST", False, "clear", 0),
            mood=MarketMood("mixed", "Selective market.", 0.7),
            strategy_stats=StrategyEvidenceStats(1.0, 0.45, 100),
            created_at=NOW,
        )
    )

    assert thesis.quantity == intent.quantity
    assert thesis.stop_loss == intent.stop_price_paise / 100
    assert thesis.targets == [intent.target_price_paise / 100]
    assert thesis.evidence == list(plan.source_claim_ids)
    assert thesis.playbook_citations[0].strategy == plan.plan_id


def test_committee_adapter_attests_every_verdict_from_existing_chain(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    approval = _approval()

    class Chain:
        def run(self, thesis, state, *, turnover, surveillance_stage):
            assert thesis == approval.thesis
            assert surveillance_stage == 0
            return approval

    role = ApprovalChainCommittee(
        Chain(),
        CommitteeVerdictAuthority(journal, HmacFactVerifier(SECRETS)),
        {
            agent: HmacFactSigner(agent, secret)
            for agent, secret in SECRETS.items()
        },
    )
    context = CommitteeReviewContext(
        inputs=CommitteeInputs(
            portfolio_state=PortfolioState(cash=50_000, open_positions=0),
            average_daily_turnover_inr=1_000_000_000,
        ),
        events=EventBrief("INFY", False, "clear", 0),
        mood=MarketMood("mixed", "Selective market.", 0.7),
    )

    result = role.review(
        approval.thesis,
        context,
        now=NOW + timedelta(minutes=1),
        command_id="committee-role-1",
    )

    assert result.approval.approved
    assert len(result.verdict_evidence_event_ids) == 4


def test_reporter_fails_closed_when_event_or_surveillance_truth_is_unknown():
    reporter = EarningsReporter(
        event_window=lambda symbol, on: (False, "earnings clear"),
        surveillance=lambda symbol, on: None,
    )

    brief = reporter.report("NSE:INFY", as_of=NOW)

    assert brief.blocked is True
    assert "surveillance" in brief.reason


def test_reporter_blocks_entry_on_verified_news_risk():
    from sensei.data.news import NewsRiskDecision, NewsRiskLevel

    reporter = EarningsReporter(
        event_window=lambda symbol, on: (False, "earnings clear"),
        surveillance=lambda symbol, on: 0,
        news_risk=lambda instrument, as_of: NewsRiskDecision(
            NewsRiskLevel.BLOCK,
            "critical news risk: exchange closure [NSE]",
            ("news:" + "a" * 64,),
        ),
    )

    brief = reporter.report("NSE:INFY", as_of=NOW)

    assert brief.blocked is True
    assert brief.news_level == "BLOCK"
    assert brief.news_event_ids == ("news:" + "a" * 64,)


def test_coach_discovers_reviewed_closed_episodes_and_proposes_only_after_recurrence(
    tmp_path,
):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    for number in range(1, 4):
        complete_episode_for_learning(journal, f"EP-COACH-{number}", day=number)
    now = max(event.occurred_at for event in journal.read_all()) + timedelta(minutes=1)
    coach = OutcomeCoach(OutcomeLearner(journal, minimum_recurrence=3))

    reflection = coach.reflect((), now=now, command_id="coach-discovery-1")

    assert reflection.observations_recorded == 3
    assert len(reflection.hypotheses_proposed) == 1
    learning_events = [
        event
        for event in journal.read_all()
        if event.event_type == "LearningObservationRecorded"
    ]
    assert {event.payload["episode_id"] for event in learning_events} == {
        "EP-COACH-1",
        "EP-COACH-2",
        "EP-COACH-3",
    }
    assert all(len(event.payload["evidence_refs"]) == 2 for event in learning_events)

    replayed = coach.reflect((), now=now, command_id="coach-discovery-1")

    assert replayed == reflection

    repeated = coach.reflect((), now=now, command_id="coach-discovery-2")

    assert repeated.observations_recorded == 0
    assert repeated.hypotheses_proposed == ()
