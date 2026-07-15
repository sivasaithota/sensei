from datetime import date, datetime
from zoneinfo import ZoneInfo

from sensei.automation.paper_sessions import LegacyPaperSessions
from sensei.automation.runner import TaskOutcomeState
from sensei.automation.scheduling import SchedulerTaskKind, ScheduledTask, scheduled_task_id


NOW = datetime(2026, 7, 16, 9, 25, tzinfo=ZoneInfo("Asia/Kolkata"))


def task(kind: SchedulerTaskKind) -> ScheduledTask:
    policy = "swing-session-v1"
    return ScheduledTask(
        task_id=scheduled_task_id(kind=kind, trading_date=date(2026, 7, 16), policy_version=policy),
        kind=kind,
        trading_date=date(2026, 7, 16),
        due_at=NOW,
        expires_at=NOW,
        policy_version=policy,
    )


def test_paper_sessions_execute_open_and_pass_only_adopted_entries_to_eod():
    calls = []
    sessions = LegacyPaperSessions(
        run_day=lambda **kwargs: calls.append(kwargs) or {"signals": 2, "opened": [{}]},
    )

    entry = sessions.entry(task(SchedulerTaskKind.ENTRY_SESSION), NOW)
    eod = sessions.eod(task(SchedulerTaskKind.END_OF_DAY_SESSION), NOW)

    assert entry.state is TaskOutcomeState.COMPLETED
    assert entry.reason_codes == ("LEGACY_ENTRY_PATH_DISABLED",)
    assert eod.state is TaskOutcomeState.COMPLETED
    assert calls[0]["adopted_entries"] == ()


def test_paper_eod_halts_without_backtest_adoption():
    sessions = LegacyPaperSessions(
        run_day=lambda **kwargs: {},
    )

    outcome = sessions.eod(task(SchedulerTaskKind.END_OF_DAY_SESSION), NOW)

    assert outcome.state is TaskOutcomeState.COMPLETED
    assert outcome.reason_codes == ("PAPER_EOD_SESSION_COMPLETED",)
