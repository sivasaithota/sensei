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
    EventAppend,
    HmacFactSigner,
    HmacFactVerifier,
    OperationalJournal,
    OperationsControlPlane,
)
from sensei.portfolio_risk import SafetyControl, SafetyResetAuthority


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
OWNER_SECRET = b"owner-reset-health-test-secret-at-least-32b"
RECON_SECRET = b"reconciliation-health-test-secret-at-least-32b"


def _operations(journal, heartbeats, *, safety_reset_authority=None):
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
        safety_reset_authority=safety_reset_authority,
    )
    return monitor, readiness


def _safety_authority(journal):
    return SafetyResetAuthority(
        journal,
        owner_verifier=HmacFactVerifier({"owner-1": OWNER_SECRET}),
        reconciliation_verifier=HmacFactVerifier(
            {"kernel-reconciler": RECON_SECRET}
        ),
        expected_reconciliation_issuer_id="kernel-reconciler",
    )


def _clean_reconciliation(journal, authority, *, suffix, occurred_at):
    broker_event_id = "event:" + suffix * 64
    snapshot_id = "broker-snapshot:" + suffix * 64
    kernel_events = journal.read_stream("kernel:paper")
    kernel_event = journal.append(
        EventAppend(
            stream_id="kernel:paper",
            event_type="ReconciliationClean",
            payload={
                "snapshot_id": snapshot_id,
                "broker_snapshot_event_id": broker_event_id,
                "issues": (),
            },
            idempotency_key=f"health-kernel-reconciliation-{suffix}",
            expected_version=len(kernel_events),
            occurred_at=occurred_at,
        )
    )
    return authority.attest_reconciliation(
        kernel_event_id=kernel_event.event_id,
        broker_snapshot_event_id=broker_event_id,
        snapshot_id=snapshot_id,
        clean=True,
        issues=(),
        signer=HmacFactSigner("kernel-reconciler", RECON_SECRET),
        occurred_at=occurred_at,
        command_id=f"health-attest-reconciliation-{suffix}",
    )


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


def test_operations_health_fails_closed_on_hash_valid_invalid_reset(tmp_path):
    journal = OperationalJournal(tmp_path / "sensei.sqlite3", clock=lambda: NOW)
    authority = _safety_authority(journal)
    safety = SafetyControl(journal, reset_authority=authority)
    safety.latch(
        reason_code="BROKER_MISMATCH",
        detail="unknown position",
        occurred_at=NOW - timedelta(seconds=30),
        idempotency_key="health-invalid-reset-latch",
    )
    journal.append(
        EventAppend(
            stream_id="safety:global",
            event_type="SafetyReset",
            payload={
                "owner_id": "owner-1",
                "owner_authorization_event_id": "event:" + "a" * 64,
                "authenticated_at": (NOW - timedelta(seconds=20)).isoformat(),
                "reconciliation_observed_at": (
                    NOW - timedelta(seconds=10)
                ).isoformat(),
                "reconciliation_event_id": "event:" + "b" * 64,
            },
            idempotency_key="health-invalid-reset",
            expected_version=1,
            occurred_at=NOW - timedelta(seconds=5),
        )
    )
    monitor, readiness = _operations(
        journal,
        {
            component: (ComponentState.HEALTHY, NOW - timedelta(seconds=5))
            for component in COMPONENT_AGES
        },
        safety_reset_authority=authority,
    )

    assessment = monitor.assess(
        HealthAssessmentInput(now=NOW, readiness=readiness),
        command_id="health-invalid-safety-history",
    )

    assert assessment.state is HealthState.HALTED
    assert "SAFETY_HISTORY_INVALID" in assessment.reason_codes
    assert "SAFETY_LATCHED" in assessment.reason_codes
    assert assessment.new_entries_allowed is False
    assert monitor.verify(assessment, no_later_than=NOW) is True


def test_operations_health_keeps_point_in_time_valid_reset_after_later_truth(
    tmp_path,
):
    journal = OperationalJournal(tmp_path / "sensei.sqlite3", clock=lambda: NOW)
    authority = _safety_authority(journal)
    safety = SafetyControl(journal, reset_authority=authority)
    safety.latch(
        reason_code="BROKER_MISMATCH",
        detail="unknown position",
        occurred_at=NOW - timedelta(seconds=50),
        idempotency_key="health-historical-reset-latch",
    )
    owner = authority.authorize_owner(
        owner_id="owner-1",
        scopes=frozenset({"safety:reset"}),
        signer=HmacFactSigner("owner-1", OWNER_SECRET),
        occurred_at=NOW - timedelta(seconds=40),
        command_id="health-historical-reset-owner",
    )
    clean = _clean_reconciliation(
        journal,
        authority,
        suffix="c",
        occurred_at=NOW - timedelta(seconds=30),
    )
    safety.reset(
        owner,
        clean,
        occurred_at=NOW - timedelta(seconds=20),
        idempotency_key="health-historical-reset",
    )
    _clean_reconciliation(
        journal,
        authority,
        suffix="d",
        occurred_at=NOW - timedelta(seconds=10),
    )
    monitor, readiness = _operations(
        journal,
        {
            component: (ComponentState.HEALTHY, NOW - timedelta(seconds=5))
            for component in COMPONENT_AGES
        },
        safety_reset_authority=authority,
    )

    assessment = monitor.assess(
        HealthAssessmentInput(now=NOW, readiness=readiness),
        command_id="health-historical-reset-valid",
    )

    assert assessment.state is HealthState.HEALTHY
    assert "SAFETY_HISTORY_INVALID" not in assessment.reason_codes
    assert "SAFETY_LATCHED" not in assessment.reason_codes
    _clean_reconciliation(
        journal,
        authority,
        suffix="e",
        occurred_at=NOW + timedelta(seconds=10),
    )
    assert (
        monitor.verify(
            assessment,
            no_later_than=NOW + timedelta(seconds=20),
        )
        is True
    )


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
