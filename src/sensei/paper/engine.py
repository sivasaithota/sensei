"""Paper-trading engine (PRD Phase P1) — simulated fills, real discipline.

Positions open from fully-approved theses only. Fills are simulated
against daily bars with the same conservative semantics as the
backtester (stop-first on ambiguous days). All state persists to
data/paper/ so the loop survives restarts.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from sensei.agents.thesis import ApprovalRecord, TradeThesis

PAPER_DIR = Path(__file__).resolve().parents[3] / "data" / "paper"
POSITIONS_FILE = PAPER_DIR / "positions.json"
CLOSED_FILE = PAPER_DIR / "closed_trades.jsonl"


@dataclass
class Position:
    thesis_id: str
    symbol: str
    direction: str
    entry_price: float
    quantity: int
    stop_loss: float
    targets: list[float]
    opened: str                      # ISO date
    max_hold_days: int
    narrative: str

    @property
    def notional(self) -> float:
        return self.entry_price * self.quantity


@dataclass
class ClosedTrade:
    thesis_id: str
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    quantity: int
    opened: str
    closed: str
    exit_reason: str                 # "stop" | "target" | "time" | "invalidation" | "kill"
    pnl: float
    narrative: str
    post_mortem: dict | None = None  # filled by the Coach


class PaperBook:
    """The simulated account: cash, open positions, closed-trade log."""

    def __init__(self, starting_cash: float = 50000):
        PAPER_DIR.mkdir(parents=True, exist_ok=True)
        if POSITIONS_FILE.exists():
            state = json.loads(POSITIONS_FILE.read_text())
            self.cash = state["cash"]
            self.positions = [Position(**p) for p in state["positions"]]
        else:
            self.cash = starting_cash
            self.positions = []

    def _save(self) -> None:
        POSITIONS_FILE.write_text(json.dumps(
            {"cash": self.cash, "positions": [asdict(p) for p in self.positions]},
            indent=2))

    def open_from(self, record: ApprovalRecord, fill_price: float,
                  today: date | None = None) -> Position:
        if not record.approved:
            raise ValueError(f"thesis {record.thesis.id} is not fully approved "
                             f"(vetoed by {record.vetoed_by}) — refusing to open")
        t = record.thesis
        cost = fill_price * t.quantity
        if cost > self.cash:
            raise ValueError(f"insufficient paper cash {self.cash:.0f} for {cost:.0f}")
        pos = Position(thesis_id=t.id, symbol=t.symbol, direction=t.direction.value,
                       entry_price=fill_price, quantity=t.quantity,
                       stop_loss=t.stop_loss, targets=t.targets,
                       opened=(today or date.today()).isoformat(),
                       max_hold_days=t.time_horizon_days, narrative=t.narrative)
        self.cash -= cost
        self.positions.append(pos)
        self._save()
        return pos

    def mark_to_market(self, bars: dict[str, dict], today: date | None = None) -> list[ClosedTrade]:
        """Process one day's bars {symbol: {open,high,low,close}}.
        Applies stop/target/time exits; returns trades closed today."""
        today = today or date.today()
        closed: list[ClosedTrade] = []
        remaining: list[Position] = []
        for pos in self.positions:
            bar = bars.get(pos.symbol)
            if bar is None:
                remaining.append(pos)
                continue
            exit_price, reason = None, None
            held = (today - date.fromisoformat(pos.opened)).days
            if bar["low"] <= pos.stop_loss:          # stop first — conservative
                exit_price, reason = pos.stop_loss, "stop"
            elif pos.targets and bar["high"] >= pos.targets[0]:
                exit_price, reason = pos.targets[0], "target"
            elif held >= pos.max_hold_days:
                exit_price, reason = bar["close"], "time"

            if exit_price is None:
                remaining.append(pos)
                continue
            closed.append(self._close(pos, exit_price, reason, today))
        self.positions = remaining
        self._save()
        return closed

    def close_manual(self, thesis_id: str, exit_price: float, reason: str,
                     today: date | None = None) -> ClosedTrade:
        """Invalidation exit or owner kill-switch."""
        pos = next(p for p in self.positions if p.thesis_id == thesis_id)
        self.positions.remove(pos)
        trade = self._close(pos, exit_price, reason, today or date.today())
        self._save()
        return trade

    def _close(self, pos: Position, exit_price: float, reason: str,
               today: date) -> ClosedTrade:
        sign = 1 if pos.direction == "BUY" else -1
        pnl = sign * (exit_price - pos.entry_price) * pos.quantity
        self.cash += exit_price * pos.quantity
        trade = ClosedTrade(thesis_id=pos.thesis_id, symbol=pos.symbol,
                            direction=pos.direction, entry_price=pos.entry_price,
                            exit_price=exit_price, quantity=pos.quantity,
                            opened=pos.opened, closed=today.isoformat(),
                            exit_reason=reason, pnl=round(pnl, 2),
                            narrative=pos.narrative)
        with CLOSED_FILE.open("a") as f:
            f.write(json.dumps(asdict(trade)) + "\n")
        return trade

    @property
    def equity_invested(self) -> float:
        return sum(p.notional for p in self.positions)


def load_closed_trades() -> list[ClosedTrade]:
    if not CLOSED_FILE.exists():
        return []
    return [ClosedTrade(**json.loads(line))
            for line in CLOSED_FILE.read_text().splitlines() if line.strip()]
