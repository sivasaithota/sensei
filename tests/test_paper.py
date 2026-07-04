from datetime import date

import pytest

from sensei.agents.thesis import ApprovalRecord, PlaybookCitation, TradeThesis, Verdict


@pytest.fixture(autouse=True)
def isolated_paper_dir(tmp_path, monkeypatch):
    import sensei.paper.engine as eng
    monkeypatch.setattr(eng, "PAPER_DIR", tmp_path)
    monkeypatch.setattr(eng, "POSITIONS_FILE", tmp_path / "positions.json")
    monkeypatch.setattr(eng, "CLOSED_FILE", tmp_path / "closed_trades.jsonl")
    yield


def make_record(approved_levels=("L1", "L2", "L3", "L4"), **thesis_over) -> ApprovalRecord:
    base = dict(
        id="TH-TEST-001", symbol="INFY", direction="BUY",
        entry_zone_low=99.0, entry_zone_high=101.0, quantity=50,
        stop_loss=95.0, targets=[110.0], time_horizon_days=20,
        invalidation="Close below 200 DMA", evidence=["test"],
        playbook_citations=[PlaybookCitation(strategy="momentum_breakout_55",
                                             oos_expectancy_pct=0.68,
                                             oos_hit_rate=0.41, oos_trades=2265)],
        narrative="test thesis",
    )
    base.update(thesis_over)
    rec = ApprovalRecord(thesis=TradeThesis(**base))
    rec.verdicts = [Verdict(level=lv, agent="x", approved=True, reasoning="ok")
                    for lv in approved_levels]
    return rec


def test_unapproved_thesis_cannot_open():
    from sensei.paper.engine import PaperBook
    book = PaperBook(50000)
    rec = make_record(approved_levels=("L1", "L2"))  # chain incomplete
    with pytest.raises(ValueError, match="not fully approved"):
        book.open_from(rec, fill_price=100.0)


def test_open_and_stop_exit():
    from sensei.paper.engine import PaperBook
    book = PaperBook(50000)
    book.open_from(make_record(), fill_price=100.0, today=date(2026, 7, 1))
    assert book.cash == 50000 - 5000
    closed = book.mark_to_market(
        {"INFY": {"open": 96, "high": 97, "low": 94, "close": 95}},
        today=date(2026, 7, 2))
    assert len(closed) == 1
    assert closed[0].exit_reason == "stop"
    assert closed[0].pnl == pytest.approx((95 - 100) * 50)
    assert book.positions == []


def test_target_exit_and_pnl():
    from sensei.paper.engine import PaperBook
    book = PaperBook(50000)
    book.open_from(make_record(), fill_price=100.0, today=date(2026, 7, 1))
    closed = book.mark_to_market(
        {"INFY": {"open": 108, "high": 112, "low": 107, "close": 111}},
        today=date(2026, 7, 5))
    assert closed[0].exit_reason == "target"
    assert closed[0].pnl == pytest.approx((110 - 100) * 50)
    assert book.cash == pytest.approx(50000 - 5000 + 110 * 50)


def test_time_exit():
    from sensei.paper.engine import PaperBook
    book = PaperBook(50000)
    book.open_from(make_record(time_horizon_days=5), fill_price=100.0,
                   today=date(2026, 7, 1))
    closed = book.mark_to_market(
        {"INFY": {"open": 101, "high": 102, "low": 100, "close": 101}},
        today=date(2026, 7, 10))
    assert closed[0].exit_reason == "time"


def test_state_persists_across_restart():
    from sensei.paper.engine import PaperBook
    book = PaperBook(50000)
    book.open_from(make_record(), fill_price=100.0, today=date(2026, 7, 1))
    book2 = PaperBook(50000)  # reload from disk
    assert book2.cash == book.cash
    assert len(book2.positions) == 1
    assert book2.positions[0].symbol == "INFY"


def test_eod_report(tmp_path, monkeypatch):
    import sensei.reporting.eod as eod
    from sensei.paper.engine import PaperBook
    monkeypatch.setattr(eod, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(eod, "AUDIT_LOG", tmp_path / "audit.jsonl")
    book = PaperBook(50000)
    book.open_from(make_record(), fill_price=100.0, today=date(2026, 7, 1))
    path = eod.generate_eod_report(book, today=date(2026, 7, 1))
    text = path.read_text()
    assert "INFY" in text and "Cash" in text
