from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from sensei.kernel import (
    BrokerSnapshotAuthority,
    EntryCommand,
    ProtectionCommand,
    RecordingPaperGateway,
)
from sensei.operations import (
    ComponentState,
    HmacFactSigner,
    HmacFactVerifier,
    OperationalJournal,
    OperationsControlPlane,
)
from sensei.operations.health import OperationsMonitor
from sensei.orchestration import (
    DeskCycleRequest,
    ExecutableQuote,
    StrategyEvidenceStats,
)
from sensei.portfolio_risk import AccountSnapshotAuthority, SafetyControl
from sensei.runtime import (
    ComponentCheckResult,
    PaperAccountProjector,
    PaperSessionInputs,
)


NOW = datetime(2026, 7, 16, 4, 0, tzinfo=timezone.utc)
ACCOUNT_SECRET = b"paper-account-adapter-secret-at-least-32-bytes"
BROKER_SECRET = b"paper-broker-adapter-secret-at-least-32-bytes"
MONITOR_SECRET = b"paper-operations-monitor-secret-at-least-32-bytes"
COMPONENT_SECRETS = {
    component: f"{component}-paper-check-secret-at-least-32-bytes".encode()
    for component in ("market-data", "paper-gateway", "reconciliation")
}


@dataclass(frozen=True)
class _SessionFixture:
    inputs: PaperSessionInputs
    journal: OperationalJournal
    account_authority: AccountSnapshotAuthority
    broker_authority: BrokerSnapshotAuthority
    operations_monitor: OperationsMonitor
    check_states: dict[str, ComponentCheckResult]
    safety: SafetyControl


def _filled_and_protected_gateway(tmp_path) -> tuple[
    RecordingPaperGateway,
    EntryCommand,
]:
    gateway = RecordingPaperGateway(
        OperationalJournal(tmp_path / "journal.sqlite3"),
        auto_fill_at_limit=True,
        clock=lambda: NOW,
    )
    entry = EntryCommand(
        intent_id="intent:paper-account-infy",
        instrument_id="INFY",
        quantity=4,
        limit_price_paise=150_000,
    )
    gateway.execute(entry)
    gateway.execute(
        ProtectionCommand(
            intent_id=entry.intent_id,
            instrument_id=entry.instrument_id,
            quantity=entry.quantity,
            stop_price_paise=145_000,
            target_price_paise=160_000,
        )
    )
    return gateway, entry


def test_account_projector_marks_durable_fills_and_protected_risk(tmp_path):
    gateway, entry = _filled_and_protected_gateway(tmp_path)
    projector = PaperAccountProjector(
        gateway,
        starting_capital_paise=10_000_000,
        high_water_mark_paise=10_000_000,
        day_pnl_paise=8_000,
        week_pnl_paise=12_000,
    )

    snapshot = projector.project(
        captured_at=NOW,
        mark_prices_paise={"INFY": 152_000},
    )

    assert snapshot.available_cash_paise == 9_400_000
    assert snapshot.marked_equity_paise == 10_008_000
    assert snapshot.high_water_mark_paise == 10_008_000
    assert snapshot.day_pnl_paise == 8_000
    assert snapshot.week_pnl_paise == 12_000
    assert snapshot.included_reservation_ids == (
        f"reservation:{entry.intent_id.removeprefix('intent:')}",
    )
    assert len(snapshot.positions) == 1
    position = snapshot.positions[0]
    assert position.instrument_id == "INFY"
    assert position.quantity == 4
    assert position.notional_paise == 608_000
    assert position.risk_to_stop_paise == 28_000


def test_account_projector_keeps_a_new_high_water_mark_monotonic(tmp_path):
    gateway, _ = _filled_and_protected_gateway(tmp_path)
    projector = PaperAccountProjector(
        gateway,
        starting_capital_paise=10_000_000,
        high_water_mark_paise=10_000_000,
    )

    peak = projector.project(
        captured_at=NOW,
        mark_prices_paise={"INFY": 152_000},
    )
    below_peak = projector.project(
        captured_at=NOW + timedelta(seconds=1),
        mark_prices_paise={"INFY": 149_000},
    )

    assert peak.high_water_mark_paise == 10_008_000
    assert below_peak.marked_equity_paise == 9_996_000
    assert below_peak.high_water_mark_paise == peak.high_water_mark_paise


