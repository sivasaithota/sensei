import hashlib
import os
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from threading import Event, Thread

import pandas as pd
import pytest

from sensei.governance.lifecycle import StrategyLifecycle
from sensei.kernel import (
    BrokerSnapshotAuthority,
    BrokerSnapshot,
    KernelAdmissionAuthority,
    ReconciliationReport,
    RecordingPaperGateway,
    TradingKernel,
)
from sensei.learning.episodes import TradeEpisodeJournal
from sensei.operations import (
    EventAppend,
    HmacFactSigner,
    HmacFactVerifier,
    OperationalJournal,
    OperationsControlPlane,
)
from sensei.operations.health import (
    HealthState,
    OperationalHealth,
    OperationsMonitor,
)
from sensei.operations.supervisor import (
    GovernedDeskSupervisor,
    SessionTruth,
    SupervisorComposition,
    SupervisorConfigurationError,
    SupervisorResult,
    SupervisorSessionRequest,
    SupervisorSessionFailed,
    SupervisorShutdownRequest,
    SupervisorState,
    SupervisorStartupError,
)
from sensei.orchestration import DeskCycleRequest, DeskCycleResult, DeskCycleStatus
from sensei.orchestration import (
    CommitteeVerdictAuthority,
    DeskRuntime,
    DispatchAuthorizationRejected,
    ExecutableQuote,
    GovernedPaperCoordinator,
    PaperTrader,
    TradeCommitteeGate,
    desk_cycle_request_id,
)
from sensei.portfolio_risk import (
    AccountSnapshot,
    AccountSnapshotAuthority,
    PortfolioRisk,
    SafetyControl,
    SafetyResetAuthority,
)
from sensei.portfolio_risk.safety import SafetyReason, SafetyState
from sensei.provenance import ProvenanceCorpus
from sensei.strategy import DecisionTraceAuthority


NOW = datetime(2026, 7, 15, 9, 15, tzinfo=timezone.utc)
SUPERVISOR_SECRET = b"governed-desk-supervisor-signing-secret-32bytes"
SUPERVISOR_ISSUER = "governed-desk-supervisor"


def fake_event_id(label: str) -> str:
    return "event:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


class NetworkGateway:
    def execute(self, command):
        raise AssertionError("a network gateway must never be invoked")


def completed_cycle(cycle_id: str = "cycle:completed") -> DeskCycleResult:
    return DeskCycleResult(
        cycle_id=cycle_id,
        status=DeskCycleStatus.PAPER_DISPATCHED,
        reason="paper entry dispatched",
        trace_id=f"trace:{cycle_id}",
        thesis_id=f"thesis:{cycle_id}",
        intent_id=f"intent:{cycle_id}",
        episode_id=f"episode:{cycle_id}",
        role_event_ids=("event:role-1",),
    )


def healthy_truth(
    *,
    health: OperationalHealth | None = None,
    account_snapshot: AccountSnapshot | None = None,
    authorized_cycle_request_ids: tuple[str, ...] = (),
) -> SessionTruth:
    return SessionTruth(
        account_snapshot=account_snapshot
        or AccountSnapshot(
            available_cash_paise=10_000_000,
            marked_equity_paise=10_000_000,
            high_water_mark_paise=10_000_000,
            day_pnl_paise=0,
            week_pnl_paise=0,
            positions=(),
            included_reservation_ids=(),
            reconciled=True,
            captured_at=NOW,
        ),
        account_snapshot_event_id=fake_event_id("account-snapshot"),
        operational_health=health
        or OperationalHealth(
            state=HealthState.HEALTHY,
            assessed_at=NOW,
            reason_codes=(),
            new_entries_allowed=True,
            protective_actions_allowed=True,
            readiness_event_id=fake_event_id("readiness"),
            readiness_evidence_event_ids=(fake_event_id("heartbeat"),),
            event_id=fake_event_id("health"),
        ),
        broker_snapshot=BrokerSnapshot(
            captured_at=NOW,
            positions=(),
            protections=(),
        ),
        broker_snapshot_event_id=fake_event_id("broker-snapshot"),
        authorized_cycle_request_ids=authorized_cycle_request_ids,
    )


def pending_cycle(
    command_id: str,
    *,
    truth: SessionTruth | None = None,
) -> DeskCycleRequest:
    selected = truth or healthy_truth()
    return DeskCycleRequest(
        lineage_id="paper-lineage",
        plan=SimpleNamespace(plan_id="plan:paper-supervisor"),
        bars=None,
        evaluation_session=NOW.date(),
        decision_market_snapshot_id="snapshot:decision",
        quote=ExecutableQuote(
            instrument_id="NSE:TEST",
            snapshot_id="snapshot:quote",
            worst_entry_price_paise=10_000,
            observed_at=NOW,
        ),
        account_snapshot=selected.account_snapshot,
        operational_health=selected.operational_health,
        signal_observed_at=NOW,
        now=NOW,
        command_id=command_id,
        strategy_stats={"trades": 20},
        committee_context=None,
    )


def authorize_cycles(
    truth: SessionTruth,
    *cycles: DeskCycleRequest,
) -> SessionTruth:
    return replace(
        truth,
        authorized_cycle_request_ids=tuple(
            desk_cycle_request_id(cycle) for cycle in cycles
        ),
    )


def journal_bound_instance(cls, journal: OperationalJournal):
    instance = object.__new__(cls)
    instance._journal = journal
    return instance


def wire_kernel_binding(
    kernel: TradingKernel,
    journal: OperationalJournal,
) -> None:
    kernel._risk = journal_bound_instance(PortfolioRisk, journal)
    kernel._admission_authority = journal_bound_instance(
        KernelAdmissionAuthority,
        journal,
    )
    kernel._broker_snapshot_authority = None
    kernel._safety_reset_authority = None
    kernel._reconciliation_signer = None
    kernel._entry_authorization_verifier = HmacFactVerifier(
        {SUPERVISOR_ISSUER: SUPERVISOR_SECRET}
    )
    kernel._expected_supervisor_issuer_id = SUPERVISOR_ISSUER


def wire_health_binding(
    health: OperationsMonitor,
    journal: OperationalJournal,
) -> None:
    health._control_plane = journal_bound_instance(
        OperationsControlPlane,
        journal,
    )


def wire_coordinator_binding(
    coordinator: GovernedPaperCoordinator,
    *,
    journal: OperationalJournal,
    kernel: TradingKernel,
    safety: SafetyControl,
    operations_monitor: OperationsMonitor,
) -> None:
    verdict_authority = journal_bound_instance(
        CommitteeVerdictAuthority,
        journal,
    )
    committee_gate = journal_bound_instance(TradeCommitteeGate, journal)
    committee_gate._verdict_authority = verdict_authority
    coordinator._journal = journal
    coordinator._lifecycle = journal_bound_instance(StrategyLifecycle, journal)
    coordinator._episodes = journal_bound_instance(TradeEpisodeJournal, journal)
    coordinator._kernel = kernel
    coordinator._safety = safety
    coordinator._committee_gate = committee_gate
    coordinator._decision_trace_authority = journal_bound_instance(
        DecisionTraceAuthority,
        journal,
    )
    coordinator._admission_authority = kernel._admission_authority
    coordinator._operations_monitor = operations_monitor
    coordinator._provenance = journal_bound_instance(ProvenanceCorpus, journal)


class KernelHarness(TradingKernel):
    def __init__(
        self,
        inner,
        *,
        journal: OperationalJournal,
        gateway: RecordingPaperGateway,
        safety: SafetyControl,
        order: list[str] | None = None,
    ):
        self.inner = inner
        self.order = order
        self._journal = journal
        self._gateway = gateway
        self._safety = safety
        wire_kernel_binding(self, journal)

    def enforce(self, *, now):
        self.inner.enforce(now=now)

    def reconcile(self, snapshot, *, snapshot_event_id, now):
        if self.order is not None:
            self.order.append("reconcile")
        return ReconciliationReport(
            snapshot_id=snapshot.snapshot_id,
            clean=True,
            issues=(),
            observed_at=now,
            broker_snapshot_event_id=snapshot_event_id,
            kernel_event_id=fake_event_id("kernel-reconciliation"),
            evidence_event_id=fake_event_id("reconciliation-evidence"),
        )


