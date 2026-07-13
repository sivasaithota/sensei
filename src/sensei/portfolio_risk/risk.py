"""Journal-backed portfolio reservations.

Every admission consumes portfolio capacity before an order can be prepared.
Optimistic stream versions make the read/check/append sequence fail closed if
two risk writers race.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime

from sensei.operations.journal import EventAppend, OperationalJournal

from .models import (
    AccountSnapshot,
    ReservationState,
    RiskLimits,
    RiskRejected,
    RiskReservation,
    TradeIntent,
    require_positive_integer,
    require_timestamp,
)

_STREAM = "risk:portfolio"


class PortfolioRisk:
    def __init__(self, journal: OperationalJournal, limits: RiskLimits) -> None:
        self._journal = journal
        self._limits = limits

    def reserve(
        self,
        intent: TradeIntent,
        account_snapshot: AccountSnapshot,
        now: datetime,
    ) -> RiskReservation:
        require_timestamp(now, "now")
        reservation_id = f"reservation:{intent.intent_id.removeprefix('intent:')}"
        current = {item.reservation_id: item for item in self.reservations()}
        existing = current.get(reservation_id)
        if existing is not None:
            if existing.intent != intent:
                raise RiskRejected("reservation identity conflicts with durable content")
            return existing

        if intent.account_snapshot_id != account_snapshot.snapshot_id:
            raise RiskRejected(
                "intent account snapshot does not match reservation evidence"
            )
        self._validate_snapshot(account_snapshot, now)
        existing_items = tuple(current.values())
        included = set(account_snapshot.included_reservation_ids)
        encumbered = sum(
            self._additional_notional(item, included) for item in existing_items
        )
        encumbered_risk = sum(
            self._additional_risk(item, included) for item in existing_items
        )

        if intent.risk_paise > self._limits.max_risk_per_trade_paise:
            raise RiskRejected(
                f"trade risk {intent.risk_paise} exceeds per-trade capacity "
                f"{self._limits.max_risk_per_trade_paise}"
            )
        total_risk = (
            account_snapshot.held_risk_paise
            + encumbered_risk
            + intent.risk_paise
        )
        if total_risk > self._limits.max_total_risk_paise:
            raise RiskRejected(
                f"total portfolio risk {total_risk} exceeds capacity "
                f"{self._limits.max_total_risk_paise}"
            )
        if encumbered + intent.notional_paise > account_snapshot.available_cash_paise:
            raise RiskRejected("insufficient cash capacity after existing reservations")

        total = (
            account_snapshot.held_notional_paise
            + encumbered
            + intent.notional_paise
        )
        if total > self._limits.max_total_notional_paise:
            raise RiskRejected("total portfolio notional capacity exceeded")

        held_for_symbol = sum(
            position.notional_paise
            for position in account_snapshot.positions
            if position.instrument_id == intent.instrument_id
        )
        reserved_for_symbol = sum(
            self._additional_notional(item, included)
            for item in existing_items
            if item.intent.instrument_id == intent.instrument_id
        )
        if (
            held_for_symbol + reserved_for_symbol + intent.notional_paise
            > self._limits.max_position_notional_paise
        ):
            raise RiskRejected("instrument position notional capacity exceeded")

        occupied_symbols = {
            position.instrument_id for position in account_snapshot.positions
        }
        occupied_symbols.update(
            item.intent.instrument_id
            for item in existing_items
            if self._additional_notional(item, included) > 0
        )
        occupied_symbols.add(intent.instrument_id)
        if len(occupied_symbols) > self._limits.max_open_positions:
            raise RiskRejected("open-position slots exhausted")

        events = self._journal.read_stream(_STREAM)
        self._journal.append(
            EventAppend(
                stream_id=_STREAM,
                event_type="RiskReserved",
                payload={
                    "reservation_id": reservation_id,
                    "intent": intent.to_payload(),
                    "account_snapshot_id": account_snapshot.snapshot_id,
                },
                idempotency_key=f"risk-reserve:{intent.intent_id.removeprefix('intent:')}",
                expected_version=len(events),
                occurred_at=now,
                correlation_id=intent.intent_id,
            )
        )
        return self._by_id(reservation_id)

    def apply_fill(
        self,
        reservation_id: str,
        *,
        cumulative_quantity: int,
        average_price_paise: int,
        occurred_at: datetime,
    ) -> RiskReservation:
        require_timestamp(occurred_at, "occurred_at")
        if isinstance(cumulative_quantity, bool) or not isinstance(
            cumulative_quantity, int
        ):
            raise TypeError("cumulative_quantity must be an integer")
        require_positive_integer(average_price_paise, "average_price_paise")
        reservation = self._by_id(reservation_id)
        if cumulative_quantity < reservation.filled_quantity:
            raise RiskRejected("cumulative fill cannot move backwards")
        if cumulative_quantity > reservation.intent.quantity:
            raise RiskRejected("cumulative fill exceeds reserved quantity")
        if cumulative_quantity == reservation.filled_quantity:
            if (
                cumulative_quantity > 0
                and reservation.average_fill_price_paise != average_price_paise
            ):
                raise RiskRejected("same cumulative fill conflicts with average price")
            return reservation
        if reservation.state in {ReservationState.FILLED, ReservationState.RELEASED}:
            raise RiskRejected("terminal reservation cannot accept another fill")

        events = self._journal.read_stream(_STREAM)
        self._journal.append(
            EventAppend(
                stream_id=_STREAM,
                event_type="RiskFillApplied",
                payload={
                    "reservation_id": reservation_id,
                    "cumulative_quantity": cumulative_quantity,
                    "average_price_paise": average_price_paise,
                },
                idempotency_key=(
                    "risk-fill:"
                    + hashlib.sha256(
                        f"{reservation_id}:{cumulative_quantity}".encode("utf-8")
                    ).hexdigest()
                ),
                expected_version=len(events),
                occurred_at=occurred_at,
                correlation_id=reservation.intent.intent_id,
            )
        )
        return self._by_id(reservation_id)

    def release(
        self, reservation_id: str, *, occurred_at: datetime
    ) -> RiskReservation:
        require_timestamp(occurred_at, "occurred_at")
        reservation = self._by_id(reservation_id)
        if reservation.state in {ReservationState.FILLED, ReservationState.RELEASED}:
            return reservation
        events = self._journal.read_stream(_STREAM)
        self._journal.append(
            EventAppend(
                stream_id=_STREAM,
                event_type="RiskReleased",
                payload={"reservation_id": reservation_id},
                idempotency_key=(
                    "risk-release:"
                    f"{reservation_id.removeprefix('reservation:')}"
                ),
                expected_version=len(events),
                occurred_at=occurred_at,
                correlation_id=reservation.intent.intent_id,
            )
        )
        return self._by_id(reservation_id)

    def reservations(self) -> tuple[RiskReservation, ...]:
        reservations: dict[str, RiskReservation] = {}
        for event in self._journal.read_stream(_STREAM):
            payload = event.payload
            if event.event_type == "RiskReserved":
                intent = TradeIntent.from_payload(payload["intent"])
                reservation_id = str(payload["reservation_id"])
                reservations[reservation_id] = RiskReservation(
                    reservation_id=reservation_id,
                    intent=intent,
                    state=ReservationState.RESERVED,
                    filled_quantity=0,
                    remaining_quantity=intent.quantity,
                    average_fill_price_paise=None,
                    version=event.stream_sequence,
                )
            elif event.event_type == "RiskFillApplied":
                reservation_id = str(payload["reservation_id"])
                current = reservations[reservation_id]
                filled = int(payload["cumulative_quantity"])
                state = (
                    ReservationState.FILLED
                    if filled == current.intent.quantity
                    else ReservationState.PARTIALLY_FILLED
                )
                reservations[reservation_id] = replace(
                    current,
                    state=state,
                    filled_quantity=filled,
                    remaining_quantity=current.intent.quantity - filled,
                    average_fill_price_paise=int(payload["average_price_paise"]),
                    version=event.stream_sequence,
                )
            elif event.event_type == "RiskReleased":
                reservation_id = str(payload["reservation_id"])
                current = reservations[reservation_id]
                reservations[reservation_id] = replace(
                    current,
                    state=(
                        ReservationState.FILLED
                        if current.filled_quantity
                        else ReservationState.RELEASED
                    ),
                    remaining_quantity=0,
                    version=event.stream_sequence,
                )
        return tuple(reservations.values())

    def _by_id(self, reservation_id: str) -> RiskReservation:
        for reservation in self.reservations():
            if reservation.reservation_id == reservation_id:
                return reservation
        raise RiskRejected(f"unknown reservation {reservation_id!r}")

    def _validate_snapshot(self, snapshot: AccountSnapshot, now: datetime) -> None:
        if not snapshot.reconciled:
            raise RiskRejected("account snapshot is not reconciled")
        age = now - snapshot.captured_at
        if age < -self._limits.snapshot_max_age:
            raise RiskRejected("account snapshot is implausibly in the future")
        if age > self._limits.snapshot_max_age:
            raise RiskRejected("account snapshot is stale")
        if snapshot.day_pnl_paise <= -self._limits.max_daily_loss_paise:
            raise RiskRejected(
                f"daily loss breaker reached: {snapshot.day_pnl_paise}"
            )
        if snapshot.week_pnl_paise <= -self._limits.max_weekly_loss_paise:
            raise RiskRejected(
                f"weekly loss breaker reached: {snapshot.week_pnl_paise}"
            )
        drawdown_paise = (
            snapshot.high_water_mark_paise - snapshot.marked_equity_paise
        )
        if (
            drawdown_paise * 10_000
            >= snapshot.high_water_mark_paise * self._limits.max_drawdown_bps
        ):
            raise RiskRejected(
                "drawdown breaker reached: "
                f"{drawdown_paise} paise from high-water mark"
            )

    @staticmethod
    def _additional_notional(
        reservation: RiskReservation, included: set[str]
    ) -> int:
        remaining = (
            reservation.remaining_quantity * reservation.intent.limit_price_paise
        )
        if reservation.reservation_id in included:
            return remaining
        filled = reservation.filled_quantity * (
            reservation.average_fill_price_paise
            or reservation.intent.limit_price_paise
        )
        return filled + remaining

    @staticmethod
    def _additional_risk(
        reservation: RiskReservation, included: set[str]
    ) -> int:
        unit_pending_risk = (
            reservation.intent.limit_price_paise
            - reservation.intent.stop_price_paise
        )
        remaining_risk = reservation.remaining_quantity * unit_pending_risk
        if reservation.reservation_id in included:
            return remaining_risk
        fill_price = (
            reservation.average_fill_price_paise
            or reservation.intent.limit_price_paise
        )
        unit_filled_risk = max(0, fill_price - reservation.intent.stop_price_paise)
        return reservation.filled_quantity * unit_filled_risk + remaining_risk
