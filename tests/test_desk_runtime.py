from dataclasses import replace
from datetime import timedelta

import pytest

from sensei.agents.thesis import ApprovalRecord
from sensei.orchestration import (
    AuthenticatedCommitteeDecision,
    CoachReflection,
    DeskCycleRequest,
    DeskCycleFailed,
    DeskCycleStatus,
    DeskRuntime,
    EventBrief,
    HistoricalDecision,
    MarketMood,
    PaperTrader,
    StrategyEvidenceStats,
)
from tests.test_governed_paper_coordinator import (
    DECISION_SNAPSHOT,
    LINEAGE,
    QUOTE_TIME,
    SIGNAL_TIME,
    governed_system,
)


class Historian:
    def __init__(self, trace, event_id):
        self.trace = trace
        self.event_id = event_id

    def evaluate(self, request):
        return HistoricalDecision(self.trace, self.event_id)


class Reporter:
    def report(self, instrument_id, *, as_of):
        return EventBrief(
            instrument_id=instrument_id,
            blocked=False,
            reason="no material event window",
            surveillance_stage=None,
        )


class CrowdReader:
    def read(self, *, as_of):
        return MarketMood(
            label="mixed",
            summary="Selective market with normal volatility.",
            confidence=0.7,
        )


class Analyst:
    def __init__(self, thesis):
        self.thesis = thesis

    def draft(self, brief):
        return self.thesis


class Committee:
    def __init__(self, approval, evidence_event_ids):
        self.approval = approval
        self.evidence_event_ids = evidence_event_ids

    def review(self, thesis, context, *, now, command_id):
        assert thesis == self.approval.thesis
        return AuthenticatedCommitteeDecision(
            approval=self.approval,
            verdict_evidence_event_ids=self.evidence_event_ids,
        )


class Coach:
    def __init__(self):
        self.calls = 0

    def reflect(self, observations, *, now, command_id):
        self.calls += 1
        return CoachReflection(observations_recorded=0, hypotheses_proposed=())


class Secretary:
    def __init__(self):
        self.calls = 0

    def report(self, day):
        self.calls += 1
        return {"day": day.isoformat(), "journal_integrity": True}


def _runtime_fixture(tmp_path):
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
        kernel,
    ) = governed_system(tmp_path)
    coach = Coach()
    secretary = Secretary()
    runtime = DeskRuntime(
        journal=journal,
        historian=Historian(trace, trace_event_id),
        reporter=Reporter(),
        crowd_reader=CrowdReader(),
        analyst=Analyst(approval.thesis),
        committee=Committee(approval, verdict_event_ids),
        trader=PaperTrader(coordinator, kernel),
        coach=coach,
        secretary=secretary,
    )
    request = DeskCycleRequest(
        lineage_id=LINEAGE,
        plan=plan,
        bars=None,
        evaluation_session=SIGNAL_TIME.date(),
        decision_market_snapshot_id=DECISION_SNAPSHOT,
        quote=quote,
        account_snapshot=account,
        operational_health=health,
        signal_observed_at=SIGNAL_TIME,
        now=QUOTE_TIME + timedelta(seconds=10),
        command_id="desk-cycle-1",
        strategy_stats=StrategyEvidenceStats(
            expectancy_pct=1.0,
            hit_rate=0.45,
            trades=100,
        ),
        committee_context=None,
    )
    return runtime, request, coach, secretary, gateway, journal, approval


def test_desk_runtime_invokes_all_nine_roles_and_dispatches_only_after_approval(
    tmp_path,
):
    runtime, request, coach, secretary, gateway, journal, _ = _runtime_fixture(
        tmp_path
    )

    result = runtime.run_cycle(request)

    assert result.status is DeskCycleStatus.PAPER_DISPATCHED
    assert result.intent_id is not None
    assert coach.calls == 1
    assert secretary.calls == 1
    assert len(gateway.commands) == 1
    role_events = [
        event
        for event in journal.read_all()
        if event.event_type in {"DeskRoleCompleted", "DeskRoleSkipped"}
        and event.correlation_id == result.cycle_id
    ]
    assert {event.payload["role"] for event in role_events} == {
        "orchestrator",
        "historian",
        "reporter",
        "crowd-reader",
        "analyst",
        "committee",
        "trader",
        "coach",
        "secretary",
    }


def test_committee_veto_prevents_trader_but_coach_and_secretary_still_run(tmp_path):
    runtime, request, coach, secretary, gateway, journal, approval = (
        _runtime_fixture(tmp_path)
    )
    vetoes = list(approval.verdicts)
    vetoes[1] = vetoes[1].model_copy(update={"approved": False})
    runtime.committee = Committee(
        ApprovalRecord(thesis=approval.thesis, verdicts=vetoes),
        (),
    )

    result = runtime.run_cycle(replace(request, command_id="desk-cycle-veto"))

    assert result.status is DeskCycleStatus.COMMITTEE_VETOED
    assert gateway.commands == ()
    assert coach.calls == 1
    assert secretary.calls == 1
    trader_event = next(
        event
        for event in journal.read_all()
        if event.event_type == "DeskRoleSkipped"
        and event.payload["role"] == "trader"
    )
    assert trader_event.payload["reason"] == "committee veto"


def test_role_failure_is_recorded_and_fails_cycle_closed(tmp_path):
    runtime, request, _, _, gateway, journal, _ = _runtime_fixture(tmp_path)

    class BrokenReporter:
        def report(self, instrument_id, *, as_of):
            raise RuntimeError("event feed unavailable")

    runtime.reporter = BrokenReporter()

    with pytest.raises(DeskCycleFailed, match="event feed unavailable"):
        runtime.run_cycle(replace(request, command_id="desk-cycle-feed-failure"))

    assert gateway.commands == ()
    failed = [
        event for event in journal.read_all() if event.event_type == "DeskCycleFailed"
    ]
    assert failed[-1].payload["new_entries_allowed"] is False


def test_completed_cycle_replay_returns_durable_result_without_rerunning_roles(
    tmp_path,
):
    runtime, request, coach, secretary, gateway, journal, _ = _runtime_fixture(
        tmp_path
    )
    completed = runtime.run_cycle(request)

    class MustNotRunReporter:
        def report(self, instrument_id, *, as_of):
            raise AssertionError("completed cycle reran an external role")

    runtime.reporter = MustNotRunReporter()
    replayed = runtime.run_cycle(request)

    assert replayed == completed
    assert coach.calls == 1
    assert secretary.calls == 1
    assert len(gateway.commands) == 1
    assert not any(
        event.event_type == "DeskCycleFailed" for event in journal.read_all()
    )


def test_cycle_command_id_cannot_be_reused_for_changed_execution_facts(tmp_path):
    runtime, request, _, _, gateway, _, _ = _runtime_fixture(tmp_path)
    runtime.run_cycle(request)

    changed = replace(
        request,
        quote=replace(
            request.quote,
            worst_entry_price_paise=request.quote.worst_entry_price_paise + 1,
        ),
    )

    with pytest.raises(DeskCycleFailed, match="idempotency key"):
        runtime.run_cycle(changed)

    assert len(gateway.commands) == 1
