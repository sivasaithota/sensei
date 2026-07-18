from datetime import datetime, timezone

from sensei.operations import EventAppend, OperationalJournal
from sensei.reporting.paper_readiness import ReadinessState, build_readiness_report


NOW = datetime(2026, 7, 18, 3, 0, tzinfo=timezone.utc)
PLAN = "sha256:" + "a" * 64


def _append(journal, stream, event_type, payload):
    version = len(journal.read_stream(stream))
    return journal.append(EventAppend(
        stream_id=stream,
        event_type=event_type,
        payload=payload,
        idempotency_key=f"test:{stream}:{version}",
        expected_version=version,
        occurred_at=NOW,
    ))


def _journal(tmp_path, *, stage="paper", completeness=0.998, halted=False):
    paper = tmp_path / "paper"
    paper.mkdir(exist_ok=True)
    (paper / "positions.json").write_text('{"cash":50000,"positions":[]}')
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    _append(journal, "plan:test", "StrategyPlanRegistered", {
        "plan_id": PLAN, "source_rule_name": "trend",
    })
    _append(journal, "lifecycle:test", "StrategyLifecycleTransitioned", {
        "plan_version_id": PLAN, "target_stage": stage,
    })
    _append(journal, "market-data:test", "MarketDataIngestionCompleted", {
        "session": "2026-07-17", "completeness": completeness,
        "eligible_symbols": ["INFY"], "failed_symbols": [],
    })
    _append(
        journal,
        "scheduler:test",
        "SchedulerTaskHalted" if halted else "SchedulerTaskCompleted",
        {"reason_codes": ["TEST_HALT"] if halted else ["PAPER_EOD_SESSION_COMPLETED"]},
    )
    return journal


def test_ready_certificate_is_structurally_read_only(tmp_path):
    journal = _journal(tmp_path)
    before = len(journal.read_all())

    report = build_readiness_report(
        tmp_path / "operations.sqlite3",
        as_of=NOW,
        kill_switch_path=tmp_path / "KILL",
    )

    assert report.state is ReadinessState.READY
    assert report.blockers == ()
    assert len(journal.read_all()) == before


def test_shadow_only_is_blocked_with_exact_reason(tmp_path):
    _journal(tmp_path, stage="shadow")

    report = build_readiness_report(
        tmp_path / "operations.sqlite3",
        as_of=NOW,
        kill_switch_path=tmp_path / "KILL",
    )

    assert report.state is ReadinessState.BLOCKED
    assert "NO_AUTHORIZED_PAPER_STRATEGY" in report.blockers


def test_operational_faults_are_reported_independently(tmp_path):
    _journal(tmp_path, completeness=0.5, halted=True)
    (tmp_path / "KILL").write_text("halted")

    report = build_readiness_report(
        tmp_path / "operations.sqlite3",
        as_of=NOW,
        kill_switch_path=tmp_path / "KILL",
    )

    assert set(report.blockers) >= {
        "KILL_SWITCH_ACTIVE",
        "LATEST_SCHEDULER_TASK_HALTED",
        "MARKET_DATA_COMPLETENESS_BELOW_POLICY",
    }


def test_unprotected_position_blocks_entry(tmp_path):
    _journal(tmp_path)
    (tmp_path / "paper" / "positions.json").write_text(
        '{"cash":40000,"positions":[{"symbol":"INFY","direction":"BUY",'
        '"quantity":10,"entry_price":100,"stop_loss":105}]}'
    )

    report = build_readiness_report(
        tmp_path / "operations.sqlite3", as_of=NOW,
        kill_switch_path=tmp_path / "KILL",
    )

    assert "UNPROTECTED_OPEN_POSITION" in report.blockers
    assert "LEGACY_POSITIONS_NOT_RECONCILED" in report.blockers


def test_missing_scheduler_config_blocks_readiness(tmp_path):
    _journal(tmp_path)
    report = build_readiness_report(
        tmp_path / "operations.sqlite3", as_of=NOW,
        config_path=tmp_path / "missing.json",
        kill_switch_path=tmp_path / "KILL",
    )
    assert "SCHEDULER_CONFIG_UNAVAILABLE" in report.blockers
