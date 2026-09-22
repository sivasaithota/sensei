"""Strict contracts for an AI decision, independent of the trading kernel."""
from datetime import timedelta
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Integer = Annotated[int, Field(strict=True, ge=0)]
Positive = Annotated[int, Field(strict=True, gt=0)]
Bps = Annotated[int, Field(strict=True, ge=0, le=10000)]
Text = Annotated[str, Field(strict=True, min_length=1, max_length=20000)]


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Instrument(Contract):
    symbol: Annotated[str, Field(pattern=r'^[A-Z0-9&-]{1,30}$')]
    price_paise: Positive
    marked_at: AwareDatetime
    held_quantity: Integer
    available_quantity: Integer

    @model_validator(mode='after')
    def available_shares(self):
        if self.available_quantity > self.held_quantity:
            raise ValueError('available shares exceed held shares')
        return self


class Evidence(Contract):
    id: Text
    symbol: str | None
    source: Text
    published_at: AwareDatetime
    available_at: AwareDatetime
    text: Text


class Limits(Contract):
    max_position_bps: Bps = 950
    min_cash_bps: Bps = 500
    max_positions: Positive = 10
    max_mark_age_hours: Positive = 96
    max_drawdown_bps: Bps = 1500


class Packet(Contract):
    label: Text
    synthetic: Annotated[bool, Field(strict=True)]
    cutoff: AwareDatetime
    cash_paise: Integer
    receivables_paise: Integer = 0
    high_water_paise: Positive
    instruments: Annotated[list[Instrument], Field(min_length=1, max_length=100)]
    evidence: Annotated[list[Evidence], Field(min_length=1, max_length=500)]
    limits: Limits

    @property
    def equity_paise(self):
        return self.cash_paise + self.receivables_paise + sum(i.price_paise * i.held_quantity for i in self.instruments)

    @model_validator(mode='after')
    def coherent_packet(self):
        symbols = {i.symbol for i in self.instruments}
        if len(symbols) != len(self.instruments) or len({e.id for e in self.evidence}) != len(self.evidence):
            raise ValueError('duplicate symbols or evidence IDs')
        for i in self.instruments:
            if not timedelta(0) <= self.cutoff - i.marked_at <= timedelta(hours=self.limits.max_mark_age_hours):
                raise ValueError(f'future or stale mark: {i.symbol}')
        for e in self.evidence:
            if e.symbol is not None and e.symbol not in symbols:
                raise ValueError('evidence references unknown symbol')
            if not e.published_at <= e.available_at <= self.cutoff:
                raise ValueError('evidence unavailable at cutoff')
        if self.equity_paise <= 0 or self.high_water_paise < self.equity_paise:
            raise ValueError('invalid equity or high water mark')
        return self


class Assessment(Contract):
    symbol: Text
    reason: Text
    evidence_ids: Annotated[list[Text], Field(min_length=1)]


class Analysis(Contract):
    summary: Text
    assessments: Annotated[list[Assessment], Field(min_length=1)]


class CoachReview(Contract):
    """Advisory process notes have no tradable symbol or allocation authority."""
    summary: Text
    assessments: list[Assessment]
    process_notes: list[Text] = Field(default_factory=list)


class Allocation(Assessment):
    weight_bps: Bps
    invalidation: Text
    review_after_sessions: Annotated[int, Field(strict=True, ge=1, le=60)]


class Decision(Contract):
    allocations: list[Allocation]
    cash_bps: Bps
    cash_reason: Text
    critic_response: Text


def validate_citations(packet: Packet, assessments: list[Assessment]):
    symbols = {i.symbol for i in packet.instruments}
    evidence = {e.id: e for e in packet.evidence}
    for a in assessments:
        if a.symbol not in symbols:
            raise ValueError(f'unknown symbol: {a.symbol}')
        if any(ref not in evidence for ref in a.evidence_ids):
            raise ValueError(f'invalid citation for {a.symbol}')
        if not any(evidence[ref].symbol == a.symbol for ref in a.evidence_ids):
            raise ValueError(f'no symbol-specific evidence for {a.symbol}')


class TargetDecision(Contract):
    """AI chooses investments; remaining cash follows arithmetically."""
    allocations: list[Allocation]
    cash_reason: Text
    critic_response: Text

    def complete(self):
        return Decision(**self.model_dump(), cash_bps=10000-sum(a.weight_bps for a in self.allocations))