class DeskHarness(DeskRuntime):
    def __init__(
        self,
        inner,
        *,
        journal: OperationalJournal,
        kernel: KernelHarness,
        safety: SafetyControl,
        operations_monitor: OperationsMonitor,
    ) -> None:
        coordinator = object.__new__(GovernedPaperCoordinator)
        wire_coordinator_binding(
            coordinator,
            journal=journal,
            kernel=kernel,
            safety=safety,
            operations_monitor=operations_monitor,
        )
        self._journal = journal
        self.trader = PaperTrader(coordinator, kernel)
        self.inner = inner

    def run_cycle(self, request, *, authorize_dispatch=None):
        before_dispatch = getattr(self.inner, "before_dispatch", None)
        if callable(before_dispatch):
            before_dispatch()
        if authorize_dispatch is not None:
            intent = SimpleNamespace(
                intent_id="intent:"
                + hashlib.sha256(
                    desk_cycle_request_id(request).encode("utf-8")
                ).hexdigest()
            )
            authorization = authorize_dispatch(request, intent)
            if authorization.reason_codes:
                raise DispatchAuthorizationRejected(authorization)
        return self.inner.run_cycle(request)


class StaticTruthSource:
    def __init__(self, truth: SessionTruth, *, order: list[str] | None = None):
        self.truth = truth
        self.order = order

    def capture(self, *, now, command_id):
        if self.order is not None:
            self.order.append("truth")
        return self.truth


class HealthVerifier(OperationsMonitor):
    def __init__(
        self,
        journal: OperationalJournal,
        *,
        valid: bool = True,
        order: list[str] | None = None,
    ):
        self._journal = journal
        wire_health_binding(self, journal)
        self.valid = valid
        self.order = order

    def verify(self, health, *, no_later_than):
        if self.order is not None:
            self.order.append("health")
        return self.valid


class AccountVerifier(AccountSnapshotAuthority):
    def __init__(self, journal: OperationalJournal, *, valid: bool = True):
        self._journal = journal
        self.valid = valid

    def verify(self, event_id, *, snapshot, no_later_than):
        return self.valid


class SafetyView(SafetyControl):
    def __init__(
        self,
        journal: OperationalJournal,
        state: SafetyState | None = None,
        *,
        order: list[str] | None = None,
    ):
        self._journal = journal
        self._reset_authority = None
        self._state = state or SafetyState(latched=False, reasons=(), version=0)
        self.order = order

    def state(self):
        if self.order is not None:
            self.order.append("safety")
        return self._state


def composition_fixture(
    journal: OperationalJournal,
    gateway: RecordingPaperGateway,
    *,
    kernel,
    cycle_source,
    desk,
    truth: SessionTruth | None = None,
    account_valid: bool = True,
    account_verifier=None,
    health_valid: bool = True,
    safety_state: SafetyState | None = None,
    safety_view: SafetyView | None = None,
    order: list[str] | None = None,
) -> SupervisorComposition:
    bound_safety = safety_view or SafetyView(
        journal,
        safety_state,
        order=order,
    )
    bound_health = HealthVerifier(
        journal,
        valid=health_valid,
        order=order,
    )
    bound_kernel = KernelHarness(
        kernel,
        journal=journal,
        gateway=gateway,
        safety=bound_safety,
        order=order,
    )
    return SupervisorComposition(
        kernel=bound_kernel,
        cycle_source=cycle_source,
        desk=DeskHarness(
            desk,
            journal=journal,
            kernel=bound_kernel,
            safety=bound_safety,
            operations_monitor=bound_health,
        ),
        truth_source=StaticTruthSource(truth or healthy_truth(), order=order),
        account_verifier=(
            account_verifier or AccountVerifier(journal, valid=account_valid)
        ),
        health_verifier=bound_health,
        safety=bound_safety,
        maximum_account_age=timedelta(minutes=2),
        maximum_health_age=timedelta(minutes=2),
        maximum_request_skew=timedelta(seconds=5),
        dispatch_signer=HmacFactSigner(
            SUPERVISOR_ISSUER, SUPERVISOR_SECRET
        ),
    )


def open_supervisor(
    *,
    journal_path: Path,
    gateway: object,
    compose,
    clock=None,
) -> GovernedDeskSupervisor:
    return GovernedDeskSupervisor._paper_only_for_tests(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
        clock=clock or (lambda: NOW),
    )


def exact_composition_fixture(
    journal: OperationalJournal,
    gateway: RecordingPaperGateway,
) -> SupervisorComposition:
    """Build exact concrete identities for public-boundary wiring tests."""

    reconciliation_secret = b"supervisor-reconciliation-secret"
    reconciliation_signer = HmacFactSigner(
        "supervisor-reconciliation",
        reconciliation_secret,
    )
    reset_authority = SafetyResetAuthority(
        journal,
        owner_verifier=HmacFactVerifier({"owner": b"o" * 32}),
        reconciliation_verifier=HmacFactVerifier(
            {"supervisor-reconciliation": reconciliation_secret}
        ),
        expected_reconciliation_issuer_id="supervisor-reconciliation",
    )
    safety = SafetyControl(journal, reset_authority=reset_authority)
    kernel = object.__new__(TradingKernel)
    kernel._journal = journal
    kernel._gateway = gateway
    kernel._safety = safety
    wire_kernel_binding(kernel, journal)
    kernel._broker_snapshot_authority = journal_bound_instance(
        BrokerSnapshotAuthority,
        journal,
    )
    kernel._safety_reset_authority = reset_authority
    kernel._reconciliation_signer = reconciliation_signer
    health = object.__new__(OperationsMonitor)
    health._journal = journal
    wire_health_binding(health, journal)
    health._safety_reset_authority = reset_authority
    account = object.__new__(AccountSnapshotAuthority)
    account._journal = journal
    coordinator = object.__new__(GovernedPaperCoordinator)
    wire_coordinator_binding(
        coordinator,
        journal=journal,
        kernel=kernel,
        safety=safety,
        operations_monitor=health,
    )
    trader = PaperTrader(coordinator, kernel)
    desk = object.__new__(DeskRuntime)
    desk._journal = journal
    desk.trader = trader

    class IdleSource:
        def pending(self, *, now):
            return ()

    return SupervisorComposition(
        kernel=kernel,
        cycle_source=IdleSource(),
        desk=desk,
        truth_source=StaticTruthSource(healthy_truth()),
        account_verifier=account,
        health_verifier=health,
        safety=safety,
        maximum_account_age=timedelta(minutes=2),
        maximum_health_age=timedelta(minutes=2),
        maximum_request_skew=timedelta(seconds=5),
        dispatch_signer=HmacFactSigner(
            SUPERVISOR_ISSUER, SUPERVISOR_SECRET
        ),
    )


def test_paper_supervisor_rejects_network_gateway_before_opening_journal(
    tmp_path: Path,
):
    journal_path = tmp_path / "missing" / "operations.sqlite3"
    composition_called = False

    def compose(journal, gateway):
        nonlocal composition_called
        composition_called = True
        raise AssertionError("composition must not run for a network gateway")

    with pytest.raises(
        SupervisorConfigurationError,
        match="RecordingPaperGateway",
    ):
        GovernedDeskSupervisor.paper_only(
            journal_path=journal_path,
            gateway=NetworkGateway(),
            compose=compose,
        )

    assert not journal_path.exists()
    assert not composition_called


def test_paper_supervisor_rejects_recording_gateway_subclasses(
    tmp_path: Path,
):
    class NetworkCapableSubclass(RecordingPaperGateway):
        def execute(self, command):
            raise AssertionError("network-capable subclass must not be admitted")

    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)

    with pytest.raises(SupervisorConfigurationError, match="exact"):
        GovernedDeskSupervisor.paper_only(
            journal_path=journal_path,
            gateway=NetworkCapableSubclass(),
            compose=lambda journal, gateway: None,
        )


def test_paper_supervisor_rejects_composition_bound_to_another_gateway(
    tmp_path: Path,
):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    supplied_gateway = RecordingPaperGateway()
    ignored_gateway = RecordingPaperGateway()

    def compose(journal, configured_gateway):
        assert configured_gateway is supplied_gateway
        return exact_composition_fixture(journal, ignored_gateway)

    with pytest.raises(SupervisorConfigurationError, match="exact paper runtime"):
        GovernedDeskSupervisor.paper_only(
            journal_path=journal_path,
            gateway=supplied_gateway,
            compose=compose,
        )


