import hashlib
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from sensei.agents.thesis import ApprovalRecord
from sensei.kernel import (
    ENTRY_DISPATCH_AUTHORIZATION_FACT_TYPE,
    entry_dispatch_authorization_fact,
)
from sensei.operations import EventAppend, HmacFactSigner, OperationalJournal
from sensei.orchestration import (
    AuthenticatedCommitteeDecision,
    CoachReflection,
    DispatchAuthorization,
    DispatchAuthorizationRejected,
    DeskCycleRequest,
    DeskCycleFailed,
    DeskCycleStatus,
    DeskRuntime,
    EventBrief,
    HistoricalDecision,
    MarketMood,
    PaperTrader,
    PaperExecutionRequest,
    StrategyEvidenceStats,
    desk_cycle_request_id,
)
from tests.test_governed_paper_coordinator import (
    DECISION_SNAPSHOT,
    LINEAGE,
    QUOTE_TIME,
    SIGNAL_TIME,
    SUPERVISOR_ISSUER,
    SUPERVISOR_SECRET,
    governed_system,
)


class Historian:
    def __init__(self, trace, event_id):
        self.trace = trace
        self.event_id = event_id

    def evaluate(self, request, *, memory_context=None):
        assert memory_context.query.role.value == "historian"
        return HistoricalDecision(self.trace, self.event_id)


class Reporter:
    def report(self, instrument_id, *, as_of, memory_context=None):
        assert memory_context.query.role.value == "reporter"
        return EventBrief(
            instrument_id=instrument_id,
            blocked=False,
            reason="no material event window",
            surveillance_stage=None,
        )


class CrowdReader:
    def read(self, *, as_of, memory_context=None):
        assert memory_context.query.role.value == "crowd_reader"
        return MarketMood(
            label="mixed",
            summary="Selective market with normal volatility.",
            confidence=0.7,
        )


class Analyst:
    def __init__(self, thesis):
        self.thesis = thesis

    def draft(self, brief, *, memory_context=None):
        assert memory_context.query.role.value == "analyst"
        return self.thesis


class Committee:
    def __init__(self, approval, evidence_event_ids):
        self.approval = approval
        self.evidence_event_ids = evidence_event_ids

    def review(self, thesis, context, *, now, command_id, memory_context=None):
        assert memory_context.query.role.value == "committee"
        assert thesis == self.approval.thesis
        return AuthenticatedCommitteeDecision(
            approval=self.approval,
            verdict_evidence_event_ids=self.evidence_event_ids,
        )


class Coach:
    def __init__(self):
        self.calls = 0

    def reflect(self, observations, *, now, command_id, memory_context=None):
        assert memory_context.query.role.value == "coach"
        self.calls += 1
        return CoachReflection(observations_recorded=0, hypotheses_proposed=())


class Secretary:
    def __init__(self):
        self.calls = 0

    def report(self, day, *, memory_context=None):
        assert memory_context.query.role.value == "secretary"
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


