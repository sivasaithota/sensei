from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from sensei.kernel import CancelEntryCommand, EntryCommand, GatewayReceipt
from sensei.operations.journal import EventAppend, JournalConflict, OperationalJournal
from sensei.portfolio_risk import (
    AccountPosition,
    AccountSnapshot,
    PortfolioRisk,
    ReservationState,
    RiskLimits,
    RiskRejected,
    TradeIntent,
)


NOW = datetime(2026, 7, 13, 4, 0, tzinfo=timezone.utc)


def _intent(
    symbol: str = "INFY",
    *,
    quantity: int = 10,
    limit_price_paise: int = 150_000,
    account_snapshot: AccountSnapshot | None = None,
) -> TradeIntent:
    account_snapshot = account_snapshot or _snapshot()
    return TradeIntent(
        strategy_plan_id="plan:hammer-v1",
        decision_trace_id=f"trace:{symbol.lower()}",
        market_snapshot_id="snapshot:market-1",
        account_snapshot_id=account_snapshot.snapshot_id,
        instrument_id=symbol,
        quantity=quantity,
        limit_price_paise=limit_price_paise,
        stop_price_paise=limit_price_paise - 5_000,
        target_price_paise=limit_price_paise + 10_000,
        created_at=NOW,
    )


def _snapshot(
    *,
    cash: int = 10_000_000,
    positions: tuple[AccountPosition, ...] = (),
    included_reservation_ids: tuple[str, ...] = (),
    reconciled: bool = True,
    captured_at: datetime = NOW,
    marked_equity_paise: int | None = None,
    high_water_mark_paise: int | None = None,
    day_pnl_paise: int = 0,
    week_pnl_paise: int = 0,
) -> AccountSnapshot:
    equity = marked_equity_paise or (
        cash + sum(position.notional_paise for position in positions)
    )
    return AccountSnapshot(
        available_cash_paise=cash,
        marked_equity_paise=equity,
        high_water_mark_paise=high_water_mark_paise or equity,
        day_pnl_paise=day_pnl_paise,
        week_pnl_paise=week_pnl_paise,
        positions=positions,
        included_reservation_ids=included_reservation_ids,
        reconciled=reconciled,
        captured_at=captured_at,
    )


def _risk(
    tmp_path,
    *,
    max_positions: int = 2,
    max_total_risk_paise: int = 500_000,
    journal: OperationalJournal | None = None,
) -> PortfolioRisk:
    return PortfolioRisk(
        journal or OperationalJournal(tmp_path / "journal.sqlite3"),
        RiskLimits(
            max_total_notional_paise=10_000_000,
            max_position_notional_paise=3_000_000,
            max_risk_per_trade_paise=100_000,
            max_total_risk_paise=max_total_risk_paise,
            max_open_positions=max_positions,
            snapshot_max_age=timedelta(minutes=2),
            max_daily_loss_paise=500_000,
            max_weekly_loss_paise=1_000_000,
            max_drawdown_bps=2_000,
        ),
    )


