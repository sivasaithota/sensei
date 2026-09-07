from dataclasses import replace

import pandas as pd
import pytest

from sensei.backtest.raw_accounting import RawAccounting, RawAction
from sensei.backtest.relative_strength import MomentumInputs, MomentumPolicy, run_momentum_portfolio


def market(prices=None):
    dates = pd.bdate_range('2025-01-01', '2025-02-07')
    values = [100.] * len(dates) if prices is None else prices
    frames = {s: pd.DataFrame({'symbol': s, 'isin': s, 'series': 'EQ',
        'identity_verified': True, 'open': values, 'close': values,
        'high': [v+1 for v in values], 'low': [v-1 for v in values],
        'volume': 100000, 'turnover': 100000000.}, index=dates) for s in ('A', 'B')}
    raw = RawAccounting(frames, {s: pd.Series(1, index=dates) for s in frames},
                        (), 'a'*64, dates[0], dates[-1])
    ranking = pd.DataFrame({'atr20': [2., 2.], 'close': [100., 100.],
        'turnover60': [100000000., 100000000.], 'rank': [1, 2]}, index=['A', 'B'])
    # Explicit preceding-session capacity inputs for this small behavioral fixture.
    turnover = {s: pd.Series(100000000., index=dates) for s in frames}
    return MomentumInputs(raw, dates, {dates[0]: ranking},
        {d: set(frames) for d in dates}, turnover)


def test_orders_wait_for_next_session_and_are_not_enlarged_by_cheaper_open():
    inputs = market()
    inputs.raw.frames['A'].loc[inputs.calendar[1]:, ['open', 'close']] = 90.
    inputs.raw.frames['A'].loc[inputs.calendar[1]:, ['high', 'low']] = [91., 89.]
    result = run_momentum_portfolio(inputs, MomentumPolicy(),
        formation_start=inputs.calendar[0], end=inputs.calendar[-1])
    buys = [f for f in result['fills'] if f['side'] == 'BUY']
    assert buys[0]['session'] == '2025-01-02'
    assert buys[0]['quantity'] == 284  # formation 299500 * 9.5% / 100.10, floored
    assert result['authority'] == 'RESEARCH_ONLY' and result['can_trade'] is False
    assert result['overhead_inr'] == 1000  # Jan 2 inception; second cycle Feb 2
    assert min(p['cash'] for p in result['equity_curve']) >= 0


def test_close_trigger_sells_next_session_and_proceeds_settle_one_session_later():
    inputs = market()
    dates = inputs.calendar
    frame = inputs.raw.frames['A']
    # Entry 100.10 => threshold 94.10. Intraday low alone must not exit.
    frame.loc[dates[2], 'low'] = 80.
    frame.loc[dates[3], ['close', 'low']] = [93., 92.]
    frame.loc[dates[4], ['open', 'high', 'low', 'close']] = [90., 92., 89., 91.]
    result = run_momentum_portfolio(inputs, MomentumPolicy(), formation_start=dates[0], end=dates[-1])
    sells = [f for f in result['fills'] if f['side'] == 'SELL']
    assert len(sells) == 1
    assert sells[0]['session'] == str(dates[4].date())
    assert sells[0]['price'] == pytest.approx(89.91)
    curve = {p['session']: p for p in result['equity_curve']}
    assert curve[str(dates[4].date())]['unsettled_sales'] > 0
    assert curve[str(dates[5].date())]['unsettled_sales'] == 0
    assert len([f for f in result['fills'] if f['symbol'] == 'A' and f['side'] == 'BUY']) == 1
    assert result['attribution_residual_inr'] == pytest.approx(0, abs=1e-6)


def test_dividend_is_not_spendable_and_does_not_mechanically_trigger_exit():
    inputs = market()
    dates = inputs.calendar
    frame = inputs.raw.frames['A']
    frame.loc[dates[3]:, ['open', 'high', 'low', 'close']] = [90., 91., 89., 90.]
    action = RawAction('A', dates[3], 'dividend', 10., 'dividend', 'Dividend')
    inputs = replace(inputs, raw=replace(inputs.raw, actions=(action,)))
    result = run_momentum_portfolio(inputs, MomentumPolicy(), formation_start=dates[0], end=dates[-1])
    assert not [f for f in result['fills'] if f['side'] == 'SELL']
    assert result['equity_curve'][-1]['dividend_receivables'] == 2840.
    assert result['attribution_residual_inr'] == pytest.approx(0, abs=1e-6)


def test_split_preserves_equity_and_defers_exit_until_shares_are_available():
    inputs = market()
    dates = inputs.calendar
    frame = inputs.raw.frames['A']
    frame.loc[dates[3]:, ['open', 'high', 'low', 'close']] = [45., 46., 44., 45.]
    action = RawAction('A', dates[3], 'split', 0., 'split', 'Split', 2, 1, dates[2],
        dates[6], dates[2], 'b'*64, 'scenario')
    inputs = replace(inputs, raw=replace(inputs.raw, actions=(action,)))
    result = run_momentum_portfolio(inputs, MomentumPolicy(), formation_start=dates[0], end=dates[-1])
    sale = [f for f in result['fills'] if f['side'] == 'SELL'][0]
    assert sale['quantity'] == 568 and sale['session'] == str(dates[6].date())
    assert result['equity_curve'][2]['pending_share_quantity'] == 568
    assert result['attribution_residual_inr'] == pytest.approx(0, abs=1e-6)