def _dispatch_authorization(
    journal,
    request,
    intent,
    *,
    observed_at=None,
    reason_codes=(),
):
    checked_at = observed_at or request.now
    material = f"{request.command_id}:{checked_at.isoformat()}:{len(journal.read_all())}"
    command_hash = hashlib.sha256(material.encode()).hexdigest()
    stream = f"desk-supervisor:{command_hash}"
    session_id = f"desk-session:{command_hash}"
    request_id = desk_cycle_request_id(request)
    journal.append(
        EventAppend(
            stream_id=stream,
            event_type="DeskSupervisorStarted",
            payload={
                "session_id": session_id,
                "mode": "paper",
                "requested_at": checked_at.isoformat(),
            },
            idempotency_key=f"test-desk-supervisor-start:{command_hash}",
            expected_version=0,
            occurred_at=checked_at,
            correlation_id=session_id,
        )
    )
    event = journal.append(
        EventAppend(
            stream_id=stream,
            event_type="DeskSupervisorTruthCaptured",
            payload={
                "session_id": session_id,
                "phase": "PRE_DISPATCH:1",
                "checked_at": checked_at.isoformat(),
                "account_snapshot_id": request.account_snapshot.snapshot_id,
                "account_snapshot_event_id": "event:test-account",
                "health_event_id": request.operational_health.event_id,
                "broker_snapshot_id": "broker-snapshot:test",
                "broker_snapshot_event_id": "event:test-broker",
                "reconciliation_evidence_event_id": "event:test-reconciliation",
                "authorized_cycle_request_ids": (request_id,),
                "cycle_request_id": request_id,
                "authorized_intent_id": intent.intent_id,
                "reason_codes": tuple(reason_codes),
            },
            idempotency_key=(
                "test-desk-supervisor-truth:"
                + hashlib.sha256(command_hash.encode()).hexdigest()
            ),
            expected_version=1,
            occurred_at=checked_at,
            correlation_id=session_id,
        )
    )
    fact = entry_dispatch_authorization_fact(
        intent_id=intent.intent_id,
        cycle_request_id=request_id,
        account_snapshot_id=request.account_snapshot.snapshot_id,
        authorized_at=checked_at,
        evidence_event_id=event.event_id,
    )
    return DispatchAuthorization(
        observed_at=checked_at,
        evidence_event_id=event.event_id,
        intent_id=intent.intent_id,
        cycle_request_id=request_id,
        issuer_id=SUPERVISOR_ISSUER,
        signature=HmacFactSigner(
            SUPERVISOR_ISSUER, SUPERVISOR_SECRET
        ).sign(ENTRY_DISPATCH_AUTHORIZATION_FACT_TYPE, fact),
        reason_codes=tuple(reason_codes),
    )


def _authorize_dispatch_for(journal):
    return lambda request, intent: _dispatch_authorization(
        journal, request, intent
    )


def test_paper_trader_reports_only_an_actual_coordinator_runtime_binding(tmp_path):
    system = governed_system(tmp_path)
    coordinator = system[0]
    journal = system[8]
    kernel = system[11]
    trader = PaperTrader(coordinator, kernel)
    safety = coordinator._safety
    monitor = coordinator._operations_monitor

    assert trader.is_bound_to_governed_paper_runtime(
        journal=journal,
        kernel=kernel,
        safety=safety,
        operations_monitor=monitor,
    )
    assert not trader.is_bound_to_governed_paper_runtime(
        journal=journal,
        kernel=object(),
        safety=safety,
        operations_monitor=monitor,
    )
    impostor = PaperTrader(object(), kernel)
    assert not impostor.is_bound_to_governed_paper_runtime(
        journal=journal,
        kernel=kernel,
        safety=safety,
        operations_monitor=monitor,
    )


def test_desk_reports_only_an_actual_paper_trader_runtime_binding(tmp_path):
    runtime, _, _, _, _, journal, _ = _runtime_fixture(tmp_path)
    kernel = runtime.trader._kernel
    coordinator = runtime.trader._coordinator
    safety = coordinator._safety
    monitor = coordinator._operations_monitor

    assert runtime.is_bound_to_governed_paper_runtime(
        journal=journal,
        kernel=kernel,
        safety=safety,
        operations_monitor=monitor,
    )
    assert not runtime.is_bound_to_governed_paper_runtime(
        journal=OperationalJournal(tmp_path / "different-journal.sqlite3"),
        kernel=kernel,
        safety=safety,
        operations_monitor=monitor,
    )
    runtime.trader = object()
    assert not runtime.is_bound_to_governed_paper_runtime(
        journal=journal,
        kernel=kernel,
        safety=safety,
        operations_monitor=monitor,
    )


