from datetime import datetime, timedelta, timezone

import pytest

from sensei.kernel import (
    BrokerPosition,
    BrokerProtection,
    BrokerSnapshot,
    BrokerSnapshotAuthority,
    BrokerWorkingOrder,
    CancelEntryCommand,
    CommandKind,
    EntryCommand,
    KernelAdmissionAuthority,
    ProtectionCommand,
    RecordingPaperGateway,
    TradingKernel,
)
from sensei.operations import HmacFactSigner, HmacFactVerifier, OperationalJournal
from sensei.portfolio_risk import (
    AccountSnapshot,
    PortfolioRisk,
    RiskLimits,
    SafetyControl,
    SafetyResetAuthority,
    TradeIntent,
)


NOW = datetime(2026, 7, 13, 4, 0, tzinfo=timezone.utc)
ADMISSION_SECRET = b"paper-admission-test-secret-at-least-32b"
BROKER_SECRET = b"paper-gateway-snapshot-test-secret-32bytes"
RECONCILIATION_SECRET = b"kernel-reconciler-test-secret-at-least-32b"
OWNER_SECRET = b"kernel-owner-test-secret-at-least-32-bytes"


def _intent(symbol: str = "INFY", quantity: int = 10) -> TradeIntent:
    account = _account()
    return TradeIntent(
        strategy_plan_id="plan:hammer-v1",
        decision_trace_id=f"trace:{symbol.lower()}",
        market_snapshot_id="snapshot:market-1",
        account_snapshot_id=account.snapshot_id,
        instrument_id=symbol,
        quantity=quantity,
        limit_price_paise=150_000,
        stop_price_paise=145_000,
        target_price_paise=160_000,
        created_at=NOW,
    )


def _account() -> AccountSnapshot:
    return AccountSnapshot(
        available_cash_paise=10_000_000,
        marked_equity_paise=10_000_000,
        high_water_mark_paise=10_000_000,
        day_pnl_paise=0,
        week_pnl_paise=0,
        positions=(),
        included_reservation_ids=(),
        reconciled=True,
        captured_at=NOW,
    )


def _kernel(tmp_path, gateway=None, after_command_completed=None):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    risk = PortfolioRisk(
        journal,
        RiskLimits(
            max_total_notional_paise=10_000_000,
            max_position_notional_paise=3_000_000,
            max_risk_per_trade_paise=100_000,
            max_total_risk_paise=500_000,
            max_open_positions=3,
            snapshot_max_age=timedelta(minutes=2),
            max_daily_loss_paise=500_000,
            max_weekly_loss_paise=1_000_000,
            max_drawdown_bps=2_000,
        ),
    )
    reset_authority = SafetyResetAuthority(
        journal,
        owner_verifier=HmacFactVerifier({"kernel-owner": OWNER_SECRET}),
        reconciliation_verifier=HmacFactVerifier(
            {"kernel-reconciler": RECONCILIATION_SECRET}
        ),
        expected_reconciliation_issuer_id="kernel-reconciler",
    )
    safety = SafetyControl(journal, reset_authority=reset_authority)
    paper = gateway or RecordingPaperGateway()
    admission_authority = KernelAdmissionAuthority(
        journal,
        HmacFactVerifier({"paper-admission": ADMISSION_SECRET}),
    )
    broker_authority = BrokerSnapshotAuthority(
        journal,
        HmacFactVerifier({"paper-gateway": BROKER_SECRET}),
        expected_issuer_id="paper-gateway",
    )
    return (
        TradingKernel(
            journal,
            risk,
            safety,
            paper,
            admission_authority=admission_authority,
            broker_snapshot_authority=broker_authority,
            safety_reset_authority=reset_authority,
            reconciliation_signer=HmacFactSigner(
                "kernel-reconciler", RECONCILIATION_SECRET
            ),
            after_command_completed=after_command_completed,
        ),
        paper,
        safety,
        journal,
    )


