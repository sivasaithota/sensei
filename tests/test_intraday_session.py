from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from sensei.intraday.session import (
    ClockEvent,
    FeedDisconnectEvent,
    FeedReconnectEvent,
    FeedResetEvent,
    IntradaySessionEngine,
    MarketDataEvent,
    SessionBoundaries,
    SessionConfig,
    SessionDirectiveType,
    SessionMode,
    SessionState,
    SignalEvent,
)


IST = ZoneInfo("Asia/Kolkata")
SESSION_DATE = date(2026, 7, 13)


def at(hour: int, minute: int) -> datetime:
    return datetime(2026, 7, 13, hour, minute, tzinfo=IST)


def config(
    *,
    mode: SessionMode = SessionMode.PAPER,
    maximum_event_latency: timedelta = timedelta(seconds=2),
    maximum_participation_rate: Decimal = Decimal("0.05"),
    opening_auction_start: time | None = None,
    closing_auction_start: time | None = None,
    special_sessions: dict[date, SessionBoundaries] | None = None,
) -> SessionConfig:
    return SessionConfig(
        mode=mode,
        exchange_timezone="Asia/Kolkata",
        trading_dates=frozenset({SESSION_DATE}),
        session_open=time(9, 15),
        last_entry=time(15, 0),
        flatten_at=time(15, 20),
        session_close=time(15, 30),
        maximum_feed_age=timedelta(minutes=5),
        maximum_event_latency=maximum_event_latency,
        maximum_participation_rate=maximum_participation_rate,
        opening_auction_start=opening_auction_start,
        closing_auction_start=closing_auction_start,
        special_sessions=special_sessions or {},
    )


def test_intraday_has_no_live_mode():
    with pytest.raises(ValueError, match="shadow or paper"):
        SessionConfig(
            mode="LIVE",  # type: ignore[arg-type]
            exchange_timezone="Asia/Kolkata",
            trading_dates=frozenset({SESSION_DATE}),
            session_open=time(9, 15),
            last_entry=time(15, 0),
            flatten_at=time(15, 20),
            session_close=time(15, 30),
            maximum_feed_age=timedelta(minutes=5),
        )


def test_intraday_signal_requires_seen_watermark_and_respects_entry_cutoff():
    engine = IntradaySessionEngine(config())
    opened = engine.advance(
        ClockEvent(occurred_at=at(9, 15), received_at=at(9, 15), sequence=1)
    )
    assert opened.state is SessionState.OPEN
    assert opened.new_entries_allowed is False  # no trusted data yet

    engine.advance(
        MarketDataEvent(
            instrument_id="NSE:INFY",
            occurred_at=at(9, 15),
            sequence=2,
            watermark=at(9, 15),
            price=Decimal("1500.00"),
            bar_volume=10_000,
            received_at=at(9, 15),
        )
    )
    accepted = engine.advance(
        SignalEvent(
            instrument_id="NSE:INFY",
            plan_id="plan:intraday-1",
            occurred_at=at(9, 16),
            sequence=3,
            data_watermark=at(9, 15),
            action="ENTER_LONG",
            quantity=100,
            received_at=at(9, 16),
        )
    )
    assert accepted.directives[0].type is SessionDirectiveType.SUBMIT_PAPER_ENTRY

    cutoff = engine.advance(
        ClockEvent(occurred_at=at(15, 0), received_at=at(15, 0), sequence=4)
    )
    assert cutoff.state is SessionState.ENTRY_CLOSED
    late = engine.advance(
        SignalEvent(
            instrument_id="NSE:INFY",
            plan_id="plan:intraday-1",
            occurred_at=at(15, 1),
            sequence=5,
            data_watermark=at(9, 15),
            action="ENTER_LONG",
            quantity=100,
            received_at=at(15, 1),
        )
    )
    assert late.directives[0].type is SessionDirectiveType.REJECT_SIGNAL


