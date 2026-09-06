import numpy as np
import pandas as pd
import pytest

from sensei.research.market_gate import entry_masks


def inputs():
    index = pd.bdate_range("2024-01-01", periods=210)
    prices = pd.DataFrame({"close": 100.}, index=index)
    benchmark = pd.Series(np.arange(210) + 100., index=index)
    return prices, benchmark


def test_gate_is_prior_only_denies_unknown_and_composes_existing_exclusion():
    frame, benchmark = inputs()
    existing = pd.Series(True, index=frame.index)
    existing.iloc[202] = False
    masks = entry_masks({"A": frame}, benchmark, {"A": existing})
    assert not masks["A"].iloc[:200].any()
    assert masks["A"].iloc[200] and not masks["A"].iloc[202]
    changed = benchmark.copy(); changed.iloc[200:] = 1
    assert entry_masks({"A": frame}, changed, {"A": existing})["A"].iloc[:201].equals(masks["A"].iloc[:201])
    assert not entry_masks({"A": frame}, changed)["A"].iloc[201]
    assert existing.iloc[201] and frame.close.eq(100).all()


def test_missing_market_session_is_denied_and_misaligned_event_mask_rejected():
    frame, benchmark = inputs()
    assert not entry_masks({"A": frame}, benchmark.iloc[:-1])["A"].iloc[-1]
    with pytest.raises(ValueError): entry_masks({"A": frame}, benchmark, {})
    with pytest.raises(ValueError): entry_masks({"A": frame}, benchmark, {"A": pd.Series(True, index=frame.index[:-1])})
