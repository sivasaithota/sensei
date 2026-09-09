from dataclasses import replace

import pandas as pd
import pytest

from sensei.backtest.raw_accounting import RawAction
from sensei.backtest.relative_strength import MomentumPolicy, run_momentum_portfolio
from sensei.backtest.entitlements import Demerger, ResultingSecurity
from tests.test_relative_strength_portfolio import market


def demerger_market():
    inputs = market()
    dates = inputs.calendar
    parent = inputs.raw.frames['A']
    parent.loc[dates[3]:, ['open', 'high', 'low', 'close']] = [60., 61., 59., 60.]
    child = inputs.raw.frames['B'].loc[dates[6]:].assign(symbol='C', isin='C',
        open=50., high=51., low=49., close=50.)
    frames = {**inputs.raw.frames, 'C': child}
    ticks = {**inputs.raw.ticks, 'C': pd.Series(1, index=child.index)}
    action = RawAction('A', dates[3], 'unsupported', 0., 'demerger', 'Demerger')
    raw = replace(inputs.raw, frames=frames, ticks=ticks, actions=(action,))
    rule = Demerger('A', dates[3], dates[2], 'demerger', 'A',
        (ResultingSecurity('C', 'C', 1, 1, dates[6], dates[5], dates[6]),), 'a'*64)
    return replace(inputs, raw=raw, demergers=(rule,),
        tradable={d: set(frames) for d in dates},
        turnover60={**inputs.turnover60, 'C': pd.Series(100000000., index=dates)})


def test_distribution_preserves_wealth_then_marks_listing_without_early_sale():
    inputs = demerger_market()
    dates = inputs.calendar
    result = run_momentum_portfolio(inputs, MomentumPolicy(), formation_start=dates[0], end=dates[8])
    curve = {p['session']: p for p in result['equity_curve']}
    before, ex, listing = [curve[str(dates[i].date())] for i in (2, 3, 6)]
    assert ex['equity'] == pytest.approx(before['equity'])
    assert ex['unlisted_entitlements'] == 11360.  # 284 old shares, 40 each
    assert ex['cash'] == before['cash']
    assert listing['unlisted_entitlements'] == 0
    assert listing['equity'] == pytest.approx(ex['equity']+2840.)
    assert not [f for f in result['fills'] if f['symbol']=='A' and f['side']=='SELL']
    sales = [f for f in result['fills'] if f['symbol']=='C']
    assert len(sales)==1 and sales[0]['session']==str(dates[7].date())
    assert sales[0]['quantity']==284 and sales[0]['side']=='SELL'
    assert result['attribution_residual_inr']==pytest.approx(0,abs=.001)


def test_no_capacity_keeps_listed_entitlement_and_its_dividend_nonspendable():
    inputs = demerger_market()
    dates = inputs.calendar
    inputs.turnover60['C'][:] = float('nan')
    dividend = RawAction('C', dates[7], 'dividend', 2., 'child-dividend', 'Dividend')
    inputs = replace(inputs,raw=replace(inputs.raw,actions=(*inputs.raw.actions,dividend)))
    inputs.raw.frames['C'].loc[dates[7]:,['open','high','low','close']]=[48.,49.,47.,48.]
    result = run_momentum_portfolio(inputs,MomentumPolicy(),formation_start=dates[0],end=dates[8])
    assert not [f for f in result['fills'] if f['symbol']=='C']
    assert result['terminal_entitlements'][0]['quantity']==284
    assert result['terminal_entitlements'][0]['marked_value']==13632.
    assert result['equity_curve'][-1]['dividend_receivables']==568.
    lifecycle=result['entitlement_lifecycles'][0]
    assert lifecycle['disposal_status']=='PENDING'
    assert lifecycle['sessions_outstanding']==6
    assert lifecycle['listed_sessions_outstanding']==3
    assert lifecycle['last_no_fill_reason']=='sixty_session_capacity_unavailable'
    assert result['equity_curve'][-1]['cash']==result['equity_curve'][1]['cash']
    assert result['attribution_residual_inr']==pytest.approx(0,abs=.001)