def test_unsupported_held_action_prevents_publishing_performance():
    inputs = market()
    action = RawAction('A', inputs.calendar[3], 'unsupported', 0., 'unknown', 'Demerger')
    inputs = replace(inputs, raw=replace(inputs.raw, actions=(action,)))
    with pytest.raises(ValueError, match='unsupported held action'):
        run_momentum_portfolio(inputs, MomentumPolicy(), formation_start=inputs.calendar[0], end=inputs.calendar[-1])


def test_missing_later_formation_blocks_complete_return():
    inputs = market()
    inputs.formations[pd.Timestamp('2025-01-31')] = 'missing formation metadata: 2025-01-31'
    with pytest.raises(ValueError, match='missing formation metadata'):
        run_momentum_portfolio(inputs, MomentumPolicy(), formation_start=inputs.calendar[0], end=inputs.calendar[-1])


def test_partial_sales_apply_daily_capacity_and_dp_once_each_sale_day():
    inputs = market()
    dates = inputs.calendar
    frame = inputs.raw.frames['A']
    frame.loc[dates[2], ['close', 'low']] = [90., 89.]
    inputs.turnover60['A'].loc[dates[3]:] = 10_000_000.
    result = run_momentum_portfolio(inputs, MomentumPolicy(), formation_start=dates[0], end=dates[-1])
    sells = [f for f in result['fills'] if f['side'] == 'SELL']
    assert [f['quantity'] for f in sells] == [100, 100, 84]
    assert all(f['participation'] <= .001 for f in result['fills'])
    assert all(f['fees'] > 15.34 for f in sells)


def test_exit_control_keeps_identical_scheduled_roster_but_omits_trailing_sales():
    inputs = market()
    dates = inputs.calendar
    inputs.raw.frames['A'].loc[dates[2]:, ['open', 'high', 'low', 'close']] = [90., 91., 89., 90.]
    base = run_momentum_portfolio(inputs, MomentumPolicy(), formation_start=dates[0], end=dates[-1])
    control = run_momentum_portfolio(inputs, MomentumPolicy(trailing_exit=False), formation_start=dates[0], end=dates[-1])
    assert [d['roster'] for d in base['formations']] == [d['roster'] for d in control['formations']]
    assert any(f['side'] == 'SELL' for f in base['fills'])
    assert not any(f['side'] == 'SELL' for f in control['fills'])


def test_buy_expires_after_five_attempt_sessions_with_missing_permissions():
    inputs = market()
    dates = inputs.calendar
    inputs = replace(inputs, tradable={d: set() for d in dates})
    result = run_momentum_portfolio(inputs, MomentumPolicy(), formation_start=dates[0], end=dates[-1])
    assert result['fills'] == []
    assert {e['session'] for e in result['events'] if e['kind'] == 'buy_expired'} == {str(dates[6].date())}
    assert result['return_pct'] == pytest.approx(-1000/300000*100)


def test_rebalance_targets_shrink_with_current_equity_and_preserve_entry_atr():
    inputs = market()
    dates = inputs.calendar
    inputs.raw.frames['A'].loc[dates[3]:, ['open', 'high', 'low', 'close']] = [50., 51., 49., 50.]
    second = dates[8]
    ranking = inputs.formations[dates[0]].copy()
    ranking.loc['A', 'close'] = 50.
    ranking.loc['A', 'atr20'] = 20.  # held position must retain original ATR2
    inputs.formations[second] = ranking
    result = run_momentum_portfolio(inputs, MomentumPolicy(trailing_exit=False), formation_start=dates[0], end=dates[-1])
    decision = result['formations'][1]
    assert decision['equity'] < 290000
    a_order = next(o for o in decision['orders'] if o['symbol'] == 'A')
    assert a_order['side'] == 'BUY' and a_order['atr'] == 2.
    assert a_order['remaining'] < 90  # current-equity risk ceiling, not original-capital budget


def test_execution_and_exit_delay_are_exchange_session_delays():
    inputs = market()
    dates = inputs.calendar
    inputs.raw.frames['A'].loc[dates[3]:, ['open', 'high', 'low', 'close']] = [90., 91., 89., 90.]
    result = run_momentum_portfolio(inputs, MomentumPolicy(execution_delay=1, exit_delay=3), formation_start=dates[0], end=dates[-1])
    assert result['fills'][0]['session'] == str(dates[2].date())
    sale = next(f for f in result['fills'] if f['side'] == 'SELL')
    assert sale['session'] == str(dates[8].date())


def test_unavailable_terminal_shares_are_marked_and_never_invented_as_cash():
    inputs = market()
    dates = inputs.calendar
    action = RawAction('A', dates[-1], 'bonus', 0., 'bonus', 'Bonus', 2, 1, dates[-2])
    inputs.raw.frames['A'].loc[dates[-1], ['open', 'high', 'low', 'close']] = [50., 51., 49., 50.]
    inputs = replace(inputs, raw=replace(inputs.raw, actions=(action,)))
    result = run_momentum_portfolio(inputs, MomentumPolicy(), formation_start=dates[0], end=dates[-1])
    position = next(p for p in result['terminal_positions'] if p['symbol'] == 'A')
    assert position['quantity'] == 568 and position['pending_shares'] == 284
    assert result['liquidation']['status'] == 'NOT_EXECUTED'
    assert result['attribution_residual_inr'] == pytest.approx(0, abs=1e-6)
