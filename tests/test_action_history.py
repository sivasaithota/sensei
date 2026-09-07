from dataclasses import replace

import pandas as pd
import pytest

from sensei.research.action_history import ShareAction, signal_history


def bars():
    return pd.DataFrame({"open": [100, 20, 11], "high": [110, 22, 12],
        "low": [90, 18, 10], "close": [100, 20, 11], "volume": [10, 50, 100],
        "turnover": [1000, 1000, 1100]}, index=pd.date_range("2024-01-01", periods=3))


def split():
    return ShareAction("split", pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-01"), "split", 5, 1)


def test_split_preserves_turnover_raw_input_and_ex_session():
    raw = bars()
    original = raw.copy(deep=True)
    result = signal_history(raw, [split()], "2024-01-02")
    assert result.iloc[0][["open", "high", "low", "close", "volume"]].tolist() == [20, 22, 18, 20, 50]
    assert result.iloc[1]["close"] == 20
    pd.testing.assert_series_equal(result.turnover, raw.turnover.iloc[:2])
    assert (result.close * result.volume).tolist() == [1000, 1000]
    pd.testing.assert_frame_equal(raw, original)


def test_composition_and_real_price_change_survive():
    bonus = ShareAction("bonus", pd.Timestamp("2024-01-03"), pd.Timestamp("2024-01-02"), "bonus", 2, 1)
    result = signal_history(bars(), [bonus, split()], "2024-01-03")
    assert result.close.tolist() == [10, 10, 11]
    assert result.volume.tolist() == [100, 100, 100]
    assert result.close.pct_change().iloc[-1] == pytest.approx(.1)


def test_future_rows_and_announced_future_event_do_not_rewrite_decision():
    raw = bars()
    expected = signal_history(raw.iloc[:1], [], "2024-01-01")
    pd.testing.assert_frame_equal(signal_history(raw, [split()], "2024-01-01"), expected)
    signal_history(raw, [split()], "2024-01-03")
    pd.testing.assert_frame_equal(signal_history(raw, [split()], "2024-01-01"), expected)


def test_already_effective_but_later_known_action_blocks():
    action = replace(split(), known_session=pd.Timestamp("2024-01-03"))
    with pytest.raises(ValueError, match="not known"):
        signal_history(bars(), [action], "2024-01-02")


@pytest.mark.parametrize("changes", [{"new_shares": 0}, {"old_shares": 0}, {"new_shares": True}])
def test_invalid_future_action_schema_still_rejected(changes):
    with pytest.raises(ValueError, match="positive integers"):
        signal_history(bars(), [replace(split(), **changes)], "2024-01-01")


@pytest.mark.parametrize("changes,message", [
    ({"kind": "demerger"}, "unsupported"), ({"kind": "dividend"}, "unsupported"),
    ({"new_shares": 0}, "positive integers"), ({"old_shares": -1}, "positive integers"),
    ({"new_shares": True}, "positive integers"), ({"new_shares": 1}, "share-increasing"),
    ({"known_session": pd.Timestamp("2024-01-01T12:00")}, "midnight"),
])
def test_unsupported_or_invalid_action_fails(changes, message):
    with pytest.raises(ValueError, match=message):
        signal_history(bars(), [replace(split(), **changes)], "2024-01-03")


@pytest.mark.parametrize("identity,message", [("split", "duplicate"), ("different", "same-session")])
def test_duplicate_or_simultaneous_actions_fail(identity, message):
    with pytest.raises(ValueError, match=message):
        signal_history(bars(), [split(), replace(split(), identity=identity)], "2024-01-03")


@pytest.mark.parametrize("column,value", [("close", float("nan")), ("low", 101), ("volume", -1)])
def test_invalid_raw_data_fails(column, value):
    raw = bars()
    raw.loc[raw.index[0], column] = value
    with pytest.raises(ValueError, match="OHLCV"):
        signal_history(raw, [], "2024-01-03")


def test_non_session_and_duplicate_dates_fail():
    with pytest.raises(ValueError, match="midnight"):
        signal_history(bars(), [], "2024-01-03T01:00Z")
    raw = bars()
    raw.index = pd.DatetimeIndex([raw.index[0]] * 3)
    with pytest.raises(ValueError, match="unique ordered"):
        signal_history(raw, [], "2024-01-03")