def test_desk_runtime_invokes_all_nine_roles_and_dispatches_only_after_approval(
    tmp_path,
):
    runtime, request, coach, secretary, gateway, journal, _ = _runtime_fixture(
        tmp_path
    )

    result = runtime.run_cycle(
        request,
        authorize_dispatch=_authorize_dispatch_for(journal),
    )

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
    invocations = [
        event
        for event in journal.read_all()
        if event.event_type == "AgentInvocationRecorded"
        and event.correlation_id == result.cycle_id
    ]
    assert {event.payload["role"] for event in invocations} == {
        "desk_head",
        "historian",
        "reporter",
        "crowd_reader",
        "analyst",
        "committee",
        "trader",
        "coach",
        "secretary",
    }
    assert all(event.payload["context_pack_id"] for event in invocations)


def test_supervised_dispatch_uses_fresh_authorization_after_committee(tmp_path):
    runtime, request, _, _, gateway, journal, approval = _runtime_fixture(tmp_path)
    order: list[str] = []

    class OrderedCommittee(Committee):
        def review(
            self, thesis, context, *, now, command_id, memory_context=None
        ):
            order.append("committee")
            return super().review(
                thesis,
                context,
                now=now,
                command_id=command_id,
                memory_context=memory_context,
            )

    runtime.committee = OrderedCommittee(
        approval,
        runtime.committee.evidence_event_ids,
    )
    dispatch_time = request.now + timedelta(seconds=20)

    def authorize_dispatch(candidate, intent):
        assert candidate is request
        order.append("dispatch-gate")
        return _dispatch_authorization(
            journal,
            candidate,
            intent,
            observed_at=dispatch_time,
        )

    result = runtime.run_cycle(
        request,
        authorize_dispatch=authorize_dispatch,
    )

    assert result.status is DeskCycleStatus.PAPER_DISPATCHED
    assert order == ["committee", "dispatch-gate"]
    assert len(gateway.commands) == 1
    prepared = next(
        event
        for event in journal.read_all()
        if event.event_type == "BrokerCommandPrepared"
    )
    assert prepared.occurred_at == dispatch_time


def test_supervised_dispatch_rejection_never_reaches_paper_gateway(tmp_path):
    runtime, request, _, _, gateway, journal, _ = _runtime_fixture(tmp_path)
    dispatch_time = request.now + timedelta(seconds=20)

    def reject_dispatch(candidate, intent):
        return _dispatch_authorization(
            journal,
            candidate,
            intent,
            observed_at=dispatch_time,
            reason_codes=("OPERATIONAL_HEALTH_STALE",),
        )

    with pytest.raises(DispatchAuthorizationRejected) as raised:
        runtime.run_cycle(request, authorize_dispatch=reject_dispatch)

    assert raised.value.reason_codes == ("OPERATIONAL_HEALTH_STALE",)
    assert gateway.commands == ()
    quarantined = next(
        event
        for event in journal.read_all()
        if event.event_type == "TradeIntentQuarantined"
    )
    assert quarantined.payload["reason_codes"] == (
        "OPERATIONAL_HEALTH_STALE",
    )
    assert str(quarantined.payload["evidence_event_id"]).startswith("event:")
    runtime.trader._kernel.run_once(
        request.account_snapshot,
        now=dispatch_time,
    )
    assert gateway.commands == ()
    failed = next(
        event
        for event in journal.read_all()
        if event.event_type == "DeskCycleFailed"
    )
    assert failed.occurred_at == dispatch_time
    assert failed.payload["reason_codes"] == ("OPERATIONAL_HEALTH_STALE",)


def test_dispatch_gate_failure_quarantines_the_accepted_intent(tmp_path):
    runtime, request, _, _, gateway, journal, _ = _runtime_fixture(tmp_path)

    def fail_before_authorization(candidate, intent):
        raise RuntimeError("account truth source unavailable")

    with pytest.raises(DeskCycleFailed, match="account truth source unavailable"):
        runtime.run_cycle(
            request,
            authorize_dispatch=fail_before_authorization,
        )

    assert gateway.commands == ()
    admission = next(
        event
        for event in journal.read_all()
        if event.event_type == "PaperIntentAdmissionAuthorized"
    )
    quarantined = next(
        event
        for event in journal.read_all()
        if event.event_type == "TradeIntentQuarantined"
    )
    assert quarantined.payload["reason_codes"] == (
        "DISPATCH_AUTHORIZATION_FAILED",
    )
    assert quarantined.payload["evidence_event_id"] == admission.event_id


