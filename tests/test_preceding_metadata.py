import pandas as pd
import pytest

from sensei.research.preceding_metadata import entry_decision, stable_history_lengths, prepare_entry_masks


META = {"TckrSymb": "STOCK", "SctySrs": "EQ", "ISIN": "OLD", "FinInstrmId": "1",
    "SctyTpFlg": "0", "CallAuctnInd": "1", "SctyStsNrmlMkt": "2", "ElgbltyNrmlMkt": "1",
    "PrtdToTrad": "0", "DelFlg": "N", "NewBrdLotQty": "1"}


def prices(n=255):
    dates = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame({"symbol": "STOCK", "isin": "OLD", "close": 100.0, "volume": 10}, index=dates)


def test_only_immediate_preceding_snapshot_admits_and_missing_day_blocks():
    frame = prices()
    calendar = frame.index
    snapshots = {calendar[251]: {"STOCK": META}, calendar[253]: {"STOCK": META}}
    masks, _, _ = prepare_entry_masks({"STOCK": frame}, calendar, snapshots)
    assert masks["STOCK"].iloc[252:].tolist() == [True, False, True]


def test_entry_price_and_future_price_changes_do_not_change_gate():
    frame = prices()
    snapshots = {d: {"STOCK": META} for d in frame.index}
    before, _, _ = prepare_entry_masks({"STOCK": frame}, frame.index, snapshots)
    changed = frame.copy()
    changed.loc[changed.index[252]:, "close"] = 999999
    changed.loc[changed.index[252]:, "volume"] = 0
    after, _, _ = prepare_entry_masks({"STOCK": changed}, frame.index, snapshots)
    assert before["STOCK"].equals(after["STOCK"])


def test_identity_change_and_gap_restart_history_without_future_effect():
    frame = prices(10)
    frame.loc[frame.index[4]:, "isin"] = "NEW"
    lengths = stable_history_lengths(frame, frame.index, [frame.index[7]])
    assert lengths.tolist() == [1, 2, 3, 4, 1, 2, 3, 1, 2, 3]
    gapped = frame.drop(frame.index[2])
    assert stable_history_lengths(gapped, frame.index).iloc[2] == 1
    assert stable_history_lengths(frame.iloc[:4], frame.index, [frame.index[7]]).tolist() == [1, 2, 3, 4]


def test_future_snapshot_and_future_identity_are_not_admissible():
    frame = prices()
    prior = frame.index[-1]
    ok, reason = entry_decision(prior=prior, source_session=prior + pd.Timedelta(days=1),
        metadata=META, history=frame, stable_count=255)
    assert not ok and reason == "missing_immediate_predecessor_master"
    ok, reason = entry_decision(prior=prior, source_session=prior,
        metadata={**META, "ISIN": "NEW"}, history=frame, stable_count=255)
    assert not ok and reason == "history_identity_differs_from_entry_metadata"


def test_missing_metadata_blocks_without_deleting_instrument_or_price_history():
    frame = prices()
    masks, lengths, _ = prepare_entry_masks({"STOCK": frame}, frame.index, {})
    assert set(masks) == {"STOCK"} and masks["STOCK"].index.equals(frame.index)
    assert not masks["STOCK"].any() and lengths["STOCK"].iloc[-1] == 255


def test_short_ranking_window_rejected():
    with pytest.raises(ValueError, match="252"):
        prepare_entry_masks({"STOCK": prices()}, prices().index, {}, warmup=60)
