"""Regression: a fill that exhausts cash/slots must skip-and-retain the
rest of the queue, never crash mid-run (2026-07-08 MOTHERSON incident)."""

from datetime import date

import pytest

from tests.test_openexec import isolated_dirs  # reuse fixtures  # noqa: F401
from tests.test_paper import make_record


def test_insufficient_cash_skips_not_crashes(monkeypatch):
    import sensei.loop.openexec as oe
    # order 1: consumes most of the 50k (400 * 100.0 = 40k)
    oe.queue_order(make_record(id="TH-A", symbol="AAA", quantity=400,
                               entry_zone_low=99.0, entry_zone_high=101.0))
    # order 2: needs 20k, only ~10k left -> must be skipped and retained
    oe.queue_order(make_record(id="TH-B", symbol="BBB", quantity=200,
                               entry_zone_low=99.0, entry_zone_high=101.0))
    monkeypatch.setattr(oe, "live_price", lambda s: 100.0)
    res = oe.execute_pending(today=date(2026, 7, 8))   # must not raise
    assert [f["symbol"] for f in res["filled"]] == ["AAA"]
    assert len(res["skipped"]) == 1
    assert "insufficient cash" in res["skipped"][0]["reason"]
    pending = oe.load_pending()
    assert len(pending) == 1   # BBB retained for retry after something closes
    assert pending[0]["record"]["thesis"]["symbol"] == "BBB"


def test_max_positions_skips_and_retains(monkeypatch):
    import sensei.loop.openexec as oe
    from sensei.paper.engine import PaperBook
    book = PaperBook(50000)
    for i in range(5):  # fill all 5 slots cheaply
        book.open_from(make_record(id=f"TH-{i}", symbol=f"SYM{i}", quantity=5),
                       fill_price=100.0, today=date(2026, 7, 7))
    oe.queue_order(make_record(id="TH-X", symbol="XXX", quantity=5))
    monkeypatch.setattr(oe, "live_price", lambda s: 100.0)
    res = oe.execute_pending(today=date(2026, 7, 8))
    assert res["filled"] == []
    assert "max positions" in res["skipped"][0]["reason"]
    assert len(oe.load_pending()) == 1
