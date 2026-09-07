"""Price-only, calendar-month relative strength; no broker or lifecycle authority."""

from collections import Counter
import math

import numpy as np
import pandas as pd


def month_ends(calendar):
    calendar = pd.DatetimeIndex(calendar)
    if calendar.has_duplicates or not calendar.is_monotonic_increasing or calendar.empty:
        raise ValueError('ordered unique exchange calendar required')
    return {period: group.iloc[-1] for period, group in
            pd.Series(calendar, index=calendar).groupby(calendar.to_period('M'))}


def rank_formation(frames, calendar, session, eligible, *, reset_dates=None,
                   selection='momentum', minimum_turnover=50_000_000.0,
                   universe_size=200):
    """Return ranked, admitted stocks and audit counts using no later prices.

    ``eligible=None`` means missing dated metadata, distinct from an empty
    eligible universe. Non-dividend action resets must be supplied by the
    accounting adapter, including unexplained identity/previous-close changes.
    """
    if eligible is None:
        raise ValueError(f'missing formation metadata: {session.date()}')
    if selection not in {'momentum', 'liquidity'}:
        raise ValueError('unknown selection policy')
    calendar = pd.DatetimeIndex(calendar)
    ends = month_ends(calendar)
    period = session.to_period('M')
    if ends.get(period) != session or period - 12 not in ends:
        raise ValueError('formation requires complete calendar-month endpoints')
    first, middle = ends[period - 12], ends[period - 6]
    window = calendar[(calendar >= first) & (calendar <= session)]
    resets = reset_dates or {}
    rows, excluded = [], Counter()
    for symbol in sorted(frames):
        if symbol not in eligible:
            excluded['metadata'] += 1
            continue
        history = frames[symbol].loc[first:session]
        if not history.index.equals(window) or len(history) < 61:
            excluded['missing_history'] += 1
            continue
        if (history['isin'].nunique() != 1
                or any(first < d <= session for d in resets.get(symbol, ()))):
            excluded['unit_discontinuity'] += 1
            continue
        values = history[['open', 'high', 'low', 'close', 'turnover']].to_numpy(float)
        if not np.isfinite(values).all() or (values[:, :4] <= 0).any() or (values[:, 4] < 0).any():
            excluded['invalid_history'] += 1
            continue
        turnover = float(history.turnover.iloc[-60:].median())
        if turnover < minimum_turnover:
            excluded['liquidity'] += 1
            continue
        close = history.close.astype(float)
        sigma = float(np.log(close).diff().iloc[1:].std(ddof=1) * math.sqrt(252))
        if not math.isfinite(sigma) or sigma <= 0:
            excluded['volatility'] += 1
            continue
        prior = close.shift(1)
        tr = pd.concat([history.high-history.low, (history.high-prior).abs(),
                        (history.low-prior).abs()], axis=1).max(axis=1)
        r6, r12 = close.iloc[-1] / close.loc[middle] - 1, close.iloc[-1] / close.iloc[0] - 1
        rows.append({'symbol': symbol, 'isin': str(history['isin'].iloc[-1]),
                     'turnover60': turnover, 'atr20': float(tr.iloc[-20:].mean()),
                     'close': float(close.iloc[-1]), 'return6': float(r6),
                     'return12': float(r12), 'sigma': sigma,
                     'x6': float(r6 / sigma), 'x12': float(r12 / sigma)})
    if len(rows) < 2:
        raise ValueError(f'invalid formation cross-section: {session.date()} ({len(rows)} names)')
    result = pd.DataFrame(rows).sort_values(['turnover60', 'isin', 'symbol'],
        ascending=[False, True, True]).head(universe_size).copy()
    for column in ('x6', 'x12'):
        std = float(result[column].std(ddof=0))
        if not math.isfinite(std) or std <= 0:
            raise ValueError(f'degenerate formation cross-section: {session.date()}')
        result['z' + column[1:]] = (result[column] - result[column].mean()) / std
    result['score'] = (result.z6 + result.z12) / 2
    order = 'score' if selection == 'momentum' else 'turnover60'
    result = result.sort_values([order, 'isin', 'symbol'], ascending=[False, True, True]).set_index('symbol')
    result['rank'] = np.arange(1, len(result) + 1)
    result.attrs['excluded'] = dict(excluded)
    result.attrs['qualified_before_top200'] = len(rows)
    return result


def buffered_roster(ranking, previous):
    """Scheduled roster is independent of filled/stopped positions."""
    ranking = list(ranking)
    if not previous:
        return ranking[:10]
    chosen = ranking[:5]
    chosen.extend(s for s in ranking[:20] if s in previous and s not in chosen)
    chosen = chosen[:10]
    chosen.extend(s for s in ranking if s not in chosen)
    return chosen[:10]