def test_account_projector_fails_closed_without_a_current_position_mark(tmp_path):
    gateway, _ = _filled_and_protected_gateway(tmp_path)
    projector = PaperAccountProjector(
        gateway,
        starting_capital_paise=10_000_000,
        high_water_mark_paise=10_000_000,
    )

    with pytest.raises(RuntimeError, match="current mark is missing for INFY"):
        projector.project(captured_at=NOW, mark_prices_paise={})


def test_account_projector_fails_closed_on_unprotected_exposure(tmp_path):
    gateway = RecordingPaperGateway(
        OperationalJournal(tmp_path / "journal.sqlite3"),
        auto_fill_at_limit=True,
        clock=lambda: NOW,
    )
    gateway.execute(
        EntryCommand(
            intent_id="intent:unprotected-infy",
            instrument_id="INFY",
            quantity=4,
            limit_price_paise=150_000,
        )
    )
    projector = PaperAccountProjector(
        gateway,
        starting_capital_paise=10_000_000,
        high_water_mark_paise=10_000_000,
    )

    with pytest.raises(RuntimeError, match="protection is missing for INFY"):
        projector.project(
            captured_at=NOW,
            mark_prices_paise={"INFY": 152_000},
        )


def test_account_projector_fails_closed_before_negative_cash(tmp_path):
    gateway, _ = _filled_and_protected_gateway(tmp_path)
    projector = PaperAccountProjector(
        gateway,
        starting_capital_paise=500_000,
        high_water_mark_paise=500_000,
    )

    with pytest.raises(RuntimeError, match="unknown negative cash"):
        projector.project(
            captured_at=NOW,
            mark_prices_paise={"INFY": 152_000},
        )


def _paper_session_inputs(tmp_path):
    journal = OperationalJournal(tmp_path / "runtime.sqlite3")
    gateway = RecordingPaperGateway(journal, clock=lambda: NOW)
    projector = PaperAccountProjector(
        gateway,
        starting_capital_paise=10_000_000,
        high_water_mark_paise=10_000_000,
    )
    account_authority = AccountSnapshotAuthority(
        journal,
        HmacFactVerifier({"paper-account": ACCOUNT_SECRET}),
        expected_issuer_id="paper-account",
    )
    broker_authority = BrokerSnapshotAuthority(
        journal,
        HmacFactVerifier({"paper-gateway": BROKER_SECRET}),
        expected_issuer_id="paper-gateway",
    )
    control_plane = OperationsControlPlane(
        journal,
        HmacFactVerifier(COMPONENT_SECRETS),
    )
    required_components = {
        component: timedelta(minutes=1) for component in COMPONENT_SECRETS
    }
    operations_monitor = OperationsMonitor(
        journal,
        control_plane=control_plane,
        required_components=required_components,
        maximum_readiness_age=timedelta(minutes=1),
        signer=HmacFactSigner("operations-monitor", MONITOR_SECRET),
        verifier=HmacFactVerifier({"operations-monitor": MONITOR_SECRET}),
    )
    safety = SafetyControl(journal)
    check_states = {
        component: ComponentCheckResult(ComponentState.HEALTHY, "check passed")
        for component in COMPONENT_SECRETS
    }

    def check_for(component):
        def check(*, now):
            assert now.tzinfo is not None
            return check_states[component]

        return check

    def mark_prices(*, instrument_ids, now):
        assert now.tzinfo is not None
        return {instrument_id: 152_000 for instrument_id in instrument_ids}

    inputs = PaperSessionInputs(
        journal=journal,
        gateway=gateway,
        account_projector=projector,
        mark_price_source=mark_prices,
        account_authority=account_authority,
        account_signer=HmacFactSigner("paper-account", ACCOUNT_SECRET),
        broker_authority=broker_authority,
        broker_signer=HmacFactSigner("paper-gateway", BROKER_SECRET),
        control_plane=control_plane,
        operations_monitor=operations_monitor,
        safety=safety,
        required_components=required_components,
        component_checks={
            component: check_for(component) for component in COMPONENT_SECRETS
        },
        component_signers={
            component: HmacFactSigner(component, secret)
            for component, secret in COMPONENT_SECRETS.items()
        },
        maximum_pin_age=timedelta(seconds=30),
    )
    return _SessionFixture(
        inputs=inputs,
        journal=journal,
        account_authority=account_authority,
        broker_authority=broker_authority,
        operations_monitor=operations_monitor,
        check_states=check_states,
        safety=safety,
    )