def test_public_paper_boundary_accepts_only_the_exact_concrete_runtime(
    tmp_path: Path,
):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()

    supervisor = GovernedDeskSupervisor.paper_only(
        journal_path=journal_path,
        gateway=gateway,
        compose=lambda journal, configured_gateway: exact_composition_fixture(
            journal,
            configured_gateway,
        ),
        clock=lambda: NOW,
    )

    supervisor.close()


def test_public_factory_binds_durable_gateway_to_exact_opened_journal(tmp_path):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    observed = {}

    def gateway_factory(journal):
        observed["journal"] = journal
        return RecordingPaperGateway(journal)

    supervisor = GovernedDeskSupervisor.paper_only_from_gateway_factory(
        journal_path=journal_path,
        gateway_factory=gateway_factory,
        compose=lambda journal, gateway: exact_composition_fixture(journal, gateway),
        clock=lambda: NOW,
    )

    assert supervisor._gateway.is_bound_to_journal(observed["journal"])
    supervisor.close()


def test_paper_supervisor_refuses_missing_journal_without_creating_it(
    tmp_path: Path,
):
    journal_path = tmp_path / "missing" / "operations.sqlite3"
    composition_called = False

    def compose(journal, gateway):
        nonlocal composition_called
        composition_called = True
        raise AssertionError("composition must not run without durable history")

    with pytest.raises(SupervisorStartupError) as raised:
        GovernedDeskSupervisor.paper_only(
            journal_path=journal_path,
            gateway=RecordingPaperGateway(),
            compose=compose,
        )

    assert raised.value.reason_codes == ("JOURNAL_MISSING",)
    assert not journal_path.exists()
    assert not composition_called


def test_paper_supervisor_refuses_tampered_journal_before_composition(
    tmp_path: Path,
):
    journal_path = tmp_path / "operations.sqlite3"
    journal = OperationalJournal(journal_path)
    event = journal.append(
        EventAppend(
            stream_id="operations:test",
            event_type="TestFactRecorded",
            payload={"state": "original"},
            idempotency_key="test-fact-1",
            expected_version=0,
            occurred_at=datetime(2026, 7, 15, 9, 15, tzinfo=timezone.utc),
        )
    )
    with sqlite3.connect(journal_path) as connection:
        connection.execute("DROP TRIGGER journal_events_no_update")
        connection.execute(
            "UPDATE journal_events SET payload_json = ? WHERE event_id = ?",
            ('{"state":"tampered"}', event.event_id),
        )

    composition_called = False

    def compose(journal, gateway):
        nonlocal composition_called
        composition_called = True
        raise AssertionError("composition must not run on untrusted history")

    with pytest.raises(SupervisorStartupError) as raised:
        GovernedDeskSupervisor.paper_only(
            journal_path=journal_path,
            gateway=RecordingPaperGateway(),
            compose=compose,
        )

    assert raised.value.reason_codes == ("JOURNAL_INTEGRITY_FAILED",)
    assert not composition_called


def test_session_command_time_is_bounded_by_a_trusted_clock(tmp_path: Path):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()
    calls: list[str] = []

    class Idle:
        def enforce(self, *, now):
            calls.append("recover")

        def pending(self, *, now):
            calls.append("poll")
            return ()

        def run_cycle(self, request):
            calls.append("cycle")
            return completed_cycle()

    def compose(journal, configured_gateway):
        idle = Idle()
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=idle,
            cycle_source=idle,
            desk=idle,
        )

    supervisor = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
        clock=lambda: NOW + timedelta(minutes=10),
    )

    with pytest.raises(SupervisorStartupError) as raised:
        supervisor.run_session(
            SupervisorSessionRequest(now=NOW, command_id="delayed-command")
        )

    assert raised.value.reason_codes == ("SESSION_TIME_SKEW",)
    assert calls == []
    assert OperationalJournal(journal_path).read_all() == ()


def test_freshness_uses_a_new_trusted_time_after_slow_recovery(tmp_path: Path):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()
    current_time = [NOW]

    class Kernel:
        def enforce(self, *, now):
            current_time[0] = NOW + timedelta(minutes=3)

    class MustNotPoll:
        def pending(self, *, now):
            raise AssertionError("truth that aged during recovery must not poll")

        def run_cycle(self, request):
            raise AssertionError("truth that aged during recovery must not run")

    def compose(journal, configured_gateway):
        stopped = MustNotPoll()
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=Kernel(),
            cycle_source=stopped,
            desk=stopped,
        )

    result = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
        clock=lambda: current_time[0],
    ).run_session(
        SupervisorSessionRequest(now=NOW, command_id="slow-recovery")
    )

    assert result.state is SupervisorState.HALTED
    assert result.reason_codes == (
        "ACCOUNT_SNAPSHOT_STALE",
        "OPERATIONAL_HEALTH_STALE",
    )


def test_session_recovers_kernel_before_polling_or_running_desk_cycles(
    tmp_path: Path,
):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()
    order: list[str] = []
    truth = healthy_truth()
    cycle = pending_cycle("ordered-cycle", truth=truth)
    truth = authorize_cycles(truth, cycle)
    cycle_result = completed_cycle("cycle:ordered")

    class Kernel:
        def enforce(self, *, now):
            order.append("recover")

    class CycleSource:
        def pending(self, *, now):
            order.append("poll")
            return (cycle,)

    class Desk:
        def run_cycle(self, request):
            assert request is cycle
            order.append("cycle")
            return cycle_result

    def compose(journal, configured_gateway):
        assert configured_gateway is gateway
        assert journal.verify().ok
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=Kernel(),
            cycle_source=CycleSource(),
            desk=Desk(),
            truth=truth,
            order=order,
        )

    supervisor = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
    )
    result = supervisor.run_session(
        SupervisorSessionRequest(
            now=datetime(2026, 7, 15, 9, 15, tzinfo=timezone.utc),
            command_id="paper-session-1",
        )
    )

    assert result.state is SupervisorState.COMPLETED
    assert result.cycles == (cycle_result,)
    assert order == [
        "recover",
        "truth",
        "reconcile",
        "health",
        "safety",
        "health",
        "safety",
        "poll",
        "health",
        "safety",
        "health",
        "safety",
        "truth",
        "reconcile",
        "health",
        "safety",
        "cycle",
        "truth",
        "reconcile",
        "health",
        "safety",
        "health",
        "safety",
    ]
    command_hash = hashlib.sha256(b"paper-session-1").hexdigest()
    truth_events = [
        event
        for event in OperationalJournal(journal_path).read_stream(
            f"desk-supervisor:{command_hash}"
        )
        if event.event_type == "DeskSupervisorTruthCaptured"
    ]
    assert [event.payload["phase"] for event in truth_events] == [
        "INITIAL",
        "PRE_DISPATCH:1",
        "POST_CYCLE:1",
    ]
    assert truth_events[0].payload["account_snapshot_event_id"] == (
        truth.account_snapshot_event_id
    )
    assert truth_events[0].payload["health_event_id"] == (
        truth.operational_health.event_id
    )
    assert truth_events[0].payload["authorized_cycle_request_ids"] == (
        desk_cycle_request_id(cycle),
    )
    assert truth_events[0].payload["authorized_intent_id"] is None
    assert str(truth_events[1].payload["authorized_intent_id"]).startswith(
        "intent:"
    )
    assert truth_events[2].payload["authorized_intent_id"] is None


