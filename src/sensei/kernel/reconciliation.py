"""Broker truth contracts and reconciliation outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sensei.portfolio_risk.models import require_positive_integer, require_timestamp

from .commands import CommandKind


@dataclass(frozen=True)
class BrokerPosition:
    instrument_id: str
    quantity: int

    def __post_init__(self) -> None:
        if not self.instrument_id.strip():
            raise ValueError("instrument_id must not be blank")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise TypeError("broker position quantity must be an integer")
        if self.quantity <= 0:
            raise ValueError("broker position quantity must be positive")


@dataclass(frozen=True)
class BrokerProtection:
    instrument_id: str
    quantity: int
    stop_price_paise: int
    target_price_paise: int
    client_command_id: str | None = None

    def __post_init__(self) -> None:
        if not self.instrument_id.strip():
            raise ValueError("instrument_id must not be blank")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise TypeError("broker protection quantity must be an integer")
        if self.quantity <= 0:
            raise ValueError("broker protection quantity must be positive")
        require_positive_integer(self.stop_price_paise, "stop_price_paise")
        require_positive_integer(self.target_price_paise, "target_price_paise")
        if self.stop_price_paise >= self.target_price_paise:
            raise ValueError("protective stop must be below target")
        if self.client_command_id is not None and not self.client_command_id.startswith(
            "command:"
        ):
            raise ValueError("client_command_id must be a command content address")


@dataclass(frozen=True)
class BrokerWorkingOrder:
    broker_order_id: str
    client_command_id: str | None
    instrument_id: str
    kind: str
    quantity: int
    stop_price_paise: int | None = None
    target_price_paise: int | None = None

    def __post_init__(self) -> None:
        if not self.broker_order_id.strip():
            raise ValueError("broker_order_id must not be blank")
        if self.client_command_id is not None and not self.client_command_id.startswith(
            "command:"
        ):
            raise ValueError("client_command_id must be a command content address")
        if not self.instrument_id.strip():
            raise ValueError("instrument_id must not be blank")
        object.__setattr__(self, "kind", CommandKind(self.kind).value)
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise TypeError("working-order quantity must be an integer")
        if self.quantity <= 0:
            raise ValueError("working-order quantity must be positive")
        if self.kind == CommandKind.PROTECTION.value:
            require_positive_integer(self.stop_price_paise, "stop_price_paise")
            require_positive_integer(self.target_price_paise, "target_price_paise")
            if self.stop_price_paise >= self.target_price_paise:  # type: ignore[operator]
                raise ValueError("protective stop must be below target")
        elif self.stop_price_paise is not None or self.target_price_paise is not None:
            raise ValueError("only protection orders may carry stop and target levels")


@dataclass(frozen=True)
class BrokerSnapshot:
    snapshot_id: str
    captured_at: datetime
    positions: tuple[BrokerPosition, ...]
    protections: tuple[BrokerProtection, ...]
    working_orders: tuple[BrokerWorkingOrder, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "positions", tuple(self.positions))
        object.__setattr__(self, "protections", tuple(self.protections))
        object.__setattr__(self, "working_orders", tuple(self.working_orders))
        if not self.snapshot_id.strip():
            raise ValueError("snapshot_id must not be blank")
        require_timestamp(self.captured_at, "captured_at")
        if len({item.instrument_id for item in self.positions}) != len(self.positions):
            raise ValueError("broker positions must be unique by instrument")
        if len({item.instrument_id for item in self.protections}) != len(
            self.protections
        ):
            raise ValueError("broker protections must be unique by instrument")
        if len({item.broker_order_id for item in self.working_orders}) != len(
            self.working_orders
        ):
            raise ValueError("working broker orders must have unique broker IDs")


@dataclass(frozen=True)
class ReconciliationReport:
    snapshot_id: str
    clean: bool
    issues: tuple[str, ...]