def _cycle_builder(*, account_snapshot, operational_health, now, command_id):
    return DeskCycleRequest(
        lineage_id="paper-lineage",
        plan=SimpleNamespace(plan_id="plan:paper-runtime"),
        bars=None,
        evaluation_session=now.date(),
        decision_market_snapshot_id="snapshot:paper-decision",
        quote=ExecutableQuote(
            instrument_id="INFY",
            snapshot_id="quote:paper-open",
            worst_entry_price_paise=150_000,
            observed_at=now,
        ),
        account_snapshot=account_snapshot,
        operational_health=operational_health,
        signal_observed_at=now,
        now=now,
        command_id=f"{command_id}:cycle",
        strategy_stats=StrategyEvidenceStats(
            expectancy_pct=1.0,
            hit_rate=0.5,
            trades=100,
        ),
        committee_context={},
    )


def test_session_inputs_prepare_authenticated_exact_single_cycle(tmp_path):
    fixture = _paper_session_inputs(tmp_path)

    prepared = fixture.inputs.prepare(
        now=NOW,
        command_id="scheduled-paper-session-1",
        cycle_builder=_cycle_builder,
    )
    truth = fixture.inputs.capture(
        now=NOW + timedelta(seconds=1),
        command_id="scheduled-paper-session-1:truth",
    )
    pending = fixture.inputs.pending(now=NOW + timedelta(seconds=1))

    assert truth is prepared.truth
    assert len(pending) == 1
    assert pending[0] is prepared.request
    assert pending[0].account_snapshot is truth.account_snapshot
    assert pending[0].operational_health is truth.operational_health
    assert truth.authorized_cycle_request_ids == (prepared.request_id,)
    assert fixture.account_authority.verify(
        truth.account_snapshot_event_id,
        snapshot=truth.account_snapshot,
        no_later_than=NOW + timedelta(seconds=1),
    )
    assert fixture.broker_authority.verify(
        truth.broker_snapshot_event_id,
        snapshot=truth.broker_snapshot,
        no_later_than=NOW + timedelta(seconds=1),
    )
    assert fixture.operations_monitor.verify(
        truth.operational_health,
        no_later_than=NOW + timedelta(seconds=1),
    )
    assert fixture.inputs.pending(now=NOW + timedelta(seconds=2)) == ()


def test_session_inputs_records_degraded_check_and_prepares_no_work(tmp_path):
    fixture = _paper_session_inputs(tmp_path)
    fixture.check_states["market-data"] = ComponentCheckResult(
        ComponentState.DEGRADED,
        "market vendor lagged",
    )

    def must_not_build(**kwargs):
        raise AssertionError("an unhealthy session must not build a cycle")

    prepared = fixture.inputs.prepare(
        now=NOW,
        command_id="scheduled-paper-session-degraded",
        cycle_builder=must_not_build,
    )

    assert prepared.request is None
    assert prepared.truth.operational_health.new_entries_allowed is False
    assert "MARKET-DATA_DEGRADED" in (
        prepared.truth.operational_health.reason_codes
    )
    assert fixture.inputs.pending(now=NOW) == ()
    market_heartbeat = next(
        event
        for event in fixture.journal.read_all()
        if event.event_type == "ComponentHeartbeatRecorded"
        and event.payload["fact"]["component"] == "market-data"
    )
    assert market_heartbeat.payload["fact"]["state"] == "DEGRADED"


def test_capture_rebuilds_unissued_cycle_when_checked_facts_change(tmp_path):
    fixture = _paper_session_inputs(tmp_path)
    original = fixture.inputs.prepare(
        now=NOW,
        command_id="scheduled-paper-session-rebuild",
        cycle_builder=_cycle_builder,
    )
    fixture.check_states["market-data"] = ComponentCheckResult(
        ComponentState.HEALTHY,
        "second independent check passed",
    )

    refreshed_truth = fixture.inputs.capture(
        now=NOW + timedelta(seconds=1),
        command_id="scheduled-paper-session-rebuild:truth",
    )
    pending = fixture.inputs.pending(now=NOW + timedelta(seconds=1))

    assert refreshed_truth is not original.truth
    assert len(pending) == 1
    assert pending[0] is not original.request
    assert pending[0].account_snapshot is refreshed_truth.account_snapshot
    assert pending[0].operational_health is refreshed_truth.operational_health


