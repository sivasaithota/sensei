from dataclasses import replace

import pandas as pd
import pytest

from sensei.backtest.portfolio_campaign import PortfolioCampaignConfig, run_portfolio_campaign
from sensei.backtest.raw_accounting import RawAccounting, RawAction
from sensei.research.raw_portfolio import action_treatment, identity_matches, merge_candidate_rows, require_frozen_inputs, tick_from_reference, tick_reference


def case(actions=(), *, prices=(100, 100, 100, 100), ticks=(5, 5, 5, 5)):
    index = pd.bdate_range("2024-01-01", periods=4)
    raw = pd.DataFrame({"open": prices, "close": prices,
        "high": [x + .1 for x in prices], "low": [x - .1 for x in prices],
        "volume": 1_000_000, "identity_verified": True}, index=index)
    signal = raw.drop(columns="identity_verified").astype(float)
    signal.loc[:, ["open", "high", "low", "close"]] /= 5
    context = RawAccounting({"TEST": raw}, {"TEST": pd.Series(ticks, index=index, dtype="Int64")},
        tuple(RawAction("TEST", index[day], kind, amount, str(n), kind) for n, (day, kind, amount) in enumerate(actions)),
        "a" * 64, index[1], index[-1])
    kwargs = dict(frames={"TEST": signal}, strategies={"trend": {
        "fn": lambda f: pd.Series([True, False, False, False], index=f.index),
        "stop_pct": 5, "target_pct": 10, "max_hold_days": 20}},
        config=PortfolioCampaignConfig(capital=1000, max_position_pct=100, max_risk_per_trade_pct=100,
            max_positions_per_strategy=5, cost_pct=0, liquidate_at_end=True),
        evaluation_start=index[1], evaluation_end=index[-1], raw_accounting=context)
    return kwargs


def test_raw_whole_shares_use_signal_warmup_without_raw_predecessor():
    kwargs = case()
    context = kwargs["raw_accounting"]
    kwargs["raw_accounting"] = replace(context,
        frames={"TEST": context.frames["TEST"].iloc[1:]}, ticks={"TEST": context.ticks["TEST"].iloc[1:]})
    result = run_portfolio_campaign(**kwargs)
    assert result.trades[0].quantity == 10
    assert result.trades[0].entry_price == 100
    assert result.final_equity == 1000
    assert result.to_dict()["quantity_units"]["mode"] == "physical_whole_shares"


def test_dividend_on_exit_day_accrues_before_sale_but_entry_day_does_not():
    result = run_portfolio_campaign(**case([(1, "dividend", 50), (3, "dividend", 3)], prices=(100, 100, 100, 94)))
    assert result.trades[0].exit_reason == "stop_gap"
    assert result.trades[0].gross_pnl == -30  # -60 price P&L +30 gross entitlement
    assert result.final_equity == 970
    assert result.equity_curve[-1].cash == 940
    assert result.raw_accounting["dividend_receivables"] == 30
    assert len(result.raw_accounting["dividend_ledger"]) == 1
    assert sum(result.strategy_pnl.values()) == result.net_pnl


def test_dividend_receivable_never_increases_buying_power():
    kwargs = case([(2, "dividend", 20)])
    index = kwargs["frames"]["TEST"].index
    kwargs["strategies"]["trend"]["fn"] = lambda f: pd.Series([True, False, True, False], index=f.index)
    kwargs["strategies"]["trend"]["max_hold_days"] = 2
    result = run_portfolio_campaign(**kwargs)
    assert [t.quantity for t in result.trades] == [10, 10]
    assert result.raw_accounting["dividend_receivables"] == 200
    assert result.final_equity == 1200
    assert result.equity_curve[-1].cash == 1000
    assert all(p.equity == pytest.approx(p.cash + p.invested + p.dividend_receivables, abs=.011)
        for p in result.equity_curve)


def test_held_unsupported_event_stops_run_but_ex_date_buyer_has_no_entitlement():
    with pytest.raises(ValueError, match="unsupported held corporate action"):
        run_portfolio_campaign(**case([(2, "unsupported", 0)]))
    result = run_portfolio_campaign(**case([(1, "unsupported", 0)]))
    assert result.final_equity == 1000


@pytest.mark.parametrize("fault", ["missing", "identity", "tick", "ohlc"])
def test_bad_raw_evidence_cannot_silently_remove_a_candidate(fault):
    kwargs = case()
    context = kwargs["raw_accounting"]
    stamp = context.start
    if fault == "missing":
        kwargs["raw_accounting"] = replace(context, frames={"TEST": context.frames["TEST"].drop(stamp)},
            ticks={"TEST": context.ticks["TEST"].drop(stamp)})
    elif fault == "identity":
        context.frames["TEST"].loc[stamp, "identity_verified"] = False
    elif fault == "tick":
        context.ticks["TEST"].loc[stamp] = pd.NA
    else:
        context.frames["TEST"].loc[stamp, "high"] = 10
    with pytest.raises(ValueError):
        run_portfolio_campaign(**kwargs)


