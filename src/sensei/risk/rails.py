"""Hard risk rails (PRD §6).

Pure code, no LLM judgment. Every trade proposal passes through
`RiskRails.check()` before it may proceed to the rest of the approval
chain; a returned violation is an unconditional veto.
"""

from __future__ import annotations

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
    surveillance_stage: int = 0   # GSM/ASM stage, 0 = none

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
