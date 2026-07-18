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


def test_legacy_paper_engine_is_explicitly_long_only():
    from sensei.paper.engine import PaperBook
    book = PaperBook(50000)
    with pytest.raises(ValueError, match="long-only"):
        book.open_from(
            make_record(direction="SELL", stop_loss=105.0, targets=[90.0]),
            fill_price=100.0,
        )


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


def test_gap_through_stop_fills_at_open_not_the_unavailable_stop():
    from sensei.paper.engine import PaperBook
    book = PaperBook(50000)
    book.open_from(make_record(), fill_price=100.0, today=date(2026, 7, 1))
    closed = book.mark_to_market(
        {"INFY": {"open": 90, "high": 92, "low": 88, "close": 89}},
        today=date(2026, 7, 2),
    )
    assert closed[0].exit_reason == "stop_gap"
    assert closed[0].exit_price == 90
    assert closed[0].pnl == pytest.approx((90 - 100) * 50)


def test_realistic_exit_is_partial_adverse_and_charge_aware():
    from sensei.execution.nse import NseExecutionModel
    from sensei.paper.engine import PaperBook

    book = PaperBook(
        50000,
        execution_model=NseExecutionModel(
            max_volume_participation_bps=100,
            base_impact_bps=5,
        ),
    )
    book.open_from(make_record(), fill_price=100.0, today=date(2026, 7, 1))

    closed = book.mark_to_market(
        {"INFY": {
            "open": 90, "high": 92, "low": 88, "close": 89,
            "volume": 2_000,
        }},
        today=date(2026, 7, 2),
    )

    assert closed[0].quantity == 20
    assert closed[0].exit_price < 90
    assert closed[0].charges > 0
    assert closed[0].pnl == pytest.approx(
        closed[0].gross_pnl - closed[0].charges
    )
    assert book.positions[0].quantity == 30


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
    bar = {"INFY": {"open": 101, "high": 102, "low": 100, "close": 101}}
    # Holding horizon is exchange sessions, not elapsed calendar days.
    for session in (
        date(2026, 7, 2),
        date(2026, 7, 3),
        date(2026, 7, 6),
    ):
        assert book.mark_to_market(bar, today=session) == []
    closed = book.mark_to_market(bar, today=date(2026, 7, 7))
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
