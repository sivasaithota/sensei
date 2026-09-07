from datetime import date

import pandas as pd
import pytest

from sensei.research.raw_execution_replay import assemble_raw_frame, in_interval_actions


def fixture():
    calendar = pd.date_range('2024-04-01', periods=2)
    raw = pd.DataFrame([dict(symbol='A', isin='old', series='EQ', instrument_class='equity',
        ok=True, open=100., high=110., low=90., close=105., volume=1000.)])
    return calendar, {d.date(): raw.copy() for d in calendar}


def test_raw_frames_preserve_actual_prices_and_full_required_calendar():
    calendar, sessions = fixture()
    frame, issues = assemble_raw_frame(sessions, calendar, symbol='A', isin='old')
    assert not issues and frame.index.equals(calendar)
    assert list(frame.open) == [100., 100.] and list(frame.volume) == [1000., 1000.]
    del sessions[date(2024, 4, 2)]
    frame, issues = assemble_raw_frame(sessions, calendar, symbol='A', isin='old')
    assert frame is None and issues == [{'date': '2024-04-02', 'reason': 'raw_session_not_captured'}]


@pytest.mark.parametrize('problem', ['wrong_isin', 'invalid', 'ambiguous', 'wrong_series'])
def test_raw_identity_or_integrity_failures_block_instead_of_filling(problem):
    calendar, sessions = fixture()
    raw = sessions[calendar[0].date()]
    if problem == 'wrong_isin':
        raw['isin'] = 'new'
    elif problem == 'invalid':
        raw['ok'] = False
    elif problem == 'ambiguous':
        sessions[calendar[0].date()] = pd.concat([raw, raw])
    else:
        raw['series'] = 'BE'
    frame, issues = assemble_raw_frame(sessions, calendar, symbol='A', isin='old')
    assert frame is None and len(issues) == 1


def test_action_coverage_includes_both_holding_boundaries():
    records = [dict(symbol='A', series='EQ', exDate=day) for day in ['01-Apr-2024','02-Apr-2024','03-Apr-2024']]
    assert in_interval_actions(records, symbol='A', start=pd.Timestamp('2024-04-01'),
        end=pd.Timestamp('2024-04-02')) == records[:2]
    assert not in_interval_actions(records, symbol='A', start=pd.Timestamp('2024-04-04'),
        end=pd.Timestamp('2024-04-05'))


@pytest.mark.parametrize('records', [[], {}, [dict(symbol='B', series='EQ', exDate='01-Apr-2024')],
    [dict(symbol='A', series='EQ', exDate='01-Apr-2025')],
    [dict(symbol='A', series='EQ', exDate='-')]])
def test_missing_or_wrong_action_coverage_cannot_clear_an_interval(records):
    with pytest.raises(ValueError):
        in_interval_actions(records, symbol='A', start=pd.Timestamp('2024-04-01'), end=pd.Timestamp('2024-04-02'))