def test_cross_session_desk_cycle_replay_uses_prior_terminal_proof(
    tmp_path: Path,
):
    journal_path = tmp_path / "operations.sqlite3"
    journal = OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()
    truth = healthy_truth()
    cycle = pending_cycle("persistent-cycle", truth=truth)
    truth = authorize_cycles(truth, cycle)
    cycle_id = "cycle:" + hashlib.sha256(cycle.command_id.encode()).hexdigest()
    cycle_result = DeskCycleResult(
        cycle_id=cycle_id,
        status=DeskCycleStatus.PAPER_DISPATCHED,
        reason="paper entry dispatched",
        trace_id="trace:persistent-cycle",
        thesis_id="thesis:persistent-cycle",
        intent_id="intent:" + "a" * 64,
        episode_id=None,
        role_event_ids=(),
    )
    desk_invocations = [0]

    class Kernel:
        def enforce(self, *, now):
            pass

    class CycleSource:
        def pending(self, *, now):
            return (cycle,)

    class InnerDesk:
        def run_cycle(self, request):
            assert request is cycle
            return cycle_result

    inner_desk = InnerDesk()

    class ReplayAwareDesk(DeskHarness):
        def run_cycle(self, request, *, authorize_dispatch=None):
            desk_invocations[0] += 1
            if desk_invocations[0] == 1:
                return super().run_cycle(
                    request,
                    authorize_dispatch=authorize_dispatch,
                )
            return self.inner.run_cycle(request)

    def compose(opened_journal, configured_gateway):
        base = composition_fixture(
            opened_journal,
            configured_gateway,
            kernel=Kernel(),
            cycle_source=CycleSource(),
            desk=inner_desk,
            truth=truth,
        )
        replay_aware = ReplayAwareDesk(
            inner_desk,
            journal=opened_journal,
            kernel=base.kernel,
            safety=base.safety,
            operations_monitor=base.health_verifier,
        )
        return replace(base, desk=replay_aware)

    first = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
    )
    first.run_session(
        SupervisorSessionRequest(now=NOW, command_id="first-owner-session")
    )
    first.close()

    journal.append(
        EventAppend(
            stream_id="desk-cycle:" + cycle_id.removeprefix("cycle:"),
            event_type="DeskCycleCompleted",
            payload={
                "cycle_id": cycle_id,
                "status": DeskCycleStatus.PAPER_DISPATCHED.value,
                "reason": cycle_result.reason,
                "trace_id": cycle_result.trace_id,
                "thesis_id": cycle_result.thesis_id,
                "intent_id": cycle_result.intent_id,
                "role_event_ids": (),
            },
            idempotency_key="test-prior-desk-terminal",
            expected_version=0,
            occurred_at=NOW,
            correlation_id=cycle_id,
        )
    )

    second = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
    )
    second_result = second.run_session(
        SupervisorSessionRequest(now=NOW, command_id="second-owner-session")
    )
    second.close()

    second_stream = "desk-supervisor:" + hashlib.sha256(
        b"second-owner-session"
    ).hexdigest()
    assert [
        event.payload["phase"]
        for event in journal.read_stream(second_stream)
        if event.event_type == "DeskSupervisorTruthCaptured"
    ] == ["INITIAL", "POST_CYCLE:1"]

    replay = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
    )
    assert replay.run_session(
        SupervisorSessionRequest(now=NOW, command_id="second-owner-session")
    ) == second_result
    replay.close()
    assert desk_invocations == [2]


def test_slow_role_chain_is_rejected_by_the_final_dispatch_gate(tmp_path: Path):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()
    current_time = [NOW]
    truth = healthy_truth()
    cycle = pending_cycle("slow-role-cycle", truth=truth)
    truth = authorize_cycles(truth, cycle)
    calls: list[str] = []

    class Kernel:
        def enforce(self, *, now):
            return None

    class CycleSource:
        def pending(self, *, now):
            return (cycle,)

    class SlowDesk:
        def before_dispatch(self):
            calls.append("roles-completed")
            current_time[0] = NOW + timedelta(minutes=3)

        def run_cycle(self, request):
            raise AssertionError("stale work must not reach the Trader")

    def compose(journal, configured_gateway):
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=Kernel(),
            cycle_source=CycleSource(),
            desk=SlowDesk(),
            truth=truth,
        )

    result = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
        clock=lambda: current_time[0],
    ).run_session(
        SupervisorSessionRequest(now=NOW, command_id="slow-role-session")
    )

    assert result.state is SupervisorState.HALTED
    assert result.reason_codes == (
        "ACCOUNT_SNAPSHOT_STALE",
        "OPERATIONAL_HEALTH_STALE",
        "CYCLE_TIME_SKEW",
    )
    assert calls == ["roles-completed"]
    command_hash = hashlib.sha256(b"slow-role-session").hexdigest()
    manifest = next(
        event
        for event in OperationalJournal(journal_path).read_stream(
            f"desk-supervisor:{command_hash}"
        )
        if event.event_type == "DeskSupervisorTruthCaptured"
        and event.payload["phase"] == "PRE_DISPATCH:1"
    )
    assert manifest.payload["reason_codes"] == result.reason_codes


def test_replay_rejects_hash_valid_malformed_truth_manifest(tmp_path: Path):
    journal_path = tmp_path / "operations.sqlite3"
    journal = OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()
    command_id = "malformed-truth-manifest"
    command_hash = hashlib.sha256(command_id.encode()).hexdigest()
    session_id = f"desk-session:{command_hash}"
    stream = f"desk-supervisor:{command_hash}"
    journal.append(
        EventAppend(
            stream_id=stream,
            event_type="DeskSupervisorStarted",
            payload={
                "session_id": session_id,
                "mode": "paper",
                "requested_at": NOW.isoformat(),
            },
            idempotency_key=f"desk-supervisor:{command_hash}:start",
            expected_version=0,
            occurred_at=NOW,
            correlation_id=session_id,
        )
    )
    journal.append(
        EventAppend(
            stream_id=stream,
            event_type="DeskSupervisorTruthCaptured",
            payload={"session_id": session_id, "phase": "INITIAL"},
            idempotency_key="malformed-supervisor-truth",
            expected_version=1,
            occurred_at=NOW,
            correlation_id=session_id,
        )
    )

    recovery_calls: list[datetime] = []

    class MustNotRun:
        def enforce(self, *, now):
            recovery_calls.append(now)

        def pending(self, *, now):
            raise AssertionError("invalid truth must fail before polling")

        def run_cycle(self, request):
            raise AssertionError("invalid truth must fail before agents")

    def compose(opened_journal, configured_gateway):
        stopped = MustNotRun()
        return composition_fixture(
            opened_journal,
            configured_gateway,
            kernel=stopped,
            cycle_source=stopped,
            desk=stopped,
        )

    supervisor = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
    )
    with pytest.raises(SupervisorStartupError) as raised:
        supervisor.run_session(
            SupervisorSessionRequest(now=NOW, command_id=command_id)
        )

    assert raised.value.reason_codes == ("SESSION_TRUTH_INVALID",)
    assert recovery_calls == [NOW]


def test_completed_session_replays_without_recovery_polling_or_agent_work(
    tmp_path: Path,
):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()
    calls: list[str] = []
    truth = healthy_truth()
    cycle = pending_cycle("replayed-cycle", truth=truth)
    truth = authorize_cycles(truth, cycle)
    cycle_result = completed_cycle()

    class Kernel:
        def enforce(self, *, now):
            calls.append("recover")

    class CycleSource:
        def pending(self, *, now):
            calls.append("poll")
            return (cycle,)

    class Desk:
        def run_cycle(self, request):
            calls.append("cycle")
            return cycle_result

    def first_composition(journal, configured_gateway):
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=Kernel(),
            cycle_source=CycleSource(),
            desk=Desk(),
            truth=truth,
        )

    request = SupervisorSessionRequest(
        now=datetime(2026, 7, 15, 9, 15, tzinfo=timezone.utc),
        command_id="paper-session-replay",
    )
    first = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=first_composition,
    ).run_session(request)
    assert calls == ["recover", "poll", "cycle"]

    class MustNotRun:
        def enforce(self, *, now):
            raise AssertionError("completed session must not recover again")

        def pending(self, *, now):
            raise AssertionError("completed session must not poll again")

        def run_cycle(self, request):
            raise AssertionError("completed session must not rerun agents")

    def replay_composition(journal, configured_gateway):
        stopped = MustNotRun()
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=stopped,
            cycle_source=stopped,
            desk=stopped,
        )

    replayed = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=replay_composition,
    ).run_session(request)

    assert replayed == first


def test_production_replay_rejects_unresolvable_truth_evidence(tmp_path: Path):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()
    truth = healthy_truth()
    cycle = pending_cycle("synthetic-evidence", truth=truth)
    truth = authorize_cycles(truth, cycle)

    class Kernel:
        def enforce(self, *, now):
            return None

    class Source:
        def pending(self, *, now):
            return (cycle,)

    class Desk:
        def run_cycle(self, request):
            return completed_cycle("cycle:synthetic-evidence")

    def test_composition(journal, configured_gateway):
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=Kernel(),
            cycle_source=Source(),
            desk=Desk(),
            truth=truth,
        )

    request = SupervisorSessionRequest(
        now=NOW,
        command_id="synthetic-evidence-session",
    )
    test_owner = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=test_composition,
    )
    assert test_owner.run_session(request).state is SupervisorState.COMPLETED
    test_owner.close()

    production = GovernedDeskSupervisor.paper_only(
        journal_path=journal_path,
        gateway=gateway,
        compose=exact_composition_fixture,
        clock=lambda: NOW,
    )
    with pytest.raises(SupervisorStartupError) as raised:
        production.run_session(request)

    assert raised.value.reason_codes == ("SESSION_TRUTH_EVIDENCE_INVALID",)
    production.close()