def _completed_cancel_evidence(
    journal: OperationalJournal,
    intent: TradeIntent,
    *,
    remaining_quantity: int,
    entry: EntryCommand | None = None,
    record_entry: bool = True,
    complete_entry: bool = True,
) -> str:
    entry = entry or EntryCommand(
        intent_id=intent.intent_id,
        instrument_id=intent.instrument_id,
        quantity=intent.quantity,
        limit_price_paise=intent.limit_price_paise,
    )
    journal.append(
        EventAppend(
            stream_id="kernel:paper",
            event_type="TradeIntentAccepted",
            payload={"intent": intent.to_payload()},
            idempotency_key=(
                f"kernel-accept:{intent.intent_id.removeprefix('intent:')}"
            ),
            expected_version=len(journal.read_stream("kernel:paper")),
            occurred_at=NOW,
            correlation_id=intent.intent_id,
        )
    )
    if record_entry:
        entry_prepared = journal.append(
            EventAppend(
                stream_id="kernel:paper",
                event_type="BrokerCommandPrepared",
                payload={"command": entry.to_payload()},
                idempotency_key=(
                    f"kernel-command:{entry.command_id.removeprefix('command:')}"
                ),
                expected_version=len(journal.read_stream("kernel:paper")),
                occurred_at=NOW,
                correlation_id=entry.intent_id,
            )
        )
        if complete_entry:
            entry_receipt = GatewayReceipt(
                command_id=entry.command_id,
                accepted=True,
                broker_reference="paper:entry-evidence",
            )
            journal.append(
                EventAppend(
                    stream_id="kernel:paper",
                    event_type="BrokerCommandCompleted",
                    payload={"receipt": entry_receipt.to_payload()},
                    idempotency_key=(
                        f"kernel-complete:{entry.command_id.removeprefix('command:')}"
                    ),
                    expected_version=entry_prepared.stream_sequence,
                    occurred_at=NOW,
                    causation_id=entry.command_id,
                    correlation_id=entry.intent_id,
                )
            )
    cancel = CancelEntryCommand(
        intent_id=intent.intent_id,
        instrument_id=intent.instrument_id,
        entry_command_id=entry.command_id,
        remaining_quantity=remaining_quantity,
    )
    prepared = journal.append(
        EventAppend(
            stream_id="kernel:paper",
            event_type="BrokerCommandPrepared",
            payload={"command": cancel.to_payload()},
            idempotency_key=f"test-prepare:{cancel.command_id.removeprefix('command:')}",
            expected_version=len(journal.read_stream("kernel:paper")),
            occurred_at=NOW,
            correlation_id=intent.intent_id,
        )
    )
    receipt = GatewayReceipt(
        command_id=cancel.command_id,
        accepted=True,
        broker_reference="paper:cancel-evidence",
    )
    completed = journal.append(
        EventAppend(
            stream_id="kernel:paper",
            event_type="BrokerCommandCompleted",
            payload={"receipt": receipt.to_payload()},
            idempotency_key=f"test-complete:{cancel.command_id.removeprefix('command:')}",
            expected_version=prepared.stream_sequence,
            occurred_at=NOW,
            causation_id=cancel.command_id,
            correlation_id=intent.intent_id,
        )
    )
    return completed.event_id


