from datetime import date

import pytest

from tests.test_paper import make_record  # reuse the approved-record factory


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    import sensei.loop.openexec as oe
    import sensei.paper.engine as eng
    import sensei.loop.daily as daily
    monkeypatch.setattr(oe, "PENDING_FILE", tmp_path / "pending.json")
    monkeypatch.setattr(eng, "PAPER_DIR", tmp_path)
    monkeypatch.setattr(eng, "POSITIONS_FILE", tmp_path / "positions.json")
    monkeypatch.setattr(eng, "CLOSED_FILE", tmp_path / "closed.jsonl")
    monkeypatch.setattr(daily, "KILL_FILE", tmp_path / "KILL")
    import sensei.data.events as events
    monkeypatch.setattr(events, "CACHE_FILE", tmp_path / "earnings_cache.json")
    # Verified-clear event status; unknown dates now intentionally fail closed.
    monkeypatch.setattr(events, "next_earnings_date", lambda s: date(2026, 8, 1))
    yield


def test_unapproved_cannot_queue():
    from sensei.loop.openexec import queue_order
    rec = make_record(approved_levels=("L1",))
    with pytest.raises(ValueError, match="not fully approved"):
        queue_order(rec)


def test_fill_within_entry_zone(monkeypatch):
    import sensei.loop.openexec as oe
    oe.queue_order(make_record())  # entry zone 99-101
    monkeypatch.setattr(oe, "live_price", lambda s: 100.5)
    res = oe.execute_pending(today=date(2026, 7, 6))
    assert len(res["filled"]) == 1
    assert res["filled"][0]["fill"] == 100.5
    assert oe.load_pending() == []


def test_gap_outside_zone_drops_order(monkeypatch):
    import sensei.loop.openexec as oe
    oe.queue_order(make_record())
    monkeypatch.setattr(oe, "live_price", lambda s: 107.0)  # gapped +6%
    res = oe.execute_pending(today=date(2026, 7, 6))
    assert res["filled"] == []
    assert "gapped outside entry zone" in res["skipped"][0]["reason"]
    assert oe.load_pending() == []  # dropped, not retained


def test_governed_executor_drops_order_without_paper_strategy_authorization(monkeypatch):
    import sensei.loop.openexec as oe
    oe.queue_order(make_record())
    monkeypatch.setattr(oe, "live_price", lambda s: 100.0)

    res = oe.execute_pending(
        today=date(2026, 7, 6),
        allowed_strategy_names=frozenset(),
    )

    assert res["filled"] == []
    assert "not authorized at governed PAPER" in res["skipped"][0]["reason"]
    assert oe.load_pending() == []


def test_no_quote_retains_order(monkeypatch):
    import sensei.loop.openexec as oe
    oe.queue_order(make_record())
    monkeypatch.setattr(oe, "live_price", lambda s: None)
    res = oe.execute_pending(today=date(2026, 7, 6))
    assert res["filled"] == []
    assert len(oe.load_pending()) == 1  # retained for retry


def test_stale_order_dropped(monkeypatch):
    import sensei.loop.openexec as oe
    import json
    oe.queue_order(make_record())
    pending = oe.load_pending()
    pending[0]["queued"] = "2026-06-01"
    oe.PENDING_FILE.write_text(json.dumps(pending))
    monkeypatch.setattr(oe, "live_price", lambda s: 100.0)
    res = oe.execute_pending(today=date(2026, 7, 6))
    assert res["filled"] == []
    assert "stale" in res["skipped"][0]["reason"]


def test_kill_switch_blocks_fills(monkeypatch, tmp_path):
    import sensei.loop.openexec as oe
    import sensei.loop.daily as daily
    oe.queue_order(make_record())
    daily.KILL_FILE.write_text("halt")
    monkeypatch.setattr(oe, "live_price", lambda s: 100.0)
    res = oe.execute_pending(today=date(2026, 7, 6))
    assert res["filled"] == []
    assert "kill-switch" in res["skipped"][0]["reason"]
    assert len(oe.load_pending()) == 1  # retained, not dropped