@pytest.mark.parametrize(
    "invalid_terminal",
    (
        {"new_entries_allowed": "false"},
        {"reconciliation": None},
        {"protective_actions_allowed": False},
    ),
)
def test_replay_rejects_hash_valid_or_impossible_completed_terminal(
    tmp_path: Path,
    invalid_terminal: dict[str, object],
):
    journal_path = tmp_path / "operations.sqlite3"
    journal = OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()
    command_id = "malformed-terminal"
    command_hash = hashlib.sha256(command_id.encode()).hexdigest()
    session_id = f"desk-session:{command_hash}"
    stream = f"desk-supervisor:{command_hash}"
    terminal_payload = {
        "session_id": session_id,
        "state": "COMPLETED",
        "reason_codes": [],
        "cycles": [],
        "new_entries_allowed": True,
        "protective_actions_allowed": True,
        "reconciliation": {
            "snapshot_id": "broker-snapshot:trusted",
            "clean": True,
            "issues": [],
            "observed_at": NOW.isoformat(),
            "broker_snapshot_event_id": "event:broker-snapshot",
            "kernel_event_id": "event:kernel-reconciliation",
            "evidence_event_id": "event:reconciliation-evidence",
        },
    }
    terminal_payload.update(invalid_terminal)
    journal.append(
        EventAppend(
            stream_id=stream,
            event_type="DeskSupervisorStarted",
            payload={
                "session_id": session_id,
                "mode": "paper",
                "requested_at": NOW.isoformat(),
            },
            idempotency_key=f"desk-supervisor:{command_hash}:start",
            expected_version=0,
            occurred_at=NOW,
            correlation_id=session_id,
        )
    )
    journal.append(
        EventAppend(
            stream_id=stream,
            event_type="DeskSupervisorCompleted",
            payload=terminal_payload,
            idempotency_key=f"desk-supervisor:{command_hash}:complete",
            expected_version=1,
            occurred_at=NOW,
            correlation_id=session_id,
        )
    )

    recovery_calls: list[datetime] = []

    class MustNotRun:
        def enforce(self, *, now):
            recovery_calls.append(now)

        def pending(self, *, now):
            raise AssertionError("malformed replay must not poll")

        def run_cycle(self, request):
            raise AssertionError("malformed replay must not run agents")

    def compose(opened_journal, configured_gateway):
        stopped = MustNotRun()
        return composition_fixture(
            opened_journal,
            configured_gateway,
            kernel=stopped,
            cycle_source=stopped,
            desk=stopped,
        )

    supervisor = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
    )
    with pytest.raises(SupervisorStartupError) as raised:
        supervisor.run_session(
            SupervisorSessionRequest(now=NOW, command_id=command_id)
        )

    assert raised.value.reason_codes == ("SESSION_TERMINAL_INVALID",)
    assert recovery_calls == [NOW]


def test_recovery_failure_is_recorded_and_replayed_without_polling_work(
    tmp_path: Path,
):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()
    recovery_calls = 0

    class FailingKernel:
        def enforce(self, *, now):
            nonlocal recovery_calls
            recovery_calls += 1
            raise RuntimeError("protection adapter unavailable")

    class MustNotPoll:
        def pending(self, *, now):
            raise AssertionError("work must not be polled after failed recovery")

        def run_cycle(self, request):
            raise AssertionError("agents must not run after failed recovery")

    def failing_composition(journal, configured_gateway):
        stopped = MustNotPoll()
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=FailingKernel(), cycle_source=stopped, desk=stopped
        )

    request = SupervisorSessionRequest(
        now=datetime(2026, 7, 15, 9, 16, tzinfo=timezone.utc),
        command_id="paper-session-recovery-failed",
    )
    with pytest.raises(SupervisorSessionFailed) as first_failure:
        open_supervisor(
            journal_path=journal_path,
            gateway=gateway,
            compose=failing_composition,
            clock=lambda: request.now,
        ).run_session(request)

    assert first_failure.value.result.state is SupervisorState.FAILED
    assert first_failure.value.result.reason_codes == (
        "RECOVERY_FAILED",
        "TERMINAL_ENFORCEMENT_FAILED",
    )
    assert recovery_calls == 2

    replay_recovery: list[str] = []
    class MustNotRestart:
        def enforce(self, *, now):
            replay_recovery.append("recover")

        def pending(self, *, now):
            raise AssertionError("failed session must not poll")

        def run_cycle(self, request):
            raise AssertionError("failed session must not run agents")

    def replay_composition(journal, configured_gateway):
        stopped = MustNotRestart()
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=stopped, cycle_source=stopped, desk=stopped
        )

    with pytest.raises(SupervisorSessionFailed) as replayed_failure:
        open_supervisor(
            journal_path=journal_path,
            gateway=gateway,
            compose=replay_composition,
            clock=lambda: request.now,
        ).run_session(request)

    assert replayed_failure.value.result == first_failure.value.result
    assert recovery_calls == 2
    assert replay_recovery == ["recover"]


def test_restart_halts_an_incomplete_session_instead_of_rerunning_roles(
    tmp_path: Path,
):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()

    class SimulatedProcessDeath(BaseException):
        pass

    class DyingKernel:
        def enforce(self, *, now):
            raise SimulatedProcessDeath

    class MustNotRun:
        def pending(self, *, now):
            raise AssertionError("dying session must not poll")

        def run_cycle(self, request):
            raise AssertionError("dying session must not run agents")

    def dying_composition(journal, configured_gateway):
        stopped = MustNotRun()
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=DyingKernel(), cycle_source=stopped, desk=stopped
        )

    request = SupervisorSessionRequest(
        now=datetime(2026, 7, 15, 9, 17, tzinfo=timezone.utc),
        command_id="paper-session-hard-crash",
    )
    with pytest.raises(SimulatedProcessDeath):
        open_supervisor(
            journal_path=journal_path,
            gateway=gateway,
            compose=dying_composition,
            clock=lambda: request.now,
        ).run_session(request)

    restart_recoveries = 0

    class RestartMustNotRun:
        def enforce(self, *, now):
            nonlocal restart_recoveries
            restart_recoveries += 1

        def pending(self, *, now):
            raise AssertionError("incomplete session must not poll")

        def run_cycle(self, request):
            raise AssertionError("incomplete session must not rerun agents")

    def restart_composition(journal, configured_gateway):
        stopped = RestartMustNotRun()
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=stopped, cycle_source=stopped, desk=stopped
        )

    halted = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=restart_composition,
        clock=lambda: request.now,
    ).run_session(request)

    assert halted.state is SupervisorState.HALTED
    assert halted.reason_codes == ("INCOMPLETE_SESSION",)
    assert halted.cycles == ()
    assert restart_recoveries == 1

    replayed = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=restart_composition,
        clock=lambda: request.now,
    ).run_session(request)
    assert replayed == halted