def _accept(kernel, journal, intent):
    authority = KernelAdmissionAuthority(
        journal,
        HmacFactVerifier({"paper-admission": ADMISSION_SECRET}),
    )
    suffix = intent.intent_id.removeprefix("intent:")
    admission = authority.issue(
        intent,
        lineage_id="kernel-test-lineage",
        trace_attestation_event_id="event:" + "1" * 64,
        lifecycle_event_id="event:" + "2" * 64,
        health_event_id="event:" + "3" * 64,
        committee_event_id="event:" + "4" * 64,
        committee_approval_id="approval:" + "5" * 64,
        verdict_evidence_event_ids=tuple(
            "event:" + str(number) * 64 for number in range(5, 9)
        ),
        provenance_claim_ids=("claim:" + "9" * 64,),
        signer=HmacFactSigner("paper-admission", ADMISSION_SECRET),
        occurred_at=NOW,
        command_id=f"authorize-{suffix}",
    )
    return kernel.accept(
        intent,
        admission_event_id=admission.event_id,
        occurred_at=NOW,
    )


def _reconcile(kernel, journal, snapshot):
    authority = BrokerSnapshotAuthority(
        journal,
        HmacFactVerifier({"paper-gateway": BROKER_SECRET}),
        expected_issuer_id="paper-gateway",
    )
    evidence = authority.record(
        snapshot,
        signer=HmacFactSigner("paper-gateway", BROKER_SECRET),
        occurred_at=NOW,
        command_id=f"observe-{snapshot.snapshot_id}",
    )
    return kernel.reconcile(
        snapshot,
        snapshot_event_id=evidence.event_id,
        now=NOW,
    )


def test_kernel_rejects_intent_without_authenticated_admission(tmp_path):
    kernel, _, _, _ = _kernel(tmp_path)

    with pytest.raises(ValueError, match="authenticated paper admission"):
        kernel.accept(
            _intent(),
            admission_event_id="event:" + "0" * 64,
            occurred_at=NOW,
        )


def test_accept_only_journals_and_run_once_uses_durable_outbox(tmp_path):
    kernel, gateway, _, journal = _kernel(tmp_path)
    accepted = _accept(kernel, journal, _intent())

    assert accepted.intent_id == _intent().intent_id
    assert gateway.commands == ()
    assert any(e.event_type == "TradeIntentAccepted" for e in journal.read_stream("kernel:paper"))

    kernel.run_once(_account(), now=NOW)
    entries = [c for c in gateway.commands if c.kind is CommandKind.ENTRY]
    assert len(entries) == 1
    assert isinstance(entries[0], EntryCommand)

    # Restarting against the journal must not send a completed command again.
    restarted, _, _, _ = _kernel(tmp_path, gateway)
    restarted.run_once(_account(), now=NOW)
    assert [c.command_id for c in gateway.commands].count(entries[0].command_id) == 1


def test_partial_entry_fill_is_protected_before_another_entry(tmp_path):
    gateway = RecordingPaperGateway()
    gateway.queue_entry_fill(cumulative_quantity=4, average_price_paise=149_500)
    kernel, gateway, _, journal = _kernel(tmp_path, gateway)
    _accept(kernel, journal, _intent("INFY", 10))
    _accept(kernel, journal, _intent("TCS", 5))

    kernel.run_once(_account(), now=NOW)

    commands = gateway.commands
    first_entry_index = next(i for i, c in enumerate(commands) if c.kind is CommandKind.ENTRY)
    protection_index = next(i for i, c in enumerate(commands) if c.kind is CommandKind.PROTECTION)
    entry_indexes = [i for i, c in enumerate(commands) if c.kind is CommandKind.ENTRY]
    assert first_entry_index < protection_index
    assert commands[protection_index].quantity == 4
    assert len(entry_indexes) == 2
    assert protection_index < entry_indexes[1]


