from dataclasses import replace

import pandas as pd
import pytest

from sensei.backtest.costs import delivery_charge, delivery_quantity
from sensei.backtest.portfolio_campaign import PortfolioCampaignConfig, run_portfolio_campaign


def fixture():
    dates = pd.bdate_range("2024-01-01", periods=4)
    frame = pd.DataFrame(dict(open=[100., 100., 100., 110.], high=[101., 101., 101., 111.],
        low=[99., 99., 99., 109.], close=[100., 100., 100., 110.], volume=1e6), index=dates)
    strategies = {"forced": dict(fn=lambda f: pd.Series([True, False, False, False], index=f.index),
        stop_pct=5, target_pct=10, max_hold_days=10)}
    config = PortfolioCampaignConfig(capital=3500, max_position_pct=100,
        max_risk_per_trade_pct=100, cost_pct=0, liquidate_at_end=True)
    return dict(frames={"A": frame}, strategies=strategies, config=config)


def with_steps(kwargs, values, evidence="a" * 64):
    return {**kwargs, "entry_quantity_steps": {"A": pd.Series(values,
        index=kwargs["frames"]["A"].index, dtype="Int64")}, "quantity_evidence_sha256": evidence}


@pytest.mark.parametrize("cost_model", ["flat_round_trip", "current_delivery_schedule"])
def test_entry_increment_rounds_down_and_preserves_cash_accounting(cost_model):
    kwargs = fixture()
    kwargs["config"] = replace(kwargs["config"], cost_model=cost_model)
    result = run_portfolio_campaign(**with_steps(kwargs, [2] * 4))
    trade = result.trades[0]
    assert trade.quantity == 34
    assert result.final_equity == pytest.approx(result.config.capital + trade.net_pnl, abs=.01)
    assert min(point.cash for point in result.equity_curve) >= 0
    assert result.to_dict()["quantity_units"]["mode"] == "explicit_entry_increments"
    assert result.to_dict()["can_trade"] is False


@pytest.mark.parametrize("cash,size,risk", [(1030., 10000., 10000.),
    (10000., 1030., 10000.), (10000., 10000., 68.)])
def test_delivery_sizing_is_maximal_on_increment_and_all_fee_boundaries(cash, size, risk):
    def feasible(q):
        buy_fee = delivery_charge(q * 100, "BUY")
        sell_fee = delivery_charge(q * 95, "SELL")
        return q * 100 <= size and q * 100 + buy_fee <= cash and q * 5 + buy_fee + sell_fee <= risk
    quantity = delivery_quantity(price=100, stop=95, cash=cash, size_budget=size,
        risk_budget=risk, dp_charge_inr=15.34, quantity_step=5)
    assert quantity > 0 and quantity % 5 == 0
    assert feasible(quantity) and not feasible(quantity + 5)


def test_unaffordable_physical_share_blocks_entry():
    kwargs = fixture()
    kwargs["config"] = replace(kwargs["config"], capital=400)
    result = run_portfolio_campaign(**with_steps(kwargs, [5] * 4))
    assert not result.trades and result.final_equity == 400


def test_entry_date_unknown_blocks_without_forward_fill_and_mask_still_applies():
    kwargs = fixture()
    assert not run_portfolio_campaign(**with_steps(kwargs, [2, None, 2, 2])).trades
    known = with_steps(kwargs, [None, 2, None, None])
    assert run_portfolio_campaign(**known).trades
    known["entry_eligibility"] = {"A": pd.Series(False, index=kwargs["frames"]["A"].index)}
    assert not run_portfolio_campaign(**known).trades
    sparse = with_steps(kwargs, [2] * 4)
    sparse["entry_quantity_steps"]["A"] = sparse["entry_quantity_steps"]["A"].iloc[:1]
    assert not run_portfolio_campaign(**sparse).trades


def test_held_quantities_are_not_credited_again_when_entry_increment_changes():
    kwargs = fixture()
    result = run_portfolio_campaign(**with_steps(kwargs, [2, 2, 1, 1]))
    assert result.trades[0].quantity == 34
    assert result.trades[0].gross_pnl == 340
    assert result.final_equity == 3840


def test_control_and_unit_one_have_identical_economics_but_distinct_identity():
    kwargs = fixture()
    control = run_portfolio_campaign(**kwargs)
    explicit = run_portfolio_campaign(**with_steps(kwargs, [1] * 4))
    assert explicit.trades == control.trades and explicit.equity_curve == control.equity_curve
    assert control.to_dict()["quantity_units"]["mode"] == "synthetic_integer_units"
    assert control.experiment_id != explicit.experiment_id
    changed_proof = run_portfolio_campaign(**with_steps(kwargs, [1] * 4, evidence="b" * 64))
    assert changed_proof.experiment_id != explicit.experiment_id
    changed_map = run_portfolio_campaign(**with_steps(kwargs, [1, 1, 2, 1]))
    assert changed_map.trades == explicit.trades
    assert changed_map.experiment_id != explicit.experiment_id


@pytest.mark.parametrize("value", [0, -1, True, 1.5, float("inf")])
def test_invalid_increment_values_are_rejected(value):
    kwargs = with_steps(fixture(), [1] * 4)
    kwargs["entry_quantity_steps"]["A"] = kwargs["entry_quantity_steps"]["A"].astype(object)
    kwargs["entry_quantity_steps"]["A"].iloc[1] = value
    with pytest.raises(ValueError, match="positive integers"):
        run_portfolio_campaign(**kwargs)
    with pytest.raises(ValueError, match="positive integer"):
        delivery_quantity(price=100, stop=95, cash=1000, size_budget=1000,
            risk_budget=100, dp_charge_inr=15.34, quantity_step=value)


def test_invalid_evidence_and_universe_are_rejected():
    kwargs = with_steps(fixture(), [1] * 4)
    for evidence in (None, "", "not-a-hash"):
        with pytest.raises(ValueError, match="SHA-256"):
            run_portfolio_campaign(**{**kwargs, "quantity_evidence_sha256": evidence})
    with pytest.raises(ValueError, match="requires an entry quantity map"):
        run_portfolio_campaign(**fixture(), quantity_evidence_sha256="a" * 64)
    kwargs["entry_quantity_steps"] = {}
    with pytest.raises(ValueError, match="price universe"):
        run_portfolio_campaign(**kwargs)


@pytest.mark.parametrize("kind", ["duplicate", "intraday", "timezone", "outside"])
def test_invalid_evidence_dates_are_rejected(kind):
    kwargs = with_steps(fixture(), [1] * 4)
    series = kwargs["entry_quantity_steps"]["A"]
    if kind == "duplicate":
        series.index = pd.DatetimeIndex([series.index[0]] * 4)
    elif kind == "intraday":
        series.index += pd.Timedelta(hours=1)
    elif kind == "timezone":
        series.index = series.index.tz_localize("Asia/Kolkata")
    else:
        series.index += pd.Timedelta(days=100)
    with pytest.raises(ValueError, match="daily price sessions"):
        run_portfolio_campaign(**kwargs)
