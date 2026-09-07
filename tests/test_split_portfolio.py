from dataclasses import replace
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from sensei.backtest.portfolio_campaign import PortfolioCampaignConfig, run_portfolio_campaign
from sensei.backtest.raw_accounting import RawAccounting, RawAction


def scenario(*, available="2024-10-22", hold=2, liquidate=True):
    dates = pd.bdate_range("2024-10-16", periods=6)
    prices = [300., 300., 100., 100., 110., 110.]
    raw = pd.DataFrame({"open": prices, "high": [p + .01 for p in prices],
        "low": [p - .01 for p in prices], "close": prices, "volume": 1000.,
        "identity_verified": True}, index=dates)
    action = RawAction("HEG", dates[2], "split", 0., "split", "Subdivision 3/1",
        new_shares=3, old_shares=1, known_from=dates[1],
        available_from=pd.Timestamp(available) if available else None,
        availability_known_from=dates[2] if available else None,
        availability_source_sha256="a" * 64 if available else None,
        availability_basis="documented_market_admission" if available else None)
    return dict(frames={"HEG": raw.drop(columns="identity_verified")},
        strategies={"test": {"stop_pct": 50, "target_pct": 100, "max_hold_days": hold}},
        prepared_signals={("test", "HEG"): pd.Series([True] + [False] * 5, index=dates)},
        config=PortfolioCampaignConfig(capital=900, max_position_pct=100, max_risk_per_trade_pct=100,
            cost_pct=0, liquidate_at_end=liquidate), evaluation_start=dates[1],
        raw_accounting=RawAccounting({"HEG": raw}, {"HEG": pd.Series(1, index=dates, dtype="Int64")},
            (action,), "b" * 64, dates[1], dates[-1]))


def test_split_replaces_all_original_shares_and_defers_the_entire_exit():
    report = run_portfolio_campaign(**scenario())
    assert [(t.quantity, t.exit_date, t.exit_reason, t.entry_price) for t in report.trades] == [
        (9, "2024-10-22", "deferred_time", 100)]
    ex = report.equity_curve[1]
    assert (ex.cash, ex.invested, ex.share_receivables, ex.equity) == (0, 0, 900, 900)
    assert report.final_equity == 990
    assert report.strategy_pnl == {"test": 90}
    assert report.raw_accounting["share_ledger"][0]["kind"] == "split"


def test_unknown_split_availability_never_sells_old_quantity_in_new_units():
    report = run_portfolio_campaign(**scenario(available=None))
    assert report.trades == ()
    assert report.equity_curve[-1].cash == 0
    assert report.equity_curve[-1].share_receivables == 990
    assert report.raw_accounting["pending_holdings"][0]["quantity"] == 9
    assert report.raw_accounting["liquidation_complete"] is False
    assert report.final_equity == 990


def test_same_session_market_admission_allows_all_new_shares_to_sell():
    report = run_portfolio_campaign(**scenario(available="2024-10-18"))
    assert [(t.quantity, t.exit_date, t.exit_reason) for t in report.trades] == [(9, "2024-10-18", "time")]
    assert report.final_equity == 900
    assert [r["event"] for r in report.raw_accounting["share_ledger"]] == ["accrual", "release"]


def test_split_release_does_not_create_cash_or_duplicate_inventory():
    report = run_portfolio_campaign(**scenario(hold=20, liquidate=False))
    released = report.equity_curve[3]
    assert (released.cash, released.invested, released.share_receivables) == (0, 990, 0)
    assert report.open_positions == 1
    assert report.trades == ()


def test_new_ex_date_buyer_receives_no_split_entitlement():
    kwargs = scenario(available=None, hold=20)
    flags = kwargs["prepared_signals"][("test", "HEG")]
    flags.iloc[:] = False
    flags.iloc[1] = True
    report = run_portfolio_campaign(**kwargs)
    assert [t.quantity for t in report.trades] == [9]
    assert report.raw_accounting["share_ledger"] == []
    assert report.final_equity == 990


def test_split_gap_stop_is_queued_until_the_whole_holding_is_available():
    kwargs = scenario(hold=20)
    kwargs["strategies"]["test"]["stop_pct"] = 5
    kwargs["raw_accounting"].frames["HEG"].loc["2024-10-18", ["open", "high", "low", "close"]] = [90, 91, 89, 90]
    report = run_portfolio_campaign(**kwargs)
    assert [(t.quantity, t.exit_reason, t.exit_price) for t in report.trades] == [(9, "deferred_stop_gap", 110)]


@pytest.mark.parametrize("changes", [
    {"new_shares": 1, "old_shares": 2}, {"new_shares": 3, "old_shares": 2},
    {"known_from": pd.Timestamp("2024-10-21")}, {"ex_date": pd.Timestamp("2024-10-19")},
    {"availability_source_sha256": None}, {"new_shares": True},
])
def test_invalid_or_fractional_split_fails_closed(changes):
    kwargs = scenario()
    raw = kwargs["raw_accounting"]
    kwargs["raw_accounting"] = replace(raw, actions=(replace(raw.actions[0], **changes),))
    with pytest.raises(ValueError):
        run_portfolio_campaign(**kwargs)


def test_split_costs_remain_once_per_actual_buy_and_sale():
    kwargs = scenario()
    kwargs["config"] = replace(kwargs["config"], cost_model="current_delivery_schedule")
    report = run_portfolio_campaign(**kwargs)
    # ₹900 cannot fund 3 old shares plus entry fees: 2 become 6.
    assert [t.quantity for t in report.trades] == [6]
    assert report.trades[0].costs == 16.80  # buy600 fee .74 + sell660 fee16.06
    assert report.final_equity == 943.20
    assert sum(report.strategy_pnl.values()) == report.net_pnl


def test_availability_knowledge_cannot_release_split_shares_early():
    kwargs = scenario(available="2024-10-18")
    raw = kwargs["raw_accounting"]
    kwargs["raw_accounting"] = replace(raw, actions=(replace(raw.actions[0], availability_known_from=pd.Timestamp("2024-10-23")),))
    report = run_portfolio_campaign(**kwargs)
    assert report.trades[0].exit_date == "2024-10-23"
    assert all(p.cash == 0 for p in report.equity_curve[:-1])


def test_inventory_implementation_changes_experiment_identity(tmp_path, monkeypatch):
    import sys
    import sensei.backtest.portfolio_campaign as campaign

    original = run_portfolio_campaign(**scenario())
    source = Path(campaign.__file__).read_text()
    altered = source.replace(
        'self.pending_quantity = self.quantity if action.kind == "split" else self.quantity - original',
        'self.pending_quantity = self.quantity - original')
    assert altered != source
    path = tmp_path / "altered_inventory_campaign.py"
    path.write_text(altered)
    spec = importlib.util.spec_from_file_location("altered_inventory_campaign", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    revised = module.run_portfolio_campaign(**scenario())
    assert (original.final_equity, revised.final_equity) == (990, 960)
    assert original.experiment_id != revised.experiment_id