def test_cancel_entry_is_typed_and_allowed_while_safety_is_latched(tmp_path):
    kernel, gateway, safety, journal = _kernel(tmp_path)
    intent = _accept(kernel, journal, _intent())
    kernel.run_once(_account(), now=NOW)
    safety.latch(
        reason_code="OWNER_HALT",
        detail="manual stop",
        occurred_at=NOW,
        idempotency_key="owner-halt-1",
    )
    kernel.cancel_entry(intent.intent_id, occurred_at=NOW)

    kernel.run_once(_account(), now=NOW)

    assert sum(command.kind is CommandKind.ENTRY for command in gateway.commands) == 1
    assert any(command.kind is CommandKind.CANCEL_ENTRY for command in gateway.commands)


def test_reconciliation_quarantines_unknown_or_unprotected_exposure(tmp_path):
    kernel, _, safety, journal = _kernel(tmp_path)
    report = _reconcile(
        kernel,
        journal,
        BrokerSnapshot(
            captured_at=NOW,
            positions=(BrokerPosition("UNKNOWN", 3), BrokerPosition("INFY", 4)),
            protections=(
                BrokerProtection(
                    "INFY",
                    2,
                    stop_price_paise=145_000,
                    target_price_paise=160_000,
                    client_command_id=None,
                ),
            ),
        ),
    )

    assert report.clean is False
    assert any("unknown" in issue.lower() for issue in report.issues)
    assert any("unprotected" in issue.lower() for issue in report.issues)
    assert safety.state().latched is True
    assert any(e.event_type == "QuarantineRaised" for e in journal.read_stream("kernel:paper"))


def test_reconciliation_rejects_an_unauthenticated_broker_snapshot(tmp_path):
    kernel, _, _, _ = _kernel(tmp_path)

    with pytest.raises(ValueError, match="authenticated broker snapshot"):
        kernel.reconcile(
            BrokerSnapshot(captured_at=NOW, positions=(), protections=()),
            snapshot_event_id="event:" + "0" * 64,
            now=NOW,
        )


def test_restart_recovers_fill_from_completed_receipt_before_protection_event(tmp_path):
    class SimulatedProcessCrash(RuntimeError):
        pass

    def crash_after_durable_completion(command, receipt):
        if isinstance(command, EntryCommand) and receipt.cumulative_fill_quantity:
            raise SimulatedProcessCrash("after completion append")

    gateway = RecordingPaperGateway()
    gateway.queue_entry_fill(cumulative_quantity=4, average_price_paise=149_500)
    kernel, gateway, _, journal = _kernel(
        tmp_path,
        gateway,
        after_command_completed=crash_after_durable_completion,
    )
    _accept(kernel, journal, _intent("INFY", 10))

    with pytest.raises(SimulatedProcessCrash, match="completion append"):
        kernel.run_once(_account(), now=NOW)

    event_types = [event.event_type for event in journal.read_stream("kernel:paper")]
    assert "BrokerCommandCompleted" in event_types
    assert "EntryFillObserved" not in event_types
    assert not any(isinstance(command, ProtectionCommand) for command in gateway.commands)

    restarted, _, _, journal = _kernel(tmp_path, gateway)
    restarted.run_once(_account(), now=NOW)

    assert sum(isinstance(command, EntryCommand) for command in gateway.commands) == 1
    protections = [
        command
        for command in gateway.commands
        if isinstance(command, ProtectionCommand)
    ]
    assert len(protections) == 1
    assert protections[0].quantity == 4
    assert any(
        event.event_type == "EntryFillObserved"
        for event in journal.read_stream("kernel:paper")
    )


