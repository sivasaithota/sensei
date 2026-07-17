from datetime import datetime, timedelta, timezone

from sensei.memory import (
    AgentMemoryRole,
    DecisionMemoryService,
    DerivedMemoryIndex,
    MemoryQualityEvaluator,
    MemoryQuery,
    RetrievalExpectation,
    RetrievalDataset,
    RetrievalBenchmarkRunner,
    ShadowRetrievalComparator,
)
from sensei.operations import EventAppend, OperationalJournal


NOW = datetime(2026, 7, 17, 10, 0, tzinfo=timezone.utc)


def _event(journal, event_type, key):
    return journal.append(
        EventAppend(
            stream_id=f"memory-quality:{key}",
            event_type=event_type,
            payload={"instrument_id": "NSE:INFY", "key": key},
            idempotency_key=f"memory-quality:{key}",
            expected_version=0,
            occurred_at=NOW,
        )
    )


def test_retrieval_quality_scores_relevance_and_counter_evidence(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3", clock=lambda: NOW)
    halted = _event(journal, "SchedulerTaskHalted", "halted")
    episode = _event(journal, "EpisodeStarted", "episode")
    expectation = RetrievalExpectation(
        query=MemoryQuery(
            role=AgentMemoryRole.ANALYST,
            as_of=NOW + timedelta(minutes=1),
            instrument_id="NSE:INFY",
        ),
        relevant_event_ids=frozenset({halted.event_id}),
        required_counter_evidence_ids=frozenset({halted.event_id}),
    )

    result = MemoryQualityEvaluator(DecisionMemoryService(journal)).evaluate(
        expectation
    )

    assert result.recall == 1.0
    assert result.precision == 0.5
    assert result.counter_evidence_recall == 1.0
    assert result.returned_event_ids == (halted.event_id, episode.event_id)


def test_graph_index_shadow_comparison_never_trusts_unknown_candidate_ids(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3", clock=lambda: NOW)
    halted = _event(journal, "SchedulerTaskHalted", "halted")
    episode = _event(journal, "EpisodeStarted", "episode")

    class Index(DerivedMemoryIndex):
        def candidate_source_ids(self, query):
            return (episode.event_id, "event:" + "f" * 64)

    comparison = ShadowRetrievalComparator(
        DecisionMemoryService(journal), Index()
    ).compare(
        RetrievalExpectation(
            query=MemoryQuery(
                role=AgentMemoryRole.ANALYST,
                as_of=NOW + timedelta(minutes=1),
                limit=1,
            ),
            relevant_event_ids=frozenset({halted.event_id}),
            required_counter_evidence_ids=frozenset({halted.event_id}),
        )
    )

    assert comparison.baseline.returned_event_ids == (halted.event_id,)
    assert comparison.indexed_candidate_ids == (episode.event_id,)
    assert comparison.unknown_candidate_ids == ("event:" + "f" * 64,)
    assert comparison.authority == "EVALUATION_ONLY"


def test_versioned_dataset_compares_structured_memory_to_no_memory(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3", clock=lambda: NOW)
    halted = _event(journal, "SchedulerTaskHalted", "dataset-halt")
    dataset = RetrievalDataset(
        dataset_id="desk-memory-regression",
        version="2026-07-17.v1",
        cases=(
            RetrievalExpectation(
                query=MemoryQuery(
                    role=AgentMemoryRole.ANALYST,
                    as_of=NOW + timedelta(minutes=1),
                ),
                relevant_event_ids=frozenset({halted.event_id}),
            ),
        ),
    )

    report = RetrievalBenchmarkRunner(DecisionMemoryService(journal)).run(dataset)

    assert report.version == "2026-07-17.v1"
    assert report.structured_average_recall == 1.0
    assert report.no_memory_average_recall == 0.0
