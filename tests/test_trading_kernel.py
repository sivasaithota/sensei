import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from sensei.kernel import (
    ENTRY_DISPATCH_AUTHORIZATION_FACT_TYPE,
    BrokerPosition,
    BrokerProtection,
    BrokerSnapshot,
    BrokerSnapshotAuthority,
    BrokerWorkingOrder,
    CancelEntryCommand,
    CommandKind,
    EntryCommand,
    EntryAuthorizationInvalid,
    EntryDispatchAuthorization,
    KernelAdmissionAuthority,
    ProtectionCommand,
    RecordingPaperGateway,
    TradingKernel,
    entry_dispatch_authorization_fact,
)
from sensei.operations import (
    EventAppend,
    HmacFactSigner,
    HmacFactVerifier,
    OperationalJournal,
)
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
SUPERVISOR_SECRET = b"desk-supervisor-entry-test-secret-at-least-32b"
SUPERVISOR_ISSUER = "desk-supervisor"


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
            entry_authorization_verifier=HmacFactVerifier(
                {SUPERVISOR_ISSUER: SUPERVISOR_SECRET}
            ),
            expected_supervisor_issuer_id=SUPERVISOR_ISSUER,
            after_command_completed=after_command_completed,
        ),
        paper,
        safety,
        journal,
    )


def test_kernel_reports_its_exact_journal_and_gateway_binding(tmp_path):
    kernel, gateway, safety, journal = _kernel(tmp_path)

    assert kernel.is_bound_to_paper_runtime(
        journal=journal,
        gateway=gateway,
        safety=safety,
    )
    assert not kernel.is_bound_to_paper_runtime(
        journal=OperationalJournal(tmp_path / "different-journal.sqlite3"),
        gateway=gateway,
        safety=safety,
    )
    assert not kernel.is_bound_to_paper_runtime(
        journal=journal,
        gateway=RecordingPaperGateway(),
        safety=safety,
    )


def test_kernel_binding_rejects_misbound_durable_dependencies(tmp_path):
    kernel, gateway, safety, journal = _kernel(tmp_path)
    other = OperationalJournal(tmp_path / "different-dependency-journal.sqlite3")
    limits = RiskLimits(
        max_total_notional_paise=10_000_000,
        max_position_notional_paise=3_000_000,
        max_risk_per_trade_paise=100_000,
        max_total_risk_paise=500_000,
        max_open_positions=3,
        snapshot_max_age=timedelta(minutes=2),
        max_daily_loss_paise=500_000,
        max_weekly_loss_paise=1_000_000,
        max_drawdown_bps=2_000,
    )
    other_reset_authority = SafetyResetAuthority(
        other,
        owner_verifier=HmacFactVerifier({"kernel-owner": OWNER_SECRET}),
        reconciliation_verifier=HmacFactVerifier(
            {"kernel-reconciler": RECONCILIATION_SECRET}
        ),
        expected_reconciliation_issuer_id="kernel-reconciler",
    )
    replacements = (
        ("_risk", PortfolioRisk(other, limits)),
        (
            "_admission_authority",
            KernelAdmissionAuthority(
                other,
                HmacFactVerifier({"paper-admission": ADMISSION_SECRET}),
            ),
        ),
        (
            "_broker_snapshot_authority",
            BrokerSnapshotAuthority(
                other,
                HmacFactVerifier({"paper-gateway": BROKER_SECRET}),
                expected_issuer_id="paper-gateway",
            ),
        ),
        ("_safety_reset_authority", other_reset_authority),
    )

    for attribute, replacement in replacements:
        original = getattr(kernel, attribute)
        setattr(kernel, attribute, replacement)
        assert not kernel.is_bound_to_paper_runtime(
            journal=journal,
            gateway=gateway,
            safety=safety,
        )
        setattr(kernel, attribute, original)


