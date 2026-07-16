"""Point-in-time projections over the authoritative Operational Journal."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime

from sensei.operations import JournalIntegrityError, OperationalJournal
from sensei.operations.journal import EventAppend, JournalEvent

from .models import (
    AgentMemoryRole,
    DecisionMemoryItem,
    MemoryContextPack,
    MemoryKind,
    MemoryPolarity,
    MemoryQuery,
    MemoryQueryResult,
)


_COUNTER_EVENTS = frozenset(
    {
        "SchedulerTaskHalted",
        "DeskCycleFailed",
        "DeskRoleSkipped",
        "TradeIntentQuarantined",
        "QuarantineRaised",
        "SafetyLatched",
        "StrategyRejected",
        "DeskSupervisorHalted",
        "DeskSupervisorFailed",
    }
)
_OUTCOME_EVENTS = frozenset(
    {
        "OutcomeAttributed",
        "EpisodeClosed",
        "EntryFillObserved",
        "ExitFillObserved",
        "ReconciliationOutcomeAttested",
        "EntryFillRecorded",
        "ExitFillRecorded",
        "CostsReconciled",
        "ReconciliationRecorded",
        "PaperGatewayCommandExecuted",
    }
)
_KNOWLEDGE_EVENTS = frozenset({"SourceArtifactIngested", "SourceClaimRecorded"})
_LEARNING_EVENTS = frozenset(
    {
        "LearningObservationRecorded",
        "MistakeHypothesisProposed",
        "ExperimentRegistered",
        "ResearchLabDossierRecorded",
        "LockedConfirmationCompleted",
        "ReviewRecorded",
    }
)
_GOVERNANCE_EVENTS = frozenset(
    {
        "StrategyPlanRegistered",
        "StrategyLifecycleTransitioned",
        "StageEvidenceProduced",
        "StageDossierIssued",
        "ShadowTrialPolicyRegistered",
        "ConfirmationAccessConsumed",
        "OperationsReadinessAssessed",
    }
)
_RISK_EVENTS = frozenset(
    {
        "RiskReserved",
        "RiskReleased",
        "RiskFillApplied",
        "TradeCommitteeApproved",
        "TradeCommitteeVerdictProduced",
        "PaperIntentAdmissionAuthorized",
        "SupervisorEntryDispatchAuthorized",
        "SupervisorEntryDispatchRuntimeBinding",
        "SafetyReset",
        "OwnerSafetyResetAuthorized",
    }
)
_MARKET_EVENTS = frozenset(
    {
        "MarketDataIngestionCompleted",
        "DecisionMarketSnapshotRecorded",
        "BrokerSnapshotObserved",
        "ShadowSessionObserved",
        "OperationalHealthAssessed",
        "ComponentHeartbeatRecorded",
        "DriftAssessed",
    }
)
_EPISODE_EVENTS = frozenset(
    {
        "EpisodeStarted",
        "TradeIntentAccepted",
        "DeskCycleStarted",
        "DeskCycleCompleted",
        "DeskRoleCompleted",
        "BrokerCommandPrepared",
        "BrokerCommandCompleted",
        "PlanDecisionTraceProduced",
        "ApprovalRecorded",
        "IntentAccepted",
        "OrderSubmitted",
        "ProtectionVerified",
        "LegacyPaperPositionsAdopted",
    }
)
_OPERATION_EVENTS = frozenset(
    {
        "SchedulerTaskClaimed",
        "SchedulerTaskCompleted",
        "DeskSupervisorStarted",
        "DeskSupervisorStopped",
        "DeskSupervisorCompleted",
        "DeskSupervisorTruthCaptured",
        "AccountSnapshotAuthenticated",
        "BrokerSnapshotAuthenticated",
        "ReconciliationClean",
        "LegacyPaperPositionsReconciled",
        "LegacyFactImported",
        "SupervisorEntryAuthorizationConsumed",
    }
)

_ROOT_SCOPE_PATHS = {
    "instrument": (("instrument_id",), ("symbol",)),
    "plan": (("plan_version_id",), ("plan_id",)),
    "lineage": (("strategy_lineage_id",), ("lineage_id",)),
    "regime": (("market_regime",), ("regime",)),
    "timeframe": (("timeframe",),),
}
_SCOPE_EXTRAS = {
    "LearningObservationRecorded": {
        "plan": (("scope", "plan_version_id"),),
        "lineage": (("scope", "strategy_lineage_id"),),
        "regime": (("scope", "market_regime"),),
        "timeframe": (("scope", "timeframe"),),
    },
    "MistakeHypothesisProposed": {
        "plan": (("scope", "plan_version_id"),),
        "lineage": (("scope", "strategy_lineage_id"),),
        "regime": (("scope", "market_regime"),),
        "timeframe": (("scope", "timeframe"),),
    },
    "PlanDecisionTraceProduced": {
        "instrument": (("fact", "trace", "instrument_id"),),
        "plan": (("fact", "trace", "plan_id"),),
    },
    "PaperIntentAdmissionAuthorized": {
        "instrument": (("fact", "intent", "instrument_id"),),
        "plan": (("fact", "intent", "plan_version_id"),),
    },
    "TradeIntentAccepted": {
        "instrument": (("intent", "instrument_id"),),
        "plan": (("intent", "plan_version_id"),),
    },
    "BrokerCommandPrepared": {
        "instrument": (("command", "instrument_id"),),
    },
    "TradeCommitteeVerdictProduced": {
        "instrument": (("fact", "thesis", "symbol"),),
    },
    "TradeCommitteeApproved": {
        "instrument": (("thesis", "symbol"), ("intent", "instrument_id")),
    },
    "ShadowSessionObserved": {
        "instrument": (("evaluations", "*", "instrument_id"),),
    },
    "MarketDataIngestionCompleted": {
        "instrument": (("eligible_symbols", "*"),),
    },
    "LegacyPaperPositionsAdopted": {
        "instrument": (("positions", "*", "symbol"),),
    },
}

_ROLE_KINDS = {
    AgentMemoryRole.DESK_HEAD: frozenset(MemoryKind),
    AgentMemoryRole.HISTORIAN: frozenset(
        {MemoryKind.EPISODE, MemoryKind.OUTCOME, MemoryKind.COUNTER_EVIDENCE,
         MemoryKind.KNOWLEDGE, MemoryKind.GOVERNANCE, MemoryKind.MARKET_CONTEXT}
    ),
    AgentMemoryRole.REPORTER: frozenset(
        {MemoryKind.EPISODE, MemoryKind.OUTCOME, MemoryKind.COUNTER_EVIDENCE,
         MemoryKind.KNOWLEDGE, MemoryKind.MARKET_CONTEXT}
    ),
    AgentMemoryRole.CROWD_READER: frozenset(
        {MemoryKind.OUTCOME, MemoryKind.COUNTER_EVIDENCE, MemoryKind.MARKET_CONTEXT}
    ),
    AgentMemoryRole.ANALYST: frozenset(
        {MemoryKind.EPISODE, MemoryKind.OUTCOME, MemoryKind.COUNTER_EVIDENCE,
         MemoryKind.KNOWLEDGE, MemoryKind.LEARNING, MemoryKind.GOVERNANCE, MemoryKind.RISK,
         MemoryKind.MARKET_CONTEXT}
    ),
    AgentMemoryRole.COMMITTEE: frozenset(MemoryKind),
    AgentMemoryRole.TRADER: frozenset(
        {MemoryKind.EPISODE, MemoryKind.COUNTER_EVIDENCE, MemoryKind.GOVERNANCE,
         MemoryKind.RISK, MemoryKind.MARKET_CONTEXT, MemoryKind.OPERATIONS}
    ),
    AgentMemoryRole.COACH: frozenset(
        {MemoryKind.EPISODE, MemoryKind.OUTCOME, MemoryKind.COUNTER_EVIDENCE,
         MemoryKind.LEARNING, MemoryKind.MARKET_CONTEXT}
    ),
    AgentMemoryRole.SECRETARY: frozenset(MemoryKind),
}


class DecisionMemoryService:
    """Read-only institutional memory; it exposes no trading mutation methods."""

    def __init__(self, journal: OperationalJournal) -> None:
        if not isinstance(journal, OperationalJournal):
            raise TypeError("journal must be an OperationalJournal")
        self._journal = journal

    def query(self, query: MemoryQuery) -> MemoryQueryResult:
        if not isinstance(query, MemoryQuery):
            raise TypeError("query must be a MemoryQuery")
        verification = self._journal.verify()
        if not verification.ok:
            raise JournalIntegrityError("decision memory requires an intact journal")
        events = self._journal.read_all()
        projected: dict[str, DecisionMemoryItem] = {}
        for event in events:
            known_at = max(event.occurred_at, event.recorded_at)
            if known_at > query.as_of:
                continue
            item = _project(event, known_at)
            if item is None:
                continue
            projected[item.event_id] = item
        allowed = _ROLE_KINDS[query.role]
        roots = sorted(
            (
                item
                for item in projected.values()
                if item.kind in allowed and _matches(item, query)
            ),
            key=_sort_key,
        )
        selected: dict[str, DecisionMemoryItem] = {}
        valid_visible: set[str] = set()
        for root in roots:
            closure = _evidence_closure(root, projected, allowed)
            if closure is None:
                continue
            valid_visible.update(item.event_id for item in closure)
            additions = {
                item.event_id: item
                for item in closure
                if item.event_id not in selected
            }
            if len(selected) + len(additions) > query.limit:
                continue
            selected.update(additions)
        visible = sorted(selected.values(), key=_sort_key)
        return MemoryQueryResult(
            query=query,
            items=tuple(visible),
            events_examined=len(events),
            events_visible=len(valid_visible),
        )

    def build_context_pack(self, query: MemoryQuery) -> MemoryContextPack:
        result = self.query(query)
        source_ids = tuple(
            sorted({source for item in result.items for source in item.source_event_ids})
        )
        return MemoryContextPack(
            context_pack_id=MemoryContextPack.content_id_for(
                query, result.items, source_ids
            ),
            query=query,
            items=result.items,
            source_event_ids=source_ids,
        )


class ContextPackAuditTrail:
    """Durably attest which non-authoritative context a role received."""

    def __init__(self, journal: OperationalJournal) -> None:
        if not isinstance(journal, OperationalJournal):
            raise TypeError("journal must be an OperationalJournal")
        self._journal = journal

    def record(
        self,
        pack: MemoryContextPack,
        *,
        command_id: str,
        occurred_at: datetime,
    ) -> JournalEvent:
        if not isinstance(pack, MemoryContextPack):
            raise TypeError("pack must be a MemoryContextPack")
        if not command_id.strip():
            raise ValueError("command_id is required")
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        if occurred_at < pack.query.as_of:
            raise ValueError("context audit cannot predate the recalled context")
        if not self._journal.verify().ok:
            raise JournalIntegrityError("context pack audit requires an intact journal")
        consumer_hash = hashlib.sha256(
            f"{pack.context_pack_id}|{command_id}".encode()
        ).hexdigest()
        stream = "memory-context-use:" + consumer_hash
        return self._journal.append(
            EventAppend(
                stream_id=stream,
                event_type="MemoryContextPackAssembled",
                payload={
                    "context_pack_id": pack.context_pack_id,
                    "consumer_command_id": command_id,
                    "query": pack.query.identity_payload(),
                    "source_event_ids": list(pack.source_event_ids),
                    "authority": pack.authority,
                    "can_authorize_trading": pack.can_authorize_trading,
                    "can_mutate_strategy": pack.can_mutate_strategy,
                    "can_mutate_risk": pack.can_mutate_risk,
                },
                idempotency_key="memory-context-audit:"
                + hashlib.sha256(command_id.encode()).hexdigest(),
                expected_version=0,
                occurred_at=occurred_at,
                correlation_id=pack.context_pack_id,
            )
        )


def _project(event: JournalEvent, known_at) -> DecisionMemoryItem | None:
    payload = _plain(event.payload)
    kind = _kind(event.event_type)
    if kind is None:
        return None
    polarity = _polarity(event.event_type, payload)
    authority = _authority(kind)
    return DecisionMemoryItem(
        event_id=event.event_id,
        event_type=event.event_type,
        occurred_at=event.occurred_at,
        known_at=known_at,
        kind=kind,
        polarity=polarity,
        authority=authority,
        summary=_summary(event.event_type, payload),
        source_event_ids=_source_event_ids(event.event_id, payload),
        facts_json=_canonical(payload),
        instrument_ids=_scope_values(event.event_type, payload, "instrument"),
        plan_version_ids=_scope_values(event.event_type, payload, "plan"),
        strategy_lineage_ids=_scope_values(event.event_type, payload, "lineage"),
        market_regimes=_scope_values(event.event_type, payload, "regime"),
        timeframes=_scope_values(event.event_type, payload, "timeframe"),
    )


def _kind(event_type: str) -> MemoryKind | None:
    if event_type in _COUNTER_EVENTS:
        return MemoryKind.COUNTER_EVIDENCE
    if event_type in _OUTCOME_EVENTS:
        return MemoryKind.OUTCOME
    if event_type in _KNOWLEDGE_EVENTS:
        return MemoryKind.KNOWLEDGE
    if event_type in _LEARNING_EVENTS:
        return MemoryKind.LEARNING
    if event_type in _GOVERNANCE_EVENTS:
        return MemoryKind.GOVERNANCE
    if event_type in _RISK_EVENTS:
        return MemoryKind.RISK
    if event_type in _MARKET_EVENTS:
        return MemoryKind.MARKET_CONTEXT
    if event_type in _EPISODE_EVENTS:
        return MemoryKind.EPISODE
    if event_type in _OPERATION_EVENTS:
        return MemoryKind.OPERATIONS
    return None


def _polarity(event_type: str, payload: dict[str, object]) -> MemoryPolarity:
    if event_type in _COUNTER_EVENTS:
        if event_type in {"SchedulerTaskHalted", "DeskRoleSkipped"}:
            return MemoryPolarity.ABSTENTION
        return MemoryPolarity.NEGATIVE
    if event_type in _OUTCOME_EVENTS:
        pnl = _find_number(payload, ("realized_pnl_paise", "pnl_paise", "pnl"))
        if pnl is not None:
            return MemoryPolarity.POSITIVE if pnl > 0 else MemoryPolarity.NEGATIVE
    return MemoryPolarity.NEUTRAL


def _authority(kind: MemoryKind) -> str:
    if kind in {MemoryKind.KNOWLEDGE, MemoryKind.LEARNING}:
        return "RESEARCH_ONLY"
    if kind is MemoryKind.GOVERNANCE:
        return "GOVERNANCE_EVIDENCE"
    if kind is MemoryKind.RISK:
        return "RISK_EVIDENCE"
    return "JOURNAL_FACT"


def _evidence_closure(
    root: DecisionMemoryItem,
    projected: Mapping[str, DecisionMemoryItem],
    allowed: frozenset[MemoryKind],
) -> tuple[DecisionMemoryItem, ...] | None:
    resolved: dict[str, DecisionMemoryItem] = {}
    pending = [root]
    while pending:
        item = pending.pop()
        if item.event_id in resolved:
            continue
        if item.kind not in allowed:
            return None
        resolved[item.event_id] = item
        for event_id in item.source_event_ids:
            if event_id == item.event_id:
                continue
            evidence = projected.get(event_id)
            if evidence is None:
                return None
            pending.append(evidence)
    return tuple(resolved.values())


def _matches(item: DecisionMemoryItem, query: MemoryQuery) -> bool:
    return all(
        expected is None or expected in actuals
        for actuals, expected in (
            (item.instrument_ids, query.instrument_id),
            (item.plan_version_ids, query.plan_version_id),
            (item.strategy_lineage_ids, query.strategy_lineage_id),
            (item.market_regimes, query.market_regime),
            (item.timeframes, query.timeframe),
        )
    )


def _sort_key(item: DecisionMemoryItem):
    priority = {
        MemoryPolarity.ABSTENTION: 0,
        MemoryPolarity.NEGATIVE: 1,
        MemoryPolarity.POSITIVE: 2,
        MemoryPolarity.NEUTRAL: 3,
    }
    return (priority[item.polarity], -item.known_at.timestamp(), item.event_id)


def _summary(event_type: str, payload: dict[str, object]) -> str:
    detail = _find_text(payload, ("summary", "detail", "reason", "failure_type"))
    return f"{event_type}: {detail}" if detail else event_type


def _source_event_ids(own_id: str, payload: object) -> tuple[str, ...]:
    found = {own_id}

    def visit(value: object, key: str = "") -> None:
        if isinstance(value, Mapping):
            for child_key, child in value.items():
                visit(child, str(child_key))
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for child in value:
                visit(child, key)
        elif isinstance(value, str) and value.startswith("event:") and (
            key.endswith("event_id")
            or key.endswith("event_ids")
            or key in {"evidence_refs", "supporting_event_ids"}
        ):
            found.add(value)

    visit(payload)
    return tuple(sorted(found))


def _find_text(value: object, keys: tuple[str, ...]) -> str | None:
    if isinstance(value, Mapping):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate
        for child in value.values():
            found = _find_text(child, keys)
            if found is not None:
                return found
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            found = _find_text(child, keys)
            if found is not None:
                return found
    return None


def _scope_values(
    event_type: str,
    payload: Mapping[str, object],
    field: str,
) -> tuple[str, ...]:
    paths = _ROOT_SCOPE_PATHS[field] + _SCOPE_EXTRAS.get(event_type, {}).get(
        field, ()
    )
    found: set[str] = set()
    for path in paths:
        found.update(_values_at_path(payload, path))
    return tuple(sorted(found))


def _values_at_path(value: object, path: tuple[str, ...]) -> tuple[str, ...]:
    if not path:
        return (value,) if isinstance(value, str) and value.strip() else ()
    head, *tail = path
    if head == "*":
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            return ()
        return tuple(
            result
            for child in value
            for result in _values_at_path(child, tuple(tail))
        )
    if not isinstance(value, Mapping) or head not in value:
        return ()
    return _values_at_path(value[head], tuple(tail))


def _find_number(value: object, keys: tuple[str, ...]) -> float | None:
    if isinstance(value, Mapping):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
                return float(candidate)
        for child in value.values():
            found = _find_number(child, keys)
            if found is not None:
                return found
    return None


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_plain(child) for child in value]
    return value


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
