from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import Event
from zoneinfo import ZoneInfo

import pytest

from sensei.automation.runner import (
    SchedulerRunResult,
    SchedulerTaskHandler,
    TaskOutcome,
    TaskOutcomeState,
    UnattendedSchedulerRunner,
)
from sensei.automation.scheduling import (
    INDIA_TIMEZONE,
    ScheduleDecision,
    ScheduleState,
    ScheduledTask,
    SchedulerHaltSource,
    SchedulerNoWorkReason,
    SchedulerTaskKind,
    SwingSessionPolicy,
    scheduled_task_id,
)
from sensei.operations import OperationalJournal
from sensei.operations.journal import JournalIntegrityError, JournalVerification


IST = ZoneInfo(INDIA_TIMEZONE)


def at_ist(day: date, hour: int, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST)


@dataclass
class StubHandler(SchedulerTaskHandler):
    outcome: TaskOutcome
    calls: list[str] = field(default_factory=list)

    def handle(self, task: ScheduledTask, *, now: datetime) -> TaskOutcome:
        self.calls.append(task.task_id)
        return self.outcome


def completed(code: str) -> TaskOutcome:
    return TaskOutcome(
        state=TaskOutcomeState.COMPLETED,
        reason_codes=(code,),
        detail=f"{code.lower()} completed",
    )


def handlers(
    *,
    entry: SchedulerTaskHandler | None = None,
    end_of_day: SchedulerTaskHandler | None = None,
) -> dict[SchedulerTaskKind, SchedulerTaskHandler]:
    return {
        SchedulerTaskKind.ENTRY_SESSION: entry
        or StubHandler(completed("ENTRY_COMPLETED")),
        SchedulerTaskKind.END_OF_DAY_SESSION: end_of_day
        or StubHandler(completed("END_OF_DAY_COMPLETED")),
    }


def test_task_outcome_requires_unique_bounded_reasons_and_json_projection() -> None:
    outcome = TaskOutcome(
        state=TaskOutcomeState.HALTED,
        reason_codes=("NO_AUTHORIZED_PLANS", "MARKET_DATA_STALE"),
        detail="new entries remain disabled",
    )

    assert outcome.to_dict() == {
        "state": "HALTED",
        "reason_codes": ["NO_AUTHORIZED_PLANS", "MARKET_DATA_STALE"],
        "detail": "new entries remain disabled",
    }
    with pytest.raises(ValueError, match="reason_codes"):
        TaskOutcome(TaskOutcomeState.HALTED, (), "blocked")
    with pytest.raises(ValueError, match="reason_codes"):
        TaskOutcome(TaskOutcomeState.HALTED, ("DUPLICATE", "DUPLICATE"), "blocked")
    with pytest.raises(ValueError, match="detail"):
        TaskOutcome(TaskOutcomeState.COMPLETED, ("OK",), "  ")


def test_completed_task_replays_without_reinvoking_handler(tmp_path: Path) -> None:
    now = at_ist(date(2026, 7, 17), 9, 21)  # Friday
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    entry = StubHandler(completed("ENTRY_COMPLETED"))
    runner = UnattendedSchedulerRunner(
        journal=journal,
        policy=SwingSessionPolicy(),
        handlers=handlers(entry=entry),
    )

    first = runner.run_once(now)
    replay = runner.run_once(now + timedelta(minutes=1))

    assert isinstance(first, SchedulerRunResult)
    assert first.schedule.state is ScheduleState.DUE
    assert first.task_results[0].outcome.state is TaskOutcomeState.COMPLETED
    assert first.task_results[0].replayed is False
    assert replay.schedule.state is ScheduleState.NO_WORK
    assert replay.schedule.no_work_reason is SchedulerNoWorkReason.ALREADY_RESOLVED
    assert replay.task_results[0].outcome == first.task_results[0].outcome
    assert replay.task_results[0].replayed is True
    assert len(entry.calls) == 1
    assert json.loads(json.dumps(replay.to_dict()))["task_results"][0][
        "replayed"
    ] is True


def test_missed_entry_is_journaled_but_end_of_day_still_runs(tmp_path: Path) -> None:
    now = at_ist(date(2026, 7, 20), 18, 31)
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    entry = StubHandler(completed("ENTRY_COMPLETED"))
    end_of_day = StubHandler(completed("END_OF_DAY_COMPLETED"))
    runner = UnattendedSchedulerRunner(
        journal=journal,
        policy=SwingSessionPolicy(),
        handlers=handlers(entry=entry, end_of_day=end_of_day),
    )

    result = runner.run_once(now)
    event_count = len(journal.read_all())
    replay = runner.run_once(now + timedelta(minutes=1))

    assert result.schedule.state is ScheduleState.DUE_WITH_HALTS
    assert [item.task.kind for item in result.task_results] == [
        SchedulerTaskKind.ENTRY_SESSION,
        SchedulerTaskKind.END_OF_DAY_SESSION,
    ]
    missed, maintained = result.task_results
    assert missed.outcome.state is TaskOutcomeState.HALTED
    assert missed.outcome.reason_codes == ("MISSED_ENTRY_WINDOW",)
    assert missed.halt_source is SchedulerHaltSource.WINDOW
    assert maintained.outcome.state is TaskOutcomeState.COMPLETED
    assert entry.calls == []
    assert len(end_of_day.calls) == 1
    assert all(item.replayed for item in replay.task_results)
    assert len(journal.read_all()) == event_count
    assert journal.verify().ok


