from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sensei.intraday.session import (
    ClockEvent,
    IntradayReplayHarness,
    MarketDataEvent,
    SessionConfig,
    SessionMode,
    SignalEvent,
)


IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 7, 13)


def at(hour: int, minute: int) -> datetime:
    return datetime(2026, 7, 13, hour, minute, tzinfo=IST)


def test_replay_produces_identical_transitions_and_directive_identities():
    config = SessionConfig(
        mode=SessionMode.SHADOW,
        exchange_timezone="Asia/Kolkata",
        trading_dates=frozenset({DAY}),
        session_open=time(9, 15),
        last_entry=time(15, 0),
        flatten_at=time(15, 20),
        session_close=time(15, 30),
        maximum_feed_age=timedelta(minutes=5),
        maximum_event_latency=timedelta(seconds=2),
        maximum_participation_rate=Decimal("0.10"),
        opening_auction_start=time(9, 0),
        closing_auction_start=time(15, 25),
    )
    events = (
        ClockEvent(occurred_at=at(9, 0), received_at=at(9, 0), sequence=1),
        MarketDataEvent(
            instrument_id="NSE:INFY",
            occurred_at=at(9, 15),
            received_at=at(9, 15),
            sequence=2,
            watermark=at(9, 15),
            price=Decimal("1500"),
            bar_volume=10_000,
        ),
        SignalEvent(
            instrument_id="NSE:INFY",
            plan_id="plan:intraday-1",
            occurred_at=at(9, 16),
            received_at=at(9, 16),
            sequence=3,
            data_watermark=at(9, 15),
            action="ENTER_LONG",
            quantity=500,
        ),
        ClockEvent(occurred_at=at(15, 25), received_at=at(15, 25), sequence=4),
        ClockEvent(occurred_at=at(15, 30), received_at=at(15, 30), sequence=5),
    )
    harness = IntradayReplayHarness(config)

    first = harness.replay(events)
    second = harness.replay(events)

    assert first == second
    assert first.transitions == second.transitions
    assert first.directives == second.directives
    assert first.replay_id.startswith("replay:")