def test_new_command_quarantines_an_incomplete_prior_session_before_work(
    tmp_path: Path,
):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()

    class SimulatedProcessDeath(BaseException):
        pass

    class DyingKernel:
        def enforce(self, *, now):
            raise SimulatedProcessDeath

    class MustNotRun:
        def pending(self, *, now):
            raise AssertionError("crashed session must not poll")

        def run_cycle(self, request):
            raise AssertionError("crashed session must not run agents")

    def dying_composition(journal, configured_gateway):
        stopped = MustNotRun()
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=DyingKernel(),
            cycle_source=stopped,
            desk=stopped,
        )

    crashed = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=dying_composition,
    )
    with pytest.raises(SimulatedProcessDeath):
        crashed.run_session(
            SupervisorSessionRequest(now=NOW, command_id="abandoned-command")
        )
    crashed.close()

    recoveries = 0

    class RecoveryOnly:
        def enforce(self, *, now):
            nonlocal recoveries
            recoveries += 1

        def pending(self, *, now):
            raise AssertionError("new work must wait for a later session")

        def run_cycle(self, request):
            raise AssertionError("new work must wait for a later session")

    def recovery_composition(journal, configured_gateway):
        stopped = RecoveryOnly()
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=stopped,
            cycle_source=stopped,
            desk=stopped,
        )

    result = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=recovery_composition,
    ).run_session(
        SupervisorSessionRequest(now=NOW, command_id="different-new-command")
    )

    assert result.state is SupervisorState.HALTED
    assert result.reason_codes == ("INCOMPLETE_PRIOR_SESSION",)
    assert recoveries == 1
    old_hash = hashlib.sha256(b"abandoned-command").hexdigest()
    old_events = OperationalJournal(journal_path).read_stream(
        f"desk-supervisor:{old_hash}"
    )
    assert [event.event_type for event in old_events] == [
        "DeskSupervisorStarted",
        "DeskSupervisorHalted",
    ]


def test_retry_quarantines_every_stream_after_crash_during_quarantine(
    tmp_path: Path,
):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()

    class SimulatedProcessDeath(BaseException):
        pass

    class Dies:
        def enforce(self, *, now):
            raise SimulatedProcessDeath

        def pending(self, *, now):
            raise AssertionError("crash path must not poll")

        def run_cycle(self, request):
            raise AssertionError("crash path must not run agents")

    def dying_composition(journal, configured_gateway):
        dying = Dies()
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=dying,
            cycle_source=dying,
            desk=dying,
        )

    first = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=dying_composition,
    )
    with pytest.raises(SimulatedProcessDeath):
        first.run_session(
            SupervisorSessionRequest(now=NOW, command_id="incomplete-a")
        )
    first.close()

    second_request = SupervisorSessionRequest(
        now=NOW,
        command_id="incomplete-b",
    )
    second = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=dying_composition,
    )
    with pytest.raises(SimulatedProcessDeath):
        second.run_session(second_request)
    second.close()

    recoveries = 0

    class Recovers:
        def enforce(self, *, now):
            nonlocal recoveries
            recoveries += 1

        def pending(self, *, now):
            raise AssertionError("quarantine retry must not poll")

        def run_cycle(self, request):
            raise AssertionError("quarantine retry must not run agents")

    def recovery_composition(journal, configured_gateway):
        recovery = Recovers()
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=recovery,
            cycle_source=recovery,
            desk=recovery,
        )

    result = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=recovery_composition,
    ).run_session(second_request)

    assert result.reason_codes == ("INCOMPLETE_SESSION",)
    assert recoveries == 1
    journal = OperationalJournal(journal_path)
    for command_id in ("incomplete-a", "incomplete-b"):
        command_hash = hashlib.sha256(command_id.encode()).hexdigest()
        assert [
            event.event_type
            for event in journal.read_stream(f"desk-supervisor:{command_hash}")
        ] == ["DeskSupervisorStarted", "DeskSupervisorHalted"]


def test_cycle_with_different_account_truth_is_halted_before_agents_run(
    tmp_path: Path,
):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()
    truth = healthy_truth()
    different_account = replace(
        truth.account_snapshot,
        available_cash_paise=9_000_000,
    )
    cycle = replace(
        pending_cycle("mismatched-cycle", truth=truth),
        account_snapshot=different_account,
    )

    class Kernel:
        def enforce(self, *, now):
            return None

    class CycleSource:
        def pending(self, *, now):
            return (cycle,)

    class DeskMustNotRun:
        def run_cycle(self, request):
            raise AssertionError("mismatched account truth must not reach agents")

    def compose(journal, configured_gateway):
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=Kernel(),
            cycle_source=CycleSource(),
            desk=DeskMustNotRun(),
            truth=truth,
        )

    result = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
    ).run_session(
        SupervisorSessionRequest(now=NOW, command_id="account-truth-mismatch")
    )

    assert result.state is SupervisorState.HALTED
    assert result.reason_codes == ("CYCLE_ACCOUNT_TRUTH_MISMATCH",)
    assert result.cycles == ()


def test_unsigned_account_truth_halts_before_work_is_polled(tmp_path: Path):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()

    class Kernel:
        def enforce(self, *, now):
            return None

    class MustNotPoll:
        def pending(self, *, now):
            raise AssertionError("unsigned account truth must block polling")

        def run_cycle(self, request):
            raise AssertionError("unsigned account truth must block agents")

    def compose(journal, configured_gateway):
        stopped = MustNotPoll()
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=Kernel(),
            cycle_source=stopped,
            desk=stopped,
            account_valid=False,
        )

    result = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
    ).run_session(
        SupervisorSessionRequest(now=NOW, command_id="unsigned-account")
    )

    assert result.state is SupervisorState.HALTED
    assert result.reason_codes == ("ACCOUNT_EVIDENCE_INVALID",)


def test_supervisor_accepts_account_truth_from_the_configured_authority(
    tmp_path: Path,
):
    journal_path = tmp_path / "operations.sqlite3"
    journal = OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()
    secret = b"account-adapter-test-secret-32-bytes"
    authority = AccountSnapshotAuthority(
        journal,
        HmacFactVerifier({"paper-account": secret}),
        expected_issuer_id="paper-account",
    )
    truth = healthy_truth()
    evidence = authority.record(
        truth.account_snapshot,
        signer=HmacFactSigner("paper-account", secret),
        occurred_at=NOW,
        command_id="supervisor-account-truth",
    )
    truth = replace(truth, account_snapshot_event_id=evidence.event_id)

    class Idle:
        def enforce(self, *, now):
            return None

        def pending(self, *, now):
            return ()

        def run_cycle(self, request):
            raise AssertionError("idle authenticated session has no work")

    def compose(opened_journal, configured_gateway):
        idle = Idle()
        opened_authority = AccountSnapshotAuthority(
            opened_journal,
            HmacFactVerifier({"paper-account": secret}),
            expected_issuer_id="paper-account",
        )
        return composition_fixture(
            opened_journal,
            configured_gateway,
            kernel=idle,
            cycle_source=idle,
            desk=idle,
            truth=truth,
            account_verifier=opened_authority,
        )

    result = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
    ).run_session(
        SupervisorSessionRequest(now=NOW, command_id="authenticated-account")
    )

    assert result.state is SupervisorState.COMPLETED


def test_cycle_market_and_quote_must_match_the_captured_session_truth(
    tmp_path: Path,
):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()
    truth = healthy_truth()
    authorized = pending_cycle("market-truth", truth=truth)
    truth = authorize_cycles(truth, authorized)
    mismatched = replace(
        authorized,
        decision_market_snapshot_id="snapshot:different-decision",
    )

    class Kernel:
        def enforce(self, *, now):
            return None

    class CycleSource:
        def pending(self, *, now):
            return (mismatched,)

    class MustNotRun:
        def run_cycle(self, request):
            raise AssertionError("unbound market truth must not reach agents")

    def compose(journal, configured_gateway):
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=Kernel(),
            cycle_source=CycleSource(),
            desk=MustNotRun(),
            truth=truth,
        )

    result = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
    ).run_session(
        SupervisorSessionRequest(now=NOW, command_id="market-truth-session")
    )

    assert result.state is SupervisorState.HALTED
    assert result.reason_codes == ("CYCLE_REQUEST_TRUTH_MISMATCH",)
    assert result.cycles == ()


def test_cycle_request_identity_includes_the_exact_bars_and_quote():
    base = pending_cycle("identity-cycle")
    changed_bars = replace(base, bars={"close": [101, 102]})
    changed_quote = replace(
        base,
        quote=replace(base.quote, worst_entry_price_paise=10_001),
    )

    identities = {
        desk_cycle_request_id(base),
        desk_cycle_request_id(changed_bars),
        desk_cycle_request_id(changed_quote),
    }

    assert len(identities) == 3

    precise_a = replace(base, bars=pd.DataFrame({"close": [1.0000000000000002]}))
    precise_b = replace(base, bars=pd.DataFrame({"close": [1.0000000000000004]}))
    assert desk_cycle_request_id(precise_a) != desk_cycle_request_id(precise_b)

    with pytest.raises(TypeError, match="string mapping keys"):
        desk_cycle_request_id(replace(base, committee_context={1: "risk-on"}))


