from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sensei.operations.journal import EventAppend, OperationalJournal
from sensei.reporting.operations import OperationalReporter, ReportingPeriod


UTC = timezone.utc
IST = ZoneInfo("Asia/Kolkata")


def _append(
    journal: OperationalJournal,
    sequence: int,
    event_type: str,
    occurred_at: datetime,
    payload: dict | None = None,
):
    return journal.append(
        EventAppend(
            stream_id=f"fixture:event-{sequence}",
            event_type=event_type,
            payload=payload or {},
            idempotency_key=f"fixture-event-{sequence}",
            expected_version=0,
            occurred_at=occurred_at,
        )
    )


def test_daily_report_counts_operations_and_only_attributed_pnl(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    local_day = date(2026, 7, 13)
    within = datetime(2026, 7, 13, 10, 0, tzinfo=IST).astimezone(UTC)
    events = (
        ("EpisodeStarted", {"episode_id": "EP-1"}),
        ("EpisodeClosed", {"episode_id": "EP-1", "pnl": "888.00"}),
        ("StrategyLifecycleTransitioned", {"stage": "shadow"}),
        ("RiskReserved", {}),
        ("RiskReleased", {}),
        ("OperationalHealthAssessed", {"fact": {"state": "HALTED"}}),
        ("OperationsReadinessAssessed", {"ready": False}),
        ("MistakeHypothesisProposed", {"hypothesis_id": "H-1"}),
        ("BrokerCommandPrepared", {"command": {"command_id": "C-1"}}),
        ("BrokerCommandCompleted", {"receipt": {"command_id": "C-1"}}),
        ("LegacyFactImported", {"record": {"pnl": "999999.00"}}),
        (
            "OutcomeAttributed",
            {
                "episode_id": "EP-1",
                "currency": "INR",
                "realized_net_pnl": "125.50",
                "evidence_refs": ["event:entry", "event:exit", "event:fees"],
                "reconciles": True,
            },
        ),
        (
            "OutcomeAttributed",
            {
                "episode_id": "EP-BAD",
                "currency": "INR",
                "realized_net_pnl": "5000.00",
                "evidence_refs": [],
                "reconciles": True,
            },
        ),
    )
    for sequence, (event_type, payload) in enumerate(events, start=1):
        _append(journal, sequence, event_type, within, payload)
    # 18:45 UTC is after midnight in India and must not leak into the report.
    _append(
        journal,
        99,
        "EpisodeStarted",
        datetime(2026, 7, 13, 18, 45, tzinfo=UTC),
        {"episode_id": "EP-TOMORROW"},
    )

    report = OperationalReporter(journal).daily(local_day, tz=IST)

    assert report.period is ReportingPeriod.DAILY
    assert report.counts.episodes == 1
    assert report.counts.lifecycle == 1
    assert report.counts.risk == 2
    assert report.counts.alerts == 2
    assert report.counts.hypotheses == 1
    assert report.counts.kernel_commands == 1
    assert report.event_type_counts["EpisodeClosed"] == 1
    assert report.pnl_by_currency == {"INR": "125.50"}
    assert report.attributed_pnl_events == 1
    assert report.excluded_pnl_events == 1
    assert report.journal_integrity.ok is True
    assert report.journal_integrity.events_checked == len(events) + 1
    assert json.loads(json.dumps(report.to_dict()))["pnl_by_currency"] == {
        "INR": "125.50"
    }


def test_weekly_report_uses_local_monday_through_sunday_window(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    monday = date(2026, 7, 13)
    _append(
        journal,
        1,
        "EpisodeStarted",
        datetime(2026, 7, 13, 0, 0, tzinfo=IST).astimezone(UTC),
    )
    _append(
        journal,
        2,
        "EpisodeStarted",
        datetime(2026, 7, 19, 23, 59, tzinfo=IST).astimezone(UTC),
    )
    _append(
        journal,
        3,
        "EpisodeStarted",
        datetime(2026, 7, 20, 0, 0, tzinfo=IST).astimezone(UTC),
    )

    report = OperationalReporter(journal).weekly(
        date(2026, 7, 16),
        tz=IST,
    )

    assert report.period is ReportingPeriod.WEEKLY
    assert report.window_start.date() == monday
    assert report.window_end.date() == monday + timedelta(days=7)
    assert report.counts.episodes == 2