def test_dated_sell_tick_rounding_and_evidence_change_identity():
    fine = run_portfolio_campaign(**case(prices=(100, 100, 100, 94.9)))
    coarse = run_portfolio_campaign(**case(prices=(100, 100, 100, 94.9), ticks=(5, 5, 5, 50)))
    assert fine.trades[0].exit_price == 94.9
    assert coarse.trades[0].exit_price == 94.5
    assert coarse.experiment_id != fine.experiment_id
    kwargs = case()
    kwargs["raw_accounting"] = replace(kwargs["raw_accounting"], evidence_sha256="b" * 64)
    assert run_portfolio_campaign(**kwargs).experiment_id != run_portfolio_campaign(**case()).experiment_id


def test_duplicate_action_rejected():
    kwargs = case([(2, "dividend", 1)])
    context = kwargs["raw_accounting"]
    kwargs["raw_accounting"] = replace(context, actions=context.actions * 2)
    with pytest.raises(ValueError, match="duplicate corporate action"):
        run_portfolio_campaign(**kwargs)


@pytest.mark.parametrize("price,tick", [(249.99, 1), (250, 5), (1000, 5), (1000.01, 10),
    (5000, 10), (5000.01, 50), (10000, 50), (10000.01, 100), (20000, 100), (20000.01, 500)])
def test_post_april_2025_tick_boundaries(price, tick):
    assert tick_from_reference(pd.Timestamp("2025-04-15"), price) == tick


def test_tick_regimes_and_reference_are_past_only():
    assert tick_from_reference(pd.Timestamp("2024-06-07"), None) == 5
    assert tick_from_reference(pd.Timestamp("2024-06-10"), 100) == 1
    assert tick_from_reference(pd.Timestamp("2025-04-14"), 2500) == 5
    assert pd.isna(tick_from_reference(pd.Timestamp("2025-04-15"), None))
    calendar = pd.DatetimeIndex(["2025-03-28", "2025-04-01", "2025-04-15", "2025-04-30", "2025-05-02"])
    assert tick_reference(pd.Timestamp("2025-04-15"), calendar) == pd.Timestamp("2025-03-28")
    assert tick_reference(pd.Timestamp("2025-05-02"), calendar) == pd.Timestamp("2025-04-30")


@pytest.mark.parametrize("subject,expected", [
    ("Annual General Meeting / Dividend - Rs 56 Per Share", ("dividend", 56)),
    ("Interim Dividend - Rs 0.75 Per Sh", ("dividend", .75)),
    ("Dividend - Re 1 Per Share", ("dividend", 1)),
    ("Dividend - Rs 10 Per Share / Special Dividend - Rs 5 Per Share", ("dividend", 15)),
    ("Dividend - Rs 10 Per Share / Bonus 1:1", ("unsupported", 0)),
    ("Annual General Meeting", ("no_accounting", 0)),
    ("Buy Back", ("unsupported", 0)),
])
def test_action_parser_retains_unmodeled_parts(subject, expected):
    assert action_treatment({"symbol": "TEST", "series": "EQ", "date": pd.Timestamp("2024-01-01"), "subject": subject}) == expected


def test_dated_split_identity_and_series():
    event = {"exchange_symbol": "TEST", "effective_date": "2024-06-01", "new_isin": "new", "old_isin": "old"}
    reference = {"exchange_symbol": "TEST", "isin": "new"}
    row = {"isin": "old", "series": "EQ", "ok": True}
    assert identity_matches(row, reference, [event], pd.Timestamp("2024-05-31"))
    assert not identity_matches(row, reference, [event], pd.Timestamp("2024-06-01"))
    assert not identity_matches({**row, "series": "GS"}, reference, [event], pd.Timestamp("2024-05-31"))


@pytest.mark.parametrize("key", ["event_risk_policy", "kite_manifest", "benchmark_sha256", "input_frames", "signal"])
def test_same_path_cannot_hide_changed_frozen_inputs(key):
    original = {"event_risk_policy": {"event_date": "2024-01-02"}, "kite_manifest": {"snapshot_id": "first"},
        "benchmark_sha256": "a" * 64, "input_frames": {"TEST": "b" * 64}, "signal": {"module_sha256": "c" * 64}}
    changed = {**original, key: "changed-at-same-path"}
    with pytest.raises(ValueError, match=f"frozen source input changed: {key}"):
        require_frozen_inputs(original, changed)
    require_frozen_inputs(original, original)


def test_conflicting_raw_rows_remain_ambiguous_after_two_lookup_union():
    one = {"symbol": "TEST", "isin": "same", "series": "EQ", "close": 100}
    two = {**one, "close": 999}
    assert len(merge_candidate_rows([(0, one)], [(0, one)])) == 1
    candidates = merge_candidate_rows([(0, one), (1, two)], [(0, one), (1, two)])
    assert len(candidates) == 2
    assert candidates[0]["close"] == 100
    assert candidates[1]["close"] == 999
