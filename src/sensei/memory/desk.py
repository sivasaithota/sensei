"""Cycle-level assembly of one audited context pack per desk role."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Mapping

from sensei.operations import OperationalJournal

from .models import AgentMemoryRole, MemoryBudget, MemoryContextPack, MemoryQuery
from .service import ContextPackAuditTrail, DecisionMemoryService


@dataclass(frozen=True)
class DeskMemoryScope:
    instrument_id: str | None = None
    plan_version_id: str | None = None
    strategy_lineage_id: str | None = None
    market_regime: str | None = None
    timeframe: str | None = None
    limit_per_role: int = 20
    max_bytes_per_role: int = 64_000

    def __post_init__(self) -> None:
        for label, value in (
            ("instrument_id", self.instrument_id),
            ("plan_version_id", self.plan_version_id),
            ("strategy_lineage_id", self.strategy_lineage_id),
            ("market_regime", self.market_regime),
            ("timeframe", self.timeframe),
        ):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{label} must be a non-empty string")
        if type(self.limit_per_role) is not int or not 1 <= self.limit_per_role <= 100:
            raise ValueError("limit_per_role must be between 1 and 100")
        if (
            type(self.max_bytes_per_role) is not int
            or not 256 <= self.max_bytes_per_role <= 1_000_000
        ):
            raise ValueError("max_bytes_per_role must be between 256 and 1000000")


@dataclass(frozen=True)
class DeskMemoryContexts:
    cycle_id: str
    as_of: datetime
    contexts: Mapping[AgentMemoryRole, MemoryContextPack]
    audit_event_ids: Mapping[AgentMemoryRole, str]
    authority: str = "CONTEXT_ONLY"

    def __post_init__(self) -> None:
        if not self.cycle_id.strip():
            raise ValueError("cycle_id is required")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if self.authority != "CONTEXT_ONLY":
            raise ValueError("desk memory authority must be CONTEXT_ONLY")
        contexts = dict(self.contexts)
        audits = dict(self.audit_event_ids)
        if set(contexts) != set(AgentMemoryRole) or set(audits) != set(AgentMemoryRole):
            raise ValueError("desk memory requires every role exactly once")
        if any(pack.query.role is not role for role, pack in contexts.items()):
            raise ValueError("desk memory pack role does not match its map key")
        if any(not isinstance(event_id, str) or not event_id for event_id in audits.values()):
            raise ValueError("desk memory audit event IDs are required")
        object.__setattr__(self, "contexts", MappingProxyType(contexts))
        object.__setattr__(self, "audit_event_ids", MappingProxyType(audits))


class DeskMemoryCoordinator:
    """Prepare and attest role-scoped memory without invoking any role."""

    def __init__(self, journal: OperationalJournal) -> None:
        self._memory = DecisionMemoryService(journal)
        self._audit = ContextPackAuditTrail(journal)

    def prepare_cycle_contexts(
        self,
        *,
        cycle_id: str,
        as_of: datetime,
        occurred_at: datetime,
        scope: DeskMemoryScope,
    ) -> DeskMemoryContexts:
        if not cycle_id.strip():
            raise ValueError("cycle_id is required")
        if not isinstance(scope, DeskMemoryScope):
            raise TypeError("scope must be a DeskMemoryScope")
        contexts = {}
        audit_ids = {}
        for role in AgentMemoryRole:
            pack = self._memory.build_context_pack(
                MemoryQuery(
                    role=role,
                    as_of=as_of,
                    instrument_id=scope.instrument_id,
                    plan_version_id=scope.plan_version_id,
                    strategy_lineage_id=scope.strategy_lineage_id,
                    market_regime=scope.market_regime,
                    timeframe=scope.timeframe,
                    limit=scope.limit_per_role,
                ),
                budget=MemoryBudget(
                    max_items=scope.limit_per_role,
                    max_bytes=scope.max_bytes_per_role,
                ),
            )
            event = self._audit.record(
                pack,
                command_id=f"{cycle_id}:{role.value}:memory",
                occurred_at=occurred_at,
            )
            contexts[role] = pack
            audit_ids[role] = event.event_id
        return DeskMemoryContexts(
            cycle_id=cycle_id,
            as_of=as_of,
            contexts=MappingProxyType(contexts),
            audit_event_ids=MappingProxyType(audit_ids),
        )
