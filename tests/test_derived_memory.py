from datetime import datetime, timedelta, timezone

import pytest

from sensei.memory import DerivedMemoryRegistry, DerivedMemoryState
from sensei.operations import EventAppend, OperationalJournal


NOW = datetime(2026, 7, 17, 10, 0, tzinfo=timezone.utc)


def test_derived_interpretation_has_provenance_and_governed_lifecycle(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3", clock=lambda: NOW)
    source = journal.append(
        EventAppend(
            stream_id="source:one",
            event_type="OutcomeAttributed",
            payload={"realized_net_pnl": "-50", "reconciles": True},
            idempotency_key="source:one",
            expected_version=0,
            occurred_at=NOW,
        )
    )
    corroboration = journal.append(
        EventAppend(
            stream_id="source:two",
            event_type="OutcomeAttributed",
            payload={"realized_net_pnl": "-75", "reconciles": True},
            idempotency_key="source:two",
            expected_version=0,
            occurred_at=NOW,
        )
    )
    registry = DerivedMemoryRegistry(journal)

    candidate = registry.register(
        statement="Late entry may explain repeated slippage.",
        source_event_ids=(source.event_id,),
        producer_id="coach:v1",
        model_id="model:reflection:v1",
        confidence=0.6,
        occurred_at=NOW + timedelta(minutes=1),
        command_id="derived-one",
    )
    corroborated = registry.transition(
        candidate.derived_memory_id,
        to_state=DerivedMemoryState.CORROBORATED,
        evidence_event_ids=(corroboration.event_id,),
        occurred_at=NOW + timedelta(minutes=2),
        command_id="corroborate-one",
    )

    assert candidate.state is DerivedMemoryState.CANDIDATE
    assert corroborated.state is DerivedMemoryState.CORROBORATED
    assert corroborated.authority == "RESEARCH_ONLY"
    with pytest.raises(ValueError, match="transition"):
        registry.transition(
            candidate.derived_memory_id,
            to_state=DerivedMemoryState.CANDIDATE,
            evidence_event_ids=(source.event_id,),
            occurred_at=NOW + timedelta(minutes=3),
            command_id="invalid-backward",
        )
