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
from sensei.execution.nse import NseExecutionModel

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
    sessions_held: int = 1
    last_marked_session: str | None = None

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
    exit_reason: str  # "stop" | "stop_gap" | "target" | "time" | "invalidation" | "kill"
    pnl: float
    narrative: str
    post_mortem: dict | None = None  # filled by the Coach
    gross_pnl: float | None = None
    charges: float = 0.0
    execution_quality: dict | None = None


class PaperBook:
    """The simulated account: cash, open positions, closed-trade log."""

    def __init__(
        self,
        starting_cash: float = 50000,
        *,
        execution_model: NseExecutionModel | None = None,
    ):
        PAPER_DIR.mkdir(parents=True, exist_ok=True)
        if POSITIONS_FILE.exists():
            state = json.loads(POSITIONS_FILE.read_text())
            self.cash = state["cash"]
            self.positions = [Position(**p) for p in state["positions"]]
        else:
            self.cash = starting_cash
            self.positions = []
        self._execution_model = execution_model

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
        if t.direction.value != "BUY":
            raise ValueError("paper execution is long-only; SELL entries are disabled")
        cost = fill_price * t.quantity
        if cost > self.cash:
            raise ValueError(f"insufficient paper cash {self.cash:.0f} for {cost:.0f}")
        pos = Position(thesis_id=t.id, symbol=t.symbol, direction=t.direction.value,
                       entry_price=fill_price, quantity=t.quantity,
                       stop_loss=t.stop_loss, targets=t.targets,
                       opened=(today or date.today()).isoformat(),
                       max_hold_days=t.time_horizon_days, narrative=t.narrative,
                       sessions_held=1,
                       last_marked_session=(today or date.today()).isoformat())
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
            if today < date.fromisoformat(pos.opened):
                raise ValueError("mark session cannot precede the position open")
            last_marked = date.fromisoformat(
                pos.last_marked_session or pos.opened
            )
            if today > last_marked:
                pos.sessions_held += 1
                pos.last_marked_session = today.isoformat()
            if bar["open"] <= pos.stop_loss:
                # A stop cannot fill at a price the market gapped through.
                exit_price, reason = bar["open"], "stop_gap"
            elif bar["low"] <= pos.stop_loss:          # stop first — conservative
                exit_price, reason = pos.stop_loss, "stop"
            elif pos.targets and bar["high"] >= pos.targets[0]:
                exit_price, reason = pos.targets[0], "target"
            elif pos.sessions_held >= pos.max_hold_days:
                exit_price, reason = bar["close"], "time"

            if exit_price is None:
                remaining.append(pos)
                continue
            if self._execution_model is None:
                closed.append(self._close(pos, exit_price, reason, today))
                continue
            volume = int(bar.get("volume", pos.quantity * 100))
            lower_circuit = round(float(bar.get("lower_circuit", 0.01)) * 100)
            if reason in {"stop", "stop_gap"}:
                fill = self._execution_model.simulate_stop_exit(
                    quantity=pos.quantity,
                    stop_price_paise=round(pos.stop_loss * 100),
                    session_open_paise=round(float(bar["open"]) * 100),
                    session_low_paise=round(float(bar["low"]) * 100),
                    available_volume=volume,
                    lower_circuit_paise=max(1, lower_circuit),
                )
            else:
                fill = self._execution_model.simulate_exit(
                    quantity=pos.quantity,
                    reference_price_paise=round(exit_price * 100),
                    available_volume=volume,
                    reason_code=reason.upper(),
                    lower_circuit_paise=max(1, lower_circuit),
                )
            if not fill.filled_quantity:
                remaining.append(pos)
                continue
            quality = fill.to_payload()
            quality["market_evidence"] = {
                "source": "GOVERNED_EOD_SESSION_BAR",
                "observed_at": datetime.combine(
                    today, datetime.min.time(), tzinfo=timezone.utc
                ).isoformat(),
                "session_volume": volume,
                "spread_is_estimated": True,
                "circuit_is_estimated": "lower_circuit" not in bar,
            }
            closed.append(self._close(
                pos,
                fill.fill_price_paise / 100,
                reason,
                today,
                quantity=fill.filled_quantity,
                charges=fill.charges.total_paise / 100,
                execution_quality=quality,
            ))
            if fill.filled_quantity < pos.quantity:
                pos.quantity -= fill.filled_quantity
                remaining.append(pos)
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
               today: date, *, quantity: int | None = None,
               charges: float = 0.0,
               execution_quality: dict | None = None) -> ClosedTrade:
        quantity = pos.quantity if quantity is None else quantity
        sign = 1 if pos.direction == "BUY" else -1
        gross_pnl = sign * (exit_price - pos.entry_price) * quantity
        pnl = gross_pnl - charges
        self.cash += exit_price * quantity - charges
        trade = ClosedTrade(thesis_id=pos.thesis_id, symbol=pos.symbol,
                            direction=pos.direction, entry_price=pos.entry_price,
                            exit_price=exit_price, quantity=quantity,
                            opened=pos.opened, closed=today.isoformat(),
                            exit_reason=reason, pnl=round(pnl, 2),
                            narrative=pos.narrative,
                            gross_pnl=round(gross_pnl, 2),
                            charges=round(charges, 2),
                            execution_quality=execution_quality)
        with CLOSED_FILE.open("a") as f:
            f.write(json.dumps(asdict(trade)) + "\n")
        return trade

    @property
    def equity_invested(self) -> float:
        return sum(p.notional for p in self.positions)


def attach_post_mortem(thesis_id: str, pm: dict) -> bool:
    """Write the Coach's post-mortem back onto the closed-trade record."""
    trades = load_closed_trades()
    hit = False
    for t in trades:
        if t.thesis_id == thesis_id and t.post_mortem is None:
            t.post_mortem = pm
            hit = True
    if hit:
        with CLOSED_FILE.open("w") as f:
            for t in trades:
                f.write(json.dumps(asdict(t)) + "\n")
    return hit


def load_closed_trades() -> list[ClosedTrade]:
    if not CLOSED_FILE.exists():
        return []
    return [ClosedTrade(**json.loads(line))
            for line in CLOSED_FILE.read_text().splitlines() if line.strip()]
