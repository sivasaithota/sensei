"""A deliberately paper-only broker boundary.

There is no live adapter in this package.  Any future broker implementation
must provide durable client-command idempotency before it can satisfy this
protocol.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from sensei.execution.nse import NseExecutionModel, NseMarketObservation

from sensei.operations.journal import (
    EventAppend,
    JournalConflict,
    JournalEvent,
    JournalIntegrityError,
    OperationalJournal,
)
from sensei.portfolio_risk.models import require_positive_integer

from .commands import (
    BrokerCommand,
    CancelEntryCommand,
    EntryCommand,
    ProtectionCommand,
    command_from_payload,
)
from .reconciliation import (
    BrokerPosition,
    BrokerProtection,
    BrokerSnapshot,
    BrokerWorkingOrder,
)


_DURABLE_EVENT_TYPE = "PaperGatewayCommandExecuted"
_DURABLE_STREAM_PREFIX = "paper-gateway:"
_DURABLE_IDEMPOTENCY_PREFIX = "paper-gateway-execute:"


@dataclass(frozen=True)
class GatewayReceipt:
    command_id: str
    accepted: bool
    broker_reference: str
    cumulative_fill_quantity: int = 0
    average_fill_price_paise: int | None = None
    execution_quality: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not self.command_id.startswith("command:"):
            raise ValueError("receipt command_id must be a content address")
        if not self.broker_reference.strip():
            raise ValueError("broker_reference must not be blank")
        if isinstance(self.cumulative_fill_quantity, bool) or not isinstance(
            self.cumulative_fill_quantity, int
        ):
            raise TypeError("cumulative_fill_quantity must be an integer")
        if self.cumulative_fill_quantity < 0:
            raise ValueError("cumulative_fill_quantity must not be negative")
        if self.cumulative_fill_quantity:
            require_positive_integer(
                self.average_fill_price_paise, "average_fill_price_paise"
            )
        elif self.average_fill_price_paise is not None:
            raise ValueError("zero fill must not carry an average fill price")
        if self.execution_quality is not None and not isinstance(
            self.execution_quality, Mapping
        ):
            raise TypeError("execution_quality must be a mapping")
        if self.execution_quality is not None:
            _validate_execution_quality(self)

    def to_payload(self) -> dict[str, object]:
        return {
            "command_id": self.command_id,
            "accepted": self.accepted,
            "broker_reference": self.broker_reference,
            "cumulative_fill_quantity": self.cumulative_fill_quantity,
            "average_fill_price_paise": self.average_fill_price_paise,
            "execution_quality": self.execution_quality,
        }


class PaperGateway(Protocol):
    def execute(self, command: BrokerCommand) -> GatewayReceipt:
        """Execute once by command_id, returning the original receipt on retry."""

    def receipt_for(self, command_id: str) -> GatewayReceipt | None:
        """Return durable outcome truth, or None only if never accepted."""

    def broker_snapshot(self, *, captured_at: datetime) -> BrokerSnapshot:
        """Return current paper broker truth reconstructed from commands."""


@dataclass(frozen=True)
class _ExecutionRecord:
    command: BrokerCommand
    receipt: GatewayReceipt


class RecordingPaperGateway:
    """Deterministic paper gateway used by tests and replay harnesses.

    Supplying an OperationalJournal enables restart-safe command receipts.  The
    no-argument form intentionally retains its original in-memory behaviour.
    """

    def __init__(
        self,
        journal: OperationalJournal | None = None,
        *,
        auto_fill_at_limit: bool = False,
        execution_model: NseExecutionModel | None = None,
        market_observation: Callable[[str], NseMarketObservation] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if journal is not None and not isinstance(journal, OperationalJournal):
            raise TypeError("journal must be an OperationalJournal")
        if not isinstance(auto_fill_at_limit, bool):
            raise TypeError("auto_fill_at_limit must be a boolean")
        if auto_fill_at_limit and execution_model is not None:
            raise ValueError("execution model replaces optimistic limit auto-fill")
        if (execution_model is None) != (market_observation is None):
            raise ValueError("execution model and market observation must be configured together")
        self._journal = journal
        self._auto_fill_at_limit = auto_fill_at_limit
        self._execution_model = execution_model
        self._market_observation = market_observation
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._commands: list[BrokerCommand] = []
        self._receipts: dict[str, GatewayReceipt] = {}
        self._queued_entry_fills: list[tuple[int, int]] = []

    @property
    def commands(self) -> tuple[BrokerCommand, ...]:
        if self._journal is not None:
            return tuple(record.command for record in self._durable_records())
        return tuple(self._commands)

    def receipt_for(self, command_id: str) -> GatewayReceipt | None:
        if self._journal is not None:
            record = self._durable_record_for(command_id)
            return record.receipt if record is not None else None
        return self._receipts.get(command_id)

    def is_bound_to_journal(self, journal: OperationalJournal) -> bool:
        """Return whether durable receipts use the exact runtime journal."""

        return self._journal is journal

    def broker_snapshot(self, *, captured_at: datetime) -> BrokerSnapshot:
        """Project filled positions and accepted working paper orders."""

        records = self._execution_records()
        cancelled_entries = {
            record.command.entry_command_id
            for record in records
            if record.receipt.accepted
            and isinstance(record.command, CancelEntryCommand)
        }
        position_quantities: dict[str, int] = {}
        protections: dict[str, BrokerProtection] = {}
        working_orders: list[BrokerWorkingOrder] = []
        for record in records:
            command = record.command
            receipt = record.receipt
            if not receipt.accepted:
                continue
            if isinstance(command, EntryCommand):
                if receipt.cumulative_fill_quantity:
                    position_quantities[command.instrument_id] = (
                        position_quantities.get(command.instrument_id, 0)
                        + receipt.cumulative_fill_quantity
                    )
                if (
                    receipt.cumulative_fill_quantity < command.quantity
                    and command.command_id not in cancelled_entries
                ):
                    working_orders.append(
                        BrokerWorkingOrder(
                            broker_order_id=receipt.broker_reference,
                            client_command_id=command.command_id,
                            instrument_id=command.instrument_id,
                            kind=command.kind.value,
                            # Reconciliation currently defines this field as
                            # the original broker command quantity.
                            quantity=command.quantity,
                        )
                    )
            elif isinstance(command, ProtectionCommand):
                protections[command.instrument_id] = BrokerProtection(
                    instrument_id=command.instrument_id,
                    quantity=command.quantity,
                    stop_price_paise=command.stop_price_paise,
                    target_price_paise=command.target_price_paise,
                    client_command_id=command.command_id,
                )
                working_orders.append(
                    BrokerWorkingOrder(
                        broker_order_id=receipt.broker_reference,
                        client_command_id=command.command_id,
                        instrument_id=command.instrument_id,
                        kind=command.kind.value,
                        quantity=command.quantity,
                        stop_price_paise=command.stop_price_paise,
                        target_price_paise=command.target_price_paise,
                    )
                )
        return BrokerSnapshot(
            captured_at=captured_at,
            positions=tuple(
                BrokerPosition(instrument_id, quantity)
                for instrument_id, quantity in position_quantities.items()
            ),
            protections=tuple(protections.values()),
            working_orders=tuple(working_orders),
        )

    def queue_entry_fill(
        self, *, cumulative_quantity: int, average_price_paise: int
    ) -> None:
        if isinstance(cumulative_quantity, bool) or not isinstance(
            cumulative_quantity, int
        ):
            raise TypeError("cumulative_quantity must be an integer")
        if cumulative_quantity < 0:
            raise ValueError("cumulative_quantity must not be negative")
        if cumulative_quantity:
            require_positive_integer(
                average_price_paise, "average_fill_price_paise"
            )
        elif average_price_paise != 0:
            raise ValueError("zero fill must use a zero average price")
        self._queued_entry_fills.append(
            (cumulative_quantity, average_price_paise)
        )

    def execute(self, command: BrokerCommand) -> GatewayReceipt:
        if self._journal is not None:
            return self._execute_durably(command)
        existing = self._receipts.get(command.command_id)
        if existing is not None:
            return existing
        fill_quantity, fill_price, _, quality = self._planned_entry_fill(
            command,
            consume_queued=True,
        )
        receipt = GatewayReceipt(
            command_id=command.command_id,
            accepted=True,
            broker_reference=f"paper:{len(self._commands) + 1}",
            cumulative_fill_quantity=fill_quantity,
            average_fill_price_paise=fill_price if fill_quantity else None,
            execution_quality=quality,
        )
        self._commands.append(command)
        self._receipts[command.command_id] = receipt
        return receipt

    def _execute_durably(self, command: BrokerCommand) -> GatewayReceipt:
        assert self._journal is not None
        existing = self._durable_record_for(command.command_id)
        if existing is not None:
            if existing.command != command:
                raise JournalIntegrityError(
                    "paper gateway command identity conflicts with durable content"
                )
            return existing.receipt

        fill_quantity, fill_price, queued_fill, quality = self._planned_entry_fill(
            command,
            consume_queued=False,
        )
        digest = _command_digest(command.command_id)
        receipt = GatewayReceipt(
            command_id=command.command_id,
            accepted=True,
            broker_reference=f"paper:{digest}",
            cumulative_fill_quantity=fill_quantity,
            average_fill_price_paise=fill_price if fill_quantity else None,
            execution_quality=quality,
        )
        append = EventAppend(
            stream_id=f"{_DURABLE_STREAM_PREFIX}{digest}",
            event_type=_DURABLE_EVENT_TYPE,
            payload={
                "mode": "PAPER",
                "command": command.to_payload(),
                "receipt": receipt.to_payload(),
            },
            idempotency_key=f"{_DURABLE_IDEMPOTENCY_PREFIX}{digest}",
            expected_version=0,
            occurred_at=self._clock(),
            correlation_id=command.intent_id,
        )
        try:
            event = self._journal.append(append)
        except (JournalConflict, JournalIntegrityError):
            recovered = self._durable_record_for(command.command_id)
            if recovered is None or recovered.command != command:
                raise
            if queued_fill:
                self._queued_entry_fills.pop(0)
            return recovered.receipt

        durable = _record_from_event(event)
        if (
            durable.command != command
            or durable.receipt.command_id != command.command_id
        ):
            raise JournalIntegrityError(
                "paper gateway durable receipt does not match its command"
            )
        if queued_fill:
            self._queued_entry_fills.pop(0)
        return durable.receipt

    def _planned_entry_fill(
        self,
        command: BrokerCommand,
        *,
        consume_queued: bool,
    ) -> tuple[int, int | None, bool, Mapping[str, object] | None]:
        if not isinstance(command, EntryCommand):
            return 0, None, False, None
        if self._queued_entry_fills:
            fill_quantity, queued_price = self._queued_entry_fills[0]
            if fill_quantity > command.quantity:
                raise ValueError("queued fill exceeds entry command quantity")
            if consume_queued:
                self._queued_entry_fills.pop(0)
            fill_price = queued_price if fill_quantity else None
            return fill_quantity, fill_price, True, None
        if self._execution_model is not None and self._market_observation is not None:
            observation = self._market_observation(command.instrument_id)
            fill = self._execution_model.simulate_entry(
                quantity=command.quantity,
                limit_price_paise=command.limit_price_paise,
                observation=observation,
                now=self._clock(),
            )
            return (
                fill.filled_quantity, fill.fill_price_paise, False,
                fill.to_payload(),
            )
        if self._auto_fill_at_limit:
            return command.quantity, command.limit_price_paise, False, None
        return 0, None, False, None

    def _durable_record_for(self, command_id: str) -> _ExecutionRecord | None:
        assert self._journal is not None
        digest = _optional_command_digest(command_id)
        if digest is None:
            return None
        events = self._journal.read_stream(f"{_DURABLE_STREAM_PREFIX}{digest}")
        if not events:
            return None
        if len(events) != 1:
            raise JournalIntegrityError(
                "paper gateway command stream must contain exactly one event"
            )
        record = _record_from_event(events[0])
        if record.command.command_id != command_id:
            raise JournalIntegrityError(
                "paper gateway stream does not match its command identity"
            )
        return record

    def _durable_records(self) -> tuple[_ExecutionRecord, ...]:
        assert self._journal is not None
        return tuple(
            _record_from_event(event)
            for event in self._journal.read_all()
            if event.event_type == _DURABLE_EVENT_TYPE
        )

    def _execution_records(self) -> tuple[_ExecutionRecord, ...]:
        if self._journal is not None:
            return self._durable_records()
        return tuple(
            _ExecutionRecord(
                command=command,
                receipt=self._receipts[command.command_id],
            )
            for command in self._commands
        )


def _record_from_event(event: JournalEvent) -> _ExecutionRecord:
    if event.event_type != _DURABLE_EVENT_TYPE:
        raise JournalIntegrityError("unexpected paper gateway event type")
    command_payload = event.payload.get("command")
    receipt_payload = event.payload.get("receipt")
    if (
        event.payload.get("mode") != "PAPER"
        or not isinstance(command_payload, Mapping)
        or not isinstance(receipt_payload, Mapping)
    ):
        raise JournalIntegrityError("paper gateway event payload is invalid")
    try:
        command = command_from_payload(command_payload)
        accepted = receipt_payload["accepted"]
        if not isinstance(accepted, bool):
            raise TypeError("receipt accepted flag must be boolean")
        average = receipt_payload["average_fill_price_paise"]
        receipt = GatewayReceipt(
            command_id=str(receipt_payload["command_id"]),
            accepted=accepted,
            broker_reference=str(receipt_payload["broker_reference"]),
            cumulative_fill_quantity=int(
                receipt_payload["cumulative_fill_quantity"]
            ),
            average_fill_price_paise=(
                int(average) if average is not None else None
            ),
            execution_quality=(
                dict(receipt_payload["execution_quality"])
                if isinstance(receipt_payload.get("execution_quality"), Mapping)
                else None
            ),
        )
        if isinstance(command, EntryCommand) and receipt.execution_quality is not None:
            if receipt.execution_quality["side"] != "BUY":
                raise ValueError("entry execution quality must use BUY side")
    except (KeyError, TypeError, ValueError) as exc:
        raise JournalIntegrityError(
            "paper gateway event cannot be reconstructed"
        ) from exc
    digest = _command_digest(command.command_id)
    if (
        receipt.command_id != command.command_id
        or event.stream_id != f"{_DURABLE_STREAM_PREFIX}{digest}"
        or event.idempotency_key != f"{_DURABLE_IDEMPOTENCY_PREFIX}{digest}"
    ):
        raise JournalIntegrityError(
            "paper gateway durable identities do not match command content"
        )
    return _ExecutionRecord(command=command, receipt=receipt)


def _validate_execution_quality(receipt: GatewayReceipt) -> None:
    quality = receipt.execution_quality
    assert quality is not None
    required = {
        "filled_quantity", "requested_quantity", "unfilled_quantity",
        "fill_price_paise", "reference_price_paise", "slippage_paise",
        "reason_code", "side", "charges", "net_cash_flow_paise",
        "market_evidence",
    }
    if set(quality) != required:
        raise ValueError("execution_quality schema is invalid")
    if quality["filled_quantity"] != receipt.cumulative_fill_quantity:
        raise ValueError("execution quality fill quantity does not match receipt")
    if quality["fill_price_paise"] != receipt.average_fill_price_paise:
        raise ValueError("execution quality fill price does not match receipt")
    requested = quality["requested_quantity"]
    unfilled = quality["unfilled_quantity"]
    if (
        type(requested) is not int
        or type(unfilled) is not int
        or requested < receipt.cumulative_fill_quantity
        or unfilled != requested - receipt.cumulative_fill_quantity
    ):
        raise ValueError("execution quality quantities are invalid")
    if quality["side"] not in {"BUY", "SELL"}:
        raise ValueError("execution quality side is invalid")
    evidence = quality["market_evidence"]
    if evidence is not None and (
        not isinstance(evidence, Mapping)
        or not isinstance(evidence.get("source"), str)
        or not evidence["source"].strip()
        or not isinstance(evidence.get("observed_at"), str)
    ):
        raise ValueError("execution quality market evidence is invalid")
    charges = quality["charges"]
    component_names = {
        "stt_paise", "exchange_paise", "sebi_paise", "stamp_duty_paise",
        "gst_paise", "ipft_paise",
    }
    if not isinstance(charges, Mapping) or set(charges) != component_names | {
        "total_paise", "schedule_id"
    }:
        raise ValueError("execution quality charges are invalid")
    if charges["schedule_id"] != "NSE_CASH_DELIVERY_2026-03-01":
        raise ValueError("execution quality charge schedule is invalid")
    if any(type(charges[name]) is not int or charges[name] < 0 for name in component_names):
        raise ValueError("execution quality charge components are invalid")
    if charges["total_paise"] != sum(charges[name] for name in component_names):
        raise ValueError("execution quality charge total is invalid")
    fill_price = quality["fill_price_paise"]
    reference = quality["reference_price_paise"]
    filled = receipt.cumulative_fill_quantity
    if filled:
        if type(reference) is not int or reference <= 0:
            raise ValueError("execution quality reference price is invalid")
        direction = 1 if quality["side"] == "BUY" else -1
        expected_slippage = direction * (fill_price - reference) * filled
        gross = fill_price * filled
        expected_cash_flow = (
            -(gross + charges["total_paise"])
            if quality["side"] == "BUY"
            else gross - charges["total_paise"]
        )
    else:
        expected_slippage = 0
        expected_cash_flow = 0
    if quality["slippage_paise"] != expected_slippage:
        raise ValueError("execution quality slippage is invalid")
    if quality["net_cash_flow_paise"] != expected_cash_flow:
        raise ValueError("execution quality cash flow is invalid")


def _command_digest(command_id: str) -> str:
    digest = _optional_command_digest(command_id)
    if digest is None:
        raise ValueError("command_id must be a command content address")
    return digest


def _optional_command_digest(command_id: str) -> str | None:
    digest = command_id.removeprefix("command:")
    if (
        not command_id.startswith("command:")
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        return None
    return digest