def test_protection_failure_latches_and_cancels_unfilled_entry_remainder(tmp_path):
    class FailingProtectionGateway(RecordingPaperGateway):
        def __init__(self):
            super().__init__()
            self.failed = False

        def execute(self, command):
            if isinstance(command, ProtectionCommand) and not self.failed:
                self.failed = True
                raise RuntimeError("protective order rejected")
            return super().execute(command)

    gateway = FailingProtectionGateway()
    gateway.queue_entry_fill(cumulative_quantity=4, average_price_paise=149_500)
    kernel, gateway, safety, journal = _kernel(tmp_path, gateway)
    _accept(kernel, journal, _intent("INFY", 10))
    _accept(kernel, journal, _intent("TCS", 5))

    with pytest.raises(RuntimeError, match="protective order rejected"):
        kernel.run_once(_account(), now=NOW)

    assert safety.state().latched is True
    entries = [command for command in gateway.commands if isinstance(command, EntryCommand)]
    cancellations = [
        command
        for command in gateway.commands
        if isinstance(command, CancelEntryCommand)
    ]
    assert len(entries) == 1
    assert entries[0].instrument_id == "INFY"
    assert len(cancellations) == 1
    assert cancellations[0].remaining_quantity == 6
    prepared_kinds = [
        event.payload["command"]["kind"]
        for event in journal.read_stream("kernel:paper")
        if event.event_type == "BrokerCommandPrepared"
    ]
    assert CommandKind.PROTECTION.value in prepared_kinds
    assert CommandKind.CANCEL_ENTRY.value in prepared_kinds


def test_reconciliation_quarantines_unknown_working_broker_order(tmp_path):
    kernel, _, safety, journal = _kernel(tmp_path)
    report = _reconcile(
        kernel,
        journal,
        BrokerSnapshot(
            captured_at=NOW,
            positions=(),
            protections=(),
            working_orders=(
                BrokerWorkingOrder(
                    broker_order_id="manual-order-7",
                    client_command_id=None,
                    instrument_id="TCS",
                    kind=CommandKind.ENTRY.value,
                    quantity=5,
                ),
            ),
        ),
    )

    assert report.clean is False
    assert any("unknown broker order" in issue.lower() for issue in report.issues)
    assert safety.state().latched is True


def test_latched_enforcement_protects_then_cancels_only_dispatched_remainder(tmp_path):
    class SimulatedProcessCrash(RuntimeError):
        pass

    def crash_after_entry_completion(command, receipt):
        if isinstance(command, EntryCommand):
            raise SimulatedProcessCrash("durable entry completion")

    gateway = RecordingPaperGateway()
    gateway.queue_entry_fill(cumulative_quantity=4, average_price_paise=149_500)
    kernel, gateway, safety, journal = _kernel(
        tmp_path,
        gateway,
        after_command_completed=crash_after_entry_completion,
    )
    _accept(kernel, journal, _intent("INFY", 10))
    _accept(kernel, journal, _intent("TCS", 5))
    with pytest.raises(SimulatedProcessCrash):
        kernel.run_once(_account(), now=NOW)
    safety.latch(
        reason_code="OWNER_HALT",
        detail="halt after uncertain partial fill",
        occurred_at=NOW,
        idempotency_key="halt-after-entry-completion",
    )

    restarted, gateway, _, journal = _kernel(tmp_path, gateway)
    restarted.run_once(_account(), now=NOW)

    assert [command.kind for command in gateway.commands] == [
        CommandKind.ENTRY,
        CommandKind.PROTECTION,
        CommandKind.CANCEL_ENTRY,
    ]
    cancellation = gateway.commands[-1]
    assert isinstance(cancellation, CancelEntryCommand)
    assert cancellation.instrument_id == "INFY"
    assert cancellation.remaining_quantity == 6
    assert not any(
        isinstance(command, EntryCommand) and command.instrument_id == "TCS"
        for command in gateway.commands
    )
    released = [
        event
        for event in journal.read_stream("risk:portfolio")
        if event.event_type == "RiskReleased"
    ]
    assert len(released) == 1
    assert str(released[0].payload["terminal_evidence_event_id"]).startswith(
        "event:"
    )


