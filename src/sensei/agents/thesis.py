"""Trade Thesis (PRD §4.5) — the structured proposal every trade must be.

Nothing executes from prose. A thesis is data; the approval chain
(chain.py) consumes it, and the audit log stores it verbatim.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class PlaybookCitation(BaseModel):
    strategy: str
    oos_expectancy_pct: float
    oos_hit_rate: float
    oos_trades: int
    oos_detail: dict = Field(
        default_factory=dict,
        description="Full out-of-sample stats: loss distribution, exit breakdown")


class TradeThesis(BaseModel):
    id: str = Field(description="Unique thesis id, e.g. TH-20260705-001")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    symbol: str
    direction: Direction
    entry_zone_low: float
    entry_zone_high: float
    quantity: int
    stop_loss: float
    targets: list[float]
    time_horizon_days: int
    invalidation: str = Field(description="Conditions under which the thesis is dead even before the stop")
    evidence: list[str] = Field(description="Specific signals/facts supporting the trade, each with its source")
    playbook_citations: list[PlaybookCitation] = Field(
        description="Playbook strategies invoked; must be adopted strategies only")
    narrative: str = Field(description="Plain-language thesis the owner can read")

    @property
    def mid_entry(self) -> float:
        return (self.entry_zone_low + self.entry_zone_high) / 2

    @property
    def risk_per_share(self) -> float:
        return abs(self.mid_entry - self.stop_loss)


class Verdict(BaseModel):
    level: str            # "L1" | "L2" | "L3" | "L4"
    agent: str
    approved: bool
    reasoning: str
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ApprovalRecord(BaseModel):
    thesis: TradeThesis
    verdicts: list[Verdict] = []

    @property
    def approved(self) -> bool:
        levels = {v.level for v in self.verdicts if v.approved}
        return {"L1", "L2", "L3", "L4"} <= levels and all(v.approved for v in self.verdicts)

    @property
    def vetoed_by(self) -> list[str]:
        return [f"{v.level}:{v.agent}" for v in self.verdicts if not v.approved]
