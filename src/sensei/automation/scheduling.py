"""Point-in-time session policy and an idempotent scheduler task ledger.

This module decides *when* bounded work is eligible and durably coordinates a
task identity.  It deliberately does not decide which strategies may trade,
construct a Desk runtime, clear safety controls, or call an execution gateway.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum
from typing import Mapping
from zoneinfo import ZoneInfo

from sensei.operations.journal import (
    EventAppend,
    JournalConflict,
    JournalEvent,
    JournalIntegrityError,
    OperationalJournal,
)


INDIA_TIMEZONE = "Asia/Kolkata"
_IST = ZoneInfo(INDIA_TIMEZONE)
_TASK_ID = re.compile(r"scheduled-task:([0-9a-f]{64})\Z")
_CLAIMANT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_REASON_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")
_MAX_DETAIL_LENGTH = 1_000


class SchedulerTaskKind(StrEnum):
    """Bounded jobs which a production composition root may implement."""

    ENTRY_SESSION = "ENTRY_SESSION"
    END_OF_DAY_SESSION = "END_OF_DAY_SESSION"


class ScheduleState(StrEnum):
    """Overall result of one point-in-time due-work calculation."""

    DUE = "DUE"
    DUE_WITH_HALTS = "DUE_WITH_HALTS"
    NO_WORK = "NO_WORK"
    HALTED = "HALTED"


class SchedulerNoWorkReason(StrEnum):
    NOT_TRADING_DAY = "NOT_TRADING_DAY"
    BEFORE_FIRST_WINDOW = "BEFORE_FIRST_WINDOW"
    NO_TASK_DUE = "NO_TASK_DUE"
    ALREADY_RESOLVED = "ALREADY_RESOLVED"


class SchedulerHaltReason(StrEnum):
    """Fail-closed task outcomes; none of these permits a late entry."""

    MISSED_ENTRY_WINDOW = "MISSED_ENTRY_WINDOW"
    MISSED_END_OF_DAY_WINDOW = "MISSED_END_OF_DAY_WINDOW"


class SchedulerHaltSource(StrEnum):
    WINDOW = "WINDOW"
    HANDLER = "HANDLER"


class SchedulerTaskState(StrEnum):
    CLAIMED = "CLAIMED"
    COMPLETED = "COMPLETED"
    HALTED = "HALTED"


@dataclass(frozen=True)
class ScheduledTask:
    task_id: str
    kind: SchedulerTaskKind
    trading_date: date
    due_at: datetime
    expires_at: datetime
    policy_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SchedulerTaskKind):
            raise TypeError("kind must be a SchedulerTaskKind")
        if type(self.trading_date) is not date:
            raise TypeError("trading_date must be a date")
        _aware("due_at", self.due_at)
        _aware("expires_at", self.expires_at)
        if self.expires_at < self.due_at:
            raise ValueError("task expiry cannot precede its due time")
        if self.due_at.astimezone(_IST).date() != self.trading_date:
            raise ValueError("task due time does not belong to its trading date")
        if not isinstance(self.policy_version, str) or not self.policy_version.strip():
            raise ValueError("policy_version is required")
        expected = scheduled_task_id(
            kind=self.kind,
            trading_date=self.trading_date,
            policy_version=self.policy_version,
        )
        if self.task_id != expected:
            raise ValueError("task_id does not match the task content")

    def to_payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "kind": self.kind.value,
            "trading_date": self.trading_date.isoformat(),
            "due_at": self.due_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "policy_version": self.policy_version,
        }


@dataclass(frozen=True)
class ScheduledTaskHalt:
    task: ScheduledTask
    reason: SchedulerHaltReason

    def to_payload(self) -> dict[str, object]:
        return {"task": self.task.to_payload(), "reason": self.reason.value}


@dataclass(frozen=True)
class ScheduleDecision:
    state: ScheduleState
    evaluated_at: datetime
    trading_date: date
    tasks: tuple[ScheduledTask, ...] = ()
    halts: tuple[ScheduledTaskHalt, ...] = ()
    no_work_reason: SchedulerNoWorkReason | None = None

    def __post_init__(self) -> None:
        _aware("evaluated_at", self.evaluated_at)
        if type(self.trading_date) is not date:
            raise TypeError("trading_date must be a date")
        if self.evaluated_at.astimezone(_IST).date() != self.trading_date:
            raise ValueError("evaluation time does not belong to trading_date")
        if len({task.task_id for task in self.tasks}) != len(self.tasks):
            raise ValueError("due task identities must be unique")
        if len({halt.task.task_id for halt in self.halts}) != len(self.halts):
            raise ValueError("halted task identities must be unique")
        if {task.task_id for task in self.tasks} & {
            halt.task.task_id for halt in self.halts
        }:
            raise ValueError("a task cannot be both due and halted")
        if self.state is ScheduleState.DUE and (not self.tasks or self.halts):
            raise ValueError("DUE requires work and no task halt")
        if self.state is ScheduleState.DUE_WITH_HALTS and (
            not self.tasks or not self.halts
        ):
            raise ValueError("DUE_WITH_HALTS requires work and a task halt")
        if self.state is ScheduleState.HALTED and (
            self.tasks or not self.halts or self.no_work_reason is not None
        ):
            raise ValueError("HALTED requires only halt results")
        if self.state is ScheduleState.NO_WORK and (
            self.tasks or self.halts or self.no_work_reason is None
        ):
            raise ValueError("NO_WORK requires one explicit no-work reason")
        if self.state is not ScheduleState.NO_WORK and self.no_work_reason is not None:
            raise ValueError("only NO_WORK may carry a no-work reason")

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "evaluated_at": self.evaluated_at.isoformat(),
            "trading_date": self.trading_date.isoformat(),
            "tasks": [task.to_payload() for task in self.tasks],
            "halts": [halt.to_payload() for halt in self.halts],
            "no_work_reason": (
                self.no_work_reason.value
                if self.no_work_reason is not None
                else None
            ),
        }


@dataclass(frozen=True)
class _TaskWindow:
    kind: SchedulerTaskKind
    opens_at: time
    closes_at: time
    missed_reason: SchedulerHaltReason


class SwingSessionPolicy:
    """Asia/Kolkata weekday policy for bounded swing-paper tasks.

    Exchange holidays can be supplied as ``closed_dates``.  An entry is never
    made up after its window; later maintenance can remain due independently.
    """

    def __init__(
        self,
        *,
        policy_version: str = "india-swing-paper-v1",
        entry_at: time = time(9, 20),
        entry_cutoff: time = time(9, 35),
        end_of_day_at: time = time(18, 30),
        end_of_day_cutoff: time = time(23, 55),
        closed_dates: frozenset[date] = frozenset(),
    ) -> None:
        if not isinstance(policy_version, str) or not policy_version.strip():
            raise ValueError("policy_version is required")
        for label, value in (
            ("entry_at", entry_at),
            ("entry_cutoff", entry_cutoff),
            ("end_of_day_at", end_of_day_at),
            ("end_of_day_cutoff", end_of_day_cutoff),
        ):
            if not isinstance(value, time) or value.tzinfo is not None:
                raise ValueError(f"{label} must be a timezone-naive wall-clock time")
        if not entry_at < entry_cutoff < end_of_day_at < end_of_day_cutoff:
            raise ValueError("session task windows must be ordered and non-overlapping")
        if any(type(item) is not date for item in closed_dates):
            raise TypeError("closed_dates must contain dates")
        self.policy_version = policy_version.strip()
        self.closed_dates = frozenset(closed_dates)
        self._windows = (
            _TaskWindow(
                SchedulerTaskKind.ENTRY_SESSION,
                entry_at,
                entry_cutoff,
                SchedulerHaltReason.MISSED_ENTRY_WINDOW,
            ),
            _TaskWindow(
                SchedulerTaskKind.END_OF_DAY_SESSION,
                end_of_day_at,
                end_of_day_cutoff,
                SchedulerHaltReason.MISSED_END_OF_DAY_WINDOW,
            ),
        )

    def is_trading_day(self, trading_date: date) -> bool:
        if type(trading_date) is not date:
            raise TypeError("trading_date must be a date")
        return trading_date.weekday() < 5 and trading_date not in self.closed_dates

    def due_tasks(
        self,
        now: datetime,
        *,
        resolved_task_ids: set[str] | frozenset[str] = frozenset(),
    ) -> ScheduleDecision:
        """Calculate eligible work from one trusted, timezone-aware instant."""

        _aware("now", now)
        if any(
            not isinstance(task_id, str) or _TASK_ID.fullmatch(task_id) is None
            for task_id in resolved_task_ids
        ):
            raise ValueError("resolved_task_ids contains an invalid identity")
        local_now = now.astimezone(_IST)
        trading_date = local_now.date()
        if not self.is_trading_day(trading_date):
            return ScheduleDecision(
                state=ScheduleState.NO_WORK,
                evaluated_at=now,
                trading_date=trading_date,
                no_work_reason=SchedulerNoWorkReason.NOT_TRADING_DAY,
            )

        due: list[ScheduledTask] = []
        halted: list[ScheduledTaskHalt] = []
        resolved_available = False
        for window in self._windows:
            task = self._task(window, trading_date)
            if task.task_id in resolved_task_ids:
                if local_now >= task.due_at:
                    resolved_available = True
                continue
            if local_now < task.due_at:
                continue
            if local_now <= task.expires_at:
                due.append(task)
            else:
                halted.append(ScheduledTaskHalt(task, window.missed_reason))

        if due and halted:
            state = ScheduleState.DUE_WITH_HALTS
        elif due:
            state = ScheduleState.DUE
        elif halted:
            state = ScheduleState.HALTED
        else:
            first_due = self._task(self._windows[0], trading_date).due_at
            if local_now < first_due:
                no_work = SchedulerNoWorkReason.BEFORE_FIRST_WINDOW
            elif resolved_available:
                no_work = SchedulerNoWorkReason.ALREADY_RESOLVED
            else:
                no_work = SchedulerNoWorkReason.NO_TASK_DUE
            return ScheduleDecision(
                state=ScheduleState.NO_WORK,
                evaluated_at=now,
                trading_date=trading_date,
                no_work_reason=no_work,
            )
        return ScheduleDecision(
            state=state,
            evaluated_at=now,
            trading_date=trading_date,
            tasks=tuple(due),
            halts=tuple(halted),
        )

    def _task(self, window: _TaskWindow, trading_date: date) -> ScheduledTask:
        due_at = datetime.combine(trading_date, window.opens_at, tzinfo=_IST)
        expires_at = datetime.combine(trading_date, window.closes_at, tzinfo=_IST)
        return ScheduledTask(
            task_id=scheduled_task_id(
                kind=window.kind,
                trading_date=trading_date,
                policy_version=self.policy_version,
            ),
            kind=window.kind,
            trading_date=trading_date,
            due_at=due_at,
            expires_at=expires_at,
            policy_version=self.policy_version,
        )


def scheduled_task_id(
    *,
    kind: SchedulerTaskKind,
    trading_date: date,
    policy_version: str,
) -> str:
    """Return a stable task identity independent of process and wall-clock retry."""

    if not isinstance(kind, SchedulerTaskKind):
        raise TypeError("kind must be a SchedulerTaskKind")
    if type(trading_date) is not date:
        raise TypeError("trading_date must be a date")
    if not isinstance(policy_version, str) or not policy_version.strip():
        raise ValueError("policy_version is required")
    material = json.dumps(
        {
            "kind": kind.value,
            "policy_version": policy_version.strip(),
            "timezone": INDIA_TIMEZONE,
            "trading_date": trading_date.isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "scheduled-task:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SchedulerTaskRecord:
    task: ScheduledTask
    state: SchedulerTaskState
    claimant_id: str | None
    claimed_at: datetime | None
    terminal_at: datetime | None
    detail: str | None
    halt_reason: SchedulerHaltReason | None
    reason_codes: tuple[str, ...]
    halt_source: SchedulerHaltSource | None
    event_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "task": self.task.to_payload(),
            "state": self.state.value,
            "claimant_id": self.claimant_id,
            "claimed_at": self.claimed_at.isoformat() if self.claimed_at else None,
            "terminal_at": (
                self.terminal_at.isoformat() if self.terminal_at else None
            ),
            "detail": self.detail,
            "halt_reason": self.halt_reason.value if self.halt_reason else None,
            "reason_codes": list(self.reason_codes),
            "halt_source": self.halt_source.value if self.halt_source else None,
            "event_ids": list(self.event_ids),
        }


@dataclass(frozen=True)
class SchedulerClaimResult:
    record: SchedulerTaskRecord
    acquired: bool
    replayed: bool


class SchedulerLedger:
    """Journal-backed single-claim and terminal result projection per task."""

    def __init__(self, journal: OperationalJournal) -> None:
        self._journal = journal

    def is_bound_to_journal(self, journal: OperationalJournal) -> bool:
        """Return whether scheduler coordination uses this exact journal."""

        return self._journal is journal

    @staticmethod
    def stream_id(task_id: str) -> str:
        match = _TASK_ID.fullmatch(task_id)
        if match is None:
            raise ValueError("invalid scheduled task identity")
        return f"scheduler:task:{match.group(1)}"

    def claim(
        self,
        task: ScheduledTask,
        *,
        occurred_at: datetime,
    ) -> SchedulerClaimResult:
        _aware("occurred_at", occurred_at)
        if occurred_at < task.due_at or occurred_at > task.expires_at:
            raise ValueError("a task may be claimed only inside its eligible window")
        stream = self.stream_id(task.task_id)
        existing = self._journal.read_stream(stream)
        if existing:
            return SchedulerClaimResult(
                record=_project(existing),
                acquired=False,
                replayed=True,
            )
        # Every invocation gets a distinct contender identity. If two processes
        # race, the journal's task-derived idempotency key admits only one
        # payload; the loser projects the winner and must not execute the task.
        claimant_id = f"scheduler-run:{uuid.uuid4().hex}"
        try:
            event = self._journal.append(
                EventAppend(
                    stream_id=stream,
                    event_type="SchedulerTaskClaimed",
                    payload={
                        "task": task.to_payload(),
                        "claimant_id": claimant_id,
                        "authority": "SCHEDULER_COORDINATION_ONLY",
                    },
                    idempotency_key=_event_key("claim", task.task_id),
                    expected_version=0,
                    occurred_at=occurred_at,
                    correlation_id=task.task_id,
                )
            )
        except (JournalConflict, JournalIntegrityError):
            raced = self._journal.read_stream(stream)
            if not raced:
                raise
            return SchedulerClaimResult(
                record=_project(raced),
                acquired=False,
                replayed=True,
            )
        return SchedulerClaimResult(
            record=_project((event,)),
            acquired=True,
            replayed=False,
        )

    def complete(
        self,
        task_id: str,
        *,
        claimant_id: str,
        occurred_at: datetime,
        detail: str,
        reason_codes: tuple[str, ...] = ("TASK_COMPLETED",),
    ) -> SchedulerTaskRecord:
        _claimant(claimant_id)
        _aware("occurred_at", occurred_at)
        normalized_detail = _detail(detail)
        normalized_reasons = _reason_code_tuple(reason_codes)
        stream = self.stream_id(task_id)
        events = self._journal.read_stream(stream)
        if not events:
            raise RuntimeError("task must be claimed before completion")
        current = _project(events)
        if current.state is SchedulerTaskState.COMPLETED:
            if (
                current.claimant_id == claimant_id
                and current.terminal_at == occurred_at
                and current.detail == normalized_detail
                and current.reason_codes == normalized_reasons
            ):
                return current
            raise RuntimeError("task is already completed with a different result")
        if current.state is SchedulerTaskState.HALTED:
            raise RuntimeError("a halted task cannot be completed")
        if current.claimant_id != claimant_id:
            raise PermissionError("only the task claimant may complete it")
        if current.claimed_at is not None and occurred_at < current.claimed_at:
            raise ValueError("completion cannot predate the claim")
        event = self._journal.append(
            EventAppend(
                stream_id=stream,
                event_type="SchedulerTaskCompleted",
                payload={
                    "task_id": task_id,
                    "claimant_id": claimant_id,
                    "detail": normalized_detail,
                    "reason_codes": normalized_reasons,
                },
                idempotency_key=_event_key("complete", task_id),
                expected_version=len(events),
                occurred_at=occurred_at,
                correlation_id=task_id,
                causation_id=events[0].event_id,
            )
        )
        return _project((*events, event))

    def halt(
        self,
        task: ScheduledTask,
        *,
        reason: SchedulerHaltReason,
        occurred_at: datetime,
        detail: str,
        claimant_id: str | None = None,
    ) -> SchedulerTaskRecord:
        if not isinstance(reason, SchedulerHaltReason):
            raise TypeError("reason must be a SchedulerHaltReason")
        _aware("occurred_at", occurred_at)
        expected_reason = _missed_reason(task.kind)
        if reason is not expected_reason:
            raise ValueError("halt reason does not match the scheduled task kind")
        if occurred_at <= task.expires_at:
            raise ValueError("a missed-window halt requires an expired task")
        normalized_detail = _detail(detail)
        if claimant_id is not None:
            _claimant(claimant_id)
        stream = self.stream_id(task.task_id)
        events = self._journal.read_stream(stream)
        if events:
            current = _project(events)
            if current.state is SchedulerTaskState.HALTED:
                if (
                    current.halt_reason is reason
                    and current.terminal_at == occurred_at
                    and current.detail == normalized_detail
                ):
                    return current
                raise RuntimeError("task is already halted with a different result")
            if current.state is SchedulerTaskState.COMPLETED:
                raise RuntimeError("a completed task cannot be halted")
            if claimant_id != current.claimant_id:
                raise PermissionError("only the task claimant may halt claimed work")
            payload: dict[str, object] = {
                "task_id": task.task_id,
                "claimant_id": claimant_id,
                "reason": reason.value,
                "reason_codes": (reason.value,),
                "halt_source": SchedulerHaltSource.WINDOW.value,
                "detail": normalized_detail,
            }
            causation_id = events[0].event_id
        else:
            if claimant_id is not None:
                raise RuntimeError("unclaimed missed work must not name a claimant")
            payload = {
                "task": task.to_payload(),
                "claimant_id": None,
                "reason": reason.value,
                "reason_codes": (reason.value,),
                "halt_source": SchedulerHaltSource.WINDOW.value,
                "detail": normalized_detail,
            }
            causation_id = None
        event = self._journal.append(
            EventAppend(
                stream_id=stream,
                event_type="SchedulerTaskHalted",
                payload=payload,
                idempotency_key=_event_key("halt", task.task_id),
                expected_version=len(events),
                occurred_at=occurred_at,
                correlation_id=task.task_id,
                causation_id=causation_id,
            )
        )
        return _project((*events, event))

    def halt_claimed(
        self,
        task_id: str,
        *,
        claimant_id: str,
        occurred_at: datetime,
        reason_codes: tuple[str, ...],
        detail: str,
    ) -> SchedulerTaskRecord:
        """Halt acquired work without pretending its task window expired."""

        _claimant(claimant_id)
        _aware("occurred_at", occurred_at)
        normalized_reasons = _reason_code_tuple(reason_codes)
        normalized_detail = _detail(detail)
        stream = self.stream_id(task_id)
        events = self._journal.read_stream(stream)
        if not events:
            raise RuntimeError("task must be claimed before a handler halt")
        current = _project(events)
        if current.state is SchedulerTaskState.HALTED:
            if (
                current.claimant_id == claimant_id
                and current.terminal_at == occurred_at
                and current.reason_codes == normalized_reasons
                and current.detail == normalized_detail
                and current.halt_source is SchedulerHaltSource.HANDLER
            ):
                return current
            raise RuntimeError("task is already halted with a different result")
        if current.state is SchedulerTaskState.COMPLETED:
            raise RuntimeError("a completed task cannot be halted")
        if current.claimant_id != claimant_id:
            raise PermissionError("only the task claimant may halt handler work")
        if current.claimed_at is not None and occurred_at < current.claimed_at:
            raise ValueError("handler halt cannot predate the claim")
        event = self._journal.append(
            EventAppend(
                stream_id=stream,
                event_type="SchedulerTaskHalted",
                payload={
                    "task_id": task_id,
                    "claimant_id": claimant_id,
                    "reason_codes": normalized_reasons,
                    "halt_source": SchedulerHaltSource.HANDLER.value,
                    "detail": normalized_detail,
                },
                idempotency_key=_event_key("handler-halt", task_id),
                expected_version=len(events),
                occurred_at=occurred_at,
                correlation_id=task_id,
                causation_id=events[0].event_id,
            )
        )
        return _project((*events, event))

    def record(self, task_id: str) -> SchedulerTaskRecord | None:
        events = self._journal.read_stream(self.stream_id(task_id))
        return _project(events) if events else None

    def resolved_task_ids(self) -> frozenset[str]:
        resolved: set[str] = set()
        streams: dict[str, list[JournalEvent]] = {}
        for event in self._journal.read_all():
            if not event.stream_id.startswith("scheduler:task:"):
                continue
            streams.setdefault(event.stream_id, []).append(event)
        for events in streams.values():
            record = _project(tuple(events))
            if record.state in (
                SchedulerTaskState.COMPLETED,
                SchedulerTaskState.HALTED,
            ):
                resolved.add(record.task.task_id)
        return frozenset(resolved)


def _project(events: tuple[JournalEvent, ...]) -> SchedulerTaskRecord:
    if not events:
        raise ValueError("scheduler task stream is empty")
    first = events[0]
    if first.stream_sequence != 1 or first.event_type not in {
        "SchedulerTaskClaimed",
        "SchedulerTaskHalted",
    }:
        raise JournalIntegrityError("invalid scheduler task stream prefix")
    first_payload = first.payload
    task_value = first_payload.get("task")
    if not isinstance(task_value, Mapping):
        raise JournalIntegrityError("scheduler task prefix is missing task content")
    task = _task_from_payload(task_value)
    if SchedulerLedger.stream_id(task.task_id) != first.stream_id:
        raise JournalIntegrityError("scheduler stream does not match task identity")

    claimant_value = first_payload.get("claimant_id")
    claimant_id = str(claimant_value) if claimant_value is not None else None
    if claimant_id is not None:
        _claimant(claimant_id)
    claimed_at = (
        first.occurred_at
        if first.event_type == "SchedulerTaskClaimed"
        else None
    )
    state = (
        SchedulerTaskState.CLAIMED
        if first.event_type == "SchedulerTaskClaimed"
        else SchedulerTaskState.HALTED
    )
    terminal_at = first.occurred_at if state is SchedulerTaskState.HALTED else None
    detail = (
        str(first_payload.get("detail"))
        if state is SchedulerTaskState.HALTED
        else None
    )
    halt_reason = (
        SchedulerHaltReason(str(first_payload.get("reason")))
        if state is SchedulerTaskState.HALTED
        else None
    )
    reason_codes = (
        _reason_code_tuple(
            tuple(
                first_payload.get(
                    "reason_codes",
                    (str(first_payload.get("reason")),),
                )
            )
        )
        if state is SchedulerTaskState.HALTED
        else ()
    )
    halt_source = (
        SchedulerHaltSource(str(first_payload.get("halt_source", "WINDOW")))
        if state is SchedulerTaskState.HALTED
        else None
    )

    if len(events) > 2:
        raise JournalIntegrityError("scheduler task has more than one terminal result")
    if len(events) == 2:
        terminal = events[1]
        if state is not SchedulerTaskState.CLAIMED or terminal.stream_sequence != 2:
            raise JournalIntegrityError("invalid scheduler task transition")
        if terminal.payload.get("task_id") != task.task_id:
            raise JournalIntegrityError("terminal result names a different task")
        if terminal.payload.get("claimant_id") != claimant_id:
            raise JournalIntegrityError("terminal result names a different claimant")
        terminal_at = terminal.occurred_at
        detail = str(terminal.payload.get("detail"))
        if terminal.event_type == "SchedulerTaskCompleted":
            state = SchedulerTaskState.COMPLETED
            reason_codes = _reason_code_tuple(
                tuple(terminal.payload.get("reason_codes", ("TASK_COMPLETED",)))
            )
        elif terminal.event_type == "SchedulerTaskHalted":
            state = SchedulerTaskState.HALTED
            reason_codes = _reason_code_tuple(
                tuple(terminal.payload.get("reason_codes", ()))
            )
            halt_source = SchedulerHaltSource(
                str(terminal.payload.get("halt_source"))
            )
            reason_value = terminal.payload.get("reason")
            halt_reason = (
                SchedulerHaltReason(str(reason_value))
                if reason_value is not None
                else None
            )
        else:
            raise JournalIntegrityError("unknown scheduler terminal event")

    return SchedulerTaskRecord(
        task=task,
        state=state,
        claimant_id=claimant_id,
        claimed_at=claimed_at,
        terminal_at=terminal_at,
        detail=detail,
        halt_reason=halt_reason,
        reason_codes=reason_codes,
        halt_source=halt_source,
        event_ids=tuple(event.event_id for event in events),
    )


def _task_from_payload(payload: Mapping[str, object]) -> ScheduledTask:
    try:
        if set(payload) != {
            "task_id",
            "kind",
            "trading_date",
            "due_at",
            "expires_at",
            "policy_version",
        }:
            raise ValueError
        return ScheduledTask(
            task_id=str(payload["task_id"]),
            kind=SchedulerTaskKind(str(payload["kind"])),
            trading_date=date.fromisoformat(str(payload["trading_date"])),
            due_at=datetime.fromisoformat(str(payload["due_at"])),
            expires_at=datetime.fromisoformat(str(payload["expires_at"])),
            policy_version=str(payload["policy_version"]),
        )
    except (KeyError, TypeError, ValueError):
        raise JournalIntegrityError("invalid scheduled task payload") from None


def _event_key(action: str, task_id: str) -> str:
    match = _TASK_ID.fullmatch(task_id)
    if match is None:
        raise ValueError("invalid scheduled task identity")
    return f"scheduler-{action}:{match.group(1)}"


def _missed_reason(kind: SchedulerTaskKind) -> SchedulerHaltReason:
    if kind is SchedulerTaskKind.ENTRY_SESSION:
        return SchedulerHaltReason.MISSED_ENTRY_WINDOW
    return SchedulerHaltReason.MISSED_END_OF_DAY_WINDOW


def _claimant(value: str) -> None:
    if not isinstance(value, str) or _CLAIMANT.fullmatch(value) is None:
        raise ValueError("claimant_id must be a bounded scheduler invocation identity")


def _detail(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("task result detail is required")
    normalized = value.strip()
    if len(normalized) > _MAX_DETAIL_LENGTH:
        raise ValueError("task result detail exceeds the scheduler limit")
    return normalized


def _reason_code_tuple(values: tuple[object, ...]) -> tuple[str, ...]:
    reasons = tuple(str(value) for value in values)
    if (
        not reasons
        or len(reasons) != len(set(reasons))
        or any(_REASON_CODE.fullmatch(reason) is None for reason in reasons)
    ):
        raise ValueError("reason_codes must be nonblank, bounded, and unique")
    return reasons


def _aware(label: str, value: datetime) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{label} must be timezone-aware")