def test_kernel_rejected_authorization_quarantines_the_accepted_intent(tmp_path):
    runtime, request, _, _, gateway, journal, _ = _runtime_fixture(tmp_path)

    def return_non_supervisor_evidence(candidate, intent):
        cycle_request_id = desk_cycle_request_id(candidate)
        fact = entry_dispatch_authorization_fact(
            intent_id=intent.intent_id,
            cycle_request_id=cycle_request_id,
            account_snapshot_id=candidate.account_snapshot.snapshot_id,
            authorized_at=request.now,
            evidence_event_id=request.operational_health.event_id,
        )
        return DispatchAuthorization(
            observed_at=request.now,
            evidence_event_id=request.operational_health.event_id,
            intent_id=intent.intent_id,
            cycle_request_id=cycle_request_id,
            issuer_id=SUPERVISOR_ISSUER,
            signature=HmacFactSigner(
                SUPERVISOR_ISSUER, SUPERVISOR_SECRET
            ).sign(ENTRY_DISPATCH_AUTHORIZATION_FACT_TYPE, fact),
        )

    with pytest.raises(
        DeskCycleFailed,
        match="Supervisor truth evidence does not authorize entry",
    ):
        runtime.run_cycle(
            request,
            authorize_dispatch=return_non_supervisor_evidence,
        )

    assert gateway.commands == ()
    quarantined = next(
        event
        for event in journal.read_all()
        if event.event_type == "TradeIntentQuarantined"
    )
    assert quarantined.payload["reason_codes"] == (
        "ENTRY_AUTHORIZATION_INVALID",
    )
    evidence = next(
        event
        for event in journal.read_all()
        if event.event_id == quarantined.payload["evidence_event_id"]
    )
    assert evidence.event_type == "OperationalHealthAssessed"


def test_gateway_failure_after_authorization_does_not_quarantine_intent(
    tmp_path,
    monkeypatch,
):
    runtime, request, _, _, gateway, journal, _ = _runtime_fixture(tmp_path)

    def fail_gateway(command):
        raise RuntimeError("paper gateway unavailable")

    monkeypatch.setattr(gateway, "execute", fail_gateway)

    with pytest.raises(DeskCycleFailed, match="paper gateway unavailable"):
        runtime.run_cycle(
            request,
            authorize_dispatch=_authorize_dispatch_for(journal),
        )

    assert any(
        event.event_type == "BrokerCommandPrepared"
        for event in journal.read_stream("kernel:paper")
    )
    assert not any(
        event.event_type == "TradeIntentQuarantined"
        for event in journal.read_stream("kernel:paper")
    )