def test_capture_invalidates_issued_cycle_when_checked_facts_change(tmp_path):
    fixture = _paper_session_inputs(tmp_path)
    prepared = fixture.inputs.prepare(
        now=NOW,
        command_id="scheduled-paper-session-invalidate",
        cycle_builder=_cycle_builder,
    )
    assert fixture.inputs.pending(now=NOW) == (prepared.request,)
    fixture.check_states["reconciliation"] = ComponentCheckResult(
        ComponentState.HALTED,
        "broker reconciliation mismatch",
    )

    refreshed_truth = fixture.inputs.capture(
        now=NOW + timedelta(seconds=1),
        command_id="scheduled-paper-session-invalidate:truth:before-dispatch",
    )

    assert refreshed_truth is not prepared.truth
    assert refreshed_truth.operational_health.new_entries_allowed is False
    assert "RECONCILIATION_HALTED" in (
        refreshed_truth.operational_health.reason_codes
    )
    assert refreshed_truth.authorized_cycle_request_ids == ()
    assert fixture.inputs.pending(now=NOW + timedelta(seconds=1)) == ()


def test_capture_invalidates_issued_cycle_when_safety_latches(tmp_path):
    fixture = _paper_session_inputs(tmp_path)
    prepared = fixture.inputs.prepare(
        now=NOW,
        command_id="scheduled-paper-session-safety",
        cycle_builder=_cycle_builder,
    )
    assert fixture.inputs.pending(now=NOW) == (prepared.request,)
    fixture.safety.latch(
        reason_code="OWNER_HALT",
        detail="owner stopped new exposure",
        occurred_at=NOW + timedelta(seconds=1),
        idempotency_key="paper-session-owner-halt",
    )

    refreshed_truth = fixture.inputs.capture(
        now=NOW + timedelta(seconds=1),
        command_id="scheduled-paper-session-safety:truth:before-dispatch",
    )

    assert refreshed_truth.operational_health.new_entries_allowed is False
    assert "SAFETY_LATCHED" in refreshed_truth.operational_health.reason_codes
    assert refreshed_truth.authorized_cycle_request_ids == ()


def test_capture_reauthenticates_and_rebuilds_after_pin_expires(tmp_path):
    fixture = _paper_session_inputs(tmp_path)
    prepared = fixture.inputs.prepare(
        now=NOW,
        command_id="scheduled-paper-session-expiry",
        cycle_builder=_cycle_builder,
    )

    refreshed_truth = fixture.inputs.capture(
        now=NOW + timedelta(seconds=31),
        command_id="scheduled-paper-session-expiry:truth",
    )
    pending = fixture.inputs.pending(now=NOW + timedelta(seconds=31))

    assert refreshed_truth is not prepared.truth
    assert len(pending) == 1
    assert pending[0].account_snapshot is refreshed_truth.account_snapshot
    assert pending[0].operational_health is refreshed_truth.operational_health


def test_empty_poll_does_not_prevent_rebuild_after_health_recovers(tmp_path):
    fixture = _paper_session_inputs(tmp_path)
    fixture.check_states["market-data"] = ComponentCheckResult(
        ComponentState.DEGRADED,
        "market vendor lagged",
    )
    prepared = fixture.inputs.prepare(
        now=NOW,
        command_id="scheduled-paper-session-recovery",
        cycle_builder=_cycle_builder,
    )
    assert prepared.request is None
    assert fixture.inputs.pending(now=NOW) == ()
    fixture.check_states["market-data"] = ComponentCheckResult(
        ComponentState.HEALTHY,
        "market vendor recovered",
    )

    refreshed_truth = fixture.inputs.capture(
        now=NOW + timedelta(seconds=1),
        command_id="scheduled-paper-session-recovery:truth",
    )

    assert refreshed_truth.operational_health.new_entries_allowed is True
    assert len(fixture.inputs.pending(now=NOW + timedelta(seconds=1))) == 1
