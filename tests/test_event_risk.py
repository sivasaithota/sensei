import json
from types import SimpleNamespace

import pandas as pd
import pytest

from sensei.research.event_risk import load_event_risk, entry_masks, held_event_exposure


def policy_file(tmp_path, **changes):
    payload = {'version':1, 'post_event_observations':252,
        'events':[{'id':'a-demerger', 'symbol':'A', 'announced_on':'2024-01-02',
                   'available_from':'2024-01-03', 'ex_date':'2024-01-08',
                   'sources':['https://example.com/exchange-notice.pdf']}]}
    payload.update(changes)
    path=tmp_path/'policy.json'; path.write_text(json.dumps(payload))
    return path


def test_announcement_is_not_known_early_and_entry_day_does_not_count_as_history(tmp_path):
    policy=load_event_risk(policy_file(tmp_path))
    index=pd.bdate_range('2024-01-01', periods=270)
    frame=pd.DataFrame({'close':100.}, index=index)
    masks=entry_masks({'A':frame, 'B':frame.copy()},policy)
    assert masks['A'].loc['2024-01-02']
    assert not masks['A'].loc['2024-01-03']
    ex=index.get_loc('2024-01-08')
    assert not masks['A'].iloc[ex+251]
    assert masks['A'].iloc[ex+252]
    assert masks['B'].all()
    assert frame.equals(pd.DataFrame({'close':100.},index=index))


def test_late_notice_cannot_block_entries_before_its_availability(tmp_path):
    path=policy_file(tmp_path)
    raw=json.loads(path.read_text()); raw['events'][0].update(announced_on='2024-01-10',available_from='2024-01-11')
    path.write_text(json.dumps(raw)); policy=load_event_risk(path)
    f=pd.DataFrame({'close':100.},index=pd.bdate_range('2024-01-01',periods=270))
    mask=entry_masks({'A':f},policy)['A']
    assert mask.loc['2024-01-10'] and not mask.loc['2024-01-11']


@pytest.mark.parametrize('mutation',['duplicate','short_history','same_day_availability','unknown_field'])
def test_invalid_event_policy_fails(tmp_path,mutation):
    path=policy_file(tmp_path); payload=json.loads(path.read_text())
    if mutation=='duplicate': payload['events'].append(payload['events'][0])
    if mutation=='short_history': payload['post_event_observations']=20
    if mutation=='same_day_availability': payload['events'][0]['available_from']='2024-01-02'
    if mutation=='unknown_field': payload['events'][0]['credit_cash']=100
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError): load_event_risk(path)


def test_unknown_symbol_and_unsorted_dates_fail_instead_of_ignoring_policy(tmp_path):
    policy=load_event_risk(policy_file(tmp_path)); f=pd.DataFrame({'close':[1,2]},index=pd.to_datetime(['2024-01-02','2024-01-01']))
    with pytest.raises(ValueError,match='symbols'): entry_masks({'B':f.sort_index()},policy)
    with pytest.raises(ValueError,match='calendar'): entry_masks({'A':f},policy)


def test_selling_on_ex_date_still_requires_entitlements_but_buying_on_ex_date_does_not(tmp_path):
    policy=load_event_risk(policy_file(tmp_path))
    trades=[SimpleNamespace(symbol='A',entry_date='2024-01-01',exit_date='2024-01-08',quantity=10),
            SimpleNamespace(symbol='A',entry_date='2024-01-08',exit_date='2024-01-09',quantity=20),
            SimpleNamespace(symbol='A',entry_date='2024-01-01',exit_date='2024-01-05',quantity=30)]
    result=held_event_exposure(trades,policy)
    assert len(result)==1 and result[0]['quantity']==10
    assert result[0]['event_id']=='a-demerger'