def test_prepared_entry_rejection_is_not_masked_by_impossible_quarantine():
    intent = SimpleNamespace(intent_id="intent:" + "d" * 64)
    accepted = SimpleNamespace(
        intent=intent,
        admission_event_id="event:" + "a" * 64,
    )

    class Coordinator:
        def accept(self, **kwargs):
            return accepted

    class Kernel:
        def __init__(self):
            self.quarantine_calls = 0

        def has_prepared_entry(self, intent_id):
            assert intent_id == intent.intent_id
            return True

        def run_once(self, snapshot, *, now, intent_id, authorize_entry):
            authorize_entry(intent)

        def quarantine_intent(self, *args, **kwargs):
            self.quarantine_calls += 1
            raise AssertionError("a prepared command cannot be quarantined")

    kernel = Kernel()
    cycle = SimpleNamespace(
        lineage_id="lineage:test",
        plan=SimpleNamespace(),
        quote=SimpleNamespace(),
        account_snapshot=SimpleNamespace(),
        operational_health=SimpleNamespace(),
        signal_observed_at=QUOTE_TIME,
        now=QUOTE_TIME,
        command_id="prepared-retry",
        decision_market_snapshot_id="snapshot:test",
    )
    rejection = DispatchAuthorization(
        observed_at=QUOTE_TIME,
        evidence_event_id="event:" + "b" * 64,
        intent_id=intent.intent_id,
        cycle_request_id="desk-request:" + "e" * 64,
        issuer_id=SUPERVISOR_ISSUER,
        signature="test-rejected-capability",
        reason_codes=("SAFETY_LATCHED",),
    )
    request = PaperExecutionRequest(
        cycle=cycle,
        history=SimpleNamespace(
            trace=SimpleNamespace(),
            trace_attestation_event_id="event:" + "c" * 64,
        ),
        decision=SimpleNamespace(
            approval=SimpleNamespace(),
            verdict_evidence_event_ids=(),
        ),
        authorize_dispatch=lambda candidate, selected: rejection,
    )

    with pytest.raises(DispatchAuthorizationRejected) as raised:
        PaperTrader(Coordinator(), kernel).execute(request)

    assert raised.value.authorization is rejection
    assert kernel.quarantine_calls == 0


def test_approved_cycle_without_supervisor_authorizer_is_not_admitted(tmp_path):
    runtime, request, _, _, gateway, journal, _ = _runtime_fixture(tmp_path)

    with pytest.raises(DeskCycleFailed, match="Supervisor dispatch authorizer"):
        runtime.run_cycle(request)

    assert gateway.commands == ()
    assert not any(
        event.event_type == "TradeIntentAccepted"
        for event in journal.read_all()
    )


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
        def report(self, instrument_id, *, as_of, memory_context=None):
            raise RuntimeError("event feed unavailable")

    runtime.reporter = BrokenReporter()

    with pytest.raises(DeskCycleFailed, match="event feed unavailable"):
        runtime.run_cycle(replace(request, command_id="desk-cycle-feed-failure"))

    assert gateway.commands == ()
    failed = [
        event for event in journal.read_all() if event.event_type == "DeskCycleFailed"
    ]
    assert failed[-1].payload["new_entries_allowed"] is False
    cycle_id = "cycle:" + hashlib.sha256(
        "desk-cycle-feed-failure".encode()
    ).hexdigest()
    invocations = [
        event
        for event in journal.read_all()
        if event.event_type == "AgentInvocationRecorded"
        and event.correlation_id == cycle_id
    ]
    outcomes = {event.payload["role"]: event.payload["outcome"] for event in invocations}
    assert len(outcomes) == 9
    assert outcomes["historian"] == "proceed"
    assert outcomes["reporter"] == "error"
    assert outcomes["desk_head"] == "error"
    assert outcomes["analyst"] == "abstain"
    assert all(
        event.payload["latency_ms"] >= 1
        for event in invocations
        if event.payload["role"] in {"historian", "reporter"}
    )
    assert all(
        event.payload["prompt_id"].startswith("callable:")
        for event in invocations
        if event.payload["role"] in {"historian", "reporter", "desk_head"}
    )
    assert all(
        event.payload["prompt_id"].startswith("not-invoked:")
        for event in invocations
        if event.payload["role"] not in {"historian", "reporter", "desk_head"}
    )


def test_completed_cycle_replay_returns_durable_result_without_rerunning_roles(
    tmp_path,
):
    runtime, request, coach, secretary, gateway, journal, _ = _runtime_fixture(
        tmp_path
    )
    completed = runtime.run_cycle(
        request,
        authorize_dispatch=_authorize_dispatch_for(journal),
    )

    class MustNotRunReporter:
        def report(self, instrument_id, *, as_of, memory_context=None):
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
    runtime, request, _, _, gateway, journal, _ = _runtime_fixture(tmp_path)
    runtime.run_cycle(
        request,
        authorize_dispatch=_authorize_dispatch_for(journal),
    )

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
