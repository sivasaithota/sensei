from dataclasses import replace

import pandas as pd
import pytest

from sensei.backtest.portfolio_campaign import PortfolioCampaignConfig, run_portfolio_campaign
from sensei.backtest.raw_accounting import RawAccounting, RawAction


def scenario(*, availability=True, hold=2, liquidate=True):
    dates = pd.bdate_range("2025-05-21", periods=6)
    prices = [300., 300., 100., 100., 110., 110.]
    raw = pd.DataFrame({"open": prices, "high": [p + .01 for p in prices],
        "low": [p - .01 for p in prices], "close": prices, "volume": 1000.,
        "identity_verified": True}, index=dates)
    bonus = RawAction("BSE", dates[2], "bonus", 0., "bonus", "Bonus 2:1",
        new_shares=3, old_shares=1, known_from=dates[0],
        available_from=dates[4] if availability else None,
        availability_known_from=dates[3] if availability else None,
        availability_source_sha256="a" * 64 if availability else None,
        availability_basis="scenario" if availability else None)
    return dict(frames={"BSE": raw.drop(columns="identity_verified")},
        strategies={"test": {"fn": lambda f: pd.Series([True, False, False, False, False, False], index=f.index),
            "stop_pct": 50, "target_pct": 100, "max_hold_days": hold}},
        config=PortfolioCampaignConfig(capital=900, max_position_pct=100, max_risk_per_trade_pct=100,
            cost_pct=0, liquidate_at_end=liquidate), evaluation_start=dates[1],
        raw_accounting=RawAccounting({"BSE": raw}, {"BSE": pd.Series(1, index=dates, dtype="Int64")},
            (bonus,), "b" * 64, dates[1], dates[-1]))


def test_bonus_time_exit_sells_original_then_waits_for_available_shares():
    report = run_portfolio_campaign(**scenario())
    assert [t.quantity for t in report.trades] == [3, 6]
    assert [t.exit_date for t in report.trades] == ["2025-05-23", "2025-05-27"]
    assert [t.exit_reason for t in report.trades] == ["time", "deferred_time"]
    assert report.equity_curve[1].cash == 300
    assert report.equity_curve[1].share_receivables == 600
    assert report.final_equity == 960
    assert report.strategy_pnl == {"test": 60}


def test_unknown_availability_leaves_visible_receivable_after_forced_liquidation():
    report = run_portfolio_campaign(**scenario(availability=False))
    assert [t.quantity for t in report.trades] == [3]
    assert report.equity_curve[-1].cash == 300
    assert report.equity_curve[-1].share_receivables == 660
    assert report.final_equity == 960
    assert report.open_positions == 1
    assert report.raw_accounting["liquidation_complete"] is False
    assert report.raw_accounting["pending_holdings"][0]["quantity"] == 6
    assert sum(report.strategy_pnl.values()) == report.net_pnl


def test_bonus_coordinate_change_creates_no_cash_or_equity_before_exit():
    report = run_portfolio_campaign(**scenario(hold=20, liquidate=False))
    point = report.equity_curve[1]
    assert (point.cash, point.invested, point.share_receivables, point.equity) == (0, 300, 600, 900)
    assert report.trades == ()
    assert [(r["event"], r["session"]) for r in report.raw_accounting["share_ledger"]] == [
        ("accrual", "2025-05-23"), ("release", "2025-05-27")]
    assert report.equity_curve[3].share_receivables == 0
    assert report.equity_curve[3].invested == 990


def test_availability_knowledge_delays_release_and_sale_until_known():
    kwargs = scenario()
    context = kwargs["raw_accounting"]
    kwargs["raw_accounting"] = replace(context, actions=(replace(context.actions[0],
        available_from=pd.Timestamp("2025-05-26"), availability_known_from=pd.Timestamp("2025-05-28")),))
    report = run_portfolio_campaign(**kwargs)
    assert [t.exit_date for t in report.trades] == ["2025-05-23", "2025-05-28"]


def test_ex_session_buyer_does_not_receive_prior_holder_bonus():
    kwargs = scenario(hold=20)
    kwargs["strategies"]["test"]["fn"] = lambda f: pd.Series([False, True, False, False, False, False], index=f.index)
    report = run_portfolio_campaign(**kwargs)
    assert report.raw_accounting["share_ledger"] == []
    assert report.trades[0].quantity == 9
    assert report.final_equity == 990


def test_ex_session_gap_stop_sells_original_shares_only_and_keeps_queued_exit():
    kwargs = scenario(hold=20)
    kwargs["strategies"]["test"]["stop_pct"] = 5
    raw = kwargs["raw_accounting"].frames["BSE"]
    raw.loc[pd.Timestamp("2025-05-23"), ["open", "high", "low", "close"]] = [90, 91, 89, 90]
    report = run_portfolio_campaign(**kwargs)
    assert [(t.quantity, t.exit_reason, t.exit_price) for t in report.trades] == [
        (3, "stop_gap", 90), (6, "deferred_stop_gap", 110)]
    assert report.final_equity == 930


