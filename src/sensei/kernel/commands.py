"""Typed broker commands for the paper-only kernel boundary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping, TypeAlias

from sensei.portfolio_risk.models import (
    require_positive_integer,
)


class CommandKind(StrEnum):
    ENTRY = "ENTRY"
    PROTECTION = "PROTECTION"
    CANCEL_ENTRY = "CANCEL_ENTRY"


def _command_id(payload: dict[str, object]) -> str:
    material = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return f"command:{hashlib.sha256(material.encode('utf-8')).hexdigest()}"


def _validate_identity(intent_id: str, instrument_id: str) -> None:
    if not intent_id.startswith("intent:") or not intent_id.removeprefix(
        "intent:"
    ):
        raise ValueError("intent_id must be a content address")
    if not instrument_id.strip():
        raise ValueError("instrument_id must not be blank")


@dataclass(frozen=True)
class EntryCommand:
    intent_id: str
    instrument_id: str
    quantity: int
    limit_price_paise: int
    kind: CommandKind = field(default=CommandKind.ENTRY, init=False)
    command_id: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_identity(self.intent_id, self.instrument_id)
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise TypeError("quantity must be an integer")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        require_positive_integer(self.limit_price_paise, "limit_price_paise")
        object.__setattr__(
            self, "command_id", _command_id(self.to_payload(include_id=False))
        )

    def to_payload(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": self.kind.value,
            "intent_id": self.intent_id,
            "instrument_id": self.instrument_id,
            "quantity": self.quantity,
            "limit_price_paise": self.limit_price_paise,
        }
        if include_id:
            payload["command_id"] = self.command_id
        return payload


@dataclass(frozen=True)
class ProtectionCommand:
    intent_id: str
    instrument_id: str
    quantity: int
    stop_price_paise: int
    target_price_paise: int
    kind: CommandKind = field(default=CommandKind.PROTECTION, init=False)
    command_id: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_identity(self.intent_id, self.instrument_id)
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise TypeError("quantity must be an integer")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        require_positive_integer(self.stop_price_paise, "stop_price_paise")
        require_positive_integer(self.target_price_paise, "target_price_paise")
        if self.stop_price_paise >= self.target_price_paise:
            raise ValueError("protective stop must be below target")
        object.__setattr__(
            self, "command_id", _command_id(self.to_payload(include_id=False))
        )

    def to_payload(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": self.kind.value,
            "intent_id": self.intent_id,
            "instrument_id": self.instrument_id,
            "quantity": self.quantity,
            "stop_price_paise": self.stop_price_paise,
            "target_price_paise": self.target_price_paise,
        }
        if include_id:
            payload["command_id"] = self.command_id
        return payload


@dataclass(frozen=True)
class CancelEntryCommand:
    intent_id: str
    instrument_id: str
    entry_command_id: str
    remaining_quantity: int
    kind: CommandKind = field(default=CommandKind.CANCEL_ENTRY, init=False)
    command_id: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_identity(self.intent_id, self.instrument_id)
        if not self.entry_command_id.startswith("command:"):
            raise ValueError("entry_command_id must be a command content address")
        if isinstance(self.remaining_quantity, bool) or not isinstance(
            self.remaining_quantity, int
        ):
            raise TypeError("remaining_quantity must be an integer")
        if self.remaining_quantity <= 0:
            raise ValueError("remaining_quantity must be positive")
        object.__setattr__(
            self, "command_id", _command_id(self.to_payload(include_id=False))
        )

    def to_payload(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": self.kind.value,
            "intent_id": self.intent_id,
            "instrument_id": self.instrument_id,
            "entry_command_id": self.entry_command_id,
            "remaining_quantity": self.remaining_quantity,
        }
        if include_id:
            payload["command_id"] = self.command_id
        return payload


BrokerCommand: TypeAlias = EntryCommand | ProtectionCommand | CancelEntryCommand


def command_from_payload(payload: Mapping[str, object]) -> BrokerCommand:
    kind = CommandKind(str(payload["kind"]))
    if kind is CommandKind.ENTRY:
        command: BrokerCommand = EntryCommand(
            intent_id=str(payload["intent_id"]),
            instrument_id=str(payload["instrument_id"]),
            quantity=int(payload["quantity"]),
            limit_price_paise=int(payload["limit_price_paise"]),
        )
    elif kind is CommandKind.PROTECTION:
        command = ProtectionCommand(
            intent_id=str(payload["intent_id"]),
            instrument_id=str(payload["instrument_id"]),
            quantity=int(payload["quantity"]),
            stop_price_paise=int(payload["stop_price_paise"]),
            target_price_paise=int(payload["target_price_paise"]),
        )
    else:
        command = CancelEntryCommand(
            intent_id=str(payload["intent_id"]),
            instrument_id=str(payload["instrument_id"]),
            entry_command_id=str(payload["entry_command_id"]),
            remaining_quantity=int(payload["remaining_quantity"]),
        )
    supplied_id = payload.get("command_id")
    if supplied_id is not None and supplied_id != command.command_id:
        raise ValueError("command payload does not match its content address")
    return command
