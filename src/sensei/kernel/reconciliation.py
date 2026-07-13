"""Broker truth contracts and reconciliation outcomes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

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
    captured_at: datetime
    positions: tuple[BrokerPosition, ...]
    protections: tuple[BrokerProtection, ...]
    working_orders: tuple[BrokerWorkingOrder, ...] = ()
    snapshot_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "positions",
            tuple(sorted(self.positions, key=lambda item: item.instrument_id)),
        )
        object.__setattr__(
            self,
            "protections",
            tuple(sorted(self.protections, key=lambda item: item.instrument_id)),
        )
        object.__setattr__(
            self,
            "working_orders",
            tuple(sorted(self.working_orders, key=lambda item: item.broker_order_id)),
        )
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
        canonical = json.dumps(
            self.to_payload(include_id=False),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        object.__setattr__(
            self,
            "snapshot_id",
            "broker-snapshot:"
            + hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )

    def to_payload(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "captured_at": self.captured_at.astimezone(timezone.utc).isoformat(),
            "positions": [
                {
                    "instrument_id": item.instrument_id,
                    "quantity": item.quantity,
                }
                for item in self.positions
            ],
            "protections": [
                {
                    "instrument_id": item.instrument_id,
                    "quantity": item.quantity,
                    "stop_price_paise": item.stop_price_paise,
                    "target_price_paise": item.target_price_paise,
                    "client_command_id": item.client_command_id,
                }
                for item in self.protections
            ],
            "working_orders": [
                {
                    "broker_order_id": item.broker_order_id,
                    "client_command_id": item.client_command_id,
                    "instrument_id": item.instrument_id,
                    "kind": item.kind,
                    "quantity": item.quantity,
                    "stop_price_paise": item.stop_price_paise,
                    "target_price_paise": item.target_price_paise,
                }
                for item in self.working_orders
            ],
        }
        if include_id:
            payload["snapshot_id"] = self.snapshot_id
        return payload


@dataclass(frozen=True)
class ReconciliationReport:
    snapshot_id: str
    clean: bool
    issues: tuple[str, ...]
    observed_at: datetime
    broker_snapshot_event_id: str
    kernel_event_id: str
    evidence_event_id: str
