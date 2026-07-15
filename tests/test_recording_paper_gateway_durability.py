from datetime import datetime, timedelta, timezone

import pytest

from sensei.kernel import (
    BrokerPosition,
    BrokerProtection,
    CancelEntryCommand,
    CommandKind,
    EntryCommand,
    ProtectionCommand,
    RecordingPaperGateway,
)
from sensei.operations import OperationalJournal


NOW = datetime(2026, 7, 16, 4, 0, tzinfo=timezone.utc)


def _entry(*, instrument_id: str = "INFY", quantity: int = 4) -> EntryCommand:
    return EntryCommand(
        intent_id=f"intent:durable-{instrument_id.lower()}",
        instrument_id=instrument_id,
        quantity=quantity,
        limit_price_paise=150_000,
    )


def test_no_argument_gateway_keeps_original_in_memory_identity_and_fill_policy():
    gateway = RecordingPaperGateway()

    receipt = gateway.execute(_entry())

    assert receipt.broker_reference == "paper:1"
    assert receipt.cumulative_fill_quantity == 0


def test_durable_receipt_survives_restart_and_retry_is_idempotent(tmp_path):
    journal_path = tmp_path / "journal.sqlite3"
    command = _entry()
    first_gateway = RecordingPaperGateway(
        OperationalJournal(journal_path),
        clock=lambda: NOW,
    )

    original = first_gateway.execute(command)

    restarted_gateway = RecordingPaperGateway(
        OperationalJournal(journal_path),
        clock=lambda: NOW,
    )
    assert restarted_gateway.receipt_for(command.command_id) == original
    assert restarted_gateway.execute(command) == original
    assert restarted_gateway.commands == (command,)


def test_limit_auto_fill_is_explicit_and_broker_state_rebuilds_after_restart(
    tmp_path,
):
    command = _entry(quantity=4)
    resting_gateway = RecordingPaperGateway(
        OperationalJournal(tmp_path / "resting.sqlite3"),
        clock=lambda: NOW,
    )

    resting_receipt = resting_gateway.execute(command)
    resting_snapshot = resting_gateway.broker_snapshot(captured_at=NOW)

    assert resting_receipt.cumulative_fill_quantity == 0
    assert resting_snapshot.positions == ()
    assert len(resting_snapshot.working_orders) == 1
    assert resting_snapshot.working_orders[0].kind == CommandKind.ENTRY.value
    assert resting_snapshot.working_orders[0].client_command_id == command.command_id

    filled_path = tmp_path / "filled.sqlite3"
    filled_gateway = RecordingPaperGateway(
        OperationalJournal(filled_path),
        auto_fill_at_limit=True,
        clock=lambda: NOW,
    )
    filled_receipt = filled_gateway.execute(command)

    assert filled_receipt.cumulative_fill_quantity == command.quantity
    assert filled_receipt.average_fill_price_paise == command.limit_price_paise

    restarted_gateway = RecordingPaperGateway(OperationalJournal(filled_path))
    rebuilt_snapshot = restarted_gateway.broker_snapshot(captured_at=NOW)
    assert rebuilt_snapshot.positions == (
        BrokerPosition(command.instrument_id, command.quantity),
    )
    assert rebuilt_snapshot.working_orders == ()


def test_committed_receipt_is_recoverable_if_process_fails_before_return(
    tmp_path,
    monkeypatch,
):
    class SimulatedProcessCrash(RuntimeError):
        pass

    path = tmp_path / "journal.sqlite3"
    journal = OperationalJournal(path)
    command = _entry()
    gateway = RecordingPaperGateway(journal, clock=lambda: NOW)
    durable_append = journal.append

    def commit_then_crash(event):
        durable_append(event)
        raise SimulatedProcessCrash("process stopped after journal commit")

    monkeypatch.setattr(journal, "append", commit_then_crash)

    with pytest.raises(SimulatedProcessCrash, match="after journal commit"):
        gateway.execute(command)

    restarted_gateway = RecordingPaperGateway(OperationalJournal(path))
    recovered = restarted_gateway.receipt_for(command.command_id)
    assert recovered is not None
    assert restarted_gateway.execute(command) == recovered
    assert restarted_gateway.commands == (command,)


def test_broker_snapshot_reconstructs_protection_and_cancelled_entry(tmp_path):
    path = tmp_path / "journal.sqlite3"
    gateway = RecordingPaperGateway(
        OperationalJournal(path),
        auto_fill_at_limit=True,
        clock=lambda: NOW,
    )
    entry = _entry()
    gateway.execute(entry)
    protection = ProtectionCommand(
        intent_id=entry.intent_id,
        instrument_id=entry.instrument_id,
        quantity=entry.quantity,
        stop_price_paise=145_000,
        target_price_paise=160_000,
    )
    gateway.execute(protection)

    restarted = RecordingPaperGateway(OperationalJournal(path))
    snapshot = restarted.broker_snapshot(captured_at=NOW + timedelta(seconds=1))

    assert snapshot.protections == (
        BrokerProtection(
            instrument_id=entry.instrument_id,
            quantity=entry.quantity,
            stop_price_paise=protection.stop_price_paise,
            target_price_paise=protection.target_price_paise,
            client_command_id=protection.command_id,
        ),
    )
    assert len(snapshot.working_orders) == 1
    assert snapshot.working_orders[0].kind == CommandKind.PROTECTION.value

    resting_entry = _entry(instrument_id="TCS", quantity=2)
    resting_gateway = RecordingPaperGateway(
        OperationalJournal(tmp_path / "cancelled.sqlite3"),
        clock=lambda: NOW,
    )
    resting_gateway.execute(resting_entry)
    resting_gateway.execute(
        CancelEntryCommand(
            intent_id=resting_entry.intent_id,
            instrument_id=resting_entry.instrument_id,
            entry_command_id=resting_entry.command_id,
            remaining_quantity=resting_entry.quantity,
        )
    )
    cancelled = resting_gateway.broker_snapshot(captured_at=NOW)
    assert cancelled.positions == ()
    assert cancelled.working_orders == ()