def test_stale_account_truth_halts_before_work_is_polled(tmp_path: Path):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()
    stale_account = AccountSnapshot(
        available_cash_paise=10_000_000,
        marked_equity_paise=10_000_000,
        high_water_mark_paise=10_000_000,
        day_pnl_paise=0,
        week_pnl_paise=0,
        positions=(),
        included_reservation_ids=(),
        reconciled=True,
        captured_at=NOW - timedelta(minutes=3),
    )
    truth = healthy_truth(account_snapshot=stale_account)

    class Kernel:
        def enforce(self, *, now):
            return None

    class MustNotPoll:
        def pending(self, *, now):
            raise AssertionError("stale account truth must block polling")

        def run_cycle(self, request):
            raise AssertionError("stale account truth must block agents")

    def compose(journal, configured_gateway):
        stopped = MustNotPoll()
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=Kernel(), cycle_source=stopped, desk=stopped, truth=truth
        )

    result = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
    ).run_session(
        SupervisorSessionRequest(now=NOW, command_id="stale-account-session")
    )

    assert result.state is SupervisorState.HALTED
    assert result.reason_codes == ("ACCOUNT_SNAPSHOT_STALE",)
    assert result.new_entries_allowed is False
    assert result.protective_actions_allowed is True


def test_stale_authenticated_health_halts_before_work_is_polled(tmp_path: Path):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()
    stale_health = OperationalHealth(
        state=HealthState.HEALTHY,
        assessed_at=NOW - timedelta(minutes=3),
        reason_codes=(),
        new_entries_allowed=True,
        protective_actions_allowed=True,
        readiness_event_id="event:stale-readiness",
        readiness_evidence_event_ids=("event:stale-heartbeat",),
        event_id=fake_event_id("stale-health"),
    )
    truth = healthy_truth(health=stale_health)

    class Kernel:
        def enforce(self, *, now):
            return None

    class MustNotPoll:
        def pending(self, *, now):
            raise AssertionError("stale health must block polling")

        def run_cycle(self, request):
            raise AssertionError("stale health must block agents")

    def compose(journal, configured_gateway):
        stopped = MustNotPoll()
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=Kernel(), cycle_source=stopped, desk=stopped, truth=truth
        )

    result = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
    ).run_session(
        SupervisorSessionRequest(now=NOW, command_id="stale-health-session")
    )

    assert result.state is SupervisorState.HALTED
    assert result.reason_codes == ("OPERATIONAL_HEALTH_STALE",)


def test_safety_is_rechecked_between_cycles_and_halts_remaining_work(
    tmp_path: Path,
):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()
    truth = healthy_truth()
    first_cycle = pending_cycle("first-cycle", truth=truth)
    second_cycle = pending_cycle("second-cycle", truth=truth)
    truth = authorize_cycles(truth, first_cycle, second_cycle)
    safety: SafetyView | None = None
    calls: list[str] = []
    first_result = completed_cycle("cycle:first")

    class Kernel:
        def enforce(self, *, now):
            return None

    class CycleSource:
        def pending(self, *, now):
            return (first_cycle, second_cycle)

    class Desk:
        def run_cycle(self, request):
            calls.append(request.command_id)
            if request is not first_cycle:
                raise AssertionError("latched safety must block the second cycle")
            assert safety is not None
            safety._state = SafetyState(
                latched=True,
                reasons=(
                    SafetyReason(
                        reason_code="FIRST_CYCLE_LATCH",
                        detail="first cycle requested containment",
                    ),
                ),
                version=1,
            )
            return first_result

    def compose(journal, configured_gateway):
        nonlocal safety
        safety = SafetyView(journal)
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=Kernel(),
            cycle_source=CycleSource(),
            desk=Desk(),
            truth=truth,
            safety_view=safety,
        )

    result = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
    ).run_session(
        SupervisorSessionRequest(now=NOW, command_id="cycle-safety-recheck")
    )

    assert result.state is SupervisorState.HALTED
    assert result.cycles == (first_result,)
    assert result.reason_codes == ("SAFETY_LATCHED", "FIRST_CYCLE_LATCH")
    assert calls == ["first-cycle"]


def test_cycle_identity_is_rechecked_after_prior_cycle_mutates_queued_facts(
    tmp_path: Path,
):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()
    truth = healthy_truth()
    first_cycle = pending_cycle("identity-first", truth=truth)
    mutable_bars = {"close": [100]}
    second_cycle = replace(
        pending_cycle("identity-second", truth=truth),
        bars=mutable_bars,
    )
    truth = authorize_cycles(truth, first_cycle, second_cycle)
    first_result = completed_cycle("cycle:identity-first")

    class Kernel:
        def enforce(self, *, now):
            return None

    class CycleSource:
        def pending(self, *, now):
            return (first_cycle, second_cycle)

    class Desk:
        def run_cycle(self, request):
            if request is not first_cycle:
                raise AssertionError("mutated second cycle must not run")
            mutable_bars["close"].append(101)
            return first_result

    def compose(journal, configured_gateway):
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=Kernel(),
            cycle_source=CycleSource(),
            desk=Desk(),
            truth=truth,
        )

    result = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
    ).run_session(
        SupervisorSessionRequest(now=NOW, command_id="identity-recheck")
    )

    assert result.state is SupervisorState.HALTED
    assert result.cycles == (first_result,)
    assert result.reason_codes == ("CYCLE_REQUEST_TRUTH_MISMATCH",)


def test_only_one_supervisor_can_own_a_journal_at_a_time(tmp_path: Path):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()

    class Idle:
        def enforce(self, *, now):
            return None

        def pending(self, *, now):
            return ()

        def run_cycle(self, request):
            raise AssertionError("idle desk has no work")

    def compose(journal, configured_gateway):
        idle = Idle()
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=idle,
            cycle_source=idle,
            desk=idle,
        )

    owner = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
    )

    with pytest.raises(SupervisorStartupError) as raised:
        open_supervisor(
            journal_path=journal_path,
            gateway=gateway,
            compose=compose,
        )
    assert raised.value.reason_codes == ("SUPERVISOR_LEASE_UNAVAILABLE",)

    owner.close()
    replacement = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
    )
    replacement.close()


def test_journal_symlink_alias_cannot_acquire_a_second_lease(tmp_path: Path):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    alias_path = tmp_path / "operations-alias.sqlite3"
    alias_path.symlink_to(journal_path)
    gateway = RecordingPaperGateway()

    class Idle:
        def enforce(self, *, now):
            return None

        def pending(self, *, now):
            return ()

        def run_cycle(self, request):
            raise AssertionError("idle desk has no work")

    def compose(journal, configured_gateway):
        idle = Idle()
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=idle,
            cycle_source=idle,
            desk=idle,
        )

    owner = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
    )
    with pytest.raises(SupervisorStartupError) as raised:
        open_supervisor(
            journal_path=alias_path,
            gateway=gateway,
            compose=compose,
        )

    assert raised.value.reason_codes == ("SUPERVISOR_LEASE_UNAVAILABLE",)
    owner.close()


def test_journal_hard_link_alias_cannot_acquire_a_second_lease(tmp_path: Path):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    alias_path = tmp_path / "operations-hard-link.sqlite3"
    os.link(journal_path, alias_path)
    gateway = RecordingPaperGateway()

    class Idle:
        def enforce(self, *, now):
            return None

        def pending(self, *, now):
            return ()

        def run_cycle(self, request):
            raise AssertionError("idle desk has no work")

    def compose(journal, configured_gateway):
        idle = Idle()
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=idle,
            cycle_source=idle,
            desk=idle,
        )

    owner = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
    )
    with pytest.raises(SupervisorStartupError) as raised:
        open_supervisor(
            journal_path=alias_path,
            gateway=gateway,
            compose=compose,
        )

    assert raised.value.reason_codes == ("SUPERVISOR_LEASE_UNAVAILABLE",)
    owner.close()


