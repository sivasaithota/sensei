import pandas as pd
import pytest

from sensei.strategy.selection import SignalRankingPolicy, average_turnover, return_correlation, current_identity_history


def test_ranking_and_correlation_use_same_explicit_identity_prefix():
    dates = pd.bdate_range("2024-01-01", periods=300)
    frame = pd.DataFrame({"close": [9999.0] * 30 + list(range(100, 370)),
        "volume": 1000, "research_history_epoch": [0] * 30 + [1] * 270}, index=dates)
    suffix = frame.iloc[30:].drop(columns="research_history_epoch")
    policy = SignalRankingPolicy()
    kwargs = {"stop_pct": 5, "target_pct": 12, "as_of": dates[-1].date()}
    assert policy.score(frame=frame, average_turnover_inr=average_turnover(frame), **kwargs) == policy.score(frame=suffix, average_turnover_inr=average_turnover(suffix), **kwargs)
    assert return_correlation(frame, frame, lookback=60) == return_correlation(suffix, suffix, lookback=60)
    assert current_identity_history(frame.iloc[:25]).equals(frame.iloc[:25])


def test_legacy_frames_unchanged_and_bad_epochs_rejected():
    frame = pd.DataFrame({"close": [1, 2], "volume": [10, 20]})
    assert current_identity_history(frame) is frame
    with pytest.raises(ValueError, match="epochs"):
        current_identity_history(frame.assign(research_history_epoch=[1, 0]))
