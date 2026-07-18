from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from sensei.automation.liveness import (
    SchedulerAlreadyRunning,
    SchedulerHealthState,
    SchedulerLease,
    SchedulerWatchdog,
)
from sensei.operations import OperationalJournal


IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 7, 20, 8, 0, tzinfo=IST)


def test_fresh_completed_wakeup_is_healthy(tmp_path):
    journal = tmp_path / "operations.sqlite3"
    OperationalJournal(journal)
    heartbeat = tmp_path / "heartbeat.json"
    with SchedulerLease(
        heartbeat_path=heartbeat, lock_path=tmp_path / "scheduler.lock",
        now=lambda: NOW, deployed_commit="abc123",
    ):
        pass

    report = SchedulerWatchdog(
        journal_path=journal, heartbeat_path=heartbeat,
        lock_path=tmp_path / "scheduler.lock", expected_commit="abc123",
    ).inspect(now=NOW + timedelta(seconds=30))

    assert report.state is SchedulerHealthState.HEALTHY
    assert report.reason_codes == ()
    assert report.heartbeat["phase"] == "IDLE"
    assert report.exit_code == 0


def test_stale_heartbeat_is_offline(tmp_path):
    journal = tmp_path / "operations.sqlite3"
    OperationalJournal(journal)
    heartbeat = tmp_path / "heartbeat.json"
    with SchedulerLease(
        heartbeat_path=heartbeat, lock_path=tmp_path / "scheduler.lock",
        now=lambda: NOW, deployed_commit="abc123",
    ):
        pass

    report = SchedulerWatchdog(
        journal_path=journal, heartbeat_path=heartbeat,
        lock_path=tmp_path / "scheduler.lock", expected_commit="abc123",
        maximum_heartbeat_age=timedelta(minutes=2),
    ).inspect(now=NOW + timedelta(minutes=3))

    assert report.state is SchedulerHealthState.OFFLINE
    assert "SCHEDULER_HEARTBEAT_STALE" in report.reason_codes
    assert report.exit_code == 2


def test_process_lease_rejects_a_second_scheduler_instance(tmp_path):
    first = SchedulerLease(
        heartbeat_path=tmp_path / "heartbeat.json",
        lock_path=tmp_path / "scheduler.lock", now=lambda: NOW,
        deployed_commit="abc123",
    )
    second = SchedulerLease(
        heartbeat_path=tmp_path / "heartbeat.json",
        lock_path=tmp_path / "scheduler.lock", now=lambda: NOW,
        deployed_commit="abc123",
    )
    with first:
        with pytest.raises(SchedulerAlreadyRunning):
            with second:
                pass


def test_watchdog_reports_missed_entry_without_retrying_it(tmp_path):
    journal = tmp_path / "operations.sqlite3"
    OperationalJournal(journal)
    heartbeat = tmp_path / "heartbeat.json"
    observed = datetime(2026, 7, 20, 10, 0, tzinfo=IST)
    with SchedulerLease(
        heartbeat_path=heartbeat, lock_path=tmp_path / "scheduler.lock",
        now=lambda: observed, deployed_commit="abc123",
    ):
        pass

    report = SchedulerWatchdog(
        journal_path=journal, heartbeat_path=heartbeat,
        lock_path=tmp_path / "scheduler.lock", expected_commit="abc123",
    ).inspect(now=observed + timedelta(seconds=10))

    assert report.state is SchedulerHealthState.DEGRADED
    assert "MISSED_ENTRY_WINDOW" in report.reason_codes
    assert report.exit_code == 1
    assert len(OperationalJournal.open_read_only(journal).read_all()) == 0


def test_malformed_heartbeat_fails_closed(tmp_path):
    journal = tmp_path / "operations.sqlite3"
    OperationalJournal(journal)
    heartbeat = tmp_path / "heartbeat.json"
    heartbeat.write_text('{"phase":"SURPRISE"}')

    report = SchedulerWatchdog(
        journal_path=journal, heartbeat_path=heartbeat,
        lock_path=tmp_path / "scheduler.lock",
    ).inspect(now=NOW)

    assert report.state is SchedulerHealthState.OFFLINE
    assert report.reason_codes == ("SCHEDULER_HEARTBEAT_INVALID",)


def test_previous_session_eod_miss_remains_visible_next_morning(tmp_path):
    journal = tmp_path / "operations.sqlite3"
    OperationalJournal(journal)
    heartbeat = tmp_path / "heartbeat.json"
    lock = tmp_path / "scheduler.lock"
    with SchedulerLease(
        heartbeat_path=heartbeat, lock_path=lock, now=lambda: NOW,
        deployed_commit="abc123",
    ):
        pass
    tuesday = datetime(2026, 7, 21, 8, 0, tzinfo=IST)
    with SchedulerLease(
        heartbeat_path=heartbeat, lock_path=lock, now=lambda: tuesday,
        deployed_commit="abc123",
    ):
        pass

    report = SchedulerWatchdog(
        journal_path=journal, heartbeat_path=heartbeat, lock_path=lock,
        expected_commit="abc123",
    ).inspect(now=tuesday + timedelta(seconds=10))

    assert "PREVIOUS_SESSION_MISSED_END_OF_DAY_WINDOW" in report.reason_codes


def test_coherent_long_running_task_is_not_mistaken_for_offline(tmp_path):
    journal = tmp_path / "operations.sqlite3"
    OperationalJournal(journal)
    lease = SchedulerLease(
        heartbeat_path=tmp_path / "heartbeat.json",
        lock_path=tmp_path / "scheduler.lock", now=lambda: NOW,
        deployed_commit="abc123",
    )
    with lease:
        report = SchedulerWatchdog(
            journal_path=journal, heartbeat_path=tmp_path / "heartbeat.json",
            lock_path=tmp_path / "scheduler.lock", expected_commit="abc123",
        ).inspect(now=NOW + timedelta(minutes=8))

    assert report.state is SchedulerHealthState.HEALTHY
    assert "SCHEDULER_HEARTBEAT_STALE" not in report.reason_codes


def test_running_task_overrun_is_detected_before_entry_cutoff(tmp_path):
    journal = tmp_path / "operations.sqlite3"
    OperationalJournal(journal)
    lease = SchedulerLease(
        heartbeat_path=tmp_path / "heartbeat.json",
        lock_path=tmp_path / "scheduler.lock", now=lambda: NOW,
        deployed_commit="abc123",
    )
    with lease:
        report = SchedulerWatchdog(
            journal_path=journal, heartbeat_path=tmp_path / "heartbeat.json",
            lock_path=tmp_path / "scheduler.lock", expected_commit="abc123",
        ).inspect(now=NOW + timedelta(minutes=11))

    assert report.state is SchedulerHealthState.DEGRADED
    assert "SCHEDULER_TASK_RUNTIME_EXCEEDED" in report.reason_codes


def test_corrupt_journal_returns_fail_closed_health(tmp_path):
    journal = tmp_path / "operations.sqlite3"
    journal.write_text("not sqlite")
    heartbeat = tmp_path / "heartbeat.json"
    with SchedulerLease(
        heartbeat_path=heartbeat, lock_path=tmp_path / "scheduler.lock",
        now=lambda: NOW, deployed_commit="abc123",
    ):
        pass

    report = SchedulerWatchdog(
        journal_path=journal, heartbeat_path=heartbeat,
        lock_path=tmp_path / "scheduler.lock", expected_commit="abc123",
    ).inspect(now=NOW + timedelta(seconds=10))

    assert report.state is SchedulerHealthState.OFFLINE
    assert "JOURNAL_INTEGRITY_FAILED" in report.reason_codes
