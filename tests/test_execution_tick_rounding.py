from dataclasses import replace
from decimal import Decimal

import pandas as pd
import pytest

from sensei.backtest.costs import delivery_charge
from sensei.backtest.portfolio_campaign import PortfolioCampaignConfig, _entry_bracket, run_portfolio_campaign


def test_decimal_brackets_preserve_exact_tick_and_round_in_declared_directions():
    assert _entry_bracket(100, 0, 5, 12, 5) == (100., 95., 112.)
    entry, stop, target = _entry_bracket(2429.75, 10, 5, 12, 5)
    assert (entry, stop, target) == (2432.2, 2310.55, 2724.1)
    assert Decimal(str(entry)) >= Decimal('2429.75') * Decimal('1.001')
    assert Decimal(str(stop)) <= Decimal(str(entry)) * Decimal('.95')
    assert Decimal(str(target)) >= Decimal(str(entry)) * Decimal('1.12')
    assert all(Decimal(str(v)) % Decimal('.05') == 0 for v in (entry, stop, target))


def test_tick_sizing_uses_rounded_risk_and_preserves_cash():
    dates = pd.bdate_range('2024-01-01', periods=3)
    bars = pd.DataFrame(dict(open=[100.01] * 3, high=[101.] * 3, low=[99., 99., 90.],
        close=[100.] * 3, volume=100000.), index=dates)
    config = PortfolioCampaignConfig(capital=10000, max_position_pct=100,
        max_risk_per_trade_pct=1, entry_slippage_bps=10,
        cost_model='current_delivery_schedule', execution_tick_paise=5)
    common = dict(frames={'A': bars}, strategies={'forced': dict(fn=lambda f: pd.Series(
        [True, False, False], index=f.index), stop_pct=5, target_pct=12, max_hold_days=10)}, config=config)
    result = run_portfolio_campaign(**common)
    trade = result.trades[0]
    assert trade.entry_price == 100.15 and trade.exit_price == 95.10
    def risk(q):
        return q * (100.15 - 95.10) + delivery_charge(q * 100.15, 'BUY') + delivery_charge(q * 95.10, 'SELL')
    assert risk(trade.quantity) <= 100 < risk(trade.quantity + 1)
    assert all(point.cash >= 0 for point in result.equity_curve)
    control = run_portfolio_campaign(**{**common, 'config': replace(config, execution_tick_paise=None)})
    assert control.trades[0].entry_price == 100.01 * 1.001
    assert control.experiment_id != result.experiment_id


@pytest.mark.parametrize('tick', [0, -1, True, .5])
def test_invalid_tick_configuration_is_rejected(tick):
    with pytest.raises(ValueError, match='execution tick'):
        run_portfolio_campaign(frames={}, strategies={}, config=PortfolioCampaignConfig(execution_tick_paise=tick))
