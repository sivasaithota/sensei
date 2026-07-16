"""Account truth projected from the durable paper broker boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime

from sensei.kernel import BrokerSnapshot, EntryCommand, RecordingPaperGateway
from sensei.portfolio_risk.models import (
    AccountPosition,
    AccountSnapshot,
    require_integer,
    require_positive_integer,
    require_timestamp,
)


class PaperAccountProjectionError(RuntimeError):
    """Durable paper broker facts cannot form reconciled account truth."""


class PaperAccountProjector:
    """Turn durable paper fills, protection and marks into account truth."""

    def __init__(
        self,
        gateway: RecordingPaperGateway,
        *,
        starting_capital_paise: int,
        high_water_mark_paise: int,
        day_pnl_paise: int = 0,
        week_pnl_paise: int = 0,
        baseline_snapshot_source: (
            Callable[[datetime, Mapping[str, int]], AccountSnapshot] | None
        ) = None,
    ) -> None:
        if type(gateway) is not RecordingPaperGateway:
            raise TypeError("gateway must be the exact RecordingPaperGateway type")
        require_positive_integer(
            starting_capital_paise,
            "starting_capital_paise",
        )
        require_positive_integer(
            high_water_mark_paise,
            "high_water_mark_paise",
        )
        require_integer(day_pnl_paise, "day_pnl_paise")
        require_integer(week_pnl_paise, "week_pnl_paise")
        self._gateway = gateway
        self._starting_capital_paise = starting_capital_paise
        self._high_water_mark_paise = high_water_mark_paise
        self._day_pnl_paise = day_pnl_paise
        self._week_pnl_paise = week_pnl_paise
        if baseline_snapshot_source is not None and not callable(
            baseline_snapshot_source
        ):
            raise TypeError("baseline_snapshot_source must be callable")
        self._baseline_snapshot_source = baseline_snapshot_source

    def is_bound_to_gateway(self, gateway: RecordingPaperGateway) -> bool:
        """Return whether projection reads the exact runtime gateway."""

        return self._gateway is gateway

    def project(
        self,
        *,
        captured_at: datetime,
        mark_prices_paise: Mapping[str, int],
    ) -> AccountSnapshot:
        require_timestamp(captured_at, "captured_at")
        broker = self._gateway.broker_snapshot(captured_at=captured_at)
        return self.project_broker_snapshot(
            broker,
            mark_prices_paise=mark_prices_paise,
        )

    def _merge_baseline(
        self,
        baseline: AccountSnapshot,
        governed: AccountSnapshot,
    ) -> AccountSnapshot:
        if not isinstance(baseline, AccountSnapshot) or not baseline.reconciled:
            raise PaperAccountProjectionError(
                "pre-cutover baseline must be a reconciled AccountSnapshot"
            )
        baseline_ids = {position.instrument_id for position in baseline.positions}
        governed_ids = {position.instrument_id for position in governed.positions}
        overlap = baseline_ids & governed_ids
        if overlap:
            raise PaperAccountProjectionError(
                "pre-cutover and governed positions overlap: "
                + ", ".join(sorted(overlap))
            )
        governed_spend = self._starting_capital_paise - governed.available_cash_paise
        available_cash = baseline.available_cash_paise - governed_spend
        if available_cash < 0:
            raise PaperAccountProjectionError(
                "combined paper exposure would create unknown negative cash"
            )
        governed_notional = sum(
            position.notional_paise for position in governed.positions
        )
        marked_equity = baseline.marked_equity_paise - governed_spend + governed_notional
        return AccountSnapshot(
            available_cash_paise=available_cash,
            marked_equity_paise=marked_equity,
            high_water_mark_paise=max(
                self._high_water_mark_paise,
                baseline.high_water_mark_paise,
                marked_equity,
            ),
            day_pnl_paise=baseline.day_pnl_paise + governed.day_pnl_paise,
            week_pnl_paise=baseline.week_pnl_paise + governed.week_pnl_paise,
            positions=baseline.positions + governed.positions,
            included_reservation_ids=(
                baseline.included_reservation_ids
                + governed.included_reservation_ids
            ),
            reconciled=True,
            captured_at=governed.captured_at,
        )

    def project_broker_snapshot(
        self,
        broker_snapshot: BrokerSnapshot,
        *,
        mark_prices_paise: Mapping[str, int],
    ) -> AccountSnapshot:
        """Project one exact broker snapshot without recapturing gateway state."""

        if not isinstance(broker_snapshot, BrokerSnapshot):
            raise TypeError("broker_snapshot must be a BrokerSnapshot")
        broker = broker_snapshot
        positions = {item.instrument_id: item for item in broker.positions}
        protections = {
            item.instrument_id: item for item in broker.protections
        }
        orphaned_protections = set(protections) - set(positions)
        if orphaned_protections:
            raise PaperAccountProjectionError(
                "paper broker has protection without a filled position: "
                + ", ".join(sorted(orphaned_protections))
            )

        filled_quantities: dict[str, int] = {}
        filled_cost_paise = 0
        included_reservations: set[str] = set()
        for command in self._gateway.commands:
            if not isinstance(command, EntryCommand):
                continue
            receipt = self._gateway.receipt_for(command.command_id)
            if receipt is None:
                raise PaperAccountProjectionError(
                    f"durable entry receipt is missing for {command.command_id}"
                )
            if not receipt.accepted or not receipt.cumulative_fill_quantity:
                continue
            average_price = receipt.average_fill_price_paise
            if average_price is None:
                raise PaperAccountProjectionError(
                    f"filled entry has no average price for {command.command_id}"
                )
            filled_quantities[command.instrument_id] = (
                filled_quantities.get(command.instrument_id, 0)
                + receipt.cumulative_fill_quantity
            )
            filled_cost_paise += (
                receipt.cumulative_fill_quantity * average_price
            )
            included_reservations.add(
                "reservation:" + command.intent_id.removeprefix("intent:")
            )

        broker_quantities = {
            instrument_id: position.quantity
            for instrument_id, position in positions.items()
        }
        if broker_quantities != filled_quantities:
            raise PaperAccountProjectionError(
                "durable fills do not match paper broker positions"
            )

        account_positions: list[AccountPosition] = []
        marked_notional_paise = 0
        for instrument_id, broker_position in positions.items():
            if instrument_id not in mark_prices_paise:
                raise PaperAccountProjectionError(
                    f"current mark is missing for {instrument_id}"
                )
            mark_price = mark_prices_paise[instrument_id]
            require_positive_integer(
                mark_price,
                f"mark_prices_paise[{instrument_id!r}]",
            )
            protection = protections.get(instrument_id)
            if protection is None:
                raise PaperAccountProjectionError(
                    f"protection is missing for {instrument_id}"
                )
            if protection.quantity != broker_position.quantity:
                raise PaperAccountProjectionError(
                    f"protection quantity does not match {instrument_id} position"
                )
            notional = broker_position.quantity * mark_price
            risk_to_stop = broker_position.quantity * max(
                0,
                mark_price - protection.stop_price_paise,
            )
            marked_notional_paise += notional
            account_positions.append(
                AccountPosition(
                    instrument_id=instrument_id,
                    quantity=broker_position.quantity,
                    notional_paise=notional,
                    risk_to_stop_paise=risk_to_stop,
                )
            )

        available_cash_paise = (
            self._starting_capital_paise - filled_cost_paise
        )
        if available_cash_paise < 0:
            raise PaperAccountProjectionError(
                "durable filled cost would create unknown negative cash"
            )
        marked_equity_paise = available_cash_paise + marked_notional_paise
        high_water_mark_paise = max(
            self._high_water_mark_paise,
            marked_equity_paise,
        )
        self._high_water_mark_paise = high_water_mark_paise
        governed = AccountSnapshot(
            available_cash_paise=available_cash_paise,
            marked_equity_paise=marked_equity_paise,
            high_water_mark_paise=high_water_mark_paise,
            day_pnl_paise=self._day_pnl_paise,
            week_pnl_paise=self._week_pnl_paise,
            positions=tuple(account_positions),
            included_reservation_ids=tuple(included_reservations),
            reconciled=True,
            captured_at=broker.captured_at,
        )
        if self._baseline_snapshot_source is None:
            return governed
        baseline = self._baseline_snapshot_source(
            broker.captured_at,
            mark_prices_paise,
        )
        return self._merge_baseline(baseline, governed)
