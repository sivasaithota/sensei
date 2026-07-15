"""Generic unattended execution of due scheduler tasks.

The runner coordinates bounded handlers; it grants no strategy, safety, or
execution authority of its own. Each due task is independently terminal so a
failed or missed entry cannot suppress maintenance work that remains eligible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, Protocol

from sensei.operations.journal import JournalIntegrityError, OperationalJournal

from .scheduling import (
    ScheduleDecision,
    ScheduledTask,
    SchedulerHaltSource,
    SchedulerLedger,
    SchedulerTaskKind,
    SchedulerTaskRecord,
    SchedulerTaskState,
)


_REASON_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")
_EXCEPTION_TYPE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
_MAX_DETAIL_LENGTH = 1_000


class TaskOutcomeState(StrEnum):
    COMPLETED = "COMPLETED"
    HALTED = "HALTED"


@dataclass(frozen=True)
class TaskOutcome:
    state: TaskOutcomeState
    reason_codes: tuple[str, ...]
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.state, TaskOutcomeState):
            raise TypeError("state must be a TaskOutcomeState")
        reasons = tuple(self.reason_codes)
        if (
            not reasons
            or len(reasons) != len(set(reasons))
            or any(
                not isinstance(reason, str)
                or _REASON_CODE.fullmatch(reason) is None
                for reason in reasons
            )
        ):
            raise ValueError("reason_codes must be nonblank, bounded, and unique")
        if not isinstance(self.detail, str) or not self.detail.strip():
            raise ValueError("detail must be nonblank")
        detail = self.detail.strip()
        if len(detail) > _MAX_DETAIL_LENGTH:
            raise ValueError("detail exceeds the scheduler result limit")
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "detail", detail)

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "reason_codes": list(self.reason_codes),
            "detail": self.detail,
        }


class SchedulerTaskHandler(Protocol):
    def handle(self, task: ScheduledTask, *, now: datetime) -> TaskOutcome: ...


class SchedulerSessionPolicy(Protocol):
    def due_tasks(
        self,
        now: datetime,
        *,
        resolved_task_ids: set[str] | frozenset[str] = frozenset(),
    ) -> ScheduleDecision: ...


@dataclass(frozen=True)
class SchedulerTaskRunResult:
    task: ScheduledTask
    outcome: TaskOutcome
    replayed: bool
    event_ids: tuple[str, ...]
    halt_source: SchedulerHaltSource | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "task": self.task.to_payload(),
            "outcome": self.outcome.to_dict(),
            "replayed": self.replayed,
            "event_ids": list(self.event_ids),
            "halt_source": self.halt_source.value if self.halt_source else None,
        }


@dataclass(frozen=True)
class SchedulerRunResult:
    schedule: ScheduleDecision
    task_results: tuple[SchedulerTaskRunResult, ...] = ()
    in_progress_task_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        result_ids = tuple(item.task.task_id for item in self.task_results)
        if len(result_ids) != len(set(result_ids)):
            raise ValueError("scheduler task results must be unique")
        if len(self.in_progress_task_ids) != len(set(self.in_progress_task_ids)):
            raise ValueError("in-progress task identities must be unique")
        if set(result_ids) & set(self.in_progress_task_ids):
            raise ValueError("a task cannot be terminal and in progress")

    def to_dict(self) -> dict[str, object]:
        return {
            "schedule": self.schedule.to_dict(),
            "task_results": [item.to_dict() for item in self.task_results],
            "in_progress_task_ids": list(self.in_progress_task_ids),
        }


class UnattendedSchedulerRunner:
    """Verify, calculate, claim, dispatch, and persist one scheduler wakeup."""

    def __init__(
        self,
        *,
        journal: OperationalJournal,
        policy: SchedulerSessionPolicy,
        handlers: Mapping[SchedulerTaskKind, SchedulerTaskHandler],
        ledger: SchedulerLedger | None = None,
    ) -> None:
        configured = set(handlers)
        required = set(SchedulerTaskKind)
        if configured != required:
            missing = sorted(item.value for item in required - configured)
            extra = sorted(str(item) for item in configured - required)
            raise ValueError(
                f"scheduler handlers must exactly cover task kinds; "
                f"missing={missing}, extra={extra}"
            )
        for kind, handler in handlers.items():
            if not callable(getattr(handler, "handle", None)):
                raise TypeError(f"handler for {kind.value} must implement handle")
        selected_ledger = ledger or SchedulerLedger(journal)
        if not selected_ledger.is_bound_to_journal(journal):
            raise ValueError("scheduler ledger must use the runner journal")
        self._journal = journal
        self._policy = policy
        self._handlers = MappingProxyType(dict(handlers))
        self._ledger = selected_ledger

    def run_once(self, now: datetime) -> SchedulerRunResult:
        _aware(now)
        verification = self._journal.verify()
        if not verification.ok:
            raise JournalIntegrityError(
                "scheduler runner requires journal integrity"
            )

        resolved = self._ledger.resolved_task_ids()
        schedule = self._policy.due_tasks(
            now,
            resolved_task_ids=resolved,
        )
        # A second, unfiltered calculation identifies terminal work from this
        # same instant so retries return durable outcomes instead of rerunning.
        availability = self._policy.due_tasks(now)
        results: list[SchedulerTaskRunResult] = []
        in_progress: list[str] = []

        for missed in availability.halts:
            current = self._ledger.record(missed.task.task_id)
            if current is None:
                current = self._ledger.halt(
                    missed.task,
                    reason=missed.reason,
                    occurred_at=now,
                    detail="scheduled task window expired before execution",
                )
                replayed = False
            elif current.state is SchedulerTaskState.CLAIMED:
                in_progress.append(missed.task.task_id)
                continue
            else:
                replayed = True
            results.append(_terminal_result(current, replayed=replayed))

        for task in availability.tasks:
            claim = self._ledger.claim(task, occurred_at=now)
            if not claim.acquired:
                current = self._ledger.record(task.task_id) or claim.record
                if current.state is SchedulerTaskState.CLAIMED:
                    in_progress.append(task.task_id)
                    continue
                results.append(_terminal_result(current, replayed=True))
                continue

            claimant_id = claim.record.claimant_id
            if claimant_id is None:  # impossible for an acquired claim
                raise JournalIntegrityError("acquired scheduler claim has no owner")
            outcome = self._invoke(task, now=now)
            if outcome.state is TaskOutcomeState.COMPLETED:
                terminal = self._ledger.complete(
                    task.task_id,
                    claimant_id=claimant_id,
                    occurred_at=now,
                    reason_codes=outcome.reason_codes,
                    detail=outcome.detail,
                )
            else:
                terminal = self._ledger.halt_claimed(
                    task.task_id,
                    claimant_id=claimant_id,
                    occurred_at=now,
                    reason_codes=outcome.reason_codes,
                    detail=outcome.detail,
                )
            results.append(_terminal_result(terminal, replayed=False))

        return SchedulerRunResult(
            schedule=schedule,
            task_results=tuple(results),
            in_progress_task_ids=tuple(in_progress),
        )

    def _invoke(self, task: ScheduledTask, *, now: datetime) -> TaskOutcome:
        try:
            outcome = self._handlers[task.kind].handle(task, now=now)
            if not isinstance(outcome, TaskOutcome):
                raise TypeError("handler did not return TaskOutcome")
            return outcome
        except Exception as exc:
            exception_type = type(exc).__name__
            if _EXCEPTION_TYPE.fullmatch(exception_type) is None:
                exception_type = "Exception"
            return TaskOutcome(
                state=TaskOutcomeState.HALTED,
                reason_codes=("TASK_HANDLER_FAILED",),
                detail=f"handler raised {exception_type}",
            )


def _terminal_result(
    record: SchedulerTaskRecord,
    *,
    replayed: bool,
) -> SchedulerTaskRunResult:
    if record.state not in (
        SchedulerTaskState.COMPLETED,
        SchedulerTaskState.HALTED,
    ):
        raise ValueError("scheduler task record is not terminal")
    if not record.reason_codes or record.detail is None:
        raise JournalIntegrityError("terminal scheduler result is incomplete")
    outcome = TaskOutcome(
        state=(
            TaskOutcomeState.COMPLETED
            if record.state is SchedulerTaskState.COMPLETED
            else TaskOutcomeState.HALTED
        ),
        reason_codes=record.reason_codes,
        detail=record.detail,
    )
    return SchedulerTaskRunResult(
        task=record.task,
        outcome=outcome,
        replayed=replayed,
        event_ids=record.event_ids,
        halt_source=record.halt_source,
    )


def _aware(value: datetime) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("scheduler run time must be timezone-aware")
