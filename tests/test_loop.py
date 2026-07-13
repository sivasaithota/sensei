from pathlib import Path

import pytest

from sensei.loop.scanner import size_position
from sensei.risk.rails import RiskConfig

CONFIG = Path(__file__).parent.parent / "config" / "risk.yaml"


@pytest.fixture
def cfg():
    return RiskConfig.load(CONFIG)


def test_sizing_respects_risk_cap(cfg):
    # 5% stop on a ₹100 stock: risk cap (1000/5=200) vs notional cap (10000/100=100)
    qty = size_position(100.0, 95.0, cfg)
    assert qty == 100  # notional cap binds
    assert qty * (100 - 95) <= cfg.capital * cfg.max_risk_per_trade_pct / 100 + 1e-9


def test_sizing_risk_cap_binds_with_wide_stop(cfg):
    # 20% stop on ₹100: risk cap 1000/20 = 50 < notional cap 100
    qty = size_position(100.0, 80.0, cfg)
    assert qty == 50
    assert qty * 20 == 1000


def test_sizing_expensive_stock(cfg):
    # ₹30,000 stock: notional cap 10000/30000 → 0 shares, correctly untradeable
    assert size_position(30000.0, 28500.0, cfg) == 0


def test_sizing_invalid_stop(cfg):
    assert size_position(100.0, 100.0, cfg) == 0
    assert size_position(100.0, 105.0, cfg) == 0


def test_sized_position_always_passes_rails(cfg):
    """Property: any scanner-sized position must clear the per-trade rails."""
    from sensei.risk.rails import PortfolioState, RiskRails, TradeProposal
    rails = RiskRails(cfg)
    state = PortfolioState(cash=cfg.capital, open_positions=0,
                           peak_equity=cfg.capital, equity=cfg.capital)
    for price in (12.0, 87.5, 240.0, 1057.0, 4300.0):
        for stop_pct in (2.0, 5.0, 8.0):
            stop = price * (1 - stop_pct / 100)
            qty = size_position(price, stop, cfg)
            if qty == 0:
                continue
            res = rails.check(TradeProposal(symbol="X", side="BUY", entry_price=price,
                                            stop_loss=stop, quantity=qty,
                                            avg_daily_turnover_inr=1e9,
                                            surveillance_stage=0), state)
            assert res.ok, f"price={price} stop_pct={stop_pct}: {res.violations}"


def test_kill_switch_blocks_new_trades(tmp_path, monkeypatch):
    import sensei.loop.daily as daily
    monkeypatch.setattr(daily, "KILL_FILE", tmp_path / "KILL")
    assert not daily.kill_switch_active()
    (tmp_path / "KILL").write_text("2026-07-05")
    assert daily.kill_switch_active()
