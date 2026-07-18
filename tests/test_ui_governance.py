from datetime import datetime, timezone

from sensei.operations import EventAppend, OperationalJournal


NOW = datetime(2026, 7, 16, tzinfo=timezone.utc)


def append(journal, stream, event_type, payload, version=0):
    return journal.append(EventAppend(
        stream_id=stream, event_type=event_type, payload=payload,
        idempotency_key=f"test:{stream}:{version}", expected_version=version,
        occurred_at=NOW,
    ))


def test_dashboard_reports_governed_stage_shadow_and_position_reconciliation(tmp_path, monkeypatch):
    import sensei.ui.server as ui
    monkeypatch.setattr(ui, "DATA_DIR", tmp_path)
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    append(journal, "plan:test", "StrategyPlanRegistered", {
        "plan_id": "sha256:" + "a" * 64, "source_rule_name": "trend"
    })
    append(journal, "lifecycle:test", "StrategyLifecycleTransitioned", {
        "plan_version_id": "sha256:" + "a" * 64, "target_stage": "shadow"
    })
    append(journal, "shadow:test", "ShadowSessionObserved", {
        "plan_id": "sha256:" + "a" * 64
    })
    append(journal, "legacy-paper-position-adoption", "LegacyPaperPositionsAdopted", {})
    append(journal, "legacy-paper-position-reconciliation", "LegacyPaperPositionsReconciled", {})

    status = ui._governance_status()
    page = ui.render()

    assert status["journal_ok"] is True
    assert status["plans"][0]["stage"] == "shadow"
    assert status["plans"][0]["shadow_sessions"] == 1
    assert status["positions_reconciled"] is True
    assert "Strategy control room" in page
    assert "1 / 5 sessions" in page
    assert "BLOCKED FROM PAPER ENTRY" in page
    assert "Strategy authorization" in page
