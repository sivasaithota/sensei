from datetime import datetime, timedelta, timezone

import pytest

from sensei.execution.nse import (
    IndianDeliveryChargeSchedule,
    NseExecutionModel,
    NseMarketObservation,
)
from sensei.kernel import EntryCommand, GatewayReceipt, RecordingPaperGateway
from sensei.operations import OperationalJournal


NOW = datetime(2026, 7, 20, 3, 51, tzinfo=timezone.utc)


def _observation(**overrides):
    values = {
        "instrument_id": "NSE:INFY", "observed_at": NOW,
        "reference_price_paise": 10_000, "best_bid_paise": 9_995,
        "best_ask_paise": 10_005, "traded_volume": 1_000,
        "lower_circuit_paise": 8_000, "upper_circuit_paise": 12_000,
    }
    values.update(overrides)
    return NseMarketObservation(**values)


def test_entry_fill_is_adverse_partial_and_charge_aware():
    model = NseExecutionModel(max_volume_participation_bps=500)

    fill = model.simulate_entry(
        quantity=100, limit_price_paise=10_100,
        observation=_observation(), now=NOW,
    )

    assert fill.filled_quantity == 50
    assert fill.unfilled_quantity == 50
    assert fill.fill_price_paise > 10_005
    assert fill.fill_price_paise <= 10_100
    assert fill.slippage_paise > 0
    assert fill.charges.total_paise > 0
    assert fill.net_cash_flow_paise == -(
        fill.filled_quantity * fill.fill_price_paise + fill.charges.total_paise
    )


def test_stale_or_non_marketable_observation_does_not_fill():
    model = NseExecutionModel(maximum_observation_age=timedelta(seconds=5))

    stale = model.simulate_entry(
        quantity=10, limit_price_paise=10_100,
        observation=_observation(observed_at=NOW - timedelta(seconds=6)), now=NOW,
    )
    below_ask = model.simulate_entry(
        quantity=10, limit_price_paise=10_000,
        observation=_observation(), now=NOW,
    )

    assert stale.filled_quantity == 0
    assert stale.reason_code == "STALE_MARKET_OBSERVATION"
    assert below_ask.filled_quantity == 0
    assert below_ask.reason_code == "LIMIT_NOT_MARKETABLE"


def test_adverse_price_above_effective_tick_limit_does_not_fill():
    fill = NseExecutionModel(base_impact_bps=50).simulate_entry(
        quantity=10,
        limit_price_paise=10_006,
        observation=_observation(),
        now=NOW,
    )

    assert fill.filled_quantity == 0
    assert fill.reason_code == "ADVERSE_PRICE_EXCEEDS_LIMIT"


def test_gap_through_stop_never_fills_at_the_unavailable_stop_price():
    model = NseExecutionModel(max_volume_participation_bps=1_000)

    fill = model.simulate_stop_exit(
        quantity=100, stop_price_paise=9_500, session_open_paise=9_100,
        session_low_paise=8_900, available_volume=2_000,
    )

    assert fill.reason_code == "STOP_GAP"
    assert fill.fill_price_paise < 9_100
    assert fill.filled_quantity == 100


def test_delivery_charge_schedule_applies_buy_and_sell_levies():
    schedule = IndianDeliveryChargeSchedule()

    buy = schedule.calculate(turnover_paise=1_000_000, side="BUY")
    sell = schedule.calculate(turnover_paise=1_000_000, side="SELL")

    assert buy.stamp_duty_paise > 0
    assert sell.stamp_duty_paise == 0
    assert buy.stt_paise > 0 and sell.stt_paise > 0
    assert buy.total_paise == sum(buy.to_payload().values())


def test_recording_gateway_durably_uses_execution_model():
    command = EntryCommand(
        intent_id="intent:test", instrument_id="NSE:INFY",
        quantity=100, limit_price_paise=10_100,
    )
    gateway = RecordingPaperGateway(
        execution_model=NseExecutionModel(max_volume_participation_bps=500),
        market_observation=lambda _instrument: _observation(),
        clock=lambda: NOW,
    )

    receipt = gateway.execute(command)

    assert receipt.cumulative_fill_quantity == 50
    assert receipt.execution_quality is not None
    assert receipt.execution_quality["charges"]["total_paise"] > 0


def test_execution_quality_survives_gateway_restart(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    command = EntryCommand(
        intent_id="intent:test", instrument_id="NSE:INFY",
        quantity=100, limit_price_paise=10_100,
    )
    gateway = RecordingPaperGateway(
        journal,
        execution_model=NseExecutionModel(max_volume_participation_bps=500),
        market_observation=lambda _instrument: _observation(),
        clock=lambda: NOW,
    )

    original = gateway.execute(command)
    recovered = RecordingPaperGateway(journal).receipt_for(command.command_id)

    assert recovered == original
    assert recovered.execution_quality["reason_code"] == "PARTIAL_LIQUIDITY_FILL"


def test_gateway_receipt_rejects_execution_quality_that_disagrees_with_fill():
    quality = NseExecutionModel().simulate_entry(
        quantity=10,
        limit_price_paise=10_100,
        observation=_observation(),
        now=NOW,
    ).to_payload()

    with pytest.raises(ValueError, match="quantity does not match"):
        GatewayReceipt(
            command_id="command:" + "a" * 64,
            accepted=True,
            broker_reference="paper:1",
            cumulative_fill_quantity=9,
            average_fill_price_paise=quality["fill_price_paise"],
            execution_quality=quality,
        )
