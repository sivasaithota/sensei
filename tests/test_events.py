from datetime import date

import pytest

import sensei.data.events as events
from sensei.data.regime import Regime


@pytest.fixture(autouse=True)
def no_network(tmp_path, monkeypatch):
    monkeypatch.setattr(events, "CACHE_FILE", tmp_path / "cache.json")


def test_blocked_inside_window(monkeypatch):
    monkeypatch.setattr(events, "next_earnings_date", lambda s: date(2026, 7, 30))
    for day in (date(2026, 7, 28), date(2026, 7, 30), date(2026, 7, 31)):
        blocked, reason = events.in_no_trade_window("X", on=day)
        assert blocked and "no-trade window" in reason


def test_allowed_outside_window(monkeypatch):
    monkeypatch.setattr(events, "next_earnings_date", lambda s: date(2026, 7, 30))
    blocked, reason = events.in_no_trade_window("X", on=date(2026, 7, 20))
    assert not blocked and "next earnings 2026-07-30" in reason


def test_unknown_earnings_allowed_but_flagged(monkeypatch):
    monkeypatch.setattr(events, "next_earnings_date", lambda s: None)
    blocked, reason = events.in_no_trade_window("X", on=date(2026, 7, 20))
    assert not blocked and reason == "earnings date unknown"


def test_regime_labels():
    strong = Regime(india_vix=12.0, pct_above_200dma=70, pct_golden_cross=65, n_symbols=100)
    assert "risk-on" in strong.label
    weak = Regime(india_vix=25.0, pct_above_200dma=30, pct_golden_cross=25, n_symbols=100)
    assert "risk-off" in weak.label and "elevated volatility" in weak.label
    mixed = Regime(india_vix=None, pct_above_200dma=50, pct_golden_cross=45, n_symbols=100)
    assert "mixed" in mixed.label
    assert "n/a" in mixed.summary()
