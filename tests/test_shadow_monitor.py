"""Shadow monitor is passive: builds reports from journal reads only."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from sensei.operations import OperationalJournal
from sensei.operations.journal import EventAppend
from sensei.automation.scheduling import SchedulerLedger, SchedulerTaskKind, SwingSessionPolicy
import sensei.reporting.shadow_monitor as sm


def _append(journal, stream, etype, payload, key, when):
    journal.append(EventAppend(
        stream_id=stream, event_type=etype, payload=payload,
        idempotency_key=key, expected_version=0,
        occurred_at=when, correlation_id="test"))


@pytest.fixture
def journal(tmp_path):
    return OperationalJournal(tmp_path / "ops.sqlite3")


def _seed(journal):
    now = datetime(2026, 7, 17, 13, 30, tzinfo=timezone.utc)
    registered = datetime(2026, 7, 16, 13, 30, tzinfo=timezone.utc)
    _append(journal, "plan:p1", "StrategyPlanRegistered",
            {"plan_id": "sha256:p1", "source_rule_name": "minervini_trend_template"},
            "reg:p1", registered)
    _append(journal, "plan:p1:shadow", "StrategyLifecycleTransitioned",
            {"plan_version_id": "sha256:p1", "target_stage": "shadow"},
            "tr:p1:shadow", registered)
    _append(journal, "ingest:s1", "MarketDataIngestionCompleted",
            {"session": "2026-07-17", "completeness": 0.996,
             "eligible_symbols": ["A", "B"], "failed_symbols": ["VEDL"],
             "excluded_symbols": ["VEDL"]},
            "ing:s1", now)
    _append(journal, "shadow:p1:s1", "ShadowSessionObserved",
            {"plan_id": "sha256:p1", "evaluation_session": "2026-07-17",
             "evaluations": [
                 {"instrument_id": "NSE:INFY", "trace": {"action": "enter_long"}},
                 {"instrument_id": "NSE:TCS", "trace": {"action": "no_action"}},
             ]},
            "obs:p1:s1", now)


def test_report_counts_observations_and_signals(journal):
    _seed(journal)
    report = sm.build_report(journal_path=_journal_path(journal), as_of=date(2026, 7, 17))
    assert report.journal_ok
    plan = report.plans[0]
    assert plan["name"] == "minervini_trend_template"
    assert plan["observations"] == 1
    assert plan["signals"] == 1                       # only enter_long counts
    assert plan["signal_instruments"] == 1
    assert plan["sessions_remaining_minimum"] == 19
    assert report.expected_sessions == 1              # Jul 17 itself
    assert report.ingestion["completeness"] == 0.996
    assert report.ingestion["excluded"] == ["VEDL"]


def _journal_path(journal) -> Path:
    for attr in ("_path", "path", "_db_path"):
        p = getattr(journal, attr, None)
        if p:
            return Path(p)
    raise AttributeError("journal path attribute not found")


def test_lagging_observations_raise_alert(journal):
    _seed(journal)
    report = sm.build_report(_journal_path(journal), as_of=date(2026, 7, 24))
    assert any("lagging" in a for a in report.alerts)


def test_halts_and_promotions_surface(journal):
    _seed(journal)
    now = datetime(2026, 7, 18, 13, 30, tzinfo=timezone.utc)
    _append(journal, "sched:halt1", "SchedulerTaskHalted",
            {"task_id": "t1", "reason_codes": ["NO_AUTHORIZED_PLANS"]},
            "halt:1", now)
    _append(journal, "plan:p1:paper", "StrategyLifecycleTransitioned",
            {"plan_version_id": "sha256:p1", "target_stage": "paper"},
            "prom:p1", now)
    report = sm.build_report(_journal_path(journal), as_of=date(2026, 7, 18))
    assert report.halts and report.halts[0]["reasons"] == ["NO_AUTHORIZED_PLANS"]
    assert report.promotions and report.promotions[0]["to"] == "paper"
    assert any("promotions recorded" in a for a in report.alerts)


def test_monitor_makes_no_journal_writes(journal):
    _seed(journal)
    path = _journal_path(journal)
    before = journal.verify().events_checked
    sm.build_report(path, as_of=date(2026, 7, 17))
    assert OperationalJournal(path).verify().events_checked == before


def test_missing_journal_alerts(tmp_path):
    report = sm.build_report(tmp_path / "nope.sqlite3")
    assert not report.journal_ok
    assert any("missing" in a for a in report.alerts)


def test_read_only_journal_refuses_append(journal):
    _seed(journal)
    read_only = OperationalJournal.open_read_only(_journal_path(journal))

    with pytest.raises(PermissionError, match="read-only"):
        _append(
            read_only,
            "must:not:write",
            "Forbidden",
            {},
            "forbidden",
            datetime(2026, 7, 17, tzinfo=timezone.utc),
        )


def test_report_uses_configured_closed_dates(journal, tmp_path):
    _seed(journal)
    config = tmp_path / "scheduler.json"
    config.write_text('{"closed_dates": ["2026-07-20"]}', encoding="utf-8")

    report = sm.build_report(
        _journal_path(journal),
        as_of=date(2026, 7, 20),
        config_path=config,
    )

    assert report.expected_sessions == 1


def test_pending_eod_is_not_reported_as_missing_ingestion(journal):
    _seed(journal)
    policy = SwingSessionPolicy()
    now = datetime(2026, 7, 20, 18, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    task = next(
        item
        for item in policy.due_tasks(now).tasks
        if item.kind is SchedulerTaskKind.END_OF_DAY_SESSION
    )
    SchedulerLedger(journal).claim(task, occurred_at=now)

    report = sm.build_report(_journal_path(journal), as_of=date(2026, 7, 20))

    assert not any("no market-data ingestion" in alert for alert in report.alerts)
    assert any("EOD ingestion pending" in alert for alert in report.alerts)
