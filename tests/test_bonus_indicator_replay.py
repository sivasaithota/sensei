import copy

import numpy as np
import pandas as pd
import pytest

from sensei.research.action_history import ShareAction, signal_history
from sensei.research.bonus_indicator_replay import bonus_negative_controls, classify_actions, replay


def fixture():
    dates = pd.date_range("2024-01-01", periods=257)
    baseline = 100. + np.arange(len(dates)) * .1 + np.sin(np.arange(len(dates)))
    actions = {"A": [ShareAction("bonus", dates[253], dates[251], "bonus", 3, 1)], "B": []}
    frames = {}
    for symbol in actions:
        # Distinct profiles avoid an artificial tie between cloned instruments.
        prices = baseline if symbol == "A" else 100. + np.arange(len(dates)) * .03 + 2 * np.cos(np.arange(len(dates)) / 3)
        units = np.where(np.arange(len(dates)) >= 253, 3., 1.) if symbol == "A" else np.ones(len(dates))
        price = prices / units
        frames[symbol] = pd.DataFrame({"open": price, "high": price + 1 / units,
            "low": price - 1 / units, "close": price, "volume": (1000. + np.arange(len(dates))) * units,
            "turnover": prices * (1000. + np.arange(len(dates)))}, index=dates)
    return frames, actions, dates[251:]


def test_bonus_replay_has_full_warmup_and_dated_features():
    frames, actions, cutoffs = fixture()
    original = {s: f.copy(deep=True) for s, f in frames.items()}
    result = replay(frames, actions, cutoffs)
    assert len(result["decisions"]) == 6
    assert result["ohlcv_oracle_cells"] == sum(range(252, 258)) * 2 * 5
    assert result["all_components_match_oracle"]
    assert result["decisions"][-1]["dated"]["scores"]["A"] != result["decisions"][-1]["raw_unnormalized"]["scores"]["A"]
    for symbol in frames:
        pd.testing.assert_frame_equal(frames[symbol], original[symbol])


def test_omitted_bonus_factor_is_detected():
    frames, actions, cutoffs = fixture()
    with pytest.raises(ValueError, match="rational oracle"):
        replay(frames, actions, cutoffs, transform=lambda f, a, c: signal_history(f, [], c))


def test_bonus_controls_require_a_knowledge_error_not_silent_raw_fallback():
    frames, actions, _ = fixture()
    bonus = actions["A"][0]
    bonus_negative_controls(frames["A"], bonus, rtol=1e-12, atol=1e-10)
    def fallback(frame, events, cutoff):
        return signal_history(frame, [], cutoff)
    with pytest.raises(ValueError, match="did not block"):
        bonus_negative_controls(frames["A"], bonus, rtol=1e-12, atol=1e-10, transform=fallback)


def test_bonus_controls_detect_mutation_on_rejection():
    frames, actions, _ = fixture()
    def mutable(frame, events, cutoff):
        if events and events[0].known_session > cutoff:
            frame.loc[frame.index[0], "turnover"] = 0
        return signal_history(frame, events, cutoff)
    with pytest.raises(AssertionError):
        bonus_negative_controls(frames["A"], actions["A"][0], rtol=1e-12, atol=1e-10, transform=mutable)


def test_future_dependency_is_detected():
    frames, actions, cutoffs = fixture()
    def leaky(frame, events, cutoff):
        result = signal_history(frame, events, cutoff)
        result["volume"] += len(frame)
        return result
    with pytest.raises(AssertionError):
        replay(frames, actions, cutoffs, transform=leaky)


def test_missing_decision_row_does_not_get_forward_filled():
    frames, actions, cutoffs = fixture()
    frames["B"] = frames["B"].drop(cutoffs[-1])
    with pytest.raises(ValueError, match="insufficient"):
        replay(frames, actions, cutoffs)


@pytest.mark.parametrize("kwargs", [{"minimum_history": 251}, {"rtol": .01}, {"atol": 1}])
def test_scope_cannot_weaken_warmup_or_oracle(kwargs):
    frames, actions, cutoffs = fixture()
    with pytest.raises(ValueError, match="scope"):
        replay(frames, actions, cutoffs, **kwargs)


def declarations():
    row = {"source_id": "id", "symbol": "BSE", "subject": "Bonus 2:1", "date": pd.Timestamp("2025-05-23"),
        "series": "EQ", "isin": "ISIN"}
    declaration = {"source_id": "id", "symbol": "BSE", "subject": "Bonus 2:1", "ex_session": "2025-05-23",
        "known_session": "2025-05-15", "kind": "bonus", "additional_shares": 2, "existing_shares": 1,
        "new_shares": 3, "old_shares": 1, "old_isin": "ISIN"}
    return row, declaration


def test_bonus_means_additional_not_total_shares():
    row, declaration = declarations()
    assert classify_actions([row], [declaration])["BSE"][0].new_shares == 3
    declaration["new_shares"] = 2
    with pytest.raises(ValueError, match="total-share"):
        classify_actions([row], [declaration])


def test_unknown_extra_or_missing_action_blocks():
    row, declaration = declarations()
    for rows, declarations_ in [([row], []), ([], [declaration]), ([row, copy.deepcopy(row)], [declaration])]:
        with pytest.raises(ValueError, match="coverage"):
            classify_actions(rows, declarations_)


def test_price_only_dividend_is_explicit_and_not_a_share_action():
    row, declaration = declarations()
    row["subject"] = declaration["subject"] = "Dividend - Rs 23 Per Share"
    declaration["kind"] = "price_only_dividend"
    assert classify_actions([row], [declaration]) == {}
    row["subject"] = declaration["subject"] = "Rights 1:1"
    with pytest.raises(ValueError, match="explicit dividend"):
        classify_actions([row], [declaration])


def test_split_ratio_must_match_face_values():
    row, declaration = declarations()
    row["subject"] = declaration["subject"] = "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share"
    declaration.update(kind="split", new_shares=5)
    assert classify_actions([row], [declaration])["BSE"][0].new_shares == 5
    declaration["new_shares"] = 3
    with pytest.raises(ValueError, match="face values"):
        classify_actions([row], [declaration])
