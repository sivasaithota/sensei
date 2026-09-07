"""Prior-session research eligibility; never a certified stock universe."""

from collections import Counter

import numpy as np
import pandas as pd

from sensei.research.security_master_batch import normalize


def stable_history_lengths(frame, calendar, reset_dates=()):
    """Count consecutive same-symbol/ISIN observations, without future resets."""
    if (not isinstance(frame.index, pd.DatetimeIndex) or frame.index.has_duplicates
            or not frame.index.is_monotonic_increasing or frame.index.tz is not None
            or frame.index.hasnans or not frame.index.equals(frame.index.normalize())):
        raise ValueError("history needs ordered unique daily observations")
    calendar = pd.DatetimeIndex(calendar)
    if calendar.has_duplicates or not calendar.is_monotonic_increasing:
        raise ValueError("history needs an ordered exchange calendar")
    positions = calendar.get_indexer(frame.index)
    if (positions < 0).any():
        raise ValueError("raw observation outside exchange calendar")
    identities = list(zip(frame["symbol"], frame["isin"]))
    resets = set(pd.Timestamp(d) for d in reset_dates)
    lengths, length = [], 0
    for i, stamp in enumerate(frame.index):
        interrupted = (i == 0 or positions[i] != positions[i - 1] + 1
            or identities[i] != identities[i - 1] or stamp in resets)
        length = 1 if interrupted else length + 1
        lengths.append(length)
    return pd.Series(lengths, index=frame.index, dtype="int64")


def entry_decision(*, prior, source_session, metadata, history, stable_count,
                   warmup=252, event_allowed=True):
    """Only pre-entry inputs: execution-session OHLC/turnover are not accepted."""
    if source_session != prior:
        return False, "missing_immediate_predecessor_master"
    if metadata is None:
        return False, "missing_or_nonqualifying_dated_identity"
    if not event_allowed:
        return False, "announced_event_blackout"
    if normalize(metadata, str(source_session.date()))["screen_status"] != "provisional_candidate":
        return False, "outside_dated_metadata_proxy"
    if history.empty or history.index[-1] != prior:
        return False, "missing_prior_price"
    last = history.iloc[-1]
    if last["symbol"] != metadata["TckrSymb"] or last["isin"] != metadata["ISIN"]:
        return False, "history_identity_differs_from_entry_metadata"
    if stable_count < warmup:
        return False, "insufficient_stable_history"
    return True, "research_proxy_eligible"


def prepare_entry_masks(frames, calendar, snapshots, *, reset_dates=None,
                        event_masks=None, warmup=252):
    """Retain false masks for all historical instruments and every entry date.

    Snapshot dictionaries are validated upstream, keyed by exact source session,
    then symbol with one EQ record. Missing/ambiguous rows must not be supplied.
    """
    if type(warmup) is not int or warmup < 252:
        raise ValueError("stable history must cover the full 252-session ranking window")
    calendar = pd.DatetimeIndex(calendar)
    previous = {d: calendar[i - 1] for i, d in enumerate(calendar) if i}
    counts, eligible, lengths = Counter(), {}, {}
    reset_dates = reset_dates or {}
    for symbol, frame in frames.items():
        stable = stable_history_lengths(frame, calendar, reset_dates.get(symbol, ()))
        lengths[symbol] = stable
        mask = np.zeros(len(frame), dtype=bool)
        for i, stamp in enumerate(frame.index):
            prior = previous.get(stamp)
            if prior is None:
                counts["no_prior_exchange_session"] += 1
                continue
            snapshot = snapshots.get(prior)
            metadata = snapshot.get(symbol) if snapshot is not None else None
            # Slicing is strictly before prospective execution, even if the full
            # raw frame already contains the entry bar and later observations.
            history = frame.iloc[:i]
            allowed, reason = entry_decision(prior=prior,
                source_session=prior if snapshot is not None else None,
                metadata=metadata, history=history, stable_count=int(stable.iloc[i - 1]) if i else 0,
                warmup=warmup, event_allowed=(bool(event_masks[symbol].get(stamp, False)) if event_masks is not None else True))
            mask[i] = allowed
            counts[reason] += 1
        eligible[symbol] = pd.Series(mask, index=frame.index, dtype=bool)
    return eligible, lengths, dict(counts)
