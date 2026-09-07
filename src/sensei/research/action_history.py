"""Synthetic research seam for dated split/bonus units, not evidence certification."""

from dataclasses import dataclass
from fractions import Fraction

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ShareAction:
    identity: str
    ex_session: pd.Timestamp
    known_session: pd.Timestamp
    kind: str
    new_shares: int
    old_shares: int


def session(value):
    stamp = pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tz is not None or stamp != stamp.normalize():
        raise ValueError("expected a timezone-naive midnight session")
    return stamp


def signal_history(raw, actions, as_of):
    """Copy one instrument into as-of units; caller must separately prove coverage.

    Actions are historical evidence inputs, not self-certifying authority. No
    cash, physical entitlement, tradability or membership is inferred here.
    """
    cutoff = session(as_of)
    if (not isinstance(raw.index, pd.DatetimeIndex) or raw.index.tz is not None
            or raw.index.hasnans or raw.index.has_duplicates
            or not raw.index.is_monotonic_increasing
            or not raw.index.equals(raw.index.normalize())):
        raise ValueError("raw history requires unique ordered session dates")
    columns = ["open", "high", "low", "close", "volume"]
    if not raw.columns.is_unique or not set(columns).issubset(raw.columns):
        raise ValueError("raw history requires unique OHLCV columns")
    frame = raw.loc[raw.index <= cutoff].copy(deep=True)
    if frame.empty:
        raise ValueError("no raw history at decision")
    try:
        values = frame[columns].to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid raw OHLCV") from exc
    o, h, low, c, v = values.T
    if (not np.isfinite(values).all() or not (low > 0).all() or not (v >= 0).all()
            or not (low <= np.minimum(o, c)).all() or not (np.maximum(o, c) <= h).all()):
        raise ValueError("invalid raw OHLCV")
    frame[columns] = values
    seen, ex_dates, effective = set(), set(), []
    for action in actions:
        ex, known = session(action.ex_session), session(action.known_session)
        if not action.identity or action.identity in seen:
            raise ValueError("duplicate or missing action identity")
        seen.add(action.identity)
        if ex in ex_dates:
            raise ValueError("conflicting same-session actions require explicit composition")
        ex_dates.add(ex)
        if (type(action.new_shares) is not int or type(action.old_shares) is not int
                or action.new_shares <= 0 or action.old_shares <= 0):
            raise ValueError("share ratio requires positive integers")
        if ex > cutoff:
            continue
        if known > cutoff:
            raise ValueError("effective action was not known at decision")
        if action.kind not in {"split", "bonus"}:
            raise ValueError("unsupported effective action")
        ratio = Fraction(action.new_shares, action.old_shares)
        if ratio <= 1:
            raise ValueError("this slice supports only share-increasing splits and bonuses")
        effective.append((ex, ratio))
    for ex, ratio in sorted(effective):
        before = frame.index < ex
        try:
            factor = float(ratio)
        except OverflowError as exc:
            raise ValueError("unrepresentable share factor") from exc
        with np.errstate(over="ignore", under="ignore", invalid="ignore"):
            frame.loc[before, columns[:4]] /= factor
            frame.loc[before, "volume"] *= factor
    adjusted = frame[columns].to_numpy(dtype=float)
    if not np.isfinite(adjusted).all() or not (adjusted[:, :4] > 0).all():
        raise ValueError("unrepresentable transformed history")
    return frame
