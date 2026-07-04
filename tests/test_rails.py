from pathlib import Path

import pytest

from sensei.risk.rails import PortfolioState, RiskConfig, RiskRails, TradeProposal

CONFIG = Path(__file__).parent.parent / "config" / "risk.yaml"


@pytest.fixture
def rails() -> RiskRails:
    return RiskRails(RiskConfig.load(CONFIG))


def healthy_state(**over) -> PortfolioState:
    base = dict(cash=50000, open_positions=0, day_pnl=0, week_pnl=0,
                peak_equity=50000, equity=50000)
    base.update(over)
    return PortfolioState(**base)


def good_trade(**over) -> TradeProposal:
    base = dict(symbol="INFY", side="BUY", entry_price=100.0, stop_loss=95.0,
                quantity=90, avg_daily_turnover_inr=1e9)
    base.update(over)
    return TradeProposal(**base)


def test_good_trade_passes(rails):
    assert rails.check(good_trade(), healthy_state()).ok


def test_missing_stop_loss_vetoed(rails):
    res = rails.check(good_trade(stop_loss=None), healthy_state())
    assert not res.ok and any("stop-loss" in v for v in res.violations)


def test_stop_on_wrong_side_vetoed(rails):
    res = rails.check(good_trade(stop_loss=105.0), healthy_state())
    assert not res.ok


def test_risk_per_trade_cap(rails):
    # risk = 10 * 200 = 2000 > 1000 (2% of 50k)
    res = rails.check(good_trade(entry_price=100, stop_loss=90, quantity=200,
                                 ), healthy_state())
    assert any("risk per trade" in v for v in res.violations)


def test_position_size_cap(rails):
    # notional 15000 > 10000 (20% of 50k); keep risk small (tight stop)
    res = rails.check(good_trade(entry_price=150, stop_loss=149, quantity=100),
                      healthy_state())
    assert any("position size" in v for v in res.violations)


def test_max_open_positions(rails):
    res = rails.check(good_trade(), healthy_state(open_positions=5))
    assert any("max concurrent" in v for v in res.violations)


def test_insufficient_cash(rails):
    res = rails.check(good_trade(), healthy_state(cash=1000))
    assert any("insufficient cash" in v for v in res.violations)


def test_liquidity_floor(rails):
    res = rails.check(good_trade(avg_daily_turnover_inr=1e6), healthy_state())
    assert any("liquidity" in v for v in res.violations)


def test_gsm_asm_ban(rails):
    res = rails.check(good_trade(surveillance_stage=2), healthy_state())
    assert any("surveillance" in v for v in res.violations)


def test_intraday_product_banned_in_v1(rails):
    res = rails.check(good_trade(product="MIS"), healthy_state())
    assert any("product MIS" in v for v in res.violations)


def test_daily_kill_switch(rails):
    res = rails.check(good_trade(), healthy_state(day_pnl=-2500))
    assert any("daily loss kill-switch" in v for v in res.violations)


def test_weekly_breaker(rails):
    res = rails.check(good_trade(), healthy_state(week_pnl=-5000))
    assert any("weekly circuit breaker" in v for v in res.violations)


def test_drawdown_floor(rails):
    res = rails.check(good_trade(), healthy_state(peak_equity=100000, equity=60000))
    assert any("drawdown floor" in v for v in res.violations)


def test_owner_kill_switch(rails):
    res = rails.check(good_trade(), healthy_state(halted=True))
    assert any("halted" in v for v in res.violations)