def test_kernel_binding_rejects_incoherent_reconciliation_runtime(tmp_path):
    kernel, gateway, safety, journal = _kernel(tmp_path)
    original_signer = kernel._reconciliation_signer
    kernel._reconciliation_signer = HmacFactSigner(
        "kernel-reconciler",
        b"different-reconciliation-secret-32b",
    )

    assert not kernel.is_bound_to_paper_runtime(
        journal=journal,
        gateway=gateway,
        safety=safety,
    )

    kernel._reconciliation_signer = original_signer
    safety._reset_authority = SafetyResetAuthority(
        journal,
        owner_verifier=HmacFactVerifier({"kernel-owner": OWNER_SECRET}),
        reconciliation_verifier=HmacFactVerifier(
            {"kernel-reconciler": RECONCILIATION_SECRET}
        ),
        expected_reconciliation_issuer_id="kernel-reconciler",
    )

    assert not kernel.is_bound_to_paper_runtime(
        journal=journal,
        gateway=gateway,
        safety=safety,
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


def _run_once(kernel, *, account=None, now=NOW):
    snapshot = account or _account()
    for intent_id in tuple(kernel._state().intent_order):
        state = kernel._state()
        if intent_id in state.quarantined_intents:
            continue
        if kernel._safety.state().latched and state.entry_for(intent_id) is None:
            continue
        kernel.run_once(
            snapshot,
            now=now,
            intent_id=intent_id,
            authorize_entry=lambda intent: _test_entry_authorization(
                kernel._journal,
                intent,
                snapshot,
                now,
            ),
        )


def _test_entry_authorization(
    journal,
    intent,
    snapshot,
    authorized_at,
):
    material = (
        f"{intent.intent_id}:{authorized_at.isoformat()}:"
        f"{len(journal.read_all())}"
    )
    command_hash = hashlib.sha256(material.encode()).hexdigest()
    stream = f"desk-supervisor:{command_hash}"
    session_id = f"desk-session:{command_hash}"
    cycle_request_id = "desk-request:" + hashlib.sha256(
        intent.intent_id.encode()
    ).hexdigest()
    journal.append(
        EventAppend(
            stream_id=stream,
            event_type="DeskSupervisorStarted",
            payload={
                "session_id": session_id,
                "mode": "paper",
                "requested_at": authorized_at.isoformat(),
            },
            idempotency_key=f"test-supervisor-start:{command_hash}",
            expected_version=0,
            occurred_at=authorized_at,
            correlation_id=session_id,
        )
    )
    phase = "PRE_DISPATCH:1"
    event = journal.append(
        EventAppend(
            stream_id=stream,
            event_type="DeskSupervisorTruthCaptured",
            payload={
                "session_id": session_id,
                "phase": phase,
                "checked_at": authorized_at.isoformat(),
                "account_snapshot_id": snapshot.snapshot_id,
                "account_snapshot_event_id": "event:test-account",
                "health_event_id": "event:test-health",
                "broker_snapshot_id": "broker-snapshot:test",
                "broker_snapshot_event_id": "event:test-broker",
                "reconciliation_evidence_event_id": "event:test-reconciliation",
                "authorized_cycle_request_ids": (cycle_request_id,),
                "cycle_request_id": cycle_request_id,
                "authorized_intent_id": intent.intent_id,
                "reason_codes": (),
            },
            idempotency_key=(
                "test-supervisor-truth:"
                + hashlib.sha256(f"{command_hash}:{phase}".encode()).hexdigest()
            ),
            expected_version=1,
            occurred_at=authorized_at,
            correlation_id=session_id,
        )
    )
    fact = entry_dispatch_authorization_fact(
        intent_id=intent.intent_id,
        cycle_request_id=cycle_request_id,
        account_snapshot_id=snapshot.snapshot_id,
        authorized_at=authorized_at,
        evidence_event_id=event.event_id,
    )
    return EntryDispatchAuthorization(
        account_snapshot=snapshot,
        authorized_at=authorized_at,
        evidence_event_id=event.event_id,
        intent_id=intent.intent_id,
        cycle_request_id=cycle_request_id,
        issuer_id=SUPERVISOR_ISSUER,
        signature=HmacFactSigner(
            SUPERVISOR_ISSUER, SUPERVISOR_SECRET
        ).sign(ENTRY_DISPATCH_AUTHORIZATION_FACT_TYPE, fact),
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

    _run_once(kernel)
    entries = [c for c in gateway.commands if c.kind is CommandKind.ENTRY]
    assert len(entries) == 1
    assert isinstance(entries[0], EntryCommand)

    # Restarting against the journal must not send a completed command again.
    restarted, _, _, _ = _kernel(tmp_path, gateway)
    _run_once(restarted)
    assert [c.command_id for c in gateway.commands].count(entries[0].command_id) == 1


def test_governed_run_dispatches_only_the_selected_intent(tmp_path):
    kernel, gateway, _, journal = _kernel(tmp_path)
    infy = _accept(kernel, journal, _intent("INFY"))
    tcs = _accept(kernel, journal, _intent("TCS"))

    kernel.run_once(
        _account(),
        now=NOW,
        intent_id=tcs.intent_id,
        authorize_entry=lambda intent: _test_entry_authorization(
            journal,
            intent,
            _account(),
            NOW,
        ),
    )

    entries = [
        command
        for command in gateway.commands
        if command.kind is CommandKind.ENTRY
    ]
    assert [command.instrument_id for command in entries] == ["TCS"]
    assert infy.intent_id != tcs.intent_id


def test_entry_authorization_runs_after_recovery_and_sets_dispatch_time(tmp_path):
    order: list[str] = []

    class OrderedGateway(RecordingPaperGateway):
        def execute(self, command):
            order.append("gateway")
            return super().execute(command)

    kernel, gateway, _, journal = _kernel(tmp_path, OrderedGateway())
    intent = _accept(kernel, journal, _intent())
    dispatch_time = NOW + timedelta(seconds=20)

    def authorize_entry(selected_intent):
        assert selected_intent == intent
        order.append("authorization")
        return _test_entry_authorization(
            journal,
            selected_intent,
            _account(),
            dispatch_time,
        )

    kernel.run_once(
        _account(),
        now=NOW,
        intent_id=intent.intent_id,
        authorize_entry=authorize_entry,
    )

    assert order == ["authorization", "gateway"]
    prepared = next(
        event
        for event in journal.read_stream("kernel:paper")
        if event.event_type == "BrokerCommandPrepared"
    )
    assert prepared.occurred_at == dispatch_time
    assert len(gateway.commands) == 1


def test_quarantined_intent_is_never_dispatched_by_a_later_sweep(tmp_path):
    kernel, gateway, _, journal = _kernel(tmp_path)
    blocked = _accept(kernel, journal, _intent("INFY"))
    allowed = _accept(kernel, journal, _intent("TCS"))

    kernel.quarantine_intent(
        blocked.intent_id,
        reason_codes=("OPERATIONAL_HEALTH_STALE",),
        evidence_event_id="event:supervisor-truth",
        occurred_at=NOW,
    )
    _run_once(kernel)

    entries = [
        command
        for command in gateway.commands
        if command.kind is CommandKind.ENTRY
    ]
    assert [command.instrument_id for command in entries] == [
        allowed.instrument_id
    ]
    event = next(
        event
        for event in journal.read_stream("kernel:paper")
        if event.event_type == "TradeIntentQuarantined"
    )
    assert event.payload["intent_id"] == blocked.intent_id


def test_scoped_pending_entry_fails_closed_without_fresh_authorization(tmp_path):
    kernel, gateway, _, journal = _kernel(tmp_path)
    intent = _accept(kernel, journal, _intent())

    with pytest.raises(EntryAuthorizationInvalid, match="fresh authorization"):
        kernel.run_once(
            _account(),
            now=NOW,
            intent_id=intent.intent_id,
        )

    assert gateway.commands == ()
    assert not any(
        event.event_type == "BrokerCommandPrepared"
        for event in journal.read_stream("kernel:paper")
    )


def test_unscoped_recovery_never_dispatches_an_accepted_intent(tmp_path):
    kernel, gateway, _, journal = _kernel(tmp_path)
    _accept(kernel, journal, _intent())

    kernel.run_once(_account(), now=NOW)

    assert gateway.commands == ()


def test_entry_authorizer_must_return_the_exact_typed_capability(tmp_path):
    kernel, gateway, _, journal = _kernel(tmp_path)
    intent = _accept(kernel, journal, _intent())

    with pytest.raises(
        EntryAuthorizationInvalid,
        match="exact EntryDispatchAuthorization",
    ):
        kernel.run_once(
            _account(),
            now=NOW,
            intent_id=intent.intent_id,
            authorize_entry=lambda selected: object(),
        )

    assert gateway.commands == ()
    assert not any(
        event.event_type == "BrokerCommandPrepared"
        for event in journal.read_stream("kernel:paper")
    )


def test_entry_authorization_must_match_the_accepted_intent_account(tmp_path):
    kernel, gateway, _, journal = _kernel(tmp_path)
    intent = _accept(kernel, journal, _intent())
    different_account = replace(
        _account(),
        available_cash_paise=9_000_000,
    )

    with pytest.raises(
        EntryAuthorizationInvalid,
        match="account does not match intent",
    ):
        kernel.run_once(
            _account(),
            now=NOW,
            intent_id=intent.intent_id,
            authorize_entry=lambda selected: _test_entry_authorization(
                journal,
                selected,
                different_account,
                NOW,
            ),
        )

    assert gateway.commands == ()


def test_entry_authorization_cannot_predate_kernel_recovery(tmp_path):
    kernel, gateway, _, journal = _kernel(tmp_path)
    intent = _accept(kernel, journal, _intent())
    authorized_at = NOW - timedelta(microseconds=1)

    with pytest.raises(
        EntryAuthorizationInvalid,
        match="cannot predate kernel recovery",
    ):
        kernel.run_once(
            _account(),
            now=NOW,
            intent_id=intent.intent_id,
            authorize_entry=lambda selected: _test_entry_authorization(
                journal,
                selected,
                _account(),
                authorized_at,
            ),
        )

    assert gateway.commands == ()


def test_entry_authorization_requires_resolvable_supervisor_truth(tmp_path):
    kernel, gateway, _, journal = _kernel(tmp_path)
    intent = _accept(kernel, journal, _intent())
    evidence_event_id = "event:" + "0" * 64
    cycle_request_id = "desk-request:" + "1" * 64
    fact = entry_dispatch_authorization_fact(
        intent_id=intent.intent_id,
        cycle_request_id=cycle_request_id,
        account_snapshot_id=_account().snapshot_id,
        authorized_at=NOW,
        evidence_event_id=evidence_event_id,
    )

    with pytest.raises(
        EntryAuthorizationInvalid,
        match="Supervisor truth evidence",
    ):
        kernel.run_once(
            _account(),
            now=NOW,
            intent_id=intent.intent_id,
            authorize_entry=lambda selected: EntryDispatchAuthorization(
                account_snapshot=_account(),
                authorized_at=NOW,
                evidence_event_id=evidence_event_id,
                intent_id=intent.intent_id,
                cycle_request_id=cycle_request_id,
                issuer_id=SUPERVISOR_ISSUER,
                signature=HmacFactSigner(
                    SUPERVISOR_ISSUER, SUPERVISOR_SECRET
                ).sign(ENTRY_DISPATCH_AUTHORIZATION_FACT_TYPE, fact),
            ),
        )

    assert gateway.commands == ()


def test_prepared_incomplete_entry_is_reauthorized_before_gateway(tmp_path):
    order: list[str] = []

    class OrderedGateway(RecordingPaperGateway):
        def execute(self, command):
            order.append("gateway")
            return super().execute(command)

    kernel, gateway, _, journal = _kernel(tmp_path, OrderedGateway())
    intent = _accept(kernel, journal, _intent())
    kernel._prepare(kernel._entry_command(intent), NOW)

    def authorize_entry(selected_intent):
        order.append("authorization")
        return _test_entry_authorization(
            journal,
            selected_intent,
            _account(),
            NOW + timedelta(seconds=10),
        )

    kernel.run_once(
        _account(),
        now=NOW,
        intent_id=intent.intent_id,
        authorize_entry=authorize_entry,
    )

    assert order == ["authorization", "gateway"]
    assert len(gateway.commands) == 1


def test_entry_authorization_is_signed_bound_and_consumed_once(tmp_path):
    class FailFirstEntryGateway(RecordingPaperGateway):
        def __init__(self):
            super().__init__()
            self.failed = False

        def execute(self, command):
            if isinstance(command, EntryCommand) and not self.failed:
                self.failed = True
                raise RuntimeError("entry transport failed")
            return super().execute(command)

    kernel, gateway, _, journal = _kernel(tmp_path, FailFirstEntryGateway())
    intent = _accept(kernel, journal, _intent())
    authorization = _test_entry_authorization(
        journal, intent, _account(), NOW
    )

    with pytest.raises(RuntimeError, match="entry transport failed"):
        kernel.run_once(
            _account(),
            now=NOW,
            intent_id=intent.intent_id,
            authorize_entry=lambda selected: authorization,
        )

    event_types = [
        event.event_type for event in journal.read_stream("kernel:paper")
    ]
    assert event_types.index("SupervisorEntryAuthorizationConsumed") < (
        event_types.index("BrokerCommandPrepared")
    )
    with pytest.raises(
        EntryAuthorizationInvalid,
        match="does not authorize entry",
    ):
        kernel.run_once(
            _account(),
            now=NOW,
            intent_id=intent.intent_id,
            authorize_entry=lambda selected: authorization,
        )
    assert gateway.commands == ()


def test_entry_authorization_rejects_a_tampered_signature(tmp_path):
    kernel, gateway, _, journal = _kernel(tmp_path)
    intent = _accept(kernel, journal, _intent())
    authorization = replace(
        _test_entry_authorization(journal, intent, _account(), NOW),
        signature="hmac-sha256:" + "0" * 64,
    )

    with pytest.raises(EntryAuthorizationInvalid, match="not authentic"):
        kernel.run_once(
            _account(),
            now=NOW,
            intent_id=intent.intent_id,
            authorize_entry=lambda selected: authorization,
        )

    assert gateway.commands == ()


def test_partial_entry_fill_is_protected_before_another_entry(tmp_path):
    gateway = RecordingPaperGateway()
    gateway.queue_entry_fill(cumulative_quantity=4, average_price_paise=149_500)
    kernel, gateway, _, journal = _kernel(tmp_path, gateway)
    _accept(kernel, journal, _intent("INFY", 10))
    _accept(kernel, journal, _intent("TCS", 5))

    _run_once(kernel)

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
    _run_once(kernel)
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
        _run_once(kernel)

    event_types = [event.event_type for event in journal.read_stream("kernel:paper")]
    assert "BrokerCommandCompleted" in event_types
    assert "EntryFillObserved" not in event_types
    assert not any(isinstance(command, ProtectionCommand) for command in gateway.commands)

    restarted, _, _, journal = _kernel(tmp_path, gateway)
    _run_once(restarted)

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


def test_receipt_append_failure_latches_and_recovers_without_resending_entry(
    tmp_path,
    monkeypatch,
):
    gateway = RecordingPaperGateway()
    gateway.queue_entry_fill(cumulative_quantity=4, average_price_paise=149_500)
    kernel, gateway, safety, journal = _kernel(tmp_path, gateway)
    _accept(kernel, journal, _intent("INFY", 10))
    real_append = journal.append
    failed = False

    def fail_first_completion(command):
        nonlocal failed
        if command.event_type == "BrokerCommandCompleted" and not failed:
            failed = True
            raise OSError("journal write interrupted")
        return real_append(command)

    monkeypatch.setattr(journal, "append", fail_first_completion)
    with pytest.raises(OSError, match="journal write interrupted"):
        _run_once(kernel)

    assert sum(isinstance(c, EntryCommand) for c in gateway.commands) == 1
    assert not any(
        event.event_type == "BrokerCommandCompleted"
        for event in journal.read_stream("kernel:paper")
    )
    assert {
        reason.reason_code for reason in safety.state().reasons
    } == {"BROKER_RECEIPT_PERSISTENCE_FAILED"}

    monkeypatch.setattr(journal, "append", real_append)
    restarted, _, restarted_safety, journal = _kernel(tmp_path, gateway)
    restarted.enforce(now=NOW)

    assert sum(isinstance(c, EntryCommand) for c in gateway.commands) == 1
    assert any(
        event.event_type == "BrokerCommandCompleted"
        for event in journal.read_stream("kernel:paper")
    )
    assert any(
        event.event_type == "EntryFillObserved"
        for event in journal.read_stream("kernel:paper")
    )
    assert any(isinstance(c, ProtectionCommand) for c in gateway.commands)
    assert any(isinstance(c, CancelEntryCommand) for c in gateway.commands)
    assert restarted_safety.state().latched is True


def test_recovered_cancel_receipt_releases_the_reservation(
    tmp_path,
    monkeypatch,
):
    kernel, gateway, _, journal = _kernel(tmp_path)
    intent = _accept(kernel, journal, _intent())
    _run_once(kernel)
    kernel.cancel_entry(intent.intent_id, occurred_at=NOW)
    cancel = next(
        command
        for command in kernel._state().commands.values()
        if isinstance(command, CancelEntryCommand)
    )
    real_append = journal.append

    def fail_cancel_completion(command):
        receipt = command.payload.get("receipt", {})
        if (
            command.event_type == "BrokerCommandCompleted"
            and receipt.get("command_id") == cancel.command_id
        ):
            raise OSError("cancel receipt persistence interrupted")
        return real_append(command)

    monkeypatch.setattr(journal, "append", fail_cancel_completion)
    with pytest.raises(OSError, match="cancel receipt persistence interrupted"):
        kernel.enforce(now=NOW)
    assert sum(
        isinstance(command, CancelEntryCommand) for command in gateway.commands
    ) == 1

    monkeypatch.setattr(journal, "append", real_append)
    restarted, _, _, journal = _kernel(tmp_path, gateway)
    restarted.enforce(now=NOW)

    assert sum(
        isinstance(command, CancelEntryCommand) for command in gateway.commands
    ) == 1
    assert any(
        event.event_type == "RiskReleased" for event in journal.read_all()
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
        _run_once(kernel)

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
        _run_once(kernel)
    safety.latch(
        reason_code="OWNER_HALT",
        detail="halt after uncertain partial fill",
        occurred_at=NOW,
        idempotency_key="halt-after-entry-completion",
    )

    restarted, gateway, _, journal = _kernel(tmp_path, gateway)
    _run_once(restarted)

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
    _run_once(kernel)
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
    _run_once(kernel)
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
    _run_once(kernel)
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