@pytest.mark.parametrize(
    ("broker_stop_paise", "broker_target_paise"),
    [(144_000, 160_000), (145_000, 161_000)],
)
def test_reconciliation_quarantines_wrong_protective_prices(
    tmp_path, broker_stop_paise, broker_target_paise
):
    gateway = RecordingPaperGateway()
    gateway.queue_entry_fill(cumulative_quantity=4, average_price_paise=149_500)
    kernel, gateway, safety, journal = _kernel(tmp_path, gateway)
    _accept(kernel, journal, _intent("INFY", 10))
    kernel.run_once(_account(), now=NOW)
    protection = next(
        command
        for command in gateway.commands
        if isinstance(command, ProtectionCommand)
    )

    report = _reconcile(
        kernel,
        journal,
        BrokerSnapshot(
            captured_at=NOW,
            positions=(BrokerPosition("INFY", 4),),
            protections=(
                BrokerProtection(
                    "INFY",
                    4,
                    stop_price_paise=broker_stop_paise,
                    target_price_paise=broker_target_paise,
                    client_command_id=protection.command_id,
                ),
            ),
            working_orders=(
                BrokerWorkingOrder(
                    broker_order_id="protection-1",
                    client_command_id=protection.command_id,
                    instrument_id="INFY",
                    kind=CommandKind.PROTECTION.value,
                    quantity=4,
                    stop_price_paise=broker_stop_paise,
                    target_price_paise=broker_target_paise,
                ),
            ),
        ),
    )

    assert report.clean is False
    assert any("protective level" in issue.lower() for issue in report.issues)
    assert safety.state().latched is True


def test_reconciliation_checks_working_protection_levels_independently(tmp_path):
    gateway = RecordingPaperGateway()
    gateway.queue_entry_fill(cumulative_quantity=4, average_price_paise=149_500)
    kernel, gateway, _, journal = _kernel(tmp_path, gateway)
    _accept(kernel, journal, _intent("INFY", 10))
    kernel.run_once(_account(), now=NOW)
    protection = next(
        command
        for command in gateway.commands
        if isinstance(command, ProtectionCommand)
    )

    report = _reconcile(
        kernel,
        journal,
        BrokerSnapshot(
            captured_at=NOW,
            positions=(BrokerPosition("INFY", 4),),
            protections=(
                BrokerProtection(
                    "INFY",
                    4,
                    stop_price_paise=145_000,
                    target_price_paise=160_000,
                    client_command_id=protection.command_id,
                ),
            ),
            working_orders=(
                BrokerWorkingOrder(
                    broker_order_id="protection-working-1",
                    client_command_id=protection.command_id,
                    instrument_id="INFY",
                    kind=CommandKind.PROTECTION.value,
                    quantity=4,
                    stop_price_paise=145_000,
                    target_price_paise=161_000,
                ),
            ),
        ),
    )

    assert any(
        "working protective level" in issue.lower() for issue in report.issues
    )


def test_latched_enforcement_attempts_every_working_cancel_after_one_failure(tmp_path):
    class FailFirstCancellationGateway(RecordingPaperGateway):
        def __init__(self):
            super().__init__()
            self.failed = False

        def execute(self, command):
            if isinstance(command, CancelEntryCommand) and not self.failed:
                self.failed = True
                raise RuntimeError("first cancellation rejected")
            return super().execute(command)

    gateway = FailFirstCancellationGateway()
    kernel, gateway, safety, journal = _kernel(tmp_path, gateway)
    _accept(kernel, journal, _intent("INFY", 10))
    _accept(kernel, journal, _intent("TCS", 5))
    kernel.run_once(_account(), now=NOW)
    safety.latch(
        reason_code="OWNER_HALT",
        detail="cancel all working entries",
        occurred_at=NOW,
        idempotency_key="halt-two-working-entries",
    )

    with pytest.raises(RuntimeError, match="first cancellation rejected"):
        kernel.enforce(now=NOW)

    assert any(
        isinstance(command, CancelEntryCommand)
        and command.instrument_id == "TCS"
        for command in gateway.commands
    )
