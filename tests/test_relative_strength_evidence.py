import hashlib

import pandas as pd
import pytest

from sensei.backtest.raw_accounting import RawAction
from sensei.research.relative_strength_evidence import join_documented_renames, repair_share_actions


def source(tmp_path):
    path = tmp_path / 'reviewed-evidence.txt'
    path.write_text('Pinned test evidence for the explicitly registered fixture claim')
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def frames():
    dates = pd.bdate_range('2025-01-01', periods=6)
    frame = pd.DataFrame({'symbol': 'OLD', 'isin': 'ISIN', 'series': 'EQ',
                          'close': 100., 'prev_close': 100.}, index=dates)
    return dates, frame


def test_documented_rename_keeps_raw_symbols_and_continuous_holding_key(tmp_path):
    dates, frame = frames()
    rule = {'old_symbol': 'OLD', 'new_symbol': 'NEW', 'isin': 'ISIN',
        'effective_from': str(dates[3].date()), 'known_from': str(dates[1].date()), 'source': source(tmp_path)}
    joined = join_documented_renames({'OLD': frame.iloc[:3], 'NEW': frame.iloc[3:].assign(symbol='NEW')}, dates, [rule])
    assert list(joined) == ['OLD']
    assert list(joined['OLD']['symbol']) == ['OLD']*3+['NEW']*3
    assert joined['OLD'].index.equals(dates)


def test_rename_cannot_stitch_different_issuers_or_a_missing_session(tmp_path):
    dates, frame = frames()
    rule = {'old_symbol': 'OLD', 'new_symbol': 'NEW', 'isin': 'ISIN',
        'effective_from': str(dates[3].date()), 'known_from': str(dates[1].date()), 'source': source(tmp_path)}
    with pytest.raises(ValueError, match='consecutive raw identities'):
        join_documented_renames({'OLD': frame.iloc[:3], 'NEW': frame.iloc[3:].assign(symbol='NEW', isin='OTHER')}, dates, [rule])


def repair_fixture(tmp_path):
    dates, frame = frames()
    rejected = RawAction('OLD', dates[2], 'unsupported', 0., 'rejected', 'stale source ISIN')
    rule = {'symbol': 'OLD', 'ex_date': str(dates[2].date()), 'known_from': str(dates[0].date()),
        'kind': 'bonus', 'new_shares': 5, 'old_shares': 1, 'subject': 'Bonus 4:1',
        'replaces_source_id': 'rejected', 'before_isin': 'ISIN', 'after_isin': 'ISIN',
        'available_from': str(dates[4].date()), 'availability_known_from': str(dates[1].date()),
        'availability_basis': 'documented_market_admission', 'sources': [source(tmp_path)]}
    return dates, frame, rejected, rule


def test_documented_bonus_can_reconcile_unrevised_previous_close(tmp_path):
    dates, frame, rejected, rule = repair_fixture(tmp_path)
    repaired = repair_share_actions({'OLD': frame}, dates, (rejected,), [rule])
    assert repaired[0].kind == 'bonus' and repaired[0].new_shares == 5
    assert repaired[0].known_from < repaired[0].ex_date
    assert repaired[0].available_from == dates[4]


@pytest.mark.parametrize('mutation', ['changed_source', 'different_event', 'different_identity', 'unexplained_previous_close', 'late_notice'])
def test_share_repair_rejects_changed_or_inconsistent_evidence(tmp_path, mutation):
    dates, frame, rejected, rule = repair_fixture(tmp_path)
    if mutation == 'changed_source':
        rule['sources'][0]['sha256'] = '0'*64
    elif mutation == 'different_event':
        rule['replaces_source_id'] = 'other'
    elif mutation == 'different_identity':
        rule['after_isin'] = 'OTHER'
    elif mutation == 'unexplained_previous_close':
        frame.loc[dates[2], 'prev_close'] = 35.
    else:
        rule['known_from'] = rule['ex_date']
    with pytest.raises(ValueError):
        repair_share_actions({'OLD': frame}, dates, (rejected,), [rule])


def test_exact_cash_repair_pins_notice_and_retains_total_dividend(tmp_path):
    from sensei.research.relative_strength_evidence import repair_cash_actions
    dates,frame=frames()
    rejected=RawAction('OLD',dates[2],'unsupported',0.,'cash-event','Interim and special dividend')
    rule={'symbol':'OLD','isin':'ISIN','ex_date':str(dates[2].date()),
        'known_from':str(dates[0].date()),'amount':57.,'subject':'11 interim plus 46 special',
        'replaces_source_id':'cash-event','sources':[source(tmp_path)]}
    repaired,resets=repair_cash_actions({'OLD':frame},dates,(rejected,),{'OLD':{dates[2],dates[4]}},[rule])
    assert resets['OLD']=={dates[4]}
    assert repaired[0].kind=='dividend' and repaired[0].amount==57.
    rule['replaces_source_id']='other-event'
    with pytest.raises(ValueError,match='exact-source cash'):
        repair_cash_actions({'OLD':frame},dates,(rejected,),{'OLD':{dates[2]}},[rule])
    rule['replaces_source_id']='cash-event'
    rule['sources'][0]['sha256']='0'*64
    with pytest.raises(ValueError):
        repair_cash_actions({'OLD':frame},dates,(rejected,),{'OLD':{dates[2]}},[rule])


def test_cash_repair_restores_ranking_eligibility_and_preserves_other_resets(tmp_path):
    from tests.test_relative_strength import histories
    from sensei.research.relative_strength_evidence import repair_cash_actions
    from sensei.strategy.relative_strength import rank_formation
    dates,fs=histories();ex=pd.Timestamp('2025-01-16');formation=pd.Timestamp('2025-01-31')
    fs['C']['series']='EQ';fs['C']['prev_close']=fs['C']['close'].shift(1)
    bad=RawAction('C',ex,'unsupported',0.,'cash','Combined dividend')
    reset={'C':{ex,pd.Timestamp('2024-01-02')}}
    assert 'C' not in rank_formation(fs,dates,formation,set(fs),reset_dates=reset).index
    rule={'symbol':'C','isin':'C','ex_date':str(ex.date()),'known_from':'2025-01-12',
        'amount':57.,'subject':'Combined dividend','replaces_source_id':'cash','sources':[source(tmp_path)]}
    _,fixed=repair_cash_actions(fs,dates,(bad,),reset,[rule])
    assert fixed['C']=={pd.Timestamp('2024-01-02')}
    assert list(rank_formation(fs,dates,formation,set(fs),reset_dates=fixed).index)==['C','B','A']
    fs['C'].loc[dates[dates.get_loc(ex)-1],'isin']='OTHER'
    with pytest.raises(ValueError,match='independent raw discontinuity'):
        repair_cash_actions(fs,dates,(bad,),reset,[rule])