def test_intraday_stale_feed_halts_entries_but_flatten_remains_available():
    engine = IntradaySessionEngine(config())
    engine.advance(
        ClockEvent(occurred_at=at(9, 15), received_at=at(9, 15), sequence=1)
    )
    engine.advance(
        MarketDataEvent(
            instrument_id="NSE:INFY",
            occurred_at=at(9, 15),
            sequence=2,
            watermark=at(9, 15),
            price=Decimal("1500.00"),
            bar_volume=10_000,
            received_at=at(9, 15),
        )
    )

    halted = engine.advance(
        ClockEvent(occurred_at=at(9, 21), received_at=at(9, 21), sequence=3)
    )
    assert halted.state is SessionState.HALTED
    assert halted.new_entries_allowed is False
    assert halted.protective_actions_allowed is True
    assert halted.directives[0].type is SessionDirectiveType.HALT_NEW_ENTRIES

    flatten = engine.advance(
        ClockEvent(occurred_at=at(15, 20), received_at=at(15, 20), sequence=4)
    )
    assert flatten.state is SessionState.FLATTENING
    assert flatten.directives[0].type is SessionDirectiveType.FLATTEN_PAPER_POSITIONS


def test_intraday_rejects_future_watermarks_and_out_of_order_events():
    engine = IntradaySessionEngine(config(mode=SessionMode.SHADOW))
    engine.advance(
        ClockEvent(occurred_at=at(9, 15), received_at=at(9, 15), sequence=1)
    )
    with pytest.raises(ValueError, match="future watermark"):
        engine.advance(
            MarketDataEvent(
                instrument_id="NSE:INFY",
                occurred_at=at(9, 16),
                sequence=2,
                watermark=at(9, 17),
                price=Decimal("1500"),
                bar_volume=1_000,
                received_at=at(9, 16),
            )
        )
    with pytest.raises(ValueError, match="event order"):
        engine.advance(
            ClockEvent(occurred_at=at(9, 14), received_at=at(9, 14), sequence=3)
        )


def test_intraday_late_receipt_latches_entry_halt():
    engine = IntradaySessionEngine(config(maximum_event_latency=timedelta(seconds=2)))

    transition = engine.advance(
        ClockEvent(
            occurred_at=at(9, 15),
            received_at=at(9, 15) + timedelta(seconds=3),
            sequence=1,
        )
    )

    assert transition.event_time == at(9, 15)
    assert transition.received_at == at(9, 15) + timedelta(seconds=3)
    assert transition.latency == timedelta(seconds=3)
    assert transition.state is SessionState.HALTED
    assert "EVENT_LATENCY_EXCEEDED" in transition.reason_codes
    assert transition.directives[0].type is SessionDirectiveType.HALT_NEW_ENTRIES


def test_disconnect_reconnect_requires_fresh_data_and_explicit_reset():
    engine = IntradaySessionEngine(config())
    engine.advance(
        ClockEvent(occurred_at=at(9, 15), received_at=at(9, 15), sequence=1)
    )
    engine.advance(
        MarketDataEvent(
            instrument_id="NSE:INFY",
            occurred_at=at(9, 15),
            received_at=at(9, 15),
            sequence=2,
            watermark=at(9, 15),
            price=Decimal("1500"),
            bar_volume=10_000,
        )
    )
    disconnected = engine.advance(
        FeedDisconnectEvent(
            feed_id="primary",
            reason="socket closed",
            occurred_at=at(9, 16),
            received_at=at(9, 16),
            sequence=3,
        )
    )
    assert disconnected.state is SessionState.HALTED

    reconnected = engine.advance(
        FeedReconnectEvent(
            feed_id="primary",
            occurred_at=at(9, 17),
            received_at=at(9, 17),
            sequence=4,
        )
    )
    assert reconnected.state is SessionState.HALTED
    assert reconnected.directives[0].type is SessionDirectiveType.FEED_RECONNECTED_AWAITING_RESET

    # A still-fresh pre-disconnect watermark is not recovery evidence.
    with pytest.raises(ValueError, match="after reconnect"):
        engine.advance(
            FeedResetEvent(
                feed_id="primary",
                authorization_ref="owner:reset-too-early",
                occurred_at=at(9, 17) + timedelta(seconds=1),
                received_at=at(9, 17) + timedelta(seconds=1),
                sequence=5,
            )
        )
    replayed = engine.advance(
        MarketDataEvent(
            instrument_id="NSE:INFY",
            occurred_at=at(9, 17) + timedelta(seconds=2),
            received_at=at(9, 17) + timedelta(seconds=2),
            sequence=5,
            watermark=at(9, 15),
            price=Decimal("1501"),
            bar_volume=20_000,
        )
    )
    assert replayed.state is SessionState.HALTED
    assert replayed.new_entries_allowed is False

    # Receipt after reconnect is insufficient if it only replays the old mark.
    with pytest.raises(ValueError, match="watermark advance"):
        engine.advance(
            FeedResetEvent(
                feed_id="primary",
                authorization_ref="owner:reset-replayed",
                occurred_at=at(9, 17) + timedelta(seconds=3),
                received_at=at(9, 17) + timedelta(seconds=3),
                sequence=6,
            )
        )

    fresh = engine.advance(
        MarketDataEvent(
            instrument_id="NSE:INFY",
            occurred_at=at(9, 17) + timedelta(seconds=4),
            received_at=at(9, 17) + timedelta(seconds=4),
            sequence=6,
            watermark=at(9, 17) + timedelta(seconds=4),
            price=Decimal("1501"),
            bar_volume=20_000,
        )
    )
    assert fresh.state is SessionState.HALTED
    assert fresh.new_entries_allowed is False

    reset = engine.advance(
        FeedResetEvent(
            feed_id="primary",
            authorization_ref="owner:reset-7",
            occurred_at=at(9, 18),
            received_at=at(9, 18),
            sequence=7,
        )
    )
    assert reset.state is SessionState.OPEN
    assert reset.new_entries_allowed is True
    assert reset.directives[0].type is SessionDirectiveType.FEED_RESET_ACCEPTED


