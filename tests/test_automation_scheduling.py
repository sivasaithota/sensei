from __future__ import annotations

import plistlib
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from sensei.automation.scheduling import (
    INDIA_TIMEZONE,
    ScheduleState,
    SchedulerHaltReason,
    SchedulerLedger,
    SchedulerNoWorkReason,
    SchedulerTaskKind,
    SchedulerTaskState,
    SwingSessionPolicy,
    scheduled_task_id,
)
from sensei.operations import OperationalJournal


IST = ZoneInfo(INDIA_TIMEZONE)


def at_ist(day: date, hour: int, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST)


def test_friday_entry_is_due_and_identity_is_timezone_stable() -> None:
    friday = date(2026, 7, 17)
    policy = SwingSessionPolicy()

    local = policy.due_tasks(at_ist(friday, 9, 21))
    same_instant = policy.due_tasks(
        at_ist(friday, 9, 21).astimezone(timezone.utc)
    )

    assert local.state is ScheduleState.DUE
    assert local.no_work_reason is None
    assert local.halts == ()
    assert len(local.tasks) == 1
    assert local.tasks[0].kind is SchedulerTaskKind.ENTRY_SESSION
    assert local.tasks[0].trading_date == friday
    assert local.tasks == same_instant.tasks
    assert local.tasks[0].task_id == scheduled_task_id(
        kind=SchedulerTaskKind.ENTRY_SESSION,
        trading_date=friday,
        policy_version=policy.policy_version,
    )


def test_sunday_never_produces_work() -> None:
    sunday = date(2026, 7, 19)

    decision = SwingSessionPolicy().due_tasks(at_ist(sunday, 9, 21))

    assert decision.state is ScheduleState.NO_WORK
    assert decision.tasks == ()
    assert decision.halts == ()
    assert decision.no_work_reason is SchedulerNoWorkReason.NOT_TRADING_DAY


def test_missed_entry_window_halts_that_task_without_late_entry() -> None:
    monday = date(2026, 7, 20)
    policy = SwingSessionPolicy()

    decision = policy.due_tasks(at_ist(monday, 9, 36))

    assert decision.state is ScheduleState.HALTED
    assert decision.tasks == ()
    assert decision.no_work_reason is None
    assert len(decision.halts) == 1
    assert decision.halts[0].task.kind is SchedulerTaskKind.ENTRY_SESSION
    assert decision.halts[0].reason is SchedulerHaltReason.MISSED_ENTRY_WINDOW


def test_completed_due_task_is_not_offered_again() -> None:
    monday = date(2026, 7, 20)
    policy = SwingSessionPolicy()
    first = policy.due_tasks(at_ist(monday, 9, 21))

    repeated = policy.due_tasks(
        at_ist(monday, 9, 22),
        resolved_task_ids={first.tasks[0].task_id},
    )

    assert repeated.state is ScheduleState.NO_WORK
    assert repeated.tasks == ()
    assert repeated.no_work_reason is SchedulerNoWorkReason.ALREADY_RESOLVED


def test_eod_remains_due_when_entry_window_was_missed() -> None:
    monday = date(2026, 7, 20)

    decision = SwingSessionPolicy().due_tasks(at_ist(monday, 18, 31))

    assert decision.state is ScheduleState.DUE_WITH_HALTS
    assert [task.kind for task in decision.tasks] == [
        SchedulerTaskKind.END_OF_DAY_SESSION
    ]
    assert [halt.reason for halt in decision.halts] == [
        SchedulerHaltReason.MISSED_ENTRY_WINDOW
    ]


def test_closed_date_is_not_a_trading_day() -> None:
    monday = date(2026, 7, 20)
    policy = SwingSessionPolicy(closed_dates=frozenset({monday}))

    decision = policy.due_tasks(at_ist(monday, 18, 31))

    assert decision.state is ScheduleState.NO_WORK
    assert decision.no_work_reason is SchedulerNoWorkReason.NOT_TRADING_DAY


