import numpy as np
import pandas as pd
import pytest

from sensei.strategy.relative_strength import rank_formation, buffered_roster


def histories():
    dates = pd.bdate_range('2024-01-01', '2025-03-31')
    frames = {}
    for i, symbol in enumerate(('A', 'B', 'C')):
        prices = 100 * np.exp(np.arange(len(dates)) * (0.001 + i * 0.0002)
                              + 0.012 * np.sin(np.arange(len(dates))))
        frames[symbol] = pd.DataFrame({'symbol': symbol, 'isin': symbol,
            'open': prices, 'high': prices + 2, 'low': prices - 2, 'close': prices,
            'volume': 1000000, 'turnover': 100000000.0}, index=dates)
    return dates, frames


def test_monthly_rank_uses_calendar_endpoints_and_ignores_future_prices():
    dates, frames = histories()
    stamp = pd.Timestamp('2025-01-31')
    result = rank_formation(frames, dates, stamp, set(frames))
    assert list(result.index) == ['C', 'B', 'A']
    assert result.loc['A', 'return12'] == pytest.approx(
        frames['A'].loc[stamp, 'close'] / frames['A'].loc['2024-01-31', 'close'] - 1)
    for f in frames.values():
        f.loc[f.index > stamp, 'close'] *= 100
    pd.testing.assert_frame_equal(result, rank_formation(frames, dates, stamp, set(frames)))


def test_buffer_preserves_model_incumbents_without_using_actual_holdings():
    ranking = [str(i) for i in range(1, 25)]
    assert buffered_roster(ranking, ['18', '19', '20', '21', '22']) == [
        '1', '2', '3', '4', '5', '6', '7', '18', '19', '20']


@pytest.mark.parametrize('problem', ['gap', 'action', 'identity', 'liquidity'])
def test_unverified_history_and_illiquid_names_are_excluded(problem):
    dates, frames = histories()
    stamp = pd.Timestamp('2025-01-31')
    resets = {}
    if problem == 'gap':
        frames['C'] = frames['C'].drop(pd.Timestamp('2024-08-01'))
    elif problem == 'action':
        resets = {'C': {pd.Timestamp('2024-08-01')}}
    elif problem == 'identity':
        frames['C'].loc['2024-08-01':, 'isin'] = 'NEW'
    else:
        frames['C']['turnover'] = 1000000.
    result = rank_formation(frames, dates, stamp, set(frames), reset_dates=resets)
    assert list(result.index) == ['B', 'A']


def test_missing_formation_metadata_blocks_instead_of_reusing_universe():
    dates, frames = histories()
    with pytest.raises(ValueError, match='missing formation metadata'):
        rank_formation(frames, dates, pd.Timestamp('2025-01-31'), None)


def test_calendar_year_age_is_separate_from_last_years_month_end_endpoint():
    dates, frames = histories()
    frames['C'] = frames['C'].loc['2024-02-29':]
    result = rank_formation(frames, dates, pd.Timestamp('2025-02-28'), set(frames))
    assert list(result.index) == ['B', 'A']  # Feb 29 endpoint exists, but age is <1 calendar year
