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
from sensei.operations import (
    ComponentState,
    HmacFactSigner,
    HmacFactVerifier,
    OperationalJournal,
    OperationsControlPlane,
)


NOW = datetime(2026, 7, 13, 9, 15, tzinfo=timezone.utc)
COMPONENT_AGES = {
    "market-data": timedelta(minutes=5),
    "paper-gateway": timedelta(minutes=2),
    "reconciliation": timedelta(minutes=5),
}
COMPONENT_SECRETS = {
    component: f"{component}-health-test-secret-at-least-32b".encode()
    for component in COMPONENT_AGES
}
MONITOR_SECRET = b"operations-monitor-test-secret-at-least-32b"


def _operations(journal, heartbeats):
    control = OperationsControlPlane(
        journal, HmacFactVerifier(COMPONENT_SECRETS)
    )
    for component, (state, observed_at) in heartbeats.items():
        control.record_heartbeat(
            component=component,
            state=state,
            occurred_at=observed_at,
            command_id=f"heartbeat-{component}",
            detail="fixture",
            signer=HmacFactSigner(component, COMPONENT_SECRETS[component]),
        )
    readiness = control.assess_readiness(
        required_components=COMPONENT_AGES,
        now=NOW,
        command_id="readiness-fixture",
    )
    monitor = OperationsMonitor(
        journal,
        control_plane=control,
        required_components=COMPONENT_AGES,
        maximum_readiness_age=timedelta(minutes=2),
        signer=HmacFactSigner("operations-monitor", MONITOR_SECRET),
        verifier=HmacFactVerifier({"operations-monitor": MONITOR_SECRET}),
    )
    return monitor, readiness


def test_operations_health_fails_closed_and_records_durable_assessment(tmp_path):
    journal = OperationalJournal(tmp_path / "sensei.sqlite3")
    monitor, readiness = _operations(
        journal,
        {
            "market-data": (
                ComponentState.HEALTHY,
                NOW - timedelta(minutes=20),
            ),
            "paper-gateway": (
                ComponentState.HEALTHY,
                NOW - timedelta(seconds=30),
            ),
            "reconciliation": (
                ComponentState.HEALTHY,
                NOW - timedelta(minutes=1),
            ),
        },
    )
    assessment = monitor.assess(
        HealthAssessmentInput(
            now=NOW,
            readiness=readiness,
        ),
        command_id="health-1",
    )

    assert assessment.state is HealthState.HALTED
    assert "MARKET-DATA_STALE" in assessment.reason_codes
    assert assessment.new_entries_allowed is False
    assert assessment.protective_actions_allowed is True
    events = journal.read_stream("operations:health")
    assert events[-1].event_type == "OperationalHealthAssessed"
    assert events[-1].payload["fact"]["state"] == "HALTED"


def test_operations_health_is_unknown_when_required_truth_is_missing(tmp_path):
    journal = OperationalJournal(tmp_path / "sensei.sqlite3")
    monitor, readiness = _operations(journal, {})
    assessment = monitor.assess(
        HealthAssessmentInput(
            now=NOW,
            readiness=readiness,
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
