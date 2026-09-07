import pandas as pd
import pytest

from sensei.backtest.strategies import momentum_breakout_55
from sensei.research.signal_causality import audit_prefixes, audit_uniform_units, checked_signal, negative_control
from sensei.strategy.selection import SignalRankingPolicy


def bars():
    dates = pd.bdate_range("2024-01-01", periods=90)
    prices = [100. + i for i in range(90)]
    return pd.DataFrame({"open": prices, "high": [p + 1 for p in prices],
        "low": [p - 1 for p in prices], "close": prices,
        "volume": [1000.] * 60 + [10000., 1000., 1000.] * 10}, index=dates)


def test_real_breakout_is_append_invariant_at_every_cutoff():
    frame = bars()
    assert momentum_breakout_55(frame).any()
    result = audit_prefixes(frame, momentum_breakout_55, frame.index)
    assert result["prefix_comparisons"] == 90
    assert result["comparisons_with_later_rows"] == 89
    assert result["boolean_cells_compared"] == 90 * 91 // 2
    assert result["mismatched_cells"] == 0


def test_audit_detects_lookahead_and_checks_earlier_cells_not_only_endpoint():
    frame = bars()
    result = audit_prefixes(frame, lambda f: f.close < f.close.shift(-2), frame.index[5:10], maximum_examples=2)
    assert result["mismatched_cells"] == 10
    assert len(result["examples"]) == 2
    assert result["examples"][0]["signal_date"] < result["examples"][0]["cutoff"]
    assert negative_control()["deliberate_future_mean_mismatches"] > 0


def test_algorithm_prefix_pass_does_not_certify_revised_history():
    frame = bars()
    revised = frame.copy()
    revised.loc[frame.index[-1], "close"] = 1.
    assert audit_prefixes(revised, momentum_breakout_55, revised.index)["mismatched_cells"] == 0
    # Both histories can be internally causal while a changed vintage changes decisions.
    revised.loc[frame.index[60], "close"] = 1.
    assert not momentum_breakout_55(frame).equals(momentum_breakout_55(revised))


def test_reciprocal_units_preserve_breakout_and_ranking_without_rounding():
    result = audit_uniform_units(bars(), momentum_breakout_55, SignalRankingPolicy(),
        {"stop_pct": 5, "target_pct": 12}, [3, 5])
    assert all(r["signal_changes"] == 0 for r in result)
    assert max(v for r in result for v in r["score_component_absolute_differences"].values()) < 1e-12


@pytest.mark.parametrize("fn", [lambda f: f.close, lambda f: pd.Series(True, index=f.index[::-1])])
def test_bad_signal_contract_rejected(fn):
    with pytest.raises(ValueError, match="aligned Boolean"):
        checked_signal(bars(), fn)


def test_signal_does_not_get_to_mutate_audit_input():
    frame = bars()
    original = frame.copy()
    def mutable(f):
        f["close"] = 0.
        return f.close > 1
    checked_signal(frame, mutable)
    pd.testing.assert_frame_equal(frame, original)
