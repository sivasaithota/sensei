from datetime import datetime, timedelta, timezone

from sensei.operations.control_plane import (
    ComponentState,
    OperationsControlPlane,
)
from sensei.operations.journal import OperationalJournal


NOW = datetime(2026, 7, 13, 9, 15, tzinfo=timezone.utc)


def test_readiness_is_derived_from_durable_fresh_component_heartbeats(tmp_path):
    journal = OperationalJournal(tmp_path / "sensei.sqlite3")
    control = OperationsControlPlane(journal)
    for component in ("market-data", "paper-gateway", "reconciliation"):
        control.record_heartbeat(
            component=component,
            state=ComponentState.HEALTHY,
            occurred_at=NOW,
            command_id=f"heartbeat-{component}",
            detail="ok",
        )

    readiness = control.assess_readiness(
        required_components={
            "market-data": timedelta(minutes=1),
            "paper-gateway": timedelta(minutes=1),
            "reconciliation": timedelta(minutes=1),
        },
        now=NOW + timedelta(seconds=30),
        command_id="readiness-1",
    )

    assert readiness.ready is True
    assert readiness.reason_codes == ()
    assert len(readiness.evidence_event_ids) == 3
    event = journal.read_stream("operations:readiness")[-1]
    assert event.event_type == "OperationsReadinessAssessed"
    assert event.payload["ready"] is True


def test_missing_stale_or_degraded_component_fails_readiness_closed(tmp_path):
    journal = OperationalJournal(tmp_path / "sensei.sqlite3")
    control = OperationsControlPlane(journal)
    control.record_heartbeat(
        component="market-data",
        state=ComponentState.DEGRADED,
        occurred_at=NOW,
        command_id="heartbeat-data",
        detail="vendor lag",
    )

    readiness = control.assess_readiness(
        required_components={
            "market-data": timedelta(seconds=10),
            "reconciliation": timedelta(minutes=1),
        },
        now=NOW + timedelta(seconds=30),
        command_id="readiness-failed",
    )

    assert readiness.ready is False
    assert "MARKET-DATA_STALE" in readiness.reason_codes
    assert "MARKET-DATA_DEGRADED" in readiness.reason_codes
    assert "RECONCILIATION_MISSING" in readiness.reason_codes
