"""A deliberately paper-only broker boundary.

There is no live adapter in this package.  Any future broker implementation
must provide durable client-command idempotency before it can satisfy this
protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sensei.portfolio_risk.models import require_positive_integer

from .commands import BrokerCommand, EntryCommand


@dataclass(frozen=True)
class GatewayReceipt:
    command_id: str
    accepted: bool
    broker_reference: str
    cumulative_fill_quantity: int = 0
    average_fill_price_paise: int | None = None

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

    def to_payload(self) -> dict[str, object]:
        return {
            "command_id": self.command_id,
            "accepted": self.accepted,
            "broker_reference": self.broker_reference,
            "cumulative_fill_quantity": self.cumulative_fill_quantity,
            "average_fill_price_paise": self.average_fill_price_paise,
        }


class PaperGateway(Protocol):
    def execute(self, command: BrokerCommand) -> GatewayReceipt:
        """Execute once by command_id, returning the original receipt on retry."""


class RecordingPaperGateway:
    """Deterministic in-memory paper gateway used by tests and replay harnesses."""

    def __init__(self) -> None:
        self._commands: list[BrokerCommand] = []
        self._receipts: dict[str, GatewayReceipt] = {}
        self._queued_entry_fills: list[tuple[int, int]] = []

    @property
    def commands(self) -> tuple[BrokerCommand, ...]:
        return tuple(self._commands)

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
        existing = self._receipts.get(command.command_id)
        if existing is not None:
            return existing
        fill_quantity = 0
        fill_price: int | None = None
        if isinstance(command, EntryCommand) and self._queued_entry_fills:
            fill_quantity, fill_price = self._queued_entry_fills.pop(0)
            if fill_quantity > command.quantity:
                raise ValueError("queued fill exceeds entry command quantity")
        receipt = GatewayReceipt(
            command_id=command.command_id,
            accepted=True,
            broker_reference=f"paper:{len(self._commands) + 1}",
            cumulative_fill_quantity=fill_quantity,
            average_fill_price_paise=fill_price if fill_quantity else None,
        )
        self._commands.append(command)
        self._receipts[command.command_id] = receipt
        return receipt
