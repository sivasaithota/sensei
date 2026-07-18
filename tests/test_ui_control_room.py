from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from sensei.operations import EventAppend, OperationalJournal


NOW = datetime(2026, 7, 17, 13, 0, tzinfo=timezone.utc)


def _append(journal, stream, event_type, payload, version=0):
    journal.append(EventAppend(
        stream_id=stream,
        event_type=event_type,
        payload=payload,
        idempotency_key=f"test:{stream}:{version}",
        expected_version=version,
        occurred_at=NOW,
    ))


def test_dashboard_model_explains_position_exit_plan_and_distance(tmp_path, monkeypatch):
    import sensei.ui.server as ui

    monkeypatch.setattr(ui, "DATA_DIR", tmp_path)
    paper = tmp_path / "paper"
    prices = tmp_path / "prices"
    paper.mkdir()
    prices.mkdir()
    (paper / "positions.json").write_text(json.dumps({
        "cash": 40_000,
        "positions": [{
            "thesis_id": "thesis:1", "symbol": "INFY", "direction": "BUY",
            "entry_price": 100.0, "quantity": 10, "stop_loss": 95.0,
            "targets": [112.0], "opened": "2026-07-10", "max_hold_days": 20,
            "sessions_held": 6, "last_marked_session": "2026-07-17",
            "narrative": "Trend remains intact while price holds the stop.",
        }],
    }))
    pd.DataFrame(
        {"close": [104.0]}, index=pd.DatetimeIndex(["2026-07-17"])
    ).to_parquet(prices / "INFY.parquet")

    model = ui.dashboard_model()
    position = model["positions"][0]

    assert position["unrealized_pnl"] == 40.0
    assert position["stop_distance_pct"] == 8.65
    assert position["target_distance_pct"] == 7.69
    assert position["sessions_remaining"] == 14
    assert position["data_session"] == "2026-07-17"
    assert position["exit_plan"] == "Stop ₹95.00 · Target ₹112.00 · Time exit in 14 sessions"


def test_control_room_surfaces_scheduler_ingestion_and_strategy_progress(tmp_path, monkeypatch):
    import sensei.ui.server as ui

    monkeypatch.setattr(ui, "DATA_DIR", tmp_path)
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    _append(journal, "plan:test", "StrategyPlanRegistered", {
        "plan_id": "sha256:" + "a" * 64, "source_rule_name": "trend"
    })
    _append(journal, "lifecycle:test", "StrategyLifecycleTransitioned", {
        "plan_version_id": "sha256:" + "a" * 64, "target_stage": "shadow"
    })
    _append(journal, "shadow:test", "ShadowSessionObserved", {
        "plan_id": "sha256:" + "a" * 64,
        "evaluations": [
            {"instrument_id": f"NSE:S{index}", "trace": {"action": "enter_long"}}
            for index in range(7)
        ],
    })
    _append(journal, "market-data:2026-07-17", "MarketDataIngestionCompleted", {
        "session": "2026-07-17", "completeness": 0.998,
        "eligible_symbols": ["INFY"], "failed_symbols": ["JBCHEPHARM"],
        "excluded_symbols": [],
    })
    _append(journal, "scheduler:test", "SchedulerTaskCompleted", {
        "task_kind": "end_of_day_session", "reason_codes": ["PAPER_EOD_SESSION_COMPLETED"]
    })

    model = ui.dashboard_model()
    page = ui.render()
    research = ui.render("/research")

    assert model["operations"]["ingestion"]["completeness"] == 0.998
    assert model["operations"]["ingestion"]["failed_symbols"] == ["JBCHEPHARM"]
    assert model["strategies"][0]["shadow_sessions"] == 1
    assert model["strategies"][0]["signals"] == 7
    assert "Trading control room" in page
    assert "Position &amp; exit command center" in page
    assert "99.8%" in page
    assert "1 / 5 sessions" in research


