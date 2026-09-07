from fractions import Fraction

import pandas as pd
import pytest

from sensei.research.stock_closure import classify_action, map_actions
from sensei.backtest.portfolio_campaign import PortfolioCampaignConfig, run_portfolio_campaign
from sensei.backtest.raw_accounting import RawAccounting


@pytest.mark.parametrize("subject,kind,ratio", [
    ("Bonus 1:2", "bonus", Fraction(3, 2)),
    ("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share", "split", Fraction(5)),
    ("Bonus 1:1 / Dividend - Rs 2 Per Share", "unsupported", None),
    ("Demerger", "unsupported", None), ("Bonus 1:0", "unsupported", None),
    ("Buy Back", "no_accounting", None),
])
def test_bounded_actions_reject_unknown_or_mixed_components(subject, kind, ratio):
    row = {"subject": subject, "symbol": "STOCK", "date": pd.Timestamp("2025-01-01"), "series": "EQ"}
    result = classify_action(row)
    assert result[0] == kind and result[2] == ratio


def frame():
    dates = pd.bdate_range("2025-01-01", periods=6)
    return pd.DataFrame({"symbol": "STOCK", "isin": "ISIN", "series": "EQ", "open": 100.0,
        "high": 101.0, "low": 99.0, "close": 100.0, "prev_close": 100.0, "volume": 100}, index=dates)


def test_share_availability_scenario_and_reset_are_explicit():
    f = frame()
    rows = [{"symbol": "STOCK", "isin": "ISIN", "series": "EQ", "date": f.index[1], "subject": "Bonus 1:1", "source_id": "one"}]
    actions, resets, details = map_actions({"STOCK": f}, rows, f.index, "a" * 64)
    assert actions[0].available_from == f.index[3]
    assert actions[0].availability_basis == "scenario"
    assert actions[0].new_shares == 2 and actions[0].old_shares == 1
    assert resets["STOCK"] == {f.index[1]} and details[0]["source_ids"] == ["one"]


def test_unknown_isin_change_is_a_held_accounting_blocker():
    f = frame()
    f.loc[f.index[3]:, "isin"] = "NEW"
    actions, resets, _ = map_actions({"STOCK": f}, [], f.index, "a" * 64)
    assert actions[0].kind == "unsupported" and actions[0].ex_date == f.index[3]
    assert f.index[3] in resets["STOCK"]


def test_non_session_event_cannot_silently_disappear():
    f = frame()
    source = {"symbol": "STOCK", "isin": "ISIN", "series": "EQ", "date": pd.Timestamp("2025-01-04"), "subject": "Demerger", "source_id": "source"}
    actions, _, _ = map_actions({"STOCK": f}, [source], f.index, "a" * 64)
    assert actions[0].ex_date == pd.Timestamp("2025-01-06") and actions[0].kind == "unsupported"


def test_missing_entry_metadata_does_not_remove_a_held_position():
    f = frame()
    signals = pd.Series(False, index=f.index)
    signals.iloc[0] = True
    mask = pd.Series(False, index=f.index)
    mask.iloc[1] = True
    spec = {"fn": lambda _: signals, "stop_pct": 20, "target_pct": 20, "max_hold_days": 3}
    report = run_portfolio_campaign(frames={"STOCK": f}, strategies={"test": spec},
        entry_eligibility={"STOCK": mask}, config=PortfolioCampaignConfig(liquidate_at_end=True))
    assert len(report.trades) == 1
    assert report.trades[0].entry_date == str(f.index[1].date())
    assert report.trades[0].exit_date > report.trades[0].entry_date


def test_raw_signal_basis_is_reported_and_part_of_experiment_identity():
    f = frame().assign(identity_verified=True)
    ticks = {"STOCK": pd.Series(5, index=f.index, dtype="Int64")}
    raw = RawAccounting({"STOCK": f}, ticks, (), "a" * 64, f.index[0], f.index[-1], signal_basis="raw identity epochs")
    legacy = RawAccounting({"STOCK": f}, ticks, (), "a" * 64, f.index[0], f.index[-1])
    assert raw.identity() != legacy.identity()
    signal = pd.Series(False, index=f.index)
    report = run_portfolio_campaign(frames={"STOCK": f}, strategies={"test": {"fn": lambda _: signal,
        "stop_pct": 5, "target_pct": 10, "max_hold_days": 3}}, config=PortfolioCampaignConfig(), raw_accounting=raw)
    assert report.raw_accounting["signal_basis"] == "raw identity epochs"