def test_trade_intent_is_long_only_validated_and_content_addressed():
    first = _intent()
    same = _intent()

    assert first.intent_id == same.intent_id
    assert first.intent_id.startswith("intent:")
    assert first.side == "BUY"
    assert first.product == "DELIVERY"
    assert (
        replace(first, market_snapshot_id="snapshot:market-2").intent_id
        != first.intent_id
    )

    with pytest.raises(ValueError, match="positive integer"):
        _intent(quantity=0)
    with pytest.raises(TypeError, match="integer paise"):
        _intent(limit_price_paise=float("nan"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="below entry"):
        TradeIntent(
            strategy_plan_id="plan:x",
            decision_trace_id="trace:x",
            market_snapshot_id="snapshot:market-x",
            account_snapshot_id=_snapshot().snapshot_id,
            instrument_id="INFY",
            quantity=1,
            limit_price_paise=100,
            stop_price_paise=100,
            target_price_paise=110,
            created_at=NOW,
        )


def test_account_snapshot_identity_covers_every_material_field():
    first = _snapshot()
    same = _snapshot()

    assert first.snapshot_id == same.snapshot_id
    assert first.snapshot_id.startswith("snapshot:")
    material_changes = (
        {"available_cash_paise": 9_999_999},
        {"marked_equity_paise": 9_999_999},
        {"high_water_mark_paise": 10_000_001},
        {"day_pnl_paise": -1},
        {"week_pnl_paise": -1},
        {"positions": (AccountPosition("INFY", 1, 100_000, 5_000),)},
        {"included_reservation_ids": (f"reservation:{'a' * 64}",)},
        {"reconciled": False},
        {"captured_at": NOW + timedelta(seconds=1)},
    )
    assert all(
        replace(first, **change).snapshot_id != first.snapshot_id
        for change in material_changes
    )
    with pytest.raises(TypeError, match="snapshot_id"):
        AccountSnapshot(  # type: ignore[call-arg]
            snapshot_id="snapshot:forged",
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


def test_reservations_atomically_include_held_and_pending_capacity(tmp_path):
    risk = _risk(tmp_path, max_positions=2)
    account = _snapshot(
        cash=4_000_000,
        positions=(AccountPosition("RELIANCE", 2, 1_000_000, 40_000),),
    )

    first = risk.reserve(_intent("INFY", account_snapshot=account), account, NOW)
    repeated = risk.reserve(_intent("INFY", account_snapshot=account), account, NOW)

    assert repeated == first
    assert first.state is ReservationState.RESERVED

    with pytest.raises(RiskRejected, match="open-position slots"):
        risk.reserve(_intent("TCS", account_snapshot=account), account, NOW)

    assert len(risk.reservations()) == 1


def test_stale_or_unreconciled_snapshot_blocks_reservation(tmp_path):
    risk = _risk(tmp_path)

    with pytest.raises(RiskRejected, match="stale"):
        stale = _snapshot(captured_at=NOW - timedelta(minutes=3))
        risk.reserve(_intent(account_snapshot=stale), stale, NOW)
    with pytest.raises(RiskRejected, match="not reconciled"):
        unreconciled = _snapshot(reconciled=False)
        risk.reserve(_intent(account_snapshot=unreconciled), unreconciled, NOW)

    assert risk.reservations() == ()


def test_reservation_requires_the_account_snapshot_pinned_by_intent(tmp_path):
    risk = _risk(tmp_path)
    original = _snapshot()
    intent = _intent(account_snapshot=original)
    mismatched = replace(original, day_pnl_paise=1)

    with pytest.raises(RiskRejected, match="does not match"):
        risk.reserve(intent, mismatched, NOW)

    forged = replace(original, day_pnl_paise=1)
    object.__setattr__(forged, "snapshot_id", original.snapshot_id)
    with pytest.raises(RiskRejected, match="content identity"):
        risk.reserve(intent, forged, NOW)


def test_fill_and_release_are_monotonic_and_do_not_free_filled_exposure(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    risk = _risk(tmp_path, journal=journal)
    account = _snapshot()
    intent = _intent(quantity=10, account_snapshot=account)
    reservation = risk.reserve(intent, account, NOW)

    partial = risk.apply_fill(
        reservation.reservation_id,
        cumulative_quantity=4,
        average_price_paise=149_000,
        occurred_at=NOW,
    )
    assert partial.state is ReservationState.PARTIALLY_FILLED
    assert partial.filled_quantity == 4
    assert partial.remaining_quantity == 6

    with pytest.raises(RiskRejected, match="cannot move backwards"):
        risk.apply_fill(
            reservation.reservation_id,
            cumulative_quantity=3,
            average_price_paise=149_000,
            occurred_at=NOW,
        )

    with pytest.raises(TypeError, match="terminal_evidence_event_id"):
        risk.release(reservation.reservation_id, occurred_at=NOW)  # type: ignore[call-arg]
    with pytest.raises(RiskRejected, match="terminal evidence"):
        risk.release(
            reservation.reservation_id,
            terminal_evidence_event_id="event:not-real",
            occurred_at=NOW,
        )
    other_intent = _intent("TCS", account_snapshot=account)
    with pytest.raises(RiskRejected, match="another intent"):
        risk.release(
            reservation.reservation_id,
            terminal_evidence_event_id=_completed_cancel_evidence(
                journal, other_intent, remaining_quantity=6
            ),
            occurred_at=NOW,
        )

    terminal = risk.release(
        reservation.reservation_id,
        terminal_evidence_event_id=_completed_cancel_evidence(
            journal, intent, remaining_quantity=6
        ),
        occurred_at=NOW,
    )
    assert terminal.state is ReservationState.FILLED
    assert terminal.filled_quantity == 4
    assert terminal.remaining_quantity == 0

    # Until a clean broker snapshot explicitly includes this reservation,
    # its filled exposure remains encumbered and cannot be silently reused.
    with pytest.raises(RiskRejected, match="cash capacity"):
        next_account = _snapshot(cash=2_000_000)
        risk.reserve(
            _intent("TCS", quantity=20, account_snapshot=next_account),
            next_account,
            NOW,
        )


@pytest.mark.parametrize(
    ("evidence_case", "message"),
    [
        ("missing-entry", "no prior entry preparation"),
        ("wrong-intent", "another intent"),
        ("wrong-instrument", "another instrument"),
        ("uncompleted-entry", "no accepted broker completion"),
    ],
)
def test_release_requires_the_exact_completed_entry_command(
    tmp_path, evidence_case, message
):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    risk = _risk(tmp_path, journal=journal)
    account = _snapshot()
    intent = _intent(account_snapshot=account)
    reservation = risk.reserve(intent, account, NOW)
    entry = EntryCommand(
        intent_id=(
            _intent("TCS", account_snapshot=account).intent_id
            if evidence_case == "wrong-intent"
            else intent.intent_id
        ),
        instrument_id=(
            "TCS" if evidence_case == "wrong-instrument" else intent.instrument_id
        ),
        quantity=intent.quantity,
        limit_price_paise=intent.limit_price_paise,
    )
    evidence = _completed_cancel_evidence(
        journal,
        intent,
        remaining_quantity=intent.quantity,
        entry=entry,
        record_entry=evidence_case != "missing-entry",
        complete_entry=evidence_case != "uncompleted-entry",
    )

    with pytest.raises(RiskRejected, match=message):
        risk.release(
            reservation.reservation_id,
            terminal_evidence_event_id=evidence,
            occurred_at=NOW,
        )

    assert risk.reservations()[0].state is ReservationState.RESERVED


def test_two_stale_risk_writers_cannot_overbook_same_capacity(tmp_path):
    path = tmp_path / "journal.sqlite3"
    limits = RiskLimits(
        max_total_notional_paise=2_000_000,
        max_position_notional_paise=2_000_000,
        max_risk_per_trade_paise=100_000,
        max_total_risk_paise=500_000,
        max_open_positions=1,
        snapshot_max_age=timedelta(minutes=2),
        max_daily_loss_paise=500_000,
        max_weekly_loss_paise=1_000_000,
        max_drawdown_bps=2_000,
    )
    first_writer = PortfolioRisk(OperationalJournal(path), limits)
    second_writer = PortfolioRisk(OperationalJournal(path), limits)
    account = _snapshot(cash=2_000_000)

    first_writer.reserve(
        _intent("INFY", quantity=10, account_snapshot=account), account, NOW
    )
    with pytest.raises((RiskRejected, JournalConflict)):
        second_writer.reserve(
            _intent("TCS", quantity=10, account_snapshot=account), account, NOW
        )

    assert len(first_writer.reservations()) == 1


def test_total_heat_includes_held_positions_and_pending_reservations(tmp_path):
    risk = _risk(tmp_path, max_positions=4, max_total_risk_paise=120_000)
    account = _snapshot(
        positions=(AccountPosition("RELIANCE", 2, 1_000_000, 60_000),),
    )

    risk.reserve(
        _intent("INFY", account_snapshot=account), account, NOW
    )  # another 50,000 paise at risk

    with pytest.raises(RiskRejected, match="total portfolio risk"):
        risk.reserve(_intent("TCS", account_snapshot=account), account, NOW)


@pytest.mark.parametrize(
    ("snapshot", "message"),
    [
        (_snapshot(day_pnl_paise=-500_000), "daily loss"),
        (_snapshot(week_pnl_paise=-1_000_000), "weekly loss"),
        (
            _snapshot(
                marked_equity_paise=8_000_000,
                high_water_mark_paise=10_000_000,
            ),
            "drawdown",
        ),
    ],
)
def test_loss_and_drawdown_breakers_reject_new_reservations(
    tmp_path, snapshot, message
):
    risk = _risk(tmp_path)

    with pytest.raises(RiskRejected, match=message):
        risk.reserve(_intent(account_snapshot=snapshot), snapshot, NOW)

    assert risk.reservations() == ()


def test_unreconciled_partial_fill_risk_remains_in_total_heat(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    risk = _risk(
        tmp_path,
        max_positions=4,
        max_total_risk_paise=70_000,
        journal=journal,
    )
    account = _snapshot()
    intent = _intent("INFY", account_snapshot=account)
    reservation = risk.reserve(intent, account, NOW)
    risk.apply_fill(
        reservation.reservation_id,
        cumulative_quantity=4,
        average_price_paise=149_000,
        occurred_at=NOW,
    )
    risk.release(
        reservation.reservation_id,
        terminal_evidence_event_id=_completed_cancel_evidence(
            journal, intent, remaining_quantity=6
        ),
        occurred_at=NOW,
    )

    # Filled risk is 4 * (149000 - 145000) = 16,000 and remains in heat
    # until a reconciled marked snapshot includes the reservation.
    with pytest.raises(RiskRejected, match="total portfolio risk"):
        next_account = _snapshot()
        risk.reserve(
            _intent("TCS", quantity=12, account_snapshot=next_account),
            next_account,
            NOW,
        )
