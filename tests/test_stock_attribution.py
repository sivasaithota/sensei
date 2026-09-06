from copy import deepcopy
import hashlib
import json

import pandas as pd
import pytest

from sensei.research.stock_attribution import pre_entry_atr, attribute_trades, volatility_bin, diagnose_report


def bars():
    dates = pd.bdate_range("2024-01-01", periods=20)
    return pd.DataFrame({"open": 100., "high": 103., "low": 99., "close": 100.}, index=dates)


def test_atr_uses_complete_pre_entry_sessions_and_ignores_entry_and_future_prices():
    frame = bars()
    entry = frame.index[16]
    assert pre_entry_atr(frame, entry, frame.index) == 4
    changed = frame.copy()
    changed.loc[entry:, :] = 10000
    assert pre_entry_atr(changed, entry, frame.index) == 4
    assert pre_entry_atr(frame.loc[:frame.index[15]], entry, frame.index) == 4
    assert pre_entry_atr(frame.drop(frame.index[10]), entry, frame.index) is None
    assert pre_entry_atr(frame, frame.index[3], frame.index) is None


def test_true_range_includes_previous_close_gap():
    frame = bars()
    frame.loc[frame.index[15], ["open", "high", "low", "close"]] = [111, 112, 110, 111]
    assert pre_entry_atr(frame, frame.index[16], frame.index) == pytest.approx((13 * 4 + 12) / 14)


@pytest.mark.parametrize("ratio,expected", [(None, "unknown"), (.99, "below_1_atr"), (1, "1_to_below_2_atr"), (2, "at_least_2_atr")])
def test_fixed_volatility_boundaries(ratio, expected):
    assert volatility_bin(ratio) == expected


def campaign():
    return {"open_positions": 0, "net_pnl": -25., "trades": [
        {"symbol": "A", "entry_date": "2024-01-23", "exit_date": "2024-01-24",
         "entry_price": 100., "exit_reason": "stop", "gross_pnl": -20., "costs": 5., "net_pnl": -25.}]}


def test_grouping_preserves_trade_pnl_and_reports_exit_year_not_account_return():
    frame = bars()
    c = campaign()
    result = attribute_trades(c, {"A": frame}, frame.index, stop_pct=5.)
    for dimension in ("exit_year", "symbol", "exit_reason", "stop_atr_bin"):
        groups = result["groups"][dimension]
        assert sum(g["trades"] for g in groups.values()) == 1
        assert sum(g["net_pnl"] for g in groups.values()) == -25
    assert result["trades"][0]["pre_entry_atr14"] == 4
    assert result["trades"][0]["stop_atr_ratio"] == 1.25
    assert result["groups"]["exit_year"]["2024"]["costs"] == 5
    assert "annual_return" not in result
    assert c == campaign()


def test_material_pnl_discrepancy_and_open_positions_block_attribution():
    frame = bars()
    for update in ({"net_pnl": 500}, {"open_positions": 1}):
        c = deepcopy(campaign()); c.update(update)
        with pytest.raises(ValueError):
            attribute_trades(c, {"A": frame}, frame.index, stop_pct=5.)


@pytest.mark.parametrize("tamper", ["report", "manifest", "settings"])
def test_source_integrity_failure_cannot_publish_derivative(tmp_path, tamper):
    identity = {"settings": {"name": "frozen"}}
    run_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    directory = tmp_path / run_id
    directory.mkdir()
    report = {"run_id": run_id, "settings": identity["settings"].copy()}
    manifest = {"run_id": run_id, "identity": identity}
    if tamper == "settings":
        report["settings"]["name"] = "different"
    if tamper == "manifest":
        manifest["identity"]["settings"]["name"] = "different"
    path = directory / "report.json"
    path.write_text(json.dumps(report))
    path.with_name("report.sha256").write_text(hashlib.sha256(path.read_bytes()).hexdigest())
    path.with_name("manifest.json").write_text(json.dumps(manifest))
    if tamper == "report":
        path.write_text('{"can_trade": true}')
    output = tmp_path / "derivatives"
    with pytest.raises(ValueError, match="mismatch"):
        diagnose_report(path, output)
    assert not output.exists()
