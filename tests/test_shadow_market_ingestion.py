from datetime import date, datetime, timedelta, timezone

import pandas as pd

from sensei.automation.market_ingestion import (
    MarketDataIngestionLedger,
    MarketDataIngestionSession,
)
from sensei.automation.runner import TaskOutcomeState
from sensei.automation.scheduling import SchedulerTaskKind, ScheduledTask, scheduled_task_id
from sensei.operations import OperationalJournal


NOW = datetime(2026, 7, 16, 13, 30, tzinfo=timezone.utc)


def _task():
    policy = "india-swing-paper-v1"
    return ScheduledTask(
        task_id=scheduled_task_id(
            kind=SchedulerTaskKind.END_OF_DAY_SESSION,
            trading_date=date(2026, 7, 16),
            policy_version=policy,
        ),
        kind=SchedulerTaskKind.END_OF_DAY_SESSION,
        trading_date=date(2026, 7, 16),
        due_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        policy_version=policy,
    )


def _bars(day):
    return pd.DataFrame(
        {"open": [100.0], "high": [101.0], "low": [99.0], "close": [100.5], "volume": [1000.0]},
        index=pd.DatetimeIndex([day]),
    )


def test_ingestion_retries_and_publishes_eligible_shadow_universe(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    calls = {"B": 0}

    def refresh(symbol):
        if symbol == "B":
            calls["B"] += 1
            if calls["B"] < 3:
                return None
        return _bars("2026-07-16")

    session = MarketDataIngestionSession(
        journal=journal,
        universe=lambda: ("A", "B"),
        refresh=refresh,
        existing=lambda symbol: _bars("2026-07-15"),
        maximum_attempts=3,
        inter_batch_delay_seconds=0,
    )

    outcome = session(_task(), NOW)
    snapshot = MarketDataIngestionLedger(journal).for_session(date(2026, 7, 16))

    assert outcome.state is TaskOutcomeState.COMPLETED
    assert snapshot.eligible_symbols == ("A", "B")
    assert snapshot.failed_symbols == ()
    assert calls["B"] == 3


def test_ingestion_retries_failed_symbols_in_paced_batches(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    calls = []
    sleeps = []
    c_attempts = 0

    def refresh_batch(symbols):
        nonlocal c_attempts
        calls.append(tuple(symbols))
        if "C" in symbols:
            c_attempts += 1
        return {
            symbol: (
                None
                if symbol == "C" and c_attempts < 3
                else _bars("2026-07-16")
            )
            for symbol in symbols
        }

    session = MarketDataIngestionSession(
        journal=journal,
        universe=lambda: ("A", "B", "C", "D"),
        refresh=lambda symbol: None,
        refresh_batch=refresh_batch,
        existing=lambda symbol: _bars("2026-07-15"),
        batch_size=2,
        maximum_attempts=3,
        inter_batch_delay_seconds=0.5,
        retry_backoff_seconds=2,
        sleep=sleeps.append,
    )

    outcome = session(_task(), NOW)

    assert outcome.state is TaskOutcomeState.COMPLETED
    assert calls == [("A", "B"), ("C", "D"), ("C",), ("C",)]
    assert sleeps == [0.5, 2, 4]


def test_ingestion_excludes_long_stale_instrument_without_deleting_history(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    session = MarketDataIngestionSession(
        journal=journal,
        universe=lambda: ("ACTIVE", "DELISTED"),
        refresh=lambda symbol: _bars("2026-07-16") if symbol == "ACTIVE" else None,
        existing=lambda symbol: _bars("2026-01-02"),
        maximum_attempts=2,
        stale_exclusion_age=timedelta(days=30),
        maximum_exclusion_fraction=0.5,
    )

    outcome = session(_task(), NOW)
    snapshot = MarketDataIngestionLedger(journal).for_session(date(2026, 7, 16))

    assert outcome.state is TaskOutcomeState.COMPLETED
    assert snapshot.eligible_symbols == ("ACTIVE",)
    assert snapshot.excluded_symbols == ("DELISTED",)
    assert snapshot.completeness == 1.0


def test_ingestion_halts_below_preregistered_completeness(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    symbols = tuple(f"S{index:03}" for index in range(100))
    session = MarketDataIngestionSession(
        journal=journal,
        universe=lambda: symbols,
        refresh=lambda symbol: None if symbol in {"S098", "S099"} else _bars("2026-07-16"),
        existing=lambda symbol: _bars("2026-07-15"),
        maximum_attempts=1,
        minimum_completeness=0.99,
    )

    outcome = session(_task(), NOW)

    assert outcome.state is TaskOutcomeState.HALTED
    assert outcome.reason_codes == ("MARKET_DATA_COMPLETENESS_BELOW_POLICY",)


def test_ingestion_accepts_exact_preregistered_ninety_nine_percent(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    symbols = tuple(f"S{index:03}" for index in range(100))
    session = MarketDataIngestionSession(
        journal=journal,
        universe=lambda: symbols,
        refresh=lambda symbol: None if symbol == "S099" else _bars("2026-07-16"),
        existing=lambda symbol: _bars("2026-07-15"),
        maximum_attempts=1,
        minimum_completeness=0.99,
    )

    outcome = session(_task(), NOW)
    snapshot = MarketDataIngestionLedger(journal).for_session(date(2026, 7, 16))

    assert outcome.state is TaskOutcomeState.COMPLETED
    assert snapshot.completeness == 0.99
    assert len(snapshot.eligible_symbols) == 99
    assert snapshot.failed_symbols == ("S099",)


def test_ingestion_cannot_hide_broad_vendor_failure_as_universe_hygiene(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    symbols = tuple(f"S{index:03}" for index in range(100))
    session = MarketDataIngestionSession(
        journal=journal,
        universe=lambda: symbols,
        refresh=lambda symbol: None if symbol in {"S097", "S098", "S099"} else _bars("2026-07-16"),
        existing=lambda symbol: _bars("2026-01-02"),
        maximum_attempts=1,
        maximum_exclusion_fraction=0.01,
    )

    outcome = session(_task(), NOW)

    assert outcome.state is TaskOutcomeState.HALTED
    assert outcome.reason_codes == ("MARKET_DATA_UNIVERSE_HYGIENE_UNRESOLVED",)
