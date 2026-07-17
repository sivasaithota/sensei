"""Governed lifecycle for probabilistic interpretations derived from facts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from sensei.operations import EventAppend, JournalIntegrityError, OperationalJournal


class DerivedMemoryState(str, Enum):
    CANDIDATE = "candidate"
    CORROBORATED = "corroborated"
    CONTRADICTED = "contradicted"
    STALE = "stale"
    RETIRED = "retired"


@dataclass(frozen=True)
class DerivedMemoryRecord:
    derived_memory_id: str
    statement: str
    source_event_ids: tuple[str, ...]
    producer_id: str
    model_id: str
    confidence: float
    state: DerivedMemoryState
    occurred_at: datetime
    authority: str = "RESEARCH_ONLY"


_TRANSITIONS = {
    DerivedMemoryState.CANDIDATE: frozenset(
        {
            DerivedMemoryState.CORROBORATED,
            DerivedMemoryState.CONTRADICTED,
            DerivedMemoryState.STALE,
            DerivedMemoryState.RETIRED,
        }
    ),
    DerivedMemoryState.CORROBORATED: frozenset(
        {
            DerivedMemoryState.CONTRADICTED,
            DerivedMemoryState.STALE,
            DerivedMemoryState.RETIRED,
        }
    ),
    DerivedMemoryState.CONTRADICTED: frozenset({DerivedMemoryState.RETIRED}),
    DerivedMemoryState.STALE: frozenset(
        {DerivedMemoryState.CANDIDATE, DerivedMemoryState.RETIRED}
    ),
    DerivedMemoryState.RETIRED: frozenset(),
}


class DerivedMemoryRegistry:
    def __init__(self, journal: OperationalJournal) -> None:
        self._journal = journal

    def register(
        self,
        *,
        statement: str,
        source_event_ids: tuple[str, ...],
        producer_id: str,
        model_id: str,
        confidence: float,
        occurred_at: datetime,
        command_id: str,
    ) -> DerivedMemoryRecord:
        if not statement.strip() or not producer_id.strip() or not model_id.strip():
            raise ValueError("statement, producer and model are required")
        if not source_event_ids or len(set(source_event_ids)) != len(source_event_ids):
            raise ValueError("derived memory requires unique source evidence")
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between zero and one")
        self._verify_sources(source_event_ids, occurred_at)
        identity = json.dumps(
            {
                "statement": statement.strip(),
                "source_event_ids": sorted(source_event_ids),
                "producer_id": producer_id,
                "model_id": model_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        derived_id = "derived-memory:sha256:" + hashlib.sha256(identity.encode()).hexdigest()
        self._journal.append(
            EventAppend(
                stream_id=derived_id,
                event_type="DerivedMemoryInterpretationRecorded",
                payload={
                    "derived_memory_id": derived_id,
                    "statement": statement.strip(),
                    "source_event_ids": list(source_event_ids),
                    "producer_id": producer_id,
                    "model_id": model_id,
                    "confidence": confidence,
                    "state": DerivedMemoryState.CANDIDATE.value,
                    "authority": "RESEARCH_ONLY",
                },
                idempotency_key="derived-memory:" + hashlib.sha256(command_id.encode()).hexdigest(),
                expected_version=0,
                occurred_at=occurred_at,
                correlation_id=derived_id,
            )
        )
        return self.get(derived_id)

    def transition(
        self,
        derived_memory_id: str,
        *,
        to_state: DerivedMemoryState,
        evidence_event_ids: tuple[str, ...],
        occurred_at: datetime,
        command_id: str,
    ) -> DerivedMemoryRecord:
        current = self.get(derived_memory_id)
        if not isinstance(to_state, DerivedMemoryState):
            raise TypeError("to_state must be a DerivedMemoryState")
        if to_state not in _TRANSITIONS[current.state]:
            raise ValueError("derived memory transition is not allowed")
        if (
            to_state is DerivedMemoryState.CORROBORATED
            and not set(evidence_event_ids).isdisjoint(current.source_event_ids)
        ):
            raise ValueError("corroboration requires independent evidence")
        self._verify_sources(evidence_event_ids, occurred_at)
        stream = self._journal.read_stream(derived_memory_id)
        self._journal.append(
            EventAppend(
                stream_id=derived_memory_id,
                event_type="DerivedMemoryStateTransitioned",
                payload={
                    "derived_memory_id": derived_memory_id,
                    "from_state": current.state.value,
                    "to_state": to_state.value,
                    "evidence_event_ids": list(evidence_event_ids),
                    "authority": "RESEARCH_ONLY",
                },
                idempotency_key="derived-memory-transition:"
                + hashlib.sha256(command_id.encode()).hexdigest(),
                expected_version=len(stream),
                occurred_at=occurred_at,
                correlation_id=derived_memory_id,
            )
        )
        return self.get(derived_memory_id)

    def get(self, derived_memory_id: str) -> DerivedMemoryRecord:
        if not self._journal.verify().ok:
            raise JournalIntegrityError("derived memory requires an intact journal")
        events = self._journal.read_stream(derived_memory_id)
        if not events or events[0].event_type != "DerivedMemoryInterpretationRecorded":
            raise ValueError("derived memory does not exist")
        payload = events[0].payload
        state = DerivedMemoryState(str(payload["state"]))
        for event in events[1:]:
            if event.event_type != "DerivedMemoryStateTransitioned":
                raise ValueError("derived memory stream contains an unknown event")
            if event.payload.get("from_state") != state.value:
                raise ValueError("derived memory transition history is inconsistent")
            state = DerivedMemoryState(str(event.payload["to_state"]))
        return DerivedMemoryRecord(
            derived_memory_id=derived_memory_id,
            statement=str(payload["statement"]),
            source_event_ids=tuple(str(value) for value in payload["source_event_ids"]),
            producer_id=str(payload["producer_id"]),
            model_id=str(payload["model_id"]),
            confidence=float(payload["confidence"]),
            state=state,
            occurred_at=events[-1].occurred_at,
        )

    def _verify_sources(
        self, source_event_ids: tuple[str, ...], occurred_at: datetime
    ) -> None:
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        if not source_event_ids:
            raise ValueError("evidence is required")
        if not self._journal.verify().ok:
            raise JournalIntegrityError("derived memory requires an intact journal")
        sources = {
            event.event_id: event
            for event in self._journal.read_all()
            if event.event_id in source_event_ids
        }
        if set(sources) != set(source_event_ids) or any(
            max(event.occurred_at, event.recorded_at) > occurred_at
            for event in sources.values()
        ):
            raise ValueError("derived memory evidence is missing or future-known")
