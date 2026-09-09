from dataclasses import replace

from sensei.backtest.raw_accounting import RawAction
from tests.test_relative_strength_portfolio import market
from sensei.research.relative_strength_preflight import audit_inputs


def test_preflight_collects_all_potential_events_before_any_account_path():
    inputs=market();dates=inputs.calendar
    actions=(RawAction('A',dates[3],'unsupported',0.,'one','Demerger'),
        RawAction('B',dates[5],'unsupported',0.,'two','Unknown cash distribution'))
    inputs=replace(inputs,raw=replace(inputs.raw,actions=actions))
    plan={'common_formation':str(dates[0].date()),'extended_formation':str(dates[0].date()),
        'end':str(dates[-1].date()),'experiments':[{'name':'candidate'}]}
    audit=audit_inputs(inputs,plan)
    assert audit['status']=='BLOCKED'
    assert {r['source_id'] for r in audit['unsupported_actions']}=={'one','two'}
    assert audit['potential_holdings']==['A','B']
