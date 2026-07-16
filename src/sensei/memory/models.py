"""Typed, non-authoritative decision-memory contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class AgentMemoryRole(str, Enum):
    DESK_HEAD = "desk_head"
    HISTORIAN = "historian"
    REPORTER = "reporter"
    CROWD_READER = "crowd_reader"
    ANALYST = "analyst"
    COMMITTEE = "committee"
    TRADER = "trader"
    COACH = "coach"
    SECRETARY = "secretary"


class MemoryKind(str, Enum):
    EPISODE = "episode"
    OUTCOME = "outcome"
    COUNTER_EVIDENCE = "counter_evidence"
    KNOWLEDGE = "knowledge"
    LEARNING = "learning"
    GOVERNANCE = "governance"
    RISK = "risk"
    MARKET_CONTEXT = "market_context"
    OPERATIONS = "operations"


class MemoryPolarity(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    ABSTENTION = "abstention"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class MemoryQuery:
    role: AgentMemoryRole
    as_of: datetime
    instrument_id: str | None = None
    plan_version_id: str | None = None
    strategy_lineage_id: str | None = None
    market_regime: str | None = None
    timeframe: str | None = None
    limit: int = 20

    def __post_init__(self) -> None:
        if not isinstance(self.role, AgentMemoryRole):
            raise TypeError("role must be an AgentMemoryRole")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        for label, value in (
            ("instrument_id", self.instrument_id),
            ("plan_version_id", self.plan_version_id),
            ("strategy_lineage_id", self.strategy_lineage_id),
            ("market_regime", self.market_regime),
            ("timeframe", self.timeframe),
        ):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{label} must be a non-empty string")
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise ValueError("limit must be between 1 and 100")

    def identity_payload(self) -> dict[str, object]:
        return {
            "role": self.role.value,
            "as_of": self.as_of.isoformat(),
            "instrument_id": self.instrument_id,
            "plan_version_id": self.plan_version_id,
            "strategy_lineage_id": self.strategy_lineage_id,
            "market_regime": self.market_regime,
            "timeframe": self.timeframe,
            "limit": self.limit,
        }


@dataclass(frozen=True)
class DecisionMemoryItem:
    event_id: str
    event_type: str
    occurred_at: datetime
    known_at: datetime
    kind: MemoryKind
    polarity: MemoryPolarity
    authority: str
    summary: str
    source_event_ids: tuple[str, ...]
    facts_json: str
    instrument_ids: tuple[str, ...] = ()
    plan_version_ids: tuple[str, ...] = ()
    strategy_lineage_ids: tuple[str, ...] = ()
    market_regimes: tuple[str, ...] = ()
    timeframes: tuple[str, ...] = ()

    @property
    def facts(self) -> dict[str, object]:
        return json.loads(self.facts_json)

    def identity_payload(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.isoformat(),
            "known_at": self.known_at.isoformat(),
            "kind": self.kind.value,
            "polarity": self.polarity.value,
            "authority": self.authority,
            "summary": self.summary,
            "source_event_ids": list(self.source_event_ids),
            "facts": self.facts,
            "instrument_ids": list(self.instrument_ids),
            "plan_version_ids": list(self.plan_version_ids),
            "strategy_lineage_ids": list(self.strategy_lineage_ids),
            "market_regimes": list(self.market_regimes),
            "timeframes": list(self.timeframes),
        }


@dataclass(frozen=True)
class MemoryQueryResult:
    query: MemoryQuery
    items: tuple[DecisionMemoryItem, ...]
    events_examined: int
    events_visible: int


@dataclass(frozen=True)
class MemoryContextPack:
    context_pack_id: str
    query: MemoryQuery
    items: tuple[DecisionMemoryItem, ...]
    source_event_ids: tuple[str, ...]
    authority: str = "CONTEXT_ONLY"
    can_authorize_trading: bool = False
    can_mutate_strategy: bool = False
    can_mutate_risk: bool = False

    def __post_init__(self) -> None:
        if self.authority != "CONTEXT_ONLY":
            raise ValueError("memory context authority must be CONTEXT_ONLY")
        if self.can_authorize_trading or self.can_mutate_strategy or self.can_mutate_risk:
            raise ValueError("memory context packs cannot carry mutation authority")
        if self.context_pack_id != self.content_id_for(
            self.query, self.items, self.source_event_ids
        ):
            raise ValueError("memory context pack ID does not match its content")

    @staticmethod
    def content_id_for(
        query: MemoryQuery,
        items: tuple[DecisionMemoryItem, ...],
        source_event_ids: tuple[str, ...],
    ) -> str:
        identity = {
            "schema_version": "1.0",
            "authority": "CONTEXT_ONLY",
            "can_authorize_trading": False,
            "can_mutate_strategy": False,
            "can_mutate_risk": False,
            "query": query.identity_payload(),
            "items": [item.identity_payload() for item in items],
            "source_event_ids": list(source_event_ids),
        }
        encoded = json.dumps(
            identity,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
        return "memory-context:sha256:" + hashlib.sha256(encoded).hexdigest()
