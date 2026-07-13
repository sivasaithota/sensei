"""Hard risk rails (PRD §6).

Pure code, no LLM judgment. Every trade proposal passes through
`RiskRails.check()` before it may proceed to the rest of the approval
chain; a returned violation is an unconditional veto.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml


@dataclass(frozen=True)
class RiskConfig:
    capital: float
    max_risk_per_trade_pct: float
    max_position_pct: float
    max_open_positions: int
    daily_loss_halt_pct: float
    weekly_loss_halt_pct: float
    max_drawdown_pct: float
    stop_loss_mandatory: bool
    min_avg_daily_turnover_inr: float
    leverage: bool
    banned_surveillance_stages: list[int]
    allowed_products: list[str]

    @classmethod
    def load(cls, path: Path | str) -> "RiskConfig":
        raw = yaml.safe_load(Path(path).read_text())
        return cls(**raw)


@dataclass(frozen=True)
class TradeProposal:
    symbol: str
    side: str                 # "BUY" | "SELL"
    entry_price: float
    stop_loss: float | None
    quantity: int
    product: str = "CNC"
    avg_daily_turnover_inr: float = 0.0
    surveillance_stage: int | None = None  # None is unverified and fails closed

    @property
    def notional(self) -> float:
        return self.entry_price * self.quantity

    @property
    def risk_amount(self) -> float | None:
        if self.stop_loss is None:
            return None
        return abs(self.entry_price - self.stop_loss) * self.quantity


@dataclass
class PortfolioState:
    cash: float
    open_positions: int
    day_pnl: float = 0.0
    week_pnl: float = 0.0
    peak_equity: float = 0.0
    equity: float = 0.0
    halted: bool = False       # owner kill-switch or breaker already tripped


@dataclass
class RailCheck:
    ok: bool
    violations: list[str] = field(default_factory=list)


class RiskRails:
    def __init__(self, config: RiskConfig):
        self.cfg = config

    # ---- circuit breakers (checked continuously, not per-trade) ----

    def breaker_status(self, state: PortfolioState) -> list[str]:
        """Return tripped breakers. Any entry means: halt, cancel entries."""
        tripped: list[str] = []
        cap = self.cfg.capital
        if state.halted:
            tripped.append("halted: owner kill-switch or prior breaker active")
        if state.day_pnl <= -cap * self.cfg.daily_loss_halt_pct / 100:
            tripped.append(
                f"daily loss kill-switch: day P&L {state.day_pnl:.0f} <= "
                f"-{self.cfg.daily_loss_halt_pct}% of capital"
            )
        if state.week_pnl <= -cap * self.cfg.weekly_loss_halt_pct / 100:
            tripped.append(
                f"weekly circuit breaker: week P&L {state.week_pnl:.0f} <= "
                f"-{self.cfg.weekly_loss_halt_pct}% of capital"
            )
        if state.peak_equity > 0:
            dd = (state.peak_equity - state.equity) / state.peak_equity * 100
            if dd >= self.cfg.max_drawdown_pct:
                tripped.append(
                    f"total drawdown floor: {dd:.1f}% >= {self.cfg.max_drawdown_pct}% from peak"
                )
        return tripped

    # ---- per-trade rails ----

    def check(self, p: TradeProposal, state: PortfolioState) -> RailCheck:
        v: list[str] = []
        cfg = self.cfg

        if not isinstance(p.side, str) or p.side not in {"BUY", "SELL"}:
            v.append("invalid side: expected BUY or SELL")
        if (
            isinstance(p.quantity, bool)
            or not isinstance(p.quantity, int)
            or p.quantity <= 0
        ):
            v.append("invalid quantity: expected a positive integer")
        if not _positive_finite(p.entry_price):
            v.append("invalid entry price: expected a positive finite value")
        if p.stop_loss is not None and not _positive_finite(p.stop_loss):
            v.append("invalid stop price: expected a positive finite value")
        if not _nonnegative_finite(p.avg_daily_turnover_inr):
            v.append("invalid turnover: expected a non-negative finite value")
        if p.surveillance_stage is None:
            v.append("surveillance status unknown: verified GSM/ASM stage required")
        elif (
            isinstance(p.surveillance_stage, bool)
            or not isinstance(p.surveillance_stage, int)
            or p.surveillance_stage < 0
        ):
            v.append("invalid surveillance stage")
        if not _nonnegative_finite(state.cash):
            v.append("invalid portfolio cash")
        if (
            isinstance(state.open_positions, bool)
            or not isinstance(state.open_positions, int)
            or state.open_positions < 0
        ):
            v.append("invalid open-position count")
        for label, value in (
            ("day P&L", state.day_pnl),
            ("week P&L", state.week_pnl),
            ("peak equity", state.peak_equity),
            ("equity", state.equity),
        ):
            if not _nonnegative_finite(value) and label not in {"day P&L", "week P&L"}:
                v.append(f"invalid portfolio {label}")
            elif label in {"day P&L", "week P&L"} and not _finite(value):
                v.append(f"invalid portfolio {label}")
        if v:
            return RailCheck(ok=False, violations=v)

        v.extend(self.breaker_status(state))

        if p.product not in cfg.allowed_products:
            v.append(f"product {p.product} not allowed (v1 allows {cfg.allowed_products})")

        if cfg.stop_loss_mandatory and p.stop_loss is None:
            v.append("mandatory stop-loss missing")
        elif p.stop_loss is not None:
            if p.side == "BUY" and p.stop_loss >= p.entry_price:
                v.append("stop-loss must be below entry for a BUY")
            if p.side == "SELL" and p.stop_loss <= p.entry_price:
                v.append("stop-loss must be above entry for a SELL")

        risk = p.risk_amount
        max_risk = cfg.capital * cfg.max_risk_per_trade_pct / 100
        if risk is not None and risk > max_risk:
            v.append(f"risk per trade {risk:.0f} > max {max_risk:.0f}")

        max_pos = cfg.capital * cfg.max_position_pct / 100
        if p.notional > max_pos:
            v.append(f"position size {p.notional:.0f} > max {max_pos:.0f}")

        if state.open_positions >= cfg.max_open_positions:
            v.append(f"max concurrent positions ({cfg.max_open_positions}) reached")

        if p.notional > state.cash and not cfg.leverage:
            v.append(f"insufficient cash: need {p.notional:.0f}, have {state.cash:.0f}")

        if p.avg_daily_turnover_inr < cfg.min_avg_daily_turnover_inr:
            v.append(
                f"liquidity below floor: turnover {p.avg_daily_turnover_inr:.0f} < "
                f"{cfg.min_avg_daily_turnover_inr:.0f}"
            )

        if p.surveillance_stage in cfg.banned_surveillance_stages:
            v.append(f"GSM/ASM surveillance stage {p.surveillance_stage} is banned")

        return RailCheck(ok=not v, violations=v)


def _finite(value: object) -> bool:
    if isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _positive_finite(value: object) -> bool:
    return _finite(value) and float(value) > 0


def _nonnegative_finite(value: object) -> bool:
    return _finite(value) and float(value) >= 0
