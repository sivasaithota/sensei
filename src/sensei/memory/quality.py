"""Offline retrieval evaluation and a non-authoritative derived-index seam."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import MemoryQuery
from .service import DecisionMemoryService


@dataclass(frozen=True)
class RetrievalExpectation:
    query: MemoryQuery
    relevant_event_ids: frozenset[str]
    required_counter_evidence_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.query, MemoryQuery):
            raise TypeError("query must be a MemoryQuery")
        if not self.relevant_event_ids:
            raise ValueError("retrieval expectation requires relevant events")
        if not self.required_counter_evidence_ids <= self.relevant_event_ids:
            raise ValueError("counter evidence must also be relevant")


@dataclass(frozen=True)
class MemoryQualityResult:
    returned_event_ids: tuple[str, ...]
    precision: float
    recall: float
    counter_evidence_recall: float
    authority: str = "EVALUATION_ONLY"


class MemoryQualityEvaluator:
    def __init__(self, memory: DecisionMemoryService) -> None:
        self._memory = memory

    def evaluate(self, expectation: RetrievalExpectation) -> MemoryQualityResult:
        items = self._memory.query(expectation.query).items
        returned = tuple(item.event_id for item in items)
        returned_set = set(returned)
        relevant = expectation.relevant_event_ids
        matched = len(returned_set & relevant)
        counters = expectation.required_counter_evidence_ids
        return MemoryQualityResult(
            returned_event_ids=returned,
            precision=round(matched / len(returned), 6) if returned else 0.0,
            recall=round(matched / len(relevant), 6),
            counter_evidence_recall=(
                round(len(returned_set & counters) / len(counters), 6)
                if counters
                else 1.0
            ),
        )


@dataclass(frozen=True)
class RetrievalDataset:
    dataset_id: str
    version: str
    cases: tuple[RetrievalExpectation, ...]

    def __post_init__(self) -> None:
        if not self.dataset_id.strip() or not self.version.strip() or not self.cases:
            raise ValueError("retrieval dataset requires identity, version and cases")


@dataclass(frozen=True)
class RetrievalBenchmarkReport:
    dataset_id: str
    version: str
    structured_results: tuple[MemoryQualityResult, ...]
    structured_average_recall: float
    no_memory_average_recall: float = 0.0
    authority: str = "EVALUATION_ONLY"


class RetrievalBenchmarkRunner:
    def __init__(self, memory: DecisionMemoryService) -> None:
        self._evaluator = MemoryQualityEvaluator(memory)

    def run(self, dataset: RetrievalDataset) -> RetrievalBenchmarkReport:
        if not isinstance(dataset, RetrievalDataset):
            raise TypeError("dataset must be a RetrievalDataset")
        results = tuple(self._evaluator.evaluate(case) for case in dataset.cases)
        return RetrievalBenchmarkReport(
            dataset_id=dataset.dataset_id,
            version=dataset.version,
            structured_results=results,
            structured_average_recall=round(
                sum(result.recall for result in results) / len(results), 6
            ),
        )


class DerivedMemoryIndex(Protocol):
    """A rebuildable candidate generator; it never returns trusted facts."""

    def candidate_source_ids(self, query: MemoryQuery) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class ShadowRetrievalComparison:
    baseline: MemoryQualityResult
    indexed_candidate_ids: tuple[str, ...]
    unknown_candidate_ids: tuple[str, ...]
    authority: str = "EVALUATION_ONLY"


class ShadowRetrievalComparator:
    """Compare an external index without allowing it into live context packs."""

    def __init__(
        self, memory: DecisionMemoryService, index: DerivedMemoryIndex
    ) -> None:
        self._memory = memory
        self._index = index

    def compare(self, expectation: RetrievalExpectation) -> ShadowRetrievalComparison:
        baseline = MemoryQualityEvaluator(self._memory).evaluate(expectation)
        candidates = tuple(dict.fromkeys(self._index.candidate_source_ids(
            expectation.query
        )))
        visible = {
            item.event_id
            for item in self._memory.resolve_candidate_source_ids(
                expectation.query, candidates
            )
        }
        return ShadowRetrievalComparison(
            baseline=baseline,
            indexed_candidate_ids=tuple(value for value in candidates if value in visible),
            unknown_candidate_ids=tuple(value for value in candidates if value not in visible),
        )