@pytest.mark.parametrize("identity_changed,previous_close", [(True, 100.0), (False, 50.0), (True, 50.0)])
def test_dividend_cannot_explain_unrelated_identity_or_unit_change(identity_changed, previous_close):
    f = frame()
    if identity_changed:
        f.loc[f.index[2]:, "isin"] = "NEW"
    f.loc[f.index[2], "prev_close"] = previous_close
    row = {"symbol": "STOCK", "isin": f.loc[f.index[2], "isin"], "series": "EQ", "date": f.index[2],
        "subject": "Dividend - Rs 1 Per Share", "source_id": "dividend"}
    actions, resets, _ = map_actions({"STOCK": f}, [row], f.index, "a" * 64)
    assert any(a.ex_date == f.index[2] and a.kind == "unsupported" for a in actions)
    assert f.index[2] in resets["STOCK"]


def test_symbol_match_with_wrong_isin_cannot_credit_dividend():
    f = frame()
    row = {"symbol": "STOCK", "isin": "OTHER", "series": "EQ", "date": f.index[2],
        "subject": "Dividend - Rs 1 Per Share", "source_id": "wrong"}
    actions, _, _ = map_actions({"STOCK": f}, [row], f.index, "a" * 64)
    assert actions[0].kind == "unsupported" and actions[0].amount == 0


def test_documented_cash_adjustment_and_split_ratio_explain_only_compatible_changes():
    f = frame()
    f.loc[f.index[2], "prev_close"] = 99
    row = {"symbol": "STOCK", "isin": "ISIN", "series": "EQ", "date": f.index[2],
        "subject": "Dividend - Rs 1 Per Share", "source_id": "cash"}
    actions, _, _ = map_actions({"STOCK": f}, [row], f.index, "a" * 64)
    assert actions[0].kind == "dividend"
    f.loc[f.index[2]:, "isin"] = "NEW"
    f.loc[f.index[2], "prev_close"] = 50
    row.update(isin="NEW", subject="Face Value Split (Sub-Division) - From Rs 2/- Per Share To Re 1/- Per Share")
    actions, _, _ = map_actions({"STOCK": f}, [row], f.index, "a" * 64)
    assert actions[0].kind == "split"


def test_documented_split_bridge_handles_old_action_isin_without_splicing_history():
    f = frame()
    stamp = f.index[2]
    f.loc[stamp:, "isin"] = "NEW"
    f.loc[stamp:, ["open", "high", "low", "close"]] /= 5
    f.loc[f.index[3]:, "prev_close"] /= 5
    row = {"symbol": "STOCK", "isin": "ISIN", "series": "EQ", "date": stamp,
        "subject": "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share", "source_id": "split"}
    bridge = {"symbol": "STOCK", "series": "EQ", "old_isin": "ISIN", "new_isin": "NEW", "ex_date": str(stamp.date()),
        "announced_on": str(f.index[1].date()), "new_shares": 5, "old_shares": 1,
        "source": {"path": "notice.pdf", "sha256": "b" * 64}}
    blocked, _, _ = map_actions({"STOCK": f}, [row], f.index, "a" * 64)
    assert blocked[0].kind == "unsupported"
    actions, resets, details = map_actions({"STOCK": f}, [row], f.index, "a" * 64, [bridge])
    assert len(actions) == 1 and actions[0].kind == "split"
    assert actions[0].new_shares == 5 and resets["STOCK"] == {stamp}
    assert details[0]["identity_bridge"] == bridge
    assert f.loc[stamp, "isin"] == "NEW" and f.loc[f.index[1], "close"] == 100
    for changed in [{"old_isin": "WRONG"}, {"new_isin": "WRONG"}, {"new_shares": 2}]:
        actions, _, _ = map_actions({"STOCK": f}, [row], f.index, "a" * 64, [{**bridge, **changed}])
        assert actions[0].kind == "unsupported"
    dividend = {**row, "subject": "Dividend - Rs 1 Per Share"}
    actions, _, _ = map_actions({"STOCK": f}, [dividend], f.index, "a" * 64, [bridge])
    assert actions[0].kind == "unsupported"
    with pytest.raises(ValueError, match="bridge"):
        map_actions({"STOCK": f}, [row], f.index, "a" * 64, [{**bridge, "announced_on": str(f.index[3].date())}])
    for field in ("announced_on", "ex_date"):
        for bad_date in (None, "NaT", "2025-01-01T12:00:00", "2025-01-01T00:00:00Z"):
            with pytest.raises(ValueError, match="bridge"):
                map_actions({"STOCK": f}, [row], f.index, "a" * 64, [{**bridge, field: bad_date}])

    with pytest.raises(ValueError, match="bridge"):
        map_actions({"STOCK": f}, [row], f.index, "a" * 64, [{**bridge, "announced_on": bridge["ex_date"]}])