def test_entry_quantity_cannot_exceed_bar_participation_cap():
    engine = IntradaySessionEngine(config(maximum_participation_rate=Decimal("0.05")))
    engine.advance(
        MarketDataEvent(
            instrument_id="NSE:INFY",
            occurred_at=at(9, 15),
            received_at=at(9, 15),
            sequence=1,
            watermark=at(9, 15),
            price=Decimal("1500"),
            bar_volume=1_000,
        )
    )

    rejected = engine.advance(
        SignalEvent(
            instrument_id="NSE:INFY",
            plan_id="plan:intraday-1",
            occurred_at=at(9, 16),
            received_at=at(9, 16),
            sequence=2,
            data_watermark=at(9, 15),
            action="ENTER_LONG",
            quantity=51,
        )
    )
    accepted = engine.advance(
        SignalEvent(
            instrument_id="NSE:INFY",
            plan_id="plan:intraday-1",
            occurred_at=at(9, 17),
            received_at=at(9, 17),
            sequence=3,
            data_watermark=at(9, 15),
            action="ENTER_LONG",
            quantity=50,
        )
    )

    assert rejected.directives[0].type is SessionDirectiveType.REJECT_SIGNAL
    assert rejected.directives[0].maximum_quantity == 50
    assert "PARTICIPATION_CAP_EXCEEDED" in rejected.reason_codes
    assert accepted.directives[0].type is SessionDirectiveType.SUBMIT_PAPER_ENTRY
    assert accepted.directives[0].quantity == 50


def test_special_session_supplies_opening_and_closing_auction_boundaries():
    boundaries = SessionBoundaries(
        opening_auction_start=time(18, 0),
        session_open=time(18, 5),
        last_entry=time(19, 0),
        flatten_at=time(19, 20),
        closing_auction_start=time(19, 25),
        session_close=time(19, 30),
    )
    engine = IntradaySessionEngine(config(special_sessions={SESSION_DATE: boundaries}))

    opening = engine.advance(
        ClockEvent(occurred_at=at(18, 0), received_at=at(18, 0), sequence=1)
    )
    closing = engine.advance(
        ClockEvent(occurred_at=at(19, 25), received_at=at(19, 25), sequence=2)
    )

    assert opening.state is SessionState.OPENING_AUCTION
    assert opening.directives[0].type is SessionDirectiveType.OPENING_AUCTION_STARTED
    assert closing.state is SessionState.CLOSING_AUCTION
    assert [directive.type for directive in closing.directives] == [
        SessionDirectiveType.FLATTEN_PAPER_POSITIONS,
        SessionDirectiveType.CLOSING_AUCTION_STARTED,
    ]