def test_control_room_flags_stale_marks_and_unhealthy_ingestion(tmp_path, monkeypatch):
    import sensei.ui.server as ui

    monkeypatch.setattr(ui, "DATA_DIR", tmp_path)
    paper, prices = tmp_path / "paper", tmp_path / "prices"
    paper.mkdir()
    prices.mkdir()
    (paper / "positions.json").write_text(json.dumps({
        "cash": 49_000,
        "positions": [{
            "symbol": "INFY", "direction": "BUY", "entry_price": 100,
            "quantity": 10, "stop_loss": 95, "targets": [110],
            "opened": "2026-07-10", "max_hold_days": 20,
        }],
    }))
    pd.DataFrame(
        {"close": [101]}, index=pd.DatetimeIndex(["2026-07-16"])
    ).to_parquet(prices / "INFY.parquet")
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    _append(journal, "market-data:2026-07-17", "MarketDataIngestionCompleted", {
        "session": "2026-07-17", "completeness": 0.412,
        "eligible_symbols": ["INFY"], "failed_symbols": ["TCS"],
        "excluded_symbols": ["VEDL"],
    })

    model = ui.dashboard_model()
    page = ui.render()

    assert model["positions"][0]["mark_state"] == "STALE"
    assert any("Stale market marks: INFY" in alert for alert in model["alerts"])
    assert any("41.2%" in alert for alert in model["alerts"])
    assert "TCS" in page and "VEDL" in page
    assert 'class="ingestion-health bad"' in page


def test_control_room_uses_configured_shadow_policy_and_ist_schedule(tmp_path, monkeypatch):
    import sensei.ui.server as ui

    monkeypatch.setattr(ui, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(ui, "CONFIG_DIR", tmp_path / "config")
    ui.CONFIG_DIR.mkdir()
    (ui.CONFIG_DIR / "scheduler.json").write_text(json.dumps({
        "shadow_trial": {"minimum_sessions": 7, "minimum_data_completeness": 0.99},
        "closed_dates": [],
    }))
    journal = OperationalJournal(ui.DATA_DIR / "operations.sqlite3")
    _append(journal, "plan:test", "StrategyPlanRegistered", {
        "plan_id": "sha256:" + "a" * 64, "source_rule_name": "trend"
    })
    _append(journal, "scheduler:test", "SchedulerTaskCompleted", {
        "reason_codes": ["PAPER_EOD_SESSION_COMPLETED"]
    })

    model = ui.dashboard_model(
        now=datetime(2026, 7, 18, 8, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
    )

    assert model["strategies"][0]["shadow_target"] == 7
    assert model["operations"]["scheduler"]["occurred_at_display"] == "17 Jul · 18:30 IST"
    assert model["next_action"]["label"] == "Entry session"
    assert model["next_action"]["when"] == "Mon 20 Jul · 09:20 IST"

    after_eod = ui.dashboard_model(
        now=datetime(2026, 7, 17, 18, 40, tzinfo=ZoneInfo("Asia/Kolkata"))
    )
    assert after_eod["next_action"]["label"] == "Passive shadow monitor"
    assert after_eod["next_action"]["when"] == "Fri 17 Jul · 19:30 IST"


def test_missing_mark_never_fabricates_current_valuation(tmp_path, monkeypatch):
    import sensei.ui.server as ui

    monkeypatch.setattr(ui, "DATA_DIR", tmp_path)
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "positions.json").write_text(json.dumps({
        "cash": 0,
        "positions": [{
            "symbol": "INFY", "direction": "BUY", "entry_price": 100,
            "quantity": 10, "stop_loss": 95, "targets": [110],
            "opened": "2026-07-10", "max_hold_days": 20,
        }],
    }))

    model = ui.dashboard_model()
    page = ui.render()

    position = model["positions"][0]
    assert position["mark"] is None
    assert position["market_value"] is None
    assert position["unrealized_pnl"] is None
    assert model["summary"]["equity"] == 0
    assert model["summary"]["unpriced_positions"] == 1
    assert "No current valuation" in page
    assert "Percentage unavailable" in page
    assert "Cost basis ₹1,000" in page
    assert "One or more holdings are unpriced" in page


def test_stalled_browser_connection_cannot_block_dashboard_requests(tmp_path, monkeypatch):
    import sensei.ui.server as ui

    monkeypatch.setattr(ui, "DATA_DIR", tmp_path)
    server = ui.create_server(port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    stalled = socket.create_connection(server.server_address, timeout=1)
    try:
        started = time.perf_counter()
        with urllib.request.urlopen(
            f"http://127.0.0.1:{server.server_port}/", timeout=1
        ) as response:
            body = response.read().decode()
        elapsed = time.perf_counter() - started
    finally:
        stalled.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=1)

    assert response.status == 200
    assert "Trading control room" in body
    assert elapsed < 0.75