def test_same_day_availability_releases_once_and_allows_whole_exit():
    kwargs = scenario()
    context = kwargs["raw_accounting"]
    kwargs["raw_accounting"] = replace(context, actions=(replace(context.actions[0],
        available_from=context.actions[0].ex_date, availability_known_from=context.actions[0].known_from),))
    report = run_portfolio_campaign(**kwargs)
    assert [t.quantity for t in report.trades] == [9]
    assert report.final_equity == 900
    assert len([r for r in report.raw_accounting["share_ledger"] if r["event"] == "release"]) == 1


def test_fractional_bonus_is_not_rounded_or_discarded():
    kwargs = scenario()
    context = kwargs["raw_accounting"]
    kwargs["raw_accounting"] = replace(context, actions=(replace(context.actions[0], new_shares=3, old_shares=2),))
    with pytest.raises(ValueError, match="fractional bonus"):
        run_portfolio_campaign(**kwargs)


@pytest.mark.parametrize("changes", [
    {"new_shares": True}, {"old_shares": 0}, {"new_shares": 1}, {"known_from": None},
    {"known_from": pd.Timestamp("2025-05-26")}, {"availability_source_sha256": None},
    {"availability_basis": "assume_credited"}, {"available_from": pd.Timestamp("2025-05-22")},
    {"availability_known_from": pd.Timestamp("2025-05-26T10:00")},
])
def test_invalid_bonus_metadata_fails_closed(changes):
    kwargs = scenario()
    context = kwargs["raw_accounting"]
    kwargs["raw_accounting"] = replace(context, actions=(replace(context.actions[0], **changes),))
    with pytest.raises(ValueError):
        run_portfolio_campaign(**kwargs)


def test_missing_bonus_ex_session_cannot_silently_erase_entitlement():
    kwargs = scenario()
    context = kwargs["raw_accounting"]
    kwargs["raw_accounting"] = replace(context, actions=(replace(context.actions[0], ex_date=pd.Timestamp("2025-05-24")),))
    with pytest.raises(ValueError, match="evaluation calendar"):
        run_portfolio_campaign(**kwargs)


def test_old_bonus_outside_narrow_evaluation_does_not_require_an_ex_session():
    kwargs = scenario()
    kwargs["evaluation_start"] = pd.Timestamp("2025-05-26")
    report = run_portfolio_campaign(**kwargs)
    assert report.raw_accounting["share_ledger"] == []


def test_dividend_while_bonus_is_pending_is_not_silently_reinterpreted():
    kwargs = scenario()
    context = kwargs["raw_accounting"]
    extra = RawAction("BSE", pd.Timestamp("2025-05-26"), "dividend", 1, "other", "Dividend")
    kwargs["raw_accounting"] = replace(context, actions=context.actions + (extra,))
    with pytest.raises(ValueError, match="pending bonus"):
        run_portfolio_campaign(**kwargs)


def test_simultaneous_bonus_and_dividend_are_rejected():
    kwargs = scenario()
    context = kwargs["raw_accounting"]
    extra = RawAction("BSE", context.actions[0].ex_date, "dividend", 1, "other", "Dividend")
    kwargs["raw_accounting"] = replace(context, actions=context.actions + (extra,))
    with pytest.raises(ValueError, match="simultaneous"):
        run_portfolio_campaign(**kwargs)


@pytest.mark.parametrize("cost_model,expected", [("flat_round_trip", 938.5), ("current_delivery_schedule", 907.85)])
def test_partial_sale_cost_allocation_and_equity_reconcile(cost_model, expected):
    kwargs = scenario()
    kwargs["config"] = replace(kwargs["config"], cost_pct=.25, cost_model=cost_model)
    report = run_portfolio_campaign(**kwargs)
    assert [t.quantity for t in report.trades] == [2, 4]
    assert sum(t.gross_pnl for t in report.trades) == 40
    assert sum(t.costs for t in report.trades) + report.net_pnl == pytest.approx(40, abs=.011)
    assert sum(report.strategy_pnl.values()) == pytest.approx(report.net_pnl, abs=.011)
    if expected is not None:
        assert report.final_equity == expected
    for point in report.equity_curve:
        assert point.cash + point.invested + point.share_receivables + point.dividend_receivables == pytest.approx(point.equity, abs=.011)