def test_one_supervisor_object_serializes_run_shutdown_and_close(tmp_path: Path):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()
    entered = Event()
    release = Event()

    class BlockingKernel:
        def __init__(self):
            self.calls = 0

        def enforce(self, *, now):
            self.calls += 1
            if self.calls == 1:
                entered.set()
                assert release.wait(timeout=2)

    class Idle:
        def pending(self, *, now):
            return ()

        def run_cycle(self, request):
            raise AssertionError("idle desk has no work")

    kernel = BlockingKernel()

    def compose(journal, configured_gateway):
        idle = Idle()
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=kernel,
            cycle_source=idle,
            desk=idle,
        )

    supervisor = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
    )
    results: list[SupervisorResult] = []
    failures: list[BaseException] = []

    def run() -> None:
        try:
            results.append(
                supervisor.run_session(
                    SupervisorSessionRequest(now=NOW, command_id="owner-run")
                )
            )
        except BaseException as exc:
            failures.append(exc)

    runner = Thread(target=run)
    runner.start()
    assert entered.wait(timeout=2)

    with pytest.raises(SupervisorStartupError) as concurrent_run:
        supervisor.run_session(
            SupervisorSessionRequest(now=NOW, command_id="second-run")
        )
    assert concurrent_run.value.reason_codes == ("SUPERVISOR_BUSY",)

    with pytest.raises(SupervisorStartupError) as concurrent_shutdown:
        supervisor.shutdown(
            SupervisorShutdownRequest(
                now=NOW,
                command_id="stop-during-run",
                reason="operator stop",
            )
        )
    assert concurrent_shutdown.value.reason_codes == ("SUPERVISOR_BUSY",)

    closed = Event()

    def close() -> None:
        supervisor.close()
        closed.set()

    closer = Thread(target=close)
    closer.start()
    assert not closed.wait(timeout=0.05)
    release.set()
    runner.join(timeout=2)
    closer.join(timeout=2)

    assert not failures
    assert len(results) == 1
    assert results[0].state is SupervisorState.COMPLETED
    assert closed.is_set()


def test_normal_shutdown_is_durable_idempotent_and_releases_the_lease(
    tmp_path: Path,
):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()

    class Idle:
        def enforce(self, *, now):
            return None

        def pending(self, *, now):
            return ()

        def run_cycle(self, request):
            raise AssertionError("idle desk has no work")

    def compose(journal, configured_gateway):
        idle = Idle()
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=idle,
            cycle_source=idle,
            desk=idle,
        )

    request = SupervisorShutdownRequest(
        now=NOW,
        command_id="operator-stop-1",
        reason="planned maintenance",
    )
    owner = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
    )
    first = owner.shutdown(request)

    with pytest.raises(SupervisorStartupError) as closed:
        owner.run_session(
            SupervisorSessionRequest(now=NOW, command_id="must-not-run")
        )
    assert closed.value.reason_codes == ("SUPERVISOR_CLOSED",)

    replacement = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
    )
    replayed = replacement.shutdown(request)

    assert replayed == first


def test_shutdown_reverifies_journal_and_releases_lease_on_corruption(
    tmp_path: Path,
):
    journal_path = tmp_path / "operations.sqlite3"
    journal = OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()

    class Idle:
        def enforce(self, *, now):
            return None

        def pending(self, *, now):
            return ()

        def run_cycle(self, request):
            raise AssertionError("idle desk has no work")

    def compose(opened_journal, configured_gateway):
        idle = Idle()
        return composition_fixture(
            opened_journal,
            configured_gateway,
            kernel=idle,
            cycle_source=idle,
            desk=idle,
        )

    owner = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
    )
    event = journal.append(
        EventAppend(
            stream_id="operations:test",
            event_type="TestFactRecorded",
            payload={"state": "original"},
            idempotency_key="test-after-supervisor-open",
            expected_version=0,
            occurred_at=NOW,
        )
    )
    with sqlite3.connect(journal_path) as connection:
        connection.execute("DROP TRIGGER journal_events_no_update")
        connection.execute(
            "UPDATE journal_events SET payload_json = ? WHERE event_id = ?",
            ('{"state":"tampered"}', event.event_id),
        )

    with pytest.raises(SupervisorStartupError) as raised:
        owner.shutdown(
            SupervisorShutdownRequest(
                now=NOW,
                command_id="unsafe-stop",
                reason="operator requested stop",
            )
        )

    assert raised.value.reason_codes == ("JOURNAL_INTEGRITY_FAILED",)
    with pytest.raises(SupervisorStartupError) as reopened:
        open_supervisor(
            journal_path=journal_path,
            gateway=gateway,
            compose=compose,
        )
    assert reopened.value.reason_codes == ("JOURNAL_INTEGRITY_FAILED",)


@pytest.mark.parametrize(
    ("truth", "safety_state", "expected_reasons"),
    (
        (
            healthy_truth(
                health=OperationalHealth(
                    state=HealthState.HALTED,
                    assessed_at=NOW,
                    reason_codes=("MARKET_DATA_DEGRADED",),
                    new_entries_allowed=False,
                    protective_actions_allowed=True,
                    readiness_event_id="event:degraded-readiness",
                    readiness_evidence_event_ids=("event:degraded-heartbeat",),
                    event_id=fake_event_id("degraded-health"),
                )
            ),
            None,
            ("MARKET_DATA_DEGRADED",),
        ),
        (
            healthy_truth(),
            SafetyState(
                latched=True,
                reasons=(
                    SafetyReason(
                        reason_code="MANUAL_KILL",
                        detail="owner stopped new entries",
                    ),
                ),
                version=1,
            ),
            ("SAFETY_LATCHED", "MANUAL_KILL"),
        ),
    ),
)
def test_degraded_health_or_existing_safety_latch_blocks_work_but_not_protection(
    tmp_path: Path,
    truth: SessionTruth,
    safety_state: SafetyState | None,
    expected_reasons: tuple[str, ...],
):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()
    enforcement_calls: list[datetime] = []

    class Kernel:
        def enforce(self, *, now):
            enforcement_calls.append(now)

    class MustNotPoll:
        def pending(self, *, now):
            raise AssertionError("containment must block new work")

        def run_cycle(self, request):
            raise AssertionError("containment must block agents")

    def compose(journal, configured_gateway):
        stopped = MustNotPoll()
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=Kernel(),
            cycle_source=stopped,
            desk=stopped,
            truth=truth,
            safety_state=safety_state,
        )

    result = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=compose,
    ).run_session(
        SupervisorSessionRequest(
            now=NOW,
            command_id="containment-" + expected_reasons[0].lower(),
        )
    )

    assert result.state is SupervisorState.HALTED
    assert result.reason_codes == expected_reasons
    assert result.new_entries_allowed is False
    assert result.protective_actions_allowed is True
    assert result.reconciliation is not None
    assert enforcement_calls == [NOW, NOW]
    assert result.reconciliation.clean is True


def test_replayed_halt_runs_protective_recovery_without_rerunning_agents(
    tmp_path: Path,
):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    gateway = RecordingPaperGateway()
    degraded = healthy_truth(
        health=OperationalHealth(
            state=HealthState.HALTED,
            assessed_at=NOW,
            reason_codes=("MARKET_DATA_DEGRADED",),
            new_entries_allowed=False,
            protective_actions_allowed=True,
            readiness_event_id=fake_event_id("replay-halt-readiness"),
            readiness_evidence_event_ids=(
                fake_event_id("replay-halt-heartbeat"),
            ),
            event_id=fake_event_id("replay-halt-health"),
        )
    )

    class FirstKernel:
        def enforce(self, *, now):
            return None

    class MustNotWork:
        def pending(self, *, now):
            raise AssertionError("halted truth must not poll")

        def run_cycle(self, request):
            raise AssertionError("halted truth must not run agents")

    def first_composition(journal, configured_gateway):
        stopped = MustNotWork()
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=FirstKernel(),
            cycle_source=stopped,
            desk=stopped,
            truth=degraded,
        )

    request = SupervisorSessionRequest(now=NOW, command_id="replayed-halt")
    first_owner = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=first_composition,
    )
    first = first_owner.run_session(request)
    first_owner.close()

    recovery: list[datetime] = []

    class ReplayKernel:
        def enforce(self, *, now):
            recovery.append(now)

    def replay_composition(journal, configured_gateway):
        stopped = MustNotWork()
        return composition_fixture(
            journal,
            configured_gateway,
            kernel=ReplayKernel(),
            cycle_source=stopped,
            desk=stopped,
            truth=degraded,
        )

    replay_owner = open_supervisor(
        journal_path=journal_path,
        gateway=gateway,
        compose=replay_composition,
    )
    replayed = replay_owner.run_session(request)
    replay_owner.close()

    assert replayed == first
    assert recovery == [NOW]
