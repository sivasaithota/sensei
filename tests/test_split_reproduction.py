import pandas as pd
import pytest

from sensei.research.action_history import ShareAction, signal_history
from sensei.research.split_reproduction import audit_transform, identity_row, pinned


def sample():
    frame = pd.DataFrame({"open": [100., 20., 22.], "high": [100., 20., 22.],
        "low": [100., 20., 22.], "close": [100., 20., 22.], "volume": [10., 50., 60.]},
        index=pd.date_range("2024-01-01", periods=3))
    action = ShareAction("split", frame.index[1], frame.index[1], "split", 5, 1)
    return frame, action


def test_real_replay_oracle_accepts_valid_transform():
    frame, action = sample()
    result = audit_transform(frame, action, rtol=1e-12, atol=1e-10)
    assert result["decision_cutoffs"] == 3
    assert result["oracle_cells"] == 30
    assert result["later_knowledge_blocked"]


def test_oracle_detects_wrong_ratio_even_when_append_invariant():
    frame, action = sample()
    def wrong(raw, actions, cutoff):
        result = signal_history(raw, actions, cutoff)
        if cutoff >= action.ex_session:
            result.loc[result.index < action.ex_session, "close"] *= 2
        return result
    with pytest.raises(ValueError, match="rational oracle"):
        audit_transform(frame, action, rtol=1e-12, atol=1e-10, transform=wrong)


def test_oracle_detects_future_raw_dependency():
    frame, action = sample()
    def leaky(raw, actions, cutoff):
        result = signal_history(raw, actions, cutoff)
        result["close"] += raw.iloc[-1].close
        return result
    with pytest.raises(AssertionError):
        audit_transform(frame, action, rtol=1e-12, atol=1e-10, transform=leaky)


def test_later_knowledge_negative_control_is_required():
    frame, action = sample()
    def ignores_knowledge(raw, actions, cutoff):
        return signal_history(raw, [action], cutoff)
    with pytest.raises(ValueError, match="negative control"):
        audit_transform(frame, action, rtol=1e-12, atol=1e-10, transform=ignores_knowledge)


def test_blocked_transform_cannot_mutate_raw_input():
    frame, action = sample()
    def mutates_on_block(raw, actions, cutoff):
        if actions[0].ex_session <= cutoff < actions[0].known_session:
            raw.loc[raw.index[0], "volume"] = 999
        return signal_history(raw, actions, cutoff)
    with pytest.raises(AssertionError):
        audit_transform(frame, action, rtol=1e-12, atol=1e-10, transform=mutates_on_block)


@pytest.mark.parametrize("rtol,atol", [(1e-3, 1e-10), (1e-12, 1), (float("nan"), 0)])
def test_tolerances_cannot_be_widened(rtol, atol):
    frame, action = sample()
    with pytest.raises(ValueError, match="tolerances"):
        audit_transform(frame, action, rtol=rtol, atol=atol)


def test_changed_pinned_input_rejected(tmp_path):
    path = tmp_path / "input.json"
    path.write_text('{}')
    with pytest.raises(ValueError, match="changed input"):
        pinned({"path": str(path), "sha256": "0" * 64})


def identity_frame():
    return pd.DataFrame([{"symbol": "HEG", "isin": "EXPECTED", "series": "EQ",
        "instrument_class": "equity", "ok": True}])


def test_isin_column_selection_and_alias_ambiguity():
    raw = identity_frame()
    assert identity_row(raw, "HEG", "EXPECTED")["isin"] == "EXPECTED"
    raw.loc[0, "symbol"] = "HISTORIC_ALIAS"
    assert identity_row(raw, "HEG", "EXPECTED")["symbol"] == "HISTORIC_ALIAS"
    with pytest.raises(ValueError, match="ambiguous"):
        identity_row(pd.concat([raw, identity_frame()]), "HEG", "EXPECTED")


@pytest.mark.parametrize("field,value", [("isin", "WRONG"), ("series", "BE"), ("ok", False)])
def test_symbol_match_does_not_override_invalid_identity(field, value):
    raw = identity_frame()
    raw.loc[0, field] = value
    with pytest.raises(ValueError, match="quality mismatch"):
        identity_row(raw, "HEG", "EXPECTED")
