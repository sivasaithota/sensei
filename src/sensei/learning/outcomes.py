"""Scoped observations and recurrence-gated mistake hypotheses."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from sensei.operations.journal import EventAppend, OperationalJournal


@dataclass(frozen=True)
class LearningScope:
    strategy_lineage_id: str
    plan_version_id: str
    timeframe: str
    market_regime: str
    failure_type: str

    def __post_init__(self) -> None:
        for label, value in (
            ("strategy_lineage_id", self.strategy_lineage_id),
            ("plan_version_id", self.plan_version_id),
            ("timeframe", self.timeframe),
            ("market_regime", self.market_regime),
            ("failure_type", self.failure_type),
        ):
            if not value or not isinstance(value, str):
                raise ValueError(f"{label} is required")

    @property
    def scope_id(self) -> str:
        return _hash(
            {
                "strategy_lineage_id": self.strategy_lineage_id,
                "plan_version_id": self.plan_version_id,
                "timeframe": self.timeframe,
                "market_regime": self.market_regime,
                "failure_type": self.failure_type,
            }
        )


@dataclass(frozen=True)
class LearningObservation:
    episode_id: str
    scope: LearningScope
    summary: str
    evidence_refs: tuple[str, ...]
    occurred_at: datetime

    def __post_init__(self) -> None:
        if not self.episode_id or not self.summary.strip():
            raise ValueError("episode_id and summary are required")
        if not self.evidence_refs or any(not reference for reference in self.evidence_refs):
            raise ValueError("at least one evidence reference is required")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("evidence references must be unique")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")


@dataclass(frozen=True)
class MistakeHypothesis:
    hypothesis_id: str
    scope: LearningScope
    evidence_episode_ids: tuple[str, ...]
    authority: str = "RESEARCH_ONLY"
    requires_examination: bool = True
    can_veto_trades: bool = False


class OutcomeLearner:
    """Forms research hypotheses; it has no trading or lifecycle authority."""

    def __init__(self, journal: OperationalJournal, *, minimum_recurrence: int = 3) -> None:
        if minimum_recurrence < 2:
            raise ValueError("minimum_recurrence must be at least two")
        self._journal = journal
        self._minimum_recurrence = minimum_recurrence

    def record(self, observation: LearningObservation, *, command_id: str):
        self._validate_evidence(observation)
        stream = _stream(observation.scope)
        events = self._journal.read_stream(stream)
        payload = {
            "episode_id": observation.episode_id,
            "scope": _scope_payload(observation.scope),
            "summary": observation.summary.strip(),
            "evidence_refs": list(observation.evidence_refs),
        }
        command = EventAppend(
            stream_id=stream,
            event_type="LearningObservationRecorded",
            payload=payload,
            idempotency_key=command_id,
            expected_version=len(events),
            occurred_at=observation.occurred_at,
            correlation_id=observation.episode_id,
        )
        if any(event.idempotency_key == command_id for event in events):
            return self._journal.append(command)
        existing_episode_ids = {
            str(event.payload["episode_id"])
            for event in events
            if event.event_type == "LearningObservationRecorded"
        }
        if observation.episode_id in existing_episode_ids:
            raise ValueError("an observation for this episode and scope already exists")
        return self._journal.append(command)

    def _validate_evidence(self, observation: LearningObservation) -> None:
        episode_events = self._journal.read_stream(
            f"episode:{observation.episode_id}"
        )
        if not episode_events or not any(
            event.event_type == "EpisodeClosed" for event in episode_events
        ):
            raise ValueError(
                "learning evidence must belong to a closed Trade Episode"
            )
        started = episode_events[0]
        if started.event_type != "EpisodeStarted":
            raise ValueError("Trade Episode has no authoritative start event")
        if (
            started.payload.get("strategy_lineage_id")
            != observation.scope.strategy_lineage_id
        ):
            raise ValueError("learning scope does not match the strategy lineage")
        if started.payload.get("plan_version_id") != observation.scope.plan_version_id:
            raise ValueError("learning scope does not match the plan version")
        if started.payload.get("timeframe") != observation.scope.timeframe:
            raise ValueError("learning scope does not match the episode timeframe")

        referenced = {
            event.event_id: event
            for event in episode_events
            if event.event_id in observation.evidence_refs
        }
        if set(referenced) != set(observation.evidence_refs):
            raise ValueError("learning evidence must belong to the Trade Episode")
        if any(
            event.occurred_at > observation.occurred_at
            for event in referenced.values()
        ):
            raise ValueError("learning evidence cannot postdate the observation")

        by_type = {event.event_type: event for event in referenced.values()}
        if not {"OutcomeAttributed", "ReviewRecorded"} <= set(by_type):
            raise ValueError(
                "learning requires outcome attribution and review evidence"
            )
        outcome = by_type["OutcomeAttributed"]
        if outcome.payload.get("reconciles") is not True:
            raise ValueError("learning requires a reconciled outcome attribution")
        review = by_type["ReviewRecorded"]
        if (
            review.payload.get("market_regime") != observation.scope.market_regime
            or review.payload.get("failure_type") != observation.scope.failure_type
        ):
            raise ValueError("learning scope does not match the recorded review")

    def propose(
        self, scope: LearningScope, *, command_id: str, now: datetime
    ) -> MistakeHypothesis | None:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        stream = _stream(scope)
        events = self._journal.read_stream(stream)
        proposed = next(
            (
                event
                for event in events
                if event.event_type == "MistakeHypothesisProposed"
            ),
            None,
        )
        if proposed is not None:
            return _hypothesis_from_payload(scope, proposed.payload)

        episode_ids = tuple(
            sorted(
                {
                    str(event.payload["episode_id"])
                    for event in events
                    if event.event_type == "LearningObservationRecorded"
                }
            )
        )
        if len(episode_ids) < self._minimum_recurrence:
            return None
        hypothesis_id = f"hypothesis:{_hash({'scope_id': scope.scope_id, 'episodes': episode_ids})}"
        event = self._journal.append(
            EventAppend(
                stream_id=stream,
                event_type="MistakeHypothesisProposed",
                payload={
                    "hypothesis_id": hypothesis_id,
                    "scope": _scope_payload(scope),
                    "evidence_episode_ids": list(episode_ids),
                    "authority": "RESEARCH_ONLY",
                    "requires_examination": True,
                    "can_veto_trades": False,
                },
                idempotency_key=command_id,
                expected_version=len(events),
                occurred_at=now,
            )
        )
        return _hypothesis_from_payload(scope, event.payload)


def _hypothesis_from_payload(scope: LearningScope, payload) -> MistakeHypothesis:
    return MistakeHypothesis(
        hypothesis_id=str(payload["hypothesis_id"]),
        scope=scope,
        evidence_episode_ids=tuple(str(value) for value in payload["evidence_episode_ids"]),
        authority=str(payload["authority"]),
        requires_examination=bool(payload["requires_examination"]),
        can_veto_trades=bool(payload["can_veto_trades"]),
    )


def _scope_payload(scope: LearningScope) -> dict[str, str | int]:
    return {
        "strategy_lineage_id": scope.strategy_lineage_id,
        "plan_version_id": scope.plan_version_id,
        "timeframe": scope.timeframe,
        "market_regime": scope.market_regime,
        "failure_type": scope.failure_type,
    }


def _stream(scope: LearningScope) -> str:
    return f"learning:{scope.scope_id}"


def _hash(value) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
