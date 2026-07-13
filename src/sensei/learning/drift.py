"""Version-pinned forward-performance drift assessment."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum

from sensei.operations.journal import EventAppend, OperationalJournal


class DriftState(str, Enum):
    UNKNOWN = "UNKNOWN"
    STABLE = "STABLE"
    DRIFTED = "DRIFTED"


@dataclass(frozen=True)
class DriftBaseline:
    plan_id: str
    plan_version: int
    mean_return: Decimal
    hit_rate: Decimal
    sample_size: int
    minimum_forward_samples: int
    maximum_mean_shift: Decimal
    maximum_hit_rate_shift: Decimal
    evidence_ref: str

    def __post_init__(self) -> None:
        if not self.plan_id or not self.evidence_ref:
            raise ValueError("plan_id and evidence_ref are required")
        if self.plan_version < 1 or self.sample_size < 1:
            raise ValueError("plan_version and sample_size must be positive")
        if self.minimum_forward_samples < 2:
            raise ValueError("minimum_forward_samples must be at least two")
        _finite(self.mean_return, "mean_return")
        hit_rate = _finite(self.hit_rate, "hit_rate")
        if not Decimal("0") <= hit_rate <= Decimal("1"):
            raise ValueError("hit_rate must be between zero and one")
        for label, value in (
            ("maximum_mean_shift", self.maximum_mean_shift),
            ("maximum_hit_rate_shift", self.maximum_hit_rate_shift),
        ):
            if _finite(value, label) < 0:
                raise ValueError(f"{label} must not be negative")

    @property
    def baseline_id(self) -> str:
        return _hash(
            {
                "plan_id": self.plan_id,
                "plan_version": self.plan_version,
                "mean_return": str(self.mean_return),
                "hit_rate": str(self.hit_rate),
                "sample_size": self.sample_size,
                "minimum_forward_samples": self.minimum_forward_samples,
                "maximum_mean_shift": str(self.maximum_mean_shift),
                "maximum_hit_rate_shift": str(self.maximum_hit_rate_shift),
                "evidence_ref": self.evidence_ref,
            }
        )


@dataclass(frozen=True)
class ForwardPerformance:
    plan_id: str
    plan_version: int
    episode_returns: tuple[Decimal, ...]

    def __post_init__(self) -> None:
        if not self.plan_id or self.plan_version < 1:
            raise ValueError("valid plan identity is required")
        for value in self.episode_returns:
            _finite(value, "episode return")


@dataclass(frozen=True)
class DriftAssessment:
    baseline_id: str
    state: DriftState
    forward_samples: int
    forward_mean_return: Decimal | None
    forward_hit_rate: Decimal | None
    action: str
    can_change_strategy: bool
    event_id: str


class DriftMonitor:
    """Detects evidence changes but cannot alter strategy lifecycle state."""

    def __init__(self, journal: OperationalJournal) -> None:
        self._journal = journal

    def assess(
        self,
        baseline: DriftBaseline,
        performance: ForwardPerformance,
        *,
        now: datetime,
        command_id: str,
    ) -> DriftAssessment:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if (performance.plan_id, performance.plan_version) != (
            baseline.plan_id,
            baseline.plan_version,
        ):
            raise ValueError("forward performance must match the exact plan version")
        count = len(performance.episode_returns)
        forward_mean: Decimal | None = None
        forward_hit_rate: Decimal | None = None
        if count < baseline.minimum_forward_samples:
            state = DriftState.UNKNOWN
            action = "COLLECT_MORE_EVIDENCE"
        else:
            forward_mean = sum(performance.episode_returns, Decimal("0")) / count
            wins = sum(1 for value in performance.episode_returns if value > 0)
            forward_hit_rate = Decimal(wins) / Decimal(count)
            mean_shift = abs(forward_mean - baseline.mean_return)
            hit_rate_shift = abs(forward_hit_rate - baseline.hit_rate)
            if (
                mean_shift > baseline.maximum_mean_shift
                or hit_rate_shift > baseline.maximum_hit_rate_shift
            ):
                state = DriftState.DRIFTED
                action = "REVIEW_ONLY"
            else:
                state = DriftState.STABLE
                action = "CONTINUE_MONITORING"

        stream = f"drift:{baseline.baseline_id}"
        events = self._journal.read_stream(stream)
        event = self._journal.append(
            EventAppend(
                stream_id=stream,
                event_type="DriftAssessed",
                payload={
                    "baseline_id": baseline.baseline_id,
                    "plan_id": baseline.plan_id,
                    "plan_version": baseline.plan_version,
                    "evidence_ref": baseline.evidence_ref,
                    "state": state.value,
                    "forward_samples": count,
                    "forward_mean_return": (
                        str(forward_mean) if forward_mean is not None else None
                    ),
                    "forward_hit_rate": (
                        str(forward_hit_rate) if forward_hit_rate is not None else None
                    ),
                    "action": action,
                    "can_change_strategy": False,
                },
                idempotency_key=command_id,
                expected_version=len(events),
                occurred_at=now,
            )
        )
        return DriftAssessment(
            baseline_id=baseline.baseline_id,
            state=state,
            forward_samples=count,
            forward_mean_return=forward_mean,
            forward_hit_rate=forward_hit_rate,
            action=action,
            can_change_strategy=False,
            event_id=event.event_id,
        )


def _finite(value: Decimal, label: str) -> Decimal:
    try:
        converted = Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{label} must be finite") from None
    if not converted.is_finite():
        raise ValueError(f"{label} must be finite")
    return converted


def _hash(value) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