def test_pending_bonus_value_cannot_fund_another_stock():
    kwargs = scenario()
    context = kwargs["raw_accounting"]
    dates = kwargs["frames"]["BSE"].index
    other = context.frames["BSE"].copy(deep=True)
    other.loc[:, ["open", "high", "low", "close"]] = [100, 100.01, 99.99, 100]
    kwargs["frames"]["OTHER"] = other.drop(columns="identity_verified")
    kwargs["raw_accounting"] = replace(context, frames={**context.frames, "OTHER": other},
        ticks={**context.ticks, "OTHER": pd.Series(1, index=dates, dtype="Int64")})
    kwargs["config"] = replace(kwargs["config"], max_positions_per_strategy=2)
    kwargs["prepared_signals"] = {
        ("test", "BSE"): pd.Series([True, False, False, False, False, False], index=dates),
        ("test", "OTHER"): pd.Series([False, False, True, False, False, False], index=dates),
    }
    report = run_portfolio_campaign(**kwargs)
    other_trade = next(t for t in report.trades if t.symbol == "OTHER")
    assert other_trade.entry_date == "2025-05-26"
    assert other_trade.quantity == 3  # only the original-share sale's ₹300 cash


def test_bonus_metadata_changes_identity_even_when_economic_dates_coincide():
    kwargs = scenario()
    original = run_portfolio_campaign(**kwargs)
    context = kwargs["raw_accounting"]
    kwargs["raw_accounting"] = replace(context, actions=(replace(context.actions[0], availability_source_sha256="c" * 64),))
    revised = run_portfolio_campaign(**kwargs)
    assert revised.final_equity == original.final_equity
    assert revised.experiment_id != original.experiment_id


def test_pending_only_stop_does_not_block_unrelated_strategy_entry():
    kwargs = scenario(hold=20)
    context = kwargs["raw_accounting"]
    dates = context.frames["BSE"].index
    kwargs["strategies"]["test"]["stop_pct"] = 5
    context.frames["BSE"].loc[dates[2:4], ["open", "high", "low", "close"]] = [90, 91, 89, 90]
    other = context.frames["BSE"].copy()
    other.loc[:, ["open", "high", "low", "close"]] = [100, 100.01, 99.99, 100]
    kwargs["frames"]["OTHER"] = other.drop(columns="identity_verified")
    kwargs["raw_accounting"] = replace(context, frames={**context.frames, "OTHER": other},
        ticks={**context.ticks, "OTHER": pd.Series(1, index=dates, dtype="Int64")})
    kwargs["config"] = replace(kwargs["config"], max_positions_per_strategy=2)
    kwargs["prepared_signals"] = {
        ("test", "BSE"): pd.Series([True, False, False, False, False, False], index=dates),
        ("test", "OTHER"): pd.Series([False, False, True, False, False, False], index=dates),
    }
    report = run_portfolio_campaign(**kwargs)
    other_trade = next(t for t in report.trades if t.symbol == "OTHER")
    assert other_trade.entry_date == "2025-05-26"
    assert other_trade.quantity == 2
    assert [(t.quantity, t.exit_reason) for t in report.trades if t.symbol == "BSE"] == [
        (3, "stop_gap"), (6, "deferred_stop_gap")]


def test_pre_bonus_dividend_is_attributed_once_across_sale_legs():
    kwargs = scenario(hold=3)
    dates = pd.bdate_range("2025-05-20", periods=7)
    prices = [300., 300., 300., 100., 100., 110., 110.]
    raw = pd.DataFrame({"open": prices, "high": [p + .01 for p in prices],
        "low": [p - .01 for p in prices], "close": prices, "volume": 1000., "identity_verified": True}, index=dates)
    context = kwargs["raw_accounting"]
    bonus = replace(context.actions[0], ex_date=dates[3], known_from=dates[0],
        available_from=dates[5], availability_known_from=dates[4])
    dividend = RawAction("BSE", dates[2], "dividend", 9., "dividend", "Dividend")
    kwargs.update(frames={"BSE": raw.drop(columns="identity_verified")}, evaluation_start=dates[1],
        raw_accounting=replace(context, frames={"BSE": raw}, ticks={"BSE": pd.Series(1, index=dates, dtype="Int64")},
            actions=(dividend, bonus), start=dates[1], end=dates[-1]))
    kwargs["strategies"]["test"]["fn"] = lambda f: pd.Series([True] + [False] * 6, index=f.index)
    report = run_portfolio_campaign(**kwargs)
    assert [t.gross_pnl for t in report.trades] == [9, 78]
    assert report.raw_accounting["dividend_receivables"] == 27
    assert report.final_equity == 987
    assert report.strategy_pnl == {"test": 87}


def test_rational_ratio_is_allowed_when_actual_entitlement_is_whole():
    kwargs = scenario()
    context = kwargs["raw_accounting"]
    raw = context.frames["BSE"]
    raw.iloc[2:, raw.columns.get_indexer(["open", "high", "low", "close"])] = [225., 225.01, 224.99, 225.]
    kwargs["raw_accounting"] = replace(context, actions=(replace(context.actions[0], new_shares=4, old_shares=3),))
    report = run_portfolio_campaign(**kwargs)
    assert [t.quantity for t in report.trades] == [3, 1]
    assert report.final_equity == 900