def test_conservative_sizing_removes_only_unlisted_value_without_changing_nav():
    inputs=demerger_market(); dates=inputs.calendar
    result=run_momentum_portfolio(inputs,MomentumPolicy(exclude_unlisted_from_sizing=True),
        formation_start=dates[0],end=dates[6])
    ex=next(r for r in result['equity_curve'] if r['session']==str(dates[3].date()))
    assert ex['equity']-ex['sizing_equity']==pytest.approx(11360.)
    assert result['equity_curve'][-1]['equity']==result['equity_curve'][-1]['sizing_equity']


def test_multiple_children_preserve_distribution_without_rounding_or_future_marks():
    inputs=demerger_market(); dates=inputs.calendar
    d=inputs.raw.frames['C'].assign(symbol='D',isin='D',open=10.,close=10.,high=11.,low=9.)
    raw=replace(inputs.raw,frames={**inputs.raw.frames,'D':d},ticks={**inputs.raw.ticks,'D':inputs.raw.ticks['C']})
    rule=inputs.demergers[0]
    rule=replace(rule,children=(*rule.children,replace(rule.children[0],symbol='D',isin='D')))
    inputs=replace(inputs,raw=raw,demergers=(rule,),turnover60={**inputs.turnover60,'D':inputs.turnover60['C']})
    early=run_momentum_portfolio(inputs,MomentumPolicy(),formation_start=dates[0],end=dates[5])
    assert [r['marked_value'] for r in early['terminal_entitlements']]==[5680.,5680.]
    inputs.raw.frames['C'].loc[dates[6],'close']=50.5
    later_future=run_momentum_portfolio(inputs,MomentumPolicy(),formation_start=dates[0],end=dates[5])
    assert early==later_future
    assert early['attribution_residual_inr']==pytest.approx(0,abs=.001)


def test_fractional_distribution_and_wrong_action_identity_fail_closed():
    inputs=demerger_market(); dates=inputs.calendar;rule=inputs.demergers[0]
    with pytest.raises(ValueError,match='exact rejected action'):
        run_momentum_portfolio(replace(inputs,demergers=(replace(rule,replaces_source_id='wrong'),)),
            MomentumPolicy(),formation_start=dates[0],end=dates[8])
    rule=replace(rule,children=(replace(rule.children[0],old_shares=3),))
    with pytest.raises(ValueError,match='fractional demerger'):
        run_momentum_portfolio(replace(inputs,demergers=(rule,)),MomentumPolicy(),formation_start=dates[0],end=dates[8])


def test_zero_initial_mark_retains_legal_entitlement_and_days_outstanding():
    inputs=demerger_market();dates=inputs.calendar
    inputs.raw.frames['A'].loc[dates[3]:,['open','high','low','close']]=[101.,102.,100.,101.]
    result=run_momentum_portfolio(inputs,MomentumPolicy(),formation_start=dates[0],end=dates[5])
    assert result['terminal_entitlements'][0]['quantity']==284
    assert result['terminal_entitlements'][0]['marked_value']==0
    assert result['sessions_with_unlisted_entitlements']==3


def test_unlisted_child_distribution_is_explicitly_unresolved():
    inputs=demerger_market();dates=inputs.calendar
    action=RawAction('C',dates[4],'dividend',2.,'early-dividend','Unlisted dividend')
    inputs=replace(inputs,raw=replace(inputs.raw,actions=(*inputs.raw.actions,action)))
    with pytest.raises(ValueError,match='unlisted resulting-security distribution'):
        run_momentum_portfolio(inputs,MomentumPolicy(),formation_start=dates[0],end=dates[8])


def test_missing_child_execution_tick_defers_sale_and_completed_disposal_is_tracked():
    inputs=demerger_market();dates=inputs.calendar
    inputs.raw.ticks['C'].loc[dates[7]]=float('nan')
    result=run_momentum_portfolio(inputs,MomentumPolicy(),formation_start=dates[0],end=dates[9])
    sale=next(f for f in result['fills'] if f['symbol']=='C')
    assert sale['session']==str(dates[8].date())
    lifecycle=result['entitlement_lifecycles'][0]
    assert lifecycle['disposal_status']=='COMPLETE'
    assert lifecycle['disposed_on']==str(dates[8].date())
    assert lifecycle['quantity_granted']==284 and lifecycle['quantity_remaining']==0
    assert lifecycle['sessions_outstanding']==6
    assert lifecycle['unlisted_sessions_outstanding']==3
    assert result['attribution_residual_inr']==pytest.approx(0,abs=.001)