def test_scheduler_ledger_claim_and_completion_are_idempotent(tmp_path: Path) -> None:
    now = at_ist(date(2026, 7, 20), 9, 21)
    task = SwingSessionPolicy().due_tasks(now).tasks[0]
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    ledger = SchedulerLedger(journal)

    claimed = ledger.claim(task, occurred_at=now)
    duplicate = ledger.claim(
        task,
        occurred_at=now + timedelta(seconds=1),
    )

    assert claimed.acquired is True
    assert claimed.replayed is False
    assert claimed.record.state is SchedulerTaskState.CLAIMED
    assert duplicate.acquired is False
    assert duplicate.replayed is True
    assert duplicate.record.claimant_id == claimed.record.claimant_id
    assert len(journal.read_stream(ledger.stream_id(task.task_id))) == 1

    claimant_id = claimed.record.claimant_id
    assert claimant_id is not None
    completed = ledger.complete(
        task.task_id,
        claimant_id=claimant_id,
        occurred_at=now + timedelta(minutes=1),
        detail="paper session completed",
    )
    repeated = ledger.complete(
        task.task_id,
        claimant_id=claimant_id,
        occurred_at=now + timedelta(minutes=1),
        detail="paper session completed",
    )

    assert completed.state is SchedulerTaskState.COMPLETED
    assert repeated == completed
    assert ledger.resolved_task_ids() == frozenset({task.task_id})
    assert len(journal.read_stream(ledger.stream_id(task.task_id))) == 2
    assert journal.verify().ok


def test_scheduler_ledger_records_missed_window_once(tmp_path: Path) -> None:
    now = at_ist(date(2026, 7, 20), 9, 36)
    missed = SwingSessionPolicy().due_tasks(now).halts[0]
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    ledger = SchedulerLedger(journal)

    first = ledger.halt(
        missed.task,
        reason=missed.reason,
        occurred_at=now,
        detail="host woke after the entry cutoff",
    )
    repeated = ledger.halt(
        missed.task,
        reason=missed.reason,
        occurred_at=now,
        detail="host woke after the entry cutoff",
    )

    assert first.state is SchedulerTaskState.HALTED
    assert first.halt_reason is SchedulerHaltReason.MISSED_ENTRY_WINDOW
    assert repeated == first
    assert ledger.resolved_task_ids() == frozenset({missed.task.task_id})
    assert len(journal.read_stream(ledger.stream_id(missed.task.task_id))) == 1


def test_claimed_handler_halt_requires_the_exact_claimant(tmp_path: Path) -> None:
    now = at_ist(date(2026, 7, 20), 9, 21)
    task = SwingSessionPolicy().due_tasks(now).tasks[0]
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    ledger = SchedulerLedger(journal)
    claim = ledger.claim(task, occurred_at=now)
    claimant_id = claim.record.claimant_id
    assert claimant_id is not None

    with pytest.raises(PermissionError, match="claimant"):
        ledger.halt_claimed(
            task.task_id,
            claimant_id="scheduler-run:not-the-owner",
            occurred_at=now,
            reason_codes=("TASK_HANDLER_FAILED",),
            detail="handler raised RuntimeError",
        )

    halted = ledger.halt_claimed(
        task.task_id,
        claimant_id=claimant_id,
        occurred_at=now,
        reason_codes=("TASK_HANDLER_FAILED",),
        detail="handler raised RuntimeError",
    )
    assert halted.reason_codes == ("TASK_HANDLER_FAILED",)
    assert halted.halt_source.value == "HANDLER"


def test_scheduler_ledger_admits_only_one_concurrent_claim(tmp_path: Path) -> None:
    now = at_ist(date(2026, 7, 20), 9, 21)
    task = SwingSessionPolicy().due_tasks(now).tasks[0]
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    ledger = SchedulerLedger(journal)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = tuple(
            executor.map(lambda _: ledger.claim(task, occurred_at=now), range(8))
        )

    assert sum(result.acquired for result in results) == 1
    assert len({result.record.event_ids[0] for result in results}) == 1
    assert len(journal.read_stream(ledger.stream_id(task.task_id))) == 1


def test_launchd_templates_use_correct_weekdays_and_new_interval_runner() -> None:
    root = Path(__file__).resolve().parents[1]
    for name in ("com.sensei.runday.plist", "com.sensei.executeopen.plist"):
        with (root / "config" / name).open("rb") as handle:
            payload = plistlib.load(handle)
        assert [item["Weekday"] for item in payload["StartCalendarInterval"]] == [
            2,
            3,
            4,
            5,
            6,
        ]

    with (root / "config" / "com.sensei.governed-scheduler.plist").open(
        "rb"
    ) as handle:
        governed = plistlib.load(handle)
    assert "Disabled" not in governed
    assert governed["RunAtLoad"] is True
    assert governed["StartInterval"] == 300
    assert "--config" in governed["ProgramArguments"]
    assert "scheduler-run-once" in governed["ProgramArguments"]
    assert governed["EnvironmentVariables"]["TZ"] == INDIA_TIMEZONE
