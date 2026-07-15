"""Read-only projection of research lab verdicts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sensei.operations import OperationalJournal


@dataclass(frozen=True)
class ResearchLabSummary:
    coach_hypothesis_id: str
    candidate_hypothesis_id: str
    recommendation: str
    shadow_eligible: bool
    experiment_id: str
    registration_id: str
    trades: int
    expectancy_pct: float | None
    hit_rate: float | None
    completed_at: datetime
    event_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "coach_hypothesis_id": self.coach_hypothesis_id,
            "candidate_hypothesis_id": self.candidate_hypothesis_id,
            "recommendation": self.recommendation,
            "shadow_eligible": self.shadow_eligible,
            "experiment_id": self.experiment_id,
            "registration_id": self.registration_id,
            "trades": self.trades,
            "expectancy_pct": self.expectancy_pct,
            "hit_rate": self.hit_rate,
            "completed_at": self.completed_at.isoformat(),
            "event_id": self.event_id,
        }


class ResearchLabReporter:
    def __init__(self, journal: OperationalJournal) -> None:
        self._journal = journal

    def latest(self, *, limit: int = 10) -> tuple[ResearchLabSummary, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        verification = self._journal.verify()
        if not verification.ok:
            raise RuntimeError("research lab status requires an intact journal")
        events = [
            event
            for event in self._journal.read_all()
            if event.event_type == "ResearchLabDossierRecorded"
        ][-limit:]
        return tuple(_summary(event) for event in reversed(events))


def _summary(event) -> ResearchLabSummary:
    aggregate = event.payload.get("aggregate")
    if not isinstance(aggregate, Mapping):
        raise ValueError("research lab event has no aggregate evidence")
    shadow_eligible = event.payload["shadow_eligible"]
    if type(shadow_eligible) is not bool:
        raise ValueError("research lab shadow_eligible must be a bool")
    return ResearchLabSummary(
        coach_hypothesis_id=str(event.payload["coach_hypothesis_id"]),
        candidate_hypothesis_id=str(event.payload["candidate_hypothesis_id"]),
        recommendation=str(event.payload["recommendation"]),
        shadow_eligible=shadow_eligible,
        experiment_id=str(event.payload["experiment_id"]),
        registration_id=str(event.payload["registration_id"]),
        trades=int(aggregate["trades"]),
        expectancy_pct=_optional_float(aggregate.get("expectancy_pct")),
        hit_rate=_optional_float(aggregate.get("hit_rate")),
        completed_at=event.occurred_at,
        event_id=event.event_id,
    )


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)