class BothDuePolicy:
    def __init__(self, now: datetime) -> None:
        day = now.astimezone(IST).date()
        self.tasks = tuple(
            ScheduledTask(
                task_id=scheduled_task_id(
                    kind=kind,
                    trading_date=day,
                    policy_version="both-due-v1",
                ),
                kind=kind,
                trading_date=day,
                due_at=now - timedelta(minutes=1),
                expires_at=now + timedelta(minutes=1),
                policy_version="both-due-v1",
            )
            for kind in SchedulerTaskKind
        )

    def due_tasks(
        self,
        now: datetime,
        *,
        resolved_task_ids: set[str] | frozenset[str] = frozenset(),
    ) -> ScheduleDecision:
        due = tuple(
            task for task in self.tasks if task.task_id not in resolved_task_ids
        )
        if due:
            return ScheduleDecision(
                state=ScheduleState.DUE,
                evaluated_at=now,
                trading_date=now.astimezone(IST).date(),
                tasks=due,
            )
        return ScheduleDecision(
            state=ScheduleState.NO_WORK,
            evaluated_at=now,
            trading_date=now.astimezone(IST).date(),
            no_work_reason=SchedulerNoWorkReason.ALREADY_RESOLVED,
        )


def test_handler_halted_entry_does_not_suppress_due_maintenance(tmp_path: Path) -> None:
    now = at_ist(date(2026, 7, 20), 18, 31)
    entry = StubHandler(
        TaskOutcome(
            TaskOutcomeState.HALTED,
            ("ENTRY_POLICY_BLOCK",),
            "entry prerequisites are incomplete",
        )
    )
    end_of_day = StubHandler(completed("END_OF_DAY_COMPLETED"))
    runner = UnattendedSchedulerRunner(
        journal=OperationalJournal(tmp_path / "operations.sqlite3"),
        policy=BothDuePolicy(now),
        handlers=handlers(entry=entry, end_of_day=end_of_day),
    )

    result = runner.run_once(now)

    assert [item.outcome.state for item in result.task_results] == [
        TaskOutcomeState.HALTED,
        TaskOutcomeState.COMPLETED,
    ]
    assert result.task_results[0].halt_source is SchedulerHaltSource.HANDLER
    assert len(entry.calls) == len(end_of_day.calls) == 1


class SecretFailureHandler:
    def handle(self, task: ScheduledTask, *, now: datetime) -> TaskOutcome:
        raise RuntimeError("broker password: do-not-persist")


def test_unexpected_handler_failure_is_sanitized_and_durably_halted(
    tmp_path: Path,
) -> None:
    now = at_ist(date(2026, 7, 17), 9, 21)
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    runner = UnattendedSchedulerRunner(
        journal=journal,
        policy=SwingSessionPolicy(),
        handlers=handlers(entry=SecretFailureHandler()),
    )

    result = runner.run_once(now)

    task_result = result.task_results[0]
    assert task_result.outcome.state is TaskOutcomeState.HALTED
    assert task_result.outcome.reason_codes == ("TASK_HANDLER_FAILED",)
    assert task_result.outcome.detail == "handler raised RuntimeError"
    assert task_result.halt_source is SchedulerHaltSource.HANDLER
    serialized = json.dumps(result.to_dict()) + repr(
        [event.payload for event in journal.read_all()]
    )
    assert "do-not-persist" not in serialized
    assert "broker password" not in serialized


class BlockingHandler:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.calls = 0

    def handle(self, task: ScheduledTask, *, now: datetime) -> TaskOutcome:
        self.calls += 1
        self.started.set()
        assert self.release.wait(timeout=2)
        return completed("ENTRY_COMPLETED")


def test_racing_runner_does_not_invoke_an_unacquired_claim(tmp_path: Path) -> None:
    now = at_ist(date(2026, 7, 17), 9, 21)
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    blocking = BlockingHandler()
    runner = UnattendedSchedulerRunner(
        journal=journal,
        policy=SwingSessionPolicy(),
        handlers=handlers(entry=blocking),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        active = executor.submit(runner.run_once, now)
        assert blocking.started.wait(timeout=2)
        contender = runner.run_once(now)
        blocking.release.set()
        completed_run = active.result(timeout=2)

    assert blocking.calls == 1
    assert len(completed_run.task_results) == 1
    assert len(contender.in_progress_task_ids) == 1
    assert contender.task_results == ()


def test_runner_refuses_unverified_journal_before_handlers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = at_ist(date(2026, 7, 17), 9, 21)
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    entry = StubHandler(completed("ENTRY_COMPLETED"))
    runner = UnattendedSchedulerRunner(
        journal=journal,
        policy=SwingSessionPolicy(),
        handlers=handlers(entry=entry),
    )
    monkeypatch.setattr(
        journal,
        "verify",
        lambda: JournalVerification(False, 0, ("tampered",)),
    )

    with pytest.raises(JournalIntegrityError, match="integrity"):
        runner.run_once(now)
    assert entry.calls == []
