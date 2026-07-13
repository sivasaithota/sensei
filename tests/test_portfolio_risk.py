from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from sensei.operations.journal import JournalConflict, OperationalJournal
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
) -> TradeIntent:
    return TradeIntent(
        strategy_plan_id="plan:hammer-v1",
        decision_trace_id=f"trace:{symbol.lower()}",
        market_snapshot_id="snapshot:market-1",
        account_snapshot_id="snapshot:broker-1",
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
        snapshot_id="snapshot:broker-1",
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
    tmp_path, *, max_positions: int = 2, max_total_risk_paise: int = 500_000
) -> PortfolioRisk:
    return PortfolioRisk(
        OperationalJournal(tmp_path / "journal.sqlite3"),
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
            account_snapshot_id="snapshot:broker-1",
            instrument_id="INFY",
            quantity=1,
            limit_price_paise=100,
            stop_price_paise=100,
            target_price_paise=110,
            created_at=NOW,
        )


def test_reservations_atomically_include_held_and_pending_capacity(tmp_path):
    risk = _risk(tmp_path, max_positions=2)
    account = _snapshot(
        cash=4_000_000,
        positions=(AccountPosition("RELIANCE", 2, 1_000_000, 40_000),),
    )

    first = risk.reserve(_intent("INFY"), account, NOW)
    repeated = risk.reserve(_intent("INFY"), account, NOW)

    assert repeated == first
    assert first.state is ReservationState.RESERVED

    with pytest.raises(RiskRejected, match="open-position slots"):
        risk.reserve(_intent("TCS"), account, NOW)

    assert len(risk.reservations()) == 1


def test_stale_or_unreconciled_snapshot_blocks_reservation(tmp_path):
    risk = _risk(tmp_path)

    with pytest.raises(RiskRejected, match="stale"):
        risk.reserve(
            _intent(),
            _snapshot(captured_at=NOW - timedelta(minutes=3)),
            NOW,
        )
    with pytest.raises(RiskRejected, match="not reconciled"):
        risk.reserve(_intent(), _snapshot(reconciled=False), NOW)

    assert risk.reservations() == ()


def test_reservation_requires_the_account_snapshot_pinned_by_intent(tmp_path):
    risk = _risk(tmp_path)
    mismatched = AccountSnapshot(
        snapshot_id="snapshot:different-account",
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

    with pytest.raises(RiskRejected, match="does not match"):
        risk.reserve(_intent(), mismatched, NOW)


def test_fill_and_release_are_monotonic_and_do_not_free_filled_exposure(tmp_path):
    risk = _risk(tmp_path)
    reservation = risk.reserve(_intent(quantity=10), _snapshot(), NOW)

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

    terminal = risk.release(reservation.reservation_id, occurred_at=NOW)
    assert terminal.state is ReservationState.FILLED
    assert terminal.filled_quantity == 4
    assert terminal.remaining_quantity == 0

    # Until a clean broker snapshot explicitly includes this reservation,
    # its filled exposure remains encumbered and cannot be silently reused.
    with pytest.raises(RiskRejected, match="cash capacity"):
        risk.reserve(_intent("TCS", quantity=20), _snapshot(cash=2_000_000), NOW)


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

    first_writer.reserve(_intent("INFY", quantity=10), account, NOW)
    with pytest.raises((RiskRejected, JournalConflict)):
        second_writer.reserve(_intent("TCS", quantity=10), account, NOW)

    assert len(first_writer.reservations()) == 1


def test_total_heat_includes_held_positions_and_pending_reservations(tmp_path):
    risk = _risk(tmp_path, max_positions=4, max_total_risk_paise=120_000)
    account = _snapshot(
        positions=(AccountPosition("RELIANCE", 2, 1_000_000, 60_000),),
    )

    risk.reserve(_intent("INFY"), account, NOW)  # another 50,000 paise at risk

    with pytest.raises(RiskRejected, match="total portfolio risk"):
        risk.reserve(_intent("TCS"), account, NOW)


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
        risk.reserve(_intent(), snapshot, NOW)

    assert risk.reservations() == ()


def test_unreconciled_partial_fill_risk_remains_in_total_heat(tmp_path):
    risk = _risk(tmp_path, max_positions=4, max_total_risk_paise=70_000)
    reservation = risk.reserve(_intent("INFY"), _snapshot(), NOW)
    risk.apply_fill(
        reservation.reservation_id,
        cumulative_quantity=4,
        average_price_paise=149_000,
        occurred_at=NOW,
    )
    risk.release(reservation.reservation_id, occurred_at=NOW)

    # Filled risk is 4 * (149000 - 145000) = 16,000 and remains in heat
    # until a reconciled marked snapshot includes the reservation.
    with pytest.raises(RiskRejected, match="total portfolio risk"):
        risk.reserve(_intent("TCS", quantity=12), _snapshot(), NOW)
