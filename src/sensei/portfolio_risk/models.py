"""Immutable contracts for portfolio-level admission control.

Money crosses this boundary as integer paise.  Binary floats are deliberately
not accepted: an execution authority should never guess how to round risk.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum


def require_timestamp(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def require_positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must use integer paise")
    if value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def require_nonnegative_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must use integer paise")
    if value < 0:
        raise ValueError(f"{label} must not be negative")
    return value


def require_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must use integer paise")
    return value


@dataclass(frozen=True)
class TradeIntent:
    """A content-addressed, delivery-only request to open a long position."""

    strategy_plan_id: str
    decision_trace_id: str
    market_snapshot_id: str
    account_snapshot_id: str
    instrument_id: str
    quantity: int
    limit_price_paise: int
    stop_price_paise: int
    target_price_paise: int
    created_at: datetime
    side: str = field(default="BUY", init=False)
    product: str = field(default="DELIVERY", init=False)
    intent_id: str = field(init=False)

    def __post_init__(self) -> None:
        for label, value in (
            ("strategy_plan_id", self.strategy_plan_id),
            ("decision_trace_id", self.decision_trace_id),
            ("market_snapshot_id", self.market_snapshot_id),
            ("account_snapshot_id", self.account_snapshot_id),
            ("instrument_id", self.instrument_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label} must not be blank")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise TypeError("quantity must be a positive integer")
        if self.quantity <= 0:
            raise ValueError("quantity must be a positive integer")
        require_positive_integer(self.limit_price_paise, "limit_price_paise")
        require_positive_integer(self.stop_price_paise, "stop_price_paise")
        require_positive_integer(self.target_price_paise, "target_price_paise")
        if self.stop_price_paise >= self.limit_price_paise:
            raise ValueError("stop price must be below entry for a long intent")
        if self.target_price_paise <= self.limit_price_paise:
            raise ValueError("target price must be above entry for a long intent")
        require_timestamp(self.created_at, "created_at")
        material = json.dumps(
            self.to_payload(include_id=False),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        object.__setattr__(self, "intent_id", f"intent:{digest}")

    @property
    def notional_paise(self) -> int:
        return self.quantity * self.limit_price_paise

    @property
    def risk_paise(self) -> int:
        return self.quantity * (self.limit_price_paise - self.stop_price_paise)

    def to_payload(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "strategy_plan_id": self.strategy_plan_id,
            "decision_trace_id": self.decision_trace_id,
            "market_snapshot_id": self.market_snapshot_id,
            "account_snapshot_id": self.account_snapshot_id,
            "instrument_id": self.instrument_id,
            "quantity": self.quantity,
            "limit_price_paise": self.limit_price_paise,
            "stop_price_paise": self.stop_price_paise,
            "target_price_paise": self.target_price_paise,
            "created_at": self.created_at.astimezone(timezone.utc).isoformat(),
            "side": self.side,
            "product": self.product,
        }
        if include_id:
            payload["intent_id"] = self.intent_id
        return payload

    @classmethod
    def from_payload(cls, payload: object) -> "TradeIntent":
        if not isinstance(payload, dict) and not hasattr(payload, "__getitem__"):
            raise TypeError("intent payload must be a mapping")
        intent = cls(
            strategy_plan_id=str(payload["strategy_plan_id"]),  # type: ignore[index]
            decision_trace_id=str(payload["decision_trace_id"]),  # type: ignore[index]
            market_snapshot_id=str(payload["market_snapshot_id"]),  # type: ignore[index]
            account_snapshot_id=str(payload["account_snapshot_id"]),  # type: ignore[index]
            instrument_id=str(payload["instrument_id"]),  # type: ignore[index]
            quantity=int(payload["quantity"]),  # type: ignore[index]
            limit_price_paise=int(payload["limit_price_paise"]),  # type: ignore[index]
            stop_price_paise=int(payload["stop_price_paise"]),  # type: ignore[index]
            target_price_paise=int(payload["target_price_paise"]),  # type: ignore[index]
            created_at=datetime.fromisoformat(str(payload["created_at"])),  # type: ignore[index]
        )
        supplied_id = payload.get("intent_id")  # type: ignore[union-attr]
        if supplied_id is not None and supplied_id != intent.intent_id:
            raise ValueError("intent payload does not match its content address")
        if payload.get("side", "BUY") != "BUY":  # type: ignore[union-attr]
            raise ValueError("only long BUY intents are supported")
        if payload.get("product", "DELIVERY") != "DELIVERY":  # type: ignore[union-attr]
            raise ValueError("only DELIVERY intents are supported")
        return intent


@dataclass(frozen=True)
class AccountPosition:
    instrument_id: str
    quantity: int
    notional_paise: int
    risk_to_stop_paise: int

    def __post_init__(self) -> None:
        if not self.instrument_id.strip():
            raise ValueError("instrument_id must not be blank")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise TypeError("position quantity must be an integer")
        if self.quantity <= 0:
            raise ValueError("position quantity must be positive")
        require_positive_integer(self.notional_paise, "position notional_paise")
        require_nonnegative_integer(
            self.risk_to_stop_paise, "position risk_to_stop_paise"
        )


@dataclass(frozen=True)
class AccountSnapshot:
    available_cash_paise: int
    marked_equity_paise: int
    high_water_mark_paise: int
    day_pnl_paise: int
    week_pnl_paise: int
    positions: tuple[AccountPosition, ...]
    included_reservation_ids: tuple[str, ...]
    reconciled: bool
    captured_at: datetime
    snapshot_id: str = field(init=False)

    def __post_init__(self) -> None:
        positions = tuple(self.positions)
        if not all(isinstance(position, AccountPosition) for position in positions):
            raise TypeError("positions must contain AccountPosition values")
        object.__setattr__(
            self,
            "positions",
            tuple(sorted(positions, key=lambda item: item.instrument_id)),
        )
        reservation_ids = tuple(self.included_reservation_ids)
        if not all(
            isinstance(value, str) and value.startswith("reservation:")
            for value in reservation_ids
        ):
            raise ValueError(
                "included_reservation_ids must be reservation content addresses"
            )
        object.__setattr__(
            self,
            "included_reservation_ids",
            tuple(sorted(reservation_ids)),
        )
        require_nonnegative_integer(
            self.available_cash_paise, "available_cash_paise"
        )
        require_positive_integer(self.marked_equity_paise, "marked_equity_paise")
        require_positive_integer(
            self.high_water_mark_paise, "high_water_mark_paise"
        )
        if self.high_water_mark_paise < self.marked_equity_paise:
            raise ValueError("high_water_mark_paise must cover marked equity")
        require_integer(self.day_pnl_paise, "day_pnl_paise")
        require_integer(self.week_pnl_paise, "week_pnl_paise")
        if not isinstance(self.reconciled, bool):
            raise TypeError("reconciled must be a boolean")
        require_timestamp(self.captured_at, "captured_at")
        if len({position.instrument_id for position in self.positions}) != len(
            self.positions
        ):
            raise ValueError("snapshot positions must be unique by instrument")
        if len(set(self.included_reservation_ids)) != len(
            self.included_reservation_ids
        ):
            raise ValueError("included_reservation_ids must be unique")
        object.__setattr__(self, "snapshot_id", self.derived_snapshot_id())

    def derived_snapshot_id(self) -> str:
        """Recompute the content address without trusting stored identity."""
        material = json.dumps(
            {
                "schema": "account-snapshot-v1",
                "available_cash_paise": self.available_cash_paise,
                "marked_equity_paise": self.marked_equity_paise,
                "high_water_mark_paise": self.high_water_mark_paise,
                "day_pnl_paise": self.day_pnl_paise,
                "week_pnl_paise": self.week_pnl_paise,
                "positions": [
                    {
                        "instrument_id": position.instrument_id,
                        "quantity": position.quantity,
                        "notional_paise": position.notional_paise,
                        "risk_to_stop_paise": position.risk_to_stop_paise,
                    }
                    for position in self.positions
                ],
                "included_reservation_ids": list(
                    self.included_reservation_ids
                ),
                "reconciled": self.reconciled,
                "captured_at": self.captured_at.astimezone(timezone.utc).isoformat(),
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        return f"snapshot:{digest}"

    def has_valid_identity(self) -> bool:
        return self.snapshot_id == self.derived_snapshot_id()

    @property
    def held_notional_paise(self) -> int:
        return sum(position.notional_paise for position in self.positions)

    @property
    def held_risk_paise(self) -> int:
        return sum(position.risk_to_stop_paise for position in self.positions)


@dataclass(frozen=True)
class RiskLimits:
    max_total_notional_paise: int
    max_position_notional_paise: int
    max_risk_per_trade_paise: int
    max_total_risk_paise: int
    max_open_positions: int
    snapshot_max_age: timedelta
    max_daily_loss_paise: int
    max_weekly_loss_paise: int
    max_drawdown_bps: int

    def __post_init__(self) -> None:
        require_positive_integer(
            self.max_total_notional_paise, "max_total_notional_paise"
        )
        require_positive_integer(
            self.max_position_notional_paise, "max_position_notional_paise"
        )
        require_positive_integer(
            self.max_risk_per_trade_paise, "max_risk_per_trade_paise"
        )
        require_positive_integer(
            self.max_total_risk_paise, "max_total_risk_paise"
        )
        require_positive_integer(
            self.max_daily_loss_paise, "max_daily_loss_paise"
        )
        require_positive_integer(
            self.max_weekly_loss_paise, "max_weekly_loss_paise"
        )
        if isinstance(self.max_drawdown_bps, bool) or not isinstance(
            self.max_drawdown_bps, int
        ):
            raise TypeError("max_drawdown_bps must be an integer")
        if not 0 < self.max_drawdown_bps <= 10_000:
            raise ValueError("max_drawdown_bps must be between 1 and 10000")
        if isinstance(self.max_open_positions, bool) or not isinstance(
            self.max_open_positions, int
        ):
            raise TypeError("max_open_positions must be an integer")
        if self.max_open_positions <= 0:
            raise ValueError("max_open_positions must be positive")
        if self.snapshot_max_age <= timedelta(0):
            raise ValueError("snapshot_max_age must be positive")


class ReservationState(StrEnum):
    RESERVED = "RESERVED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    RELEASED = "RELEASED"


@dataclass(frozen=True)
class RiskReservation:
    reservation_id: str
    intent: TradeIntent
    state: ReservationState
    filled_quantity: int
    remaining_quantity: int
    average_fill_price_paise: int | None
    version: int


class RiskRejected(RuntimeError):
    """Portfolio admission was rejected by deterministic risk policy."""
