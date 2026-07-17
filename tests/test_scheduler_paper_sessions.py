from datetime import date, datetime
import json
from zoneinfo import ZoneInfo

import pandas as pd

from sensei.automation.paper_sessions import LegacyPaperSessions, refresh_held_position_bars
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


def test_paper_eod_refreshes_held_positions_before_processing_exits():
    order = []
    sessions = LegacyPaperSessions(
        refresh_held_positions=lambda trading_date: order.append(
            ("refresh", trading_date)
        ) or True,
        run_day=lambda **kwargs: order.append(("exits", kwargs["today"])) or {},
    )

    outcome = sessions.eod(task(SchedulerTaskKind.END_OF_DAY_SESSION), NOW)

    assert outcome.state is TaskOutcomeState.COMPLETED
    assert order == [
        ("refresh", date(2026, 7, 16)),
        ("exits", date(2026, 7, 16)),
    ]


def test_paper_eod_never_marks_positions_from_stale_bars():
    called = []
    sessions = LegacyPaperSessions(
        refresh_held_positions=lambda trading_date: False,
        run_day=lambda **kwargs: called.append(kwargs) or {},
    )

    outcome = sessions.eod(task(SchedulerTaskKind.END_OF_DAY_SESSION), NOW)

    assert outcome.state is TaskOutcomeState.HALTED
    assert outcome.reason_codes == ("LEGACY_POSITION_DATA_UNAVAILABLE",)
    assert called == []


def test_held_position_refresh_retries_only_failed_symbols(tmp_path):
    path = tmp_path / "positions.json"
    path.write_text(json.dumps({"positions": [{"symbol": "INFY"}, {"symbol": "TCS"}]}))
    frame = pd.DataFrame(
        {"close": [1]}, index=pd.DatetimeIndex(["2026-07-16"])
    )
    calls, sleeps = [], []

    def refresh(symbols):
        calls.append(symbols)
        return {
            symbol: frame
            for symbol in symbols
            if symbol == "INFY" or len(calls) > 1
        }

    refreshed = refresh_held_position_bars(
        positions_path=path,
        session=date(2026, 7, 16),
        refresh_batch=refresh,
        retry_backoff_seconds=2,
        sleep=sleeps.append,
    )

    assert refreshed is True
    assert calls == [("INFY", "TCS"), ("TCS",)]
    assert sleeps == [2]
