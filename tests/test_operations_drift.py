from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sensei.learning.drift import (
    DriftBaseline,
    DriftMonitor,
    DriftState,
    ForwardPerformance,
)
from sensei.operations.health import (
    HealthAssessmentInput,
    HealthState,
    OperationsMonitor,
)
from sensei.operations.journal import OperationalJournal


NOW = datetime(2026, 7, 13, 9, 15, tzinfo=timezone.utc)


def test_operations_health_fails_closed_and_records_durable_assessment(tmp_path):
    journal = OperationalJournal(tmp_path / "sensei.sqlite3")
    monitor = OperationsMonitor(journal)
    assessment = monitor.assess(
        HealthAssessmentInput(
            now=NOW,
            market_data_watermark=NOW - timedelta(minutes=20),
            broker_snapshot_at=NOW - timedelta(seconds=30),
            last_reconciliation_at=NOW - timedelta(minutes=1),
            maximum_market_data_age=timedelta(minutes=5),
            maximum_broker_age=timedelta(minutes=2),
            maximum_reconciliation_age=timedelta(minutes=5),
            session_active=True,
            safety_latched=False,
            unprotected_quantity=0,
            unknown_broker_objects=0,
        ),
        command_id="health-1",
    )

    assert assessment.state is HealthState.HALTED
    assert "MARKET_DATA_STALE" in assessment.reason_codes
    assert assessment.new_entries_allowed is False
    assert assessment.protective_actions_allowed is True
    events = journal.read_stream("operations:health")
    assert events[-1].event_type == "OperationalHealthAssessed"
    assert events[-1].payload["state"] == "HALTED"


def test_operations_health_is_unknown_when_required_truth_is_missing(tmp_path):
    monitor = OperationsMonitor(OperationalJournal(tmp_path / "sensei.sqlite3"))
    assessment = monitor.assess(
        HealthAssessmentInput(
            now=NOW,
            market_data_watermark=None,
            broker_snapshot_at=None,
            last_reconciliation_at=None,
            maximum_market_data_age=timedelta(minutes=5),
            maximum_broker_age=timedelta(minutes=2),
            maximum_reconciliation_age=timedelta(minutes=5),
            session_active=False,
            safety_latched=False,
            unprotected_quantity=0,
            unknown_broker_objects=0,
        ),
        command_id="health-missing",
    )
    assert assessment.state is HealthState.UNKNOWN
    assert assessment.new_entries_allowed is False


def test_drift_is_version_pinned_and_unknown_until_sample_is_sufficient(tmp_path):
    monitor = DriftMonitor(OperationalJournal(tmp_path / "sensei.sqlite3"))
    baseline = DriftBaseline(
        plan_id="plan:abc",
        plan_version=2,
        mean_return=Decimal("0.0200"),
        hit_rate=Decimal("0.60"),
        sample_size=100,
        minimum_forward_samples=5,
        maximum_mean_shift=Decimal("0.0100"),
        maximum_hit_rate_shift=Decimal("0.15"),
        evidence_ref="dossier:confirmed-abc",
    )

    insufficient = monitor.assess(
        baseline,
        ForwardPerformance(
            plan_id="plan:abc",
            plan_version=2,
            episode_returns=(Decimal("0.01"), Decimal("-0.01")),
        ),
        now=NOW,
        command_id="drift-1",
    )
    assert insufficient.state is DriftState.UNKNOWN
    assert insufficient.action == "COLLECT_MORE_EVIDENCE"

    drifted = monitor.assess(
        baseline,
        ForwardPerformance(
            plan_id="plan:abc",
            plan_version=2,
            episode_returns=(
                Decimal("-0.03"),
                Decimal("-0.02"),
                Decimal("-0.01"),
                Decimal("-0.04"),
                Decimal("0.01"),
            ),
        ),
        now=NOW + timedelta(days=5),
        command_id="drift-2",
    )
    assert drifted.state is DriftState.DRIFTED
    assert drifted.action == "REVIEW_ONLY"
    assert drifted.can_change_strategy is False
