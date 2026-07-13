"""Read-only projection showing which desk roles actually ran."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sensei.operations import OperationalJournal


@dataclass(frozen=True)
class DeskCycleSummary:
    cycle_id: str
    status: str
    reason: str
    completed_at: datetime
    plan_id: str
    trace_id: str | None
    thesis_id: str | None
    intent_id: str | None
    completed_roles: tuple[str, ...]
    skipped_roles: tuple[str, ...]
    event_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "cycle_id": self.cycle_id,
            "status": self.status,
            "reason": self.reason,
            "completed_at": self.completed_at.isoformat(),
            "plan_id": self.plan_id,
            "trace_id": self.trace_id,
            "thesis_id": self.thesis_id,
            "intent_id": self.intent_id,
            "completed_roles": list(self.completed_roles),
            "skipped_roles": list(self.skipped_roles),
            "event_id": self.event_id,
        }


class DeskStatusReporter:
    def __init__(self, journal: OperationalJournal) -> None:
        self._journal = journal

    def latest(self, *, limit: int = 10) -> tuple[DeskCycleSummary, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        verification = self._journal.verify()
        if not verification.ok:
            raise RuntimeError("desk status requires an intact operational journal")
        all_events = self._journal.read_all()
        completed = [
            event
            for event in all_events
            if event.event_type in {"DeskCycleCompleted", "DeskCycleFailed"}
        ][-limit:]
        summaries: list[DeskCycleSummary] = []
        for event in reversed(completed):
            cycle_id = str(event.payload["cycle_id"])
            role_events = [
                candidate
                for candidate in all_events
                if candidate.correlation_id == cycle_id
                and candidate.event_type
                in {"DeskRoleCompleted", "DeskRoleSkipped"}
            ]
            started = next(
                candidate
                for candidate in all_events
                if candidate.correlation_id == cycle_id
                and candidate.event_type == "DeskCycleStarted"
            )
            failed = event.event_type == "DeskCycleFailed"
            historian = next(
                (
                    item
                    for item in role_events
                    if item.event_type == "DeskRoleCompleted"
                    and item.payload.get("role") == "historian"
                ),
                None,
            )
            summaries.append(
                DeskCycleSummary(
                    cycle_id=cycle_id,
                    status=(
                        "FAILED" if failed else str(event.payload["status"])
                    ),
                    reason=str(
                        event.payload["detail"]
                        if failed
                        else event.payload["reason"]
                    ),
                    completed_at=event.occurred_at,
                    plan_id=str(started.payload["plan_id"]),
                    trace_id=(
                        _optional(
                            historian.payload["details"].get("trace_id")
                            if historian is not None
                            else None
                        )
                        if failed
                        else str(event.payload["trace_id"])
                    ),
                    thesis_id=_optional(event.payload.get("thesis_id")),
                    intent_id=_optional(event.payload.get("intent_id")),
                    completed_roles=tuple(
                        str(item.payload["role"])
                        for item in role_events
                        if item.event_type == "DeskRoleCompleted"
                    ),
                    skipped_roles=tuple(
                        str(item.payload["role"])
                        for item in role_events
                        if item.event_type == "DeskRoleSkipped"
                    ),
                    event_id=event.event_id,
                )
            )
        return tuple(summaries)


def _optional(value: object) -> str | None:
    return None if value is None else str(value)
