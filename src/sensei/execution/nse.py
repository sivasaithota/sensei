"""Deterministic, conservative NSE cash-delivery execution semantics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class NseMarketObservation:
    instrument_id: str
    observed_at: datetime
    reference_price_paise: int
    best_bid_paise: int
    best_ask_paise: int
    traded_volume: int
    lower_circuit_paise: int
    upper_circuit_paise: int
    evidence_source: str = "TEST_FIXTURE"
    spread_is_estimated: bool = False
    circuit_is_estimated: bool = False

    def __post_init__(self) -> None:
        if not self.instrument_id.startswith("NSE:"):
            raise ValueError("instrument must use an NSE identifier")
        _aware(self.observed_at)
        values = (
            self.reference_price_paise, self.best_bid_paise,
            self.best_ask_paise, self.lower_circuit_paise,
            self.upper_circuit_paise,
        )
        if any(type(value) is not int or value <= 0 for value in values):
            raise ValueError("market prices must be positive integer paise")
        if self.best_bid_paise > self.best_ask_paise:
            raise ValueError("best bid cannot exceed best ask")
        if not (
            self.lower_circuit_paise <= self.best_bid_paise
            <= self.best_ask_paise <= self.upper_circuit_paise
        ):
            raise ValueError("market prices must lie within circuit limits")
        if type(self.traded_volume) is not int or self.traded_volume < 0:
            raise ValueError("traded volume cannot be negative")
        if not self.evidence_source.strip():
            raise ValueError("market evidence source cannot be blank")


@dataclass(frozen=True)
class ChargeBreakdown:
    stt_paise: int
    exchange_paise: int
    sebi_paise: int
    stamp_duty_paise: int
    gst_paise: int
    ipft_paise: int = 0
    schedule_id: str = "NSE_CASH_DELIVERY_2026-03-01"

    @property
    def total_paise(self) -> int:
        return sum(self.to_payload().values())

    def to_payload(self) -> dict[str, int]:
        return {
            "stt_paise": self.stt_paise,
            "exchange_paise": self.exchange_paise,
            "sebi_paise": self.sebi_paise,
            "stamp_duty_paise": self.stamp_duty_paise,
            "gst_paise": self.gst_paise,
            "ipft_paise": self.ipft_paise,
        }


@dataclass(frozen=True)
class IndianDeliveryChargeSchedule:
    """Conservative NSE delivery fees effective 2026-03-01.

    Exchange/IPFT: NSE circular FA73061. Other levies are configurable so a
    future schedule can be pre-registered without rewriting fill history.
    """

    stt_ppm: int = 1_000
    exchange_ppm: int = 31
    sebi_ppm: int = 1
    buy_stamp_duty_ppm: int = 150
    gst_ppm: int = 180_000

    def calculate(self, *, turnover_paise: int, side: str) -> ChargeBreakdown:
        if turnover_paise < 0:
            raise ValueError("turnover cannot be negative")
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        stt = _charge(turnover_paise, self.stt_ppm)
        exchange = _charge(turnover_paise, self.exchange_ppm)
        sebi = _charge(turnover_paise, self.sebi_ppm)
        stamp = (
            _charge(turnover_paise, self.buy_stamp_duty_ppm)
            if side == "BUY" else 0
        )
        gst = _charge(exchange + sebi, self.gst_ppm)
        ipft = math.ceil(turnover_paise / 1_000_000_000) if turnover_paise else 0
        return ChargeBreakdown(stt, exchange, sebi, stamp, gst, ipft)


@dataclass(frozen=True)
class SimulatedFill:
    filled_quantity: int
    requested_quantity: int
    fill_price_paise: int | None
    reference_price_paise: int | None
    reason_code: str
    charges: ChargeBreakdown
    side: str
    market_evidence: dict[str, object] | None = None

    @property
    def unfilled_quantity(self) -> int:
        return self.requested_quantity - self.filled_quantity

    @property
    def slippage_paise(self) -> int:
        if self.fill_price_paise is None or self.reference_price_paise is None:
            return 0
        direction = 1 if self.side == "BUY" else -1
        return direction * (
            self.fill_price_paise - self.reference_price_paise
        ) * self.filled_quantity

    @property
    def net_cash_flow_paise(self) -> int:
        if self.fill_price_paise is None:
            return 0
        gross = self.fill_price_paise * self.filled_quantity
        return (
            -(gross + self.charges.total_paise)
            if self.side == "BUY"
            else gross - self.charges.total_paise
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "filled_quantity": self.filled_quantity,
            "requested_quantity": self.requested_quantity,
            "unfilled_quantity": self.unfilled_quantity,
            "fill_price_paise": self.fill_price_paise,
            "reference_price_paise": self.reference_price_paise,
            "slippage_paise": self.slippage_paise,
            "reason_code": self.reason_code,
            "side": self.side,
            "charges": {
                **self.charges.to_payload(),
                "total_paise": self.charges.total_paise,
                "schedule_id": self.charges.schedule_id,
            },
            "net_cash_flow_paise": self.net_cash_flow_paise,
            "market_evidence": self.market_evidence,
        }


class NseExecutionModel:
    def __init__(
        self, *, max_volume_participation_bps: int = 500,
        base_impact_bps: int = 5, tick_size_paise: int = 5,
        maximum_observation_age: timedelta = timedelta(seconds=30),
        charges: IndianDeliveryChargeSchedule | None = None,
    ) -> None:
        if not 1 <= max_volume_participation_bps <= 10_000:
            raise ValueError("volume participation must be within 1..10000 bps")
        if base_impact_bps < 0 or tick_size_paise <= 0:
            raise ValueError("impact and tick size are invalid")
        if maximum_observation_age <= timedelta(0):
            raise ValueError("maximum observation age must be positive")
        self._participation_bps = max_volume_participation_bps
        self._impact_bps = base_impact_bps
        self._tick = tick_size_paise
        self._maximum_age = maximum_observation_age
        self._charges = charges or IndianDeliveryChargeSchedule()

    def simulate_entry(
        self, *, quantity: int, limit_price_paise: int,
        observation: NseMarketObservation, now: datetime,
    ) -> SimulatedFill:
        _positive_integer(quantity, "quantity")
        _positive_integer(limit_price_paise, "limit_price_paise")
        _aware(now)
        if observation.observed_at > now or now - observation.observed_at > self._maximum_age:
            return self._empty(quantity, "STALE_MARKET_OBSERVATION", "BUY")
        if observation.best_ask_paise > limit_price_paise:
            return self._empty(quantity, "LIMIT_NOT_MARKETABLE", "BUY")
        available = observation.traded_volume * self._participation_bps // 10_000
        filled = min(quantity, available)
        if filled <= 0:
            return self._empty(quantity, "INSUFFICIENT_LIQUIDITY", "BUY")
        utilization_bps = filled * 10_000 // max(1, observation.traded_volume)
        impact_bps = self._impact_bps + utilization_bps // 100
        impacted = observation.best_ask_paise + math.ceil(
            observation.best_ask_paise * impact_bps / 10_000
        )
        effective_limit = _round_down(limit_price_paise, self._tick)
        price = min(
            _round_down(observation.upper_circuit_paise, self._tick),
            _round_up(impacted, self._tick),
        )
        if price > effective_limit:
            return self._empty(quantity, "ADVERSE_PRICE_EXCEEDS_LIMIT", "BUY")
        charges = self._charges.calculate(
            turnover_paise=filled * price, side="BUY"
        )
        reason = "FILLED" if filled == quantity else "PARTIAL_LIQUIDITY_FILL"
        return SimulatedFill(
            filled, quantity, price, observation.reference_price_paise,
            reason, charges, "BUY",
            {
                "source": observation.evidence_source,
                "observed_at": observation.observed_at.isoformat(),
                "session_volume": observation.traded_volume,
                "spread_is_estimated": observation.spread_is_estimated,
                "circuit_is_estimated": observation.circuit_is_estimated,
            },
        )

    def simulate_stop_exit(
        self, *, quantity: int, stop_price_paise: int,
        session_open_paise: int, session_low_paise: int,
        available_volume: int, lower_circuit_paise: int = 1,
    ) -> SimulatedFill:
        _positive_integer(quantity, "quantity")
        _positive_integer(stop_price_paise, "stop_price_paise")
        _positive_integer(session_open_paise, "session_open_paise")
        _positive_integer(session_low_paise, "session_low_paise")
        _positive_integer(lower_circuit_paise, "lower_circuit_paise")
        if type(available_volume) is not int or available_volume < 0:
            raise ValueError("available_volume must be a non-negative integer")
        triggered = session_open_paise <= stop_price_paise or session_low_paise <= stop_price_paise
        if not triggered:
            return self._empty(quantity, "STOP_NOT_TRIGGERED", "SELL")
        available = available_volume * self._participation_bps // 10_000
        filled = min(quantity, available)
        if filled <= 0:
            return self._empty(quantity, "INSUFFICIENT_LIQUIDITY", "SELL")
        reference = session_open_paise if session_open_paise <= stop_price_paise else stop_price_paise
        impacted = reference - math.ceil(reference * self._impact_bps / 10_000)
        price = max(lower_circuit_paise, _round_down(impacted, self._tick))
        charges = self._charges.calculate(
            turnover_paise=filled * price, side="SELL"
        )
        reason = "STOP_GAP" if session_open_paise <= stop_price_paise else "STOP_TRIGGERED"
        return SimulatedFill(filled, quantity, price, reference, reason, charges, "SELL")

    def simulate_exit(
        self, *, quantity: int, reference_price_paise: int,
        available_volume: int, reason_code: str,
        lower_circuit_paise: int = 1,
    ) -> SimulatedFill:
        """Simulate a marketable long-position exit at an adverse sell price."""
        _positive_integer(quantity, "quantity")
        _positive_integer(reference_price_paise, "reference_price_paise")
        _positive_integer(lower_circuit_paise, "lower_circuit_paise")
        if type(available_volume) is not int or available_volume < 0:
            raise ValueError("available_volume must be a non-negative integer")
        available = available_volume * self._participation_bps // 10_000
        filled = min(quantity, available)
        if filled <= 0:
            return self._empty(quantity, "INSUFFICIENT_LIQUIDITY", "SELL")
        impacted = reference_price_paise - math.ceil(
            reference_price_paise * self._impact_bps / 10_000
        )
        price = max(lower_circuit_paise, _round_down(impacted, self._tick))
        charges = self._charges.calculate(
            turnover_paise=filled * price, side="SELL"
        )
        reason = reason_code if filled == quantity else f"PARTIAL_{reason_code}"
        return SimulatedFill(
            filled, quantity, price, reference_price_paise,
            reason, charges, "SELL",
        )

    def _empty(self, quantity: int, reason: str, side: str) -> SimulatedFill:
        return SimulatedFill(
            0, quantity, None, None, reason,
            ChargeBreakdown(0, 0, 0, 0, 0), side,
        )


def _charge(amount: int, ppm: int) -> int:
    return math.ceil(amount * ppm / 1_000_000) if amount and ppm else 0


def _round_up(value: int, tick: int) -> int:
    return math.ceil(value / tick) * tick


def _round_down(value: int, tick: int) -> int:
    return value // tick * tick


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")


def _positive_integer(value: int, field: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field} must be a positive integer")


__all__ = [
    "ChargeBreakdown", "IndianDeliveryChargeSchedule", "NseExecutionModel",
    "NseMarketObservation", "SimulatedFill",
]
