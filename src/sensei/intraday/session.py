"""Deterministic, fail-closed intraday session and replay engine.

This module deliberately emits shadow or paper directives only.  It contains
no live mode, product type, broker adapter, or network call.  Exchange event
time and local receipt time remain separate so replay reproduces the same
latency, auction, feed-latch, and participation decisions as the original run.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from enum import Enum
from types import MappingProxyType
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class SessionMode(str, Enum):
    SHADOW = "SHADOW"
    PAPER = "PAPER"


class SessionState(str, Enum):
    PREOPEN = "PREOPEN"
    OPENING_AUCTION = "OPENING_AUCTION"
    OPEN = "OPEN"
    ENTRY_CLOSED = "ENTRY_CLOSED"
    FLATTENING = "FLATTENING"
    CLOSING_AUCTION = "CLOSING_AUCTION"
    CLOSED = "CLOSED"
    HALTED = "HALTED"


class SessionDirectiveType(str, Enum):
    RECORD_SHADOW_ENTRY = "RECORD_SHADOW_ENTRY"
    RECORD_SHADOW_EXIT = "RECORD_SHADOW_EXIT"
    SUBMIT_PAPER_ENTRY = "SUBMIT_PAPER_ENTRY"
    SUBMIT_PAPER_EXIT = "SUBMIT_PAPER_EXIT"
    FLATTEN_PAPER_POSITIONS = "FLATTEN_PAPER_POSITIONS"
    HALT_NEW_ENTRIES = "HALT_NEW_ENTRIES"
    REJECT_SIGNAL = "REJECT_SIGNAL"
    OPENING_AUCTION_STARTED = "OPENING_AUCTION_STARTED"
    CLOSING_AUCTION_STARTED = "CLOSING_AUCTION_STARTED"
    FEED_RECONNECTED_AWAITING_RESET = "FEED_RECONNECTED_AWAITING_RESET"
    FEED_RESET_ACCEPTED = "FEED_RESET_ACCEPTED"


@dataclass(frozen=True)
class SessionBoundaries:
    """All clock boundaries for one explicit exchange session."""

    session_open: time
    last_entry: time
    flatten_at: time
    session_close: time
    opening_auction_start: time | None = None
    closing_auction_start: time | None = None

    def __post_init__(self) -> None:
        if not (
            self.session_open
            < self.last_entry
            < self.flatten_at
            < self.session_close
        ):
            raise ValueError("session boundaries must be strictly ordered")
        if (
            self.opening_auction_start is not None
            and self.opening_auction_start >= self.session_open
        ):
            raise ValueError("opening auction must end at session_open")
        if self.closing_auction_start is not None and not (
            self.flatten_at <= self.closing_auction_start < self.session_close
        ):
            raise ValueError(
                "closing auction must start after flatten and before session close"
            )


@dataclass(frozen=True)
class SessionConfig:
    mode: SessionMode
    exchange_timezone: str
    trading_dates: frozenset[date]
    session_open: time
    last_entry: time
    flatten_at: time
    session_close: time
    maximum_feed_age: timedelta
    maximum_event_latency: timedelta = timedelta(seconds=2)
    maximum_participation_rate: Decimal = Decimal("0.05")
    opening_auction_start: time | None = None
    closing_auction_start: time | None = None
    special_sessions: Mapping[date, SessionBoundaries] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.mode, SessionMode):
            raise ValueError("intraday mode must be shadow or paper")
        try:
            ZoneInfo(self.exchange_timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("exchange_timezone is not available") from None
        trading_dates = frozenset(self.trading_dates)
        if not trading_dates or any(
            not isinstance(session_date, date) for session_date in trading_dates
        ):
            raise ValueError("an explicit exchange trading calendar is required")
        object.__setattr__(self, "trading_dates", trading_dates)
        SessionBoundaries(
            session_open=self.session_open,
            last_entry=self.last_entry,
            flatten_at=self.flatten_at,
            session_close=self.session_close,
            opening_auction_start=self.opening_auction_start,
            closing_auction_start=self.closing_auction_start,
        )
        if self.maximum_feed_age <= timedelta(0):
            raise ValueError("maximum_feed_age must be positive")
        if self.maximum_event_latency <= timedelta(0):
            raise ValueError("maximum_event_latency must be positive")
        try:
            participation = Decimal(str(self.maximum_participation_rate))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError(
                "maximum_participation_rate must be a finite fraction"
            ) from None
        if not participation.is_finite() or not Decimal("0") < participation <= Decimal("1"):
            raise ValueError("maximum_participation_rate must be in (0, 1]")
        object.__setattr__(self, "maximum_participation_rate", participation)

        copied: dict[date, SessionBoundaries] = {}
        for session_date, boundaries in self.special_sessions.items():
            if session_date not in self.trading_dates:
                raise ValueError("special session date must be in trading_dates")
            if not isinstance(boundaries, SessionBoundaries):
                raise ValueError("special session must provide complete boundaries")
            copied[session_date] = boundaries
        object.__setattr__(self, "special_sessions", MappingProxyType(copied))

    def boundaries_for(self, session_date: date) -> SessionBoundaries:
        special = self.special_sessions.get(session_date)
        if special is not None:
            return special
        return SessionBoundaries(
            session_open=self.session_open,
            last_entry=self.last_entry,
            flatten_at=self.flatten_at,
            session_close=self.session_close,
            opening_auction_start=self.opening_auction_start,
            closing_auction_start=self.closing_auction_start,
        )


@dataclass(frozen=True)
class ClockEvent:
    occurred_at: datetime
    sequence: int
    received_at: datetime | None = None

    @property
    def event_time(self) -> datetime:
        return self.occurred_at


@dataclass(frozen=True)
class MarketDataEvent:
    instrument_id: str
    occurred_at: datetime
    sequence: int
    watermark: datetime
    price: Decimal
    received_at: datetime | None = None
    bar_volume: int | None = None

    @property
    def event_time(self) -> datetime:
        return self.occurred_at


@dataclass(frozen=True)
class SignalEvent:
    instrument_id: str
    plan_id: str
    occurred_at: datetime
    sequence: int
    data_watermark: datetime
    action: str
    received_at: datetime | None = None
    quantity: int | None = None

    @property
    def event_time(self) -> datetime:
        return self.occurred_at


@dataclass(frozen=True)
class FeedDisconnectEvent:
    feed_id: str
    reason: str
    occurred_at: datetime
    sequence: int
    received_at: datetime | None = None

    @property
    def event_time(self) -> datetime:
        return self.occurred_at


@dataclass(frozen=True)
class FeedReconnectEvent:
    feed_id: str
    occurred_at: datetime
    sequence: int
    received_at: datetime | None = None

    @property
    def event_time(self) -> datetime:
        return self.occurred_at


@dataclass(frozen=True)
class FeedResetEvent:
    feed_id: str
    authorization_ref: str
    occurred_at: datetime
    sequence: int
    received_at: datetime | None = None

    @property
    def event_time(self) -> datetime:
        return self.occurred_at


SessionEvent = (
    ClockEvent
    | MarketDataEvent
    | SignalEvent
    | FeedDisconnectEvent
    | FeedReconnectEvent
    | FeedResetEvent
)


@dataclass(frozen=True)
class SessionDirective:
    type: SessionDirectiveType
    directive_id: str
    instrument_id: str | None = None
    plan_id: str | None = None
    feed_id: str | None = None
    reason: str | None = None
    quantity: int | None = None
    maximum_quantity: int | None = None


@dataclass(frozen=True)
class SessionTransition:
    state: SessionState
    directives: tuple[SessionDirective, ...]
    reason_codes: tuple[str, ...]
    new_entries_allowed: bool
    protective_actions_allowed: bool
    event_time: datetime
    received_at: datetime
    latency: timedelta


@dataclass(frozen=True)
class ReplayResult:
    replay_id: str
    transitions: tuple[SessionTransition, ...]
    directives: tuple[SessionDirective, ...]
    final_state: SessionState


class IntradayReplayHarness:
    """Create a fresh engine for every deterministic event replay."""

    def __init__(self, config: SessionConfig) -> None:
        self._config = config

    def replay(self, events: Iterable[SessionEvent]) -> ReplayResult:
        engine = IntradaySessionEngine(self._config)
        transitions = tuple(engine.advance(event) for event in events)
        directives = tuple(
            directive
            for transition in transitions
            for directive in transition.directives
        )
        replay_payload = [
            {
                "state": transition.state.value,
                "event_time": transition.event_time.isoformat(),
                "received_at": transition.received_at.isoformat(),
                "latency_microseconds": int(
                    transition.latency.total_seconds() * 1_000_000
                ),
                "reason_codes": list(transition.reason_codes),
                "new_entries_allowed": transition.new_entries_allowed,
                "directives": [directive.directive_id for directive in transition.directives],
            }
            for transition in transitions
        ]
        encoded = json.dumps(
            replay_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return ReplayResult(
            replay_id=f"replay:{hashlib.sha256(encoded).hexdigest()}",
            transitions=transitions,
            directives=directives,
            final_state=engine.state,
        )


class IntradaySessionEngine:
    """Advance one exchange-calendar session in deterministic receipt order."""

    _DATA_HALT_REASONS = {
        "FEED_DISCONNECTED",
        "FEED_RESET_REQUIRED",
        "MARKET_DATA_MISSING",
        "MARKET_DATA_STALE",
        "EVENT_LATENCY_EXCEEDED",
    }

    def __init__(self, config: SessionConfig) -> None:
        self._config = config
        self._timezone = ZoneInfo(config.exchange_timezone)
        self._state = SessionState.PREOPEN
        self._last_event_time: datetime | None = None
        self._last_received_at: datetime | None = None
        self._last_sequence = 0
        self._active_date: date | None = None
        self._watermarks: dict[str, datetime] = {}
        self._volume_by_bar: dict[tuple[str, datetime], int] = {}
        self._latest_watermark: datetime | None = None
        self._latest_market_data_received_at: datetime | None = None
        self._entry_halts: set[str] = set()
        self._disconnected_feeds: set[str] = set()
        self._awaiting_reset: set[str] = set()
        self._reconnected_at: dict[str, datetime] = {}
        self._reconnect_watermark_baseline: dict[str, datetime | None] = {}
        self._flatten_emitted = False
        self._opening_auction_emitted = False
        self._closing_auction_emitted = False

    @property
    def state(self) -> SessionState:
        return self._state

    def advance(self, event: SessionEvent) -> SessionTransition:
        event_time, received_at = self._validate_common(event)
        self._validate_event(event)
        self._validate_stateful_event(event, event_time, received_at)
        self._last_sequence = event.sequence
        self._last_event_time = event_time
        self._last_received_at = received_at

        local_now = received_at.astimezone(self._timezone)
        self._roll_session(local_now.date())
        directives: list[SessionDirective] = []
        reasons: list[str] = []
        latency = received_at - event_time

        trading_day = local_now.date() in self._config.trading_dates
        if trading_day:
            boundaries = self._config.boundaries_for(local_now.date())
            scheduled_state = self._scheduled_state(local_now, boundaries)
            self._schedule_directives(
                scheduled_state,
                event,
                event_time,
                received_at,
                directives,
            )
        else:
            boundaries = None
            scheduled_state = SessionState.CLOSED

        if latency > self._config.maximum_event_latency:
            self._latch(
                "EVENT_LATENCY_EXCEEDED",
                event,
                event_time,
                received_at,
                directives,
            )

        if isinstance(event, MarketDataEvent):
            self._record_market_data(event, received_at)
        elif isinstance(event, FeedDisconnectEvent):
            self._disconnect(event, event_time, received_at, directives)
        elif isinstance(event, FeedReconnectEvent):
            self._reconnect(event, event_time, received_at, directives)
        elif isinstance(event, FeedResetEvent):
            self._reset_feed(event, received_at, event_time, directives)

        if scheduled_state is SessionState.OPEN:
            self._assess_data_readiness(
                local_now,
                boundaries,
                event,
                event_time,
                received_at,
                directives,
                reasons,
            )

        self._state = self._effective_state(scheduled_state)

        if isinstance(event, SignalEvent):
            if not trading_day:
                self._reject_signal(
                    event,
                    "NON_TRADING_DAY",
                    event_time,
                    received_at,
                    directives,
                    reasons,
                )
            else:
                self._handle_signal(
                    event,
                    event_time,
                    received_at,
                    directives,
                    reasons,
                )

        reasons = _unique([*sorted(self._entry_halts), *reasons])
        return self._transition(
            event_time,
            received_at,
            latency,
            directives,
            tuple(reasons),
        )

    def _roll_session(self, session_date: date) -> None:
        if session_date == self._active_date:
            return
        self._active_date = session_date
        self._watermarks.clear()
        self._volume_by_bar.clear()
        self._latest_watermark = None
        self._latest_market_data_received_at = None
        self._flatten_emitted = False
        self._opening_auction_emitted = False
        self._closing_auction_emitted = False

    @staticmethod
    def _scheduled_state(
        local_now: datetime,
        boundaries: SessionBoundaries,
    ) -> SessionState:
        clock = local_now.timetz().replace(tzinfo=None)
        if (
            boundaries.opening_auction_start is not None
            and boundaries.opening_auction_start <= clock < boundaries.session_open
        ):
            return SessionState.OPENING_AUCTION
        if clock < boundaries.session_open:
            return SessionState.PREOPEN
        if clock >= boundaries.session_close:
            return SessionState.CLOSED
        if (
            boundaries.closing_auction_start is not None
            and clock >= boundaries.closing_auction_start
        ):
            return SessionState.CLOSING_AUCTION
        if clock >= boundaries.flatten_at:
            return SessionState.FLATTENING
        if clock >= boundaries.last_entry:
            return SessionState.ENTRY_CLOSED
        return SessionState.OPEN

    def _schedule_directives(
        self,
        state: SessionState,
        event: SessionEvent,
        event_time: datetime,
        received_at: datetime,
        directives: list[SessionDirective],
    ) -> None:
        if state in {SessionState.FLATTENING, SessionState.CLOSING_AUCTION}:
            if not self._flatten_emitted:
                directive_type = (
                    SessionDirectiveType.FLATTEN_PAPER_POSITIONS
                    if self._config.mode is SessionMode.PAPER
                    else SessionDirectiveType.RECORD_SHADOW_EXIT
                )
                directives.append(
                    self._directive(
                        directive_type,
                        event,
                        "SESSION_FLATTEN",
                        event_time,
                        received_at,
                    )
                )
                self._flatten_emitted = True
        if state is SessionState.OPENING_AUCTION and not self._opening_auction_emitted:
            directives.append(
                self._directive(
                    SessionDirectiveType.OPENING_AUCTION_STARTED,
                    event,
                    "OPENING_AUCTION",
                    event_time,
                    received_at,
                )
            )
            self._opening_auction_emitted = True
        if state is SessionState.CLOSING_AUCTION and not self._closing_auction_emitted:
            directives.append(
                self._directive(
                    SessionDirectiveType.CLOSING_AUCTION_STARTED,
                    event,
                    "CLOSING_AUCTION",
                    event_time,
                    received_at,
                )
            )
            self._closing_auction_emitted = True

    def _record_market_data(
        self, event: MarketDataEvent, received_at: datetime
    ) -> None:
        prior = self._watermarks.get(event.instrument_id)
        if prior is not None and event.watermark < prior:
            raise ValueError("market-data watermark must not move backwards")
        self._watermarks[event.instrument_id] = event.watermark
        if event.bar_volume is not None:
            self._volume_by_bar[(event.instrument_id, event.watermark)] = event.bar_volume
        if self._latest_watermark is None or event.watermark > self._latest_watermark:
            self._latest_watermark = event.watermark
        self._latest_market_data_received_at = received_at

    def _disconnect(
        self,
        event: FeedDisconnectEvent,
        event_time: datetime,
        received_at: datetime,
        directives: list[SessionDirective],
    ) -> None:
        self._disconnected_feeds.add(event.feed_id)
        self._awaiting_reset.discard(event.feed_id)
        self._reconnected_at.pop(event.feed_id, None)
        self._reconnect_watermark_baseline.pop(event.feed_id, None)
        self._latch(
            "FEED_DISCONNECTED",
            event,
            event_time,
            received_at,
            directives,
        )

    def _reconnect(
        self,
        event: FeedReconnectEvent,
        event_time: datetime,
        received_at: datetime,
        directives: list[SessionDirective],
    ) -> None:
        if event.feed_id not in self._disconnected_feeds:
            raise ValueError("feed reconnect requires a prior disconnect")
        self._disconnected_feeds.remove(event.feed_id)
        self._awaiting_reset.add(event.feed_id)
        self._reconnected_at[event.feed_id] = received_at
        # MarketDataEvent is currently a single-feed/global-watermark contract.
        # Pin the best watermark seen before recovery so replayed data cannot
        # masquerade as post-reconnect progress.
        self._reconnect_watermark_baseline[event.feed_id] = self._latest_watermark
        self._entry_halts.add("FEED_RESET_REQUIRED")
        directives.append(
            self._directive(
                SessionDirectiveType.FEED_RECONNECTED_AWAITING_RESET,
                event,
                "FEED_RESET_REQUIRED",
                event_time,
                received_at,
            )
        )

    def _reset_feed(
        self,
        event: FeedResetEvent,
        received_at: datetime,
        event_time: datetime,
        directives: list[SessionDirective],
    ) -> None:
        if event.feed_id in self._disconnected_feeds:
            raise ValueError("cannot reset a disconnected feed")
        if event.feed_id not in self._awaiting_reset and not (
            self._entry_halts & self._DATA_HALT_REASONS
        ):
            raise ValueError("feed reset requires a latched feed or data halt")
        if self._latest_watermark is None:
            raise ValueError("feed reset requires fresh market data")
        self._require_post_reconnect_data(event.feed_id)
        age = received_at - self._latest_watermark
        if age < timedelta(0) or age > self._config.maximum_feed_age:
            raise ValueError("feed reset requires fresh market data")
        if received_at - event_time > self._config.maximum_event_latency:
            raise ValueError("late reset event cannot clear an entry halt")

        self._awaiting_reset.discard(event.feed_id)
        self._reconnected_at.pop(event.feed_id, None)
        self._reconnect_watermark_baseline.pop(event.feed_id, None)
        if not self._disconnected_feeds and not self._awaiting_reset:
            self._entry_halts.difference_update(self._DATA_HALT_REASONS)
        directives.append(
            self._directive(
                SessionDirectiveType.FEED_RESET_ACCEPTED,
                event,
                "EXPLICIT_FEED_RESET",
                event_time,
                received_at,
            )
        )

    def _assess_data_readiness(
        self,
        local_now: datetime,
        boundaries: SessionBoundaries,
        event: SessionEvent,
        event_time: datetime,
        received_at: datetime,
        directives: list[SessionDirective],
        reasons: list[str],
    ) -> None:
        if self._latest_watermark is None:
            reasons.append("DATA_NOT_READY")
            open_time = datetime.combine(
                local_now.date(),
                boundaries.session_open,
                self._timezone,
            )
            if local_now - open_time > self._config.maximum_feed_age:
                reasons.remove("DATA_NOT_READY")
                self._latch(
                    "MARKET_DATA_MISSING",
                    event,
                    event_time,
                    received_at,
                    directives,
                )
            return
        if received_at - self._latest_watermark > self._config.maximum_feed_age:
            self._latch(
                "MARKET_DATA_STALE",
                event,
                event_time,
                received_at,
                directives,
            )

    def _handle_signal(
        self,
        event: SignalEvent,
        event_time: datetime,
        received_at: datetime,
        directives: list[SessionDirective],
        reasons: list[str],
    ) -> None:
        seen_watermark = self._watermarks.get(event.instrument_id)
        if seen_watermark is None or seen_watermark < event.data_watermark:
            self._reject_signal(
                event,
                "DATA_WATERMARK_NOT_SEEN",
                event_time,
                received_at,
                directives,
                reasons,
            )
            return
        if event.action == "EXIT":
            directive_type = (
                SessionDirectiveType.SUBMIT_PAPER_EXIT
                if self._config.mode is SessionMode.PAPER
                else SessionDirectiveType.RECORD_SHADOW_EXIT
            )
            directives.append(
                self._directive(
                    directive_type,
                    event,
                    "PROTECTIVE_EXIT",
                    event_time,
                    received_at,
                    quantity=event.quantity,
                )
            )
            return
        if event.action != "ENTER_LONG":
            raise ValueError("signal action must be ENTER_LONG or EXIT")
        if self._state is not SessionState.OPEN:
            self._reject_signal(
                event,
                "ENTRY_WINDOW_CLOSED",
                event_time,
                received_at,
                directives,
                reasons,
            )
            return
        if event.quantity is None:
            self._reject_signal(
                event,
                "ENTRY_QUANTITY_MISSING",
                event_time,
                received_at,
                directives,
                reasons,
            )
            return
        volume = self._volume_by_bar.get((event.instrument_id, event.data_watermark))
        if volume is None:
            self._reject_signal(
                event,
                "BAR_VOLUME_NOT_SEEN",
                event_time,
                received_at,
                directives,
                reasons,
            )
            return
        maximum_quantity = int(
            (Decimal(volume) * self._config.maximum_participation_rate).to_integral_value(
                rounding=ROUND_FLOOR
            )
        )
        if maximum_quantity < 1 or event.quantity > maximum_quantity:
            reasons.append("PARTICIPATION_CAP_EXCEEDED")
            directives.append(
                self._directive(
                    SessionDirectiveType.REJECT_SIGNAL,
                    event,
                    "PARTICIPATION_CAP_EXCEEDED",
                    event_time,
                    received_at,
                    quantity=event.quantity,
                    maximum_quantity=maximum_quantity,
                )
            )
            return
        directive_type = (
            SessionDirectiveType.SUBMIT_PAPER_ENTRY
            if self._config.mode is SessionMode.PAPER
            else SessionDirectiveType.RECORD_SHADOW_ENTRY
        )
        directives.append(
            self._directive(
                directive_type,
                event,
                "SIGNAL_ACCEPTED",
                event_time,
                received_at,
                quantity=event.quantity,
                maximum_quantity=maximum_quantity,
            )
        )

    def _reject_signal(
        self,
        event: SignalEvent,
        reason: str,
        event_time: datetime,
        received_at: datetime,
        directives: list[SessionDirective],
        reasons: list[str],
    ) -> None:
        reasons.append(reason)
        directives.append(
            self._directive(
                SessionDirectiveType.REJECT_SIGNAL,
                event,
                reason,
                event_time,
                received_at,
                quantity=event.quantity,
            )
        )

    def _latch(
        self,
        reason: str,
        event: SessionEvent,
        event_time: datetime,
        received_at: datetime,
        directives: list[SessionDirective],
    ) -> None:
        if reason in self._entry_halts:
            return
        self._entry_halts.add(reason)
        directives.append(
            self._directive(
                SessionDirectiveType.HALT_NEW_ENTRIES,
                event,
                reason,
                event_time,
                received_at,
            )
        )

    def _effective_state(self, scheduled_state: SessionState) -> SessionState:
        if scheduled_state is SessionState.OPEN and self._entry_halts:
            return SessionState.HALTED
        return scheduled_state

    def _validate_common(self, event: SessionEvent) -> tuple[datetime, datetime]:
        if isinstance(event.sequence, bool) or not isinstance(event.sequence, int):
            raise ValueError("event sequence must be a positive integer")
        if event.sequence <= self._last_sequence:
            raise ValueError("event order must be strictly increasing")
        event_time = event.occurred_at
        received_at = event.received_at or event_time
        _aware("occurred_at", event_time)
        _aware("received_at", received_at)
        if received_at < event_time:
            raise ValueError("receipt time cannot precede event time")
        if self._last_event_time is not None and event_time < self._last_event_time:
            raise ValueError("event order must be strictly increasing")
        if self._last_received_at is not None and received_at < self._last_received_at:
            raise ValueError("receipt order must be strictly increasing")
        return event_time, received_at

    def _validate_event(self, event: SessionEvent) -> None:
        if isinstance(event, MarketDataEvent):
            _identity("instrument_id", event.instrument_id)
            _aware("watermark", event.watermark)
            if event.watermark > event.occurred_at:
                raise ValueError("market data has a future watermark")
            try:
                price = Decimal(event.price)
            except (InvalidOperation, TypeError, ValueError):
                raise ValueError("price must be a positive finite decimal") from None
            if not price.is_finite() or price <= 0:
                raise ValueError("price must be a positive finite decimal")
            if event.bar_volume is not None and (
                isinstance(event.bar_volume, bool)
                or not isinstance(event.bar_volume, int)
                or event.bar_volume < 0
            ):
                raise ValueError("bar_volume must be a non-negative integer")
            prior = self._watermarks.get(event.instrument_id)
            if prior is not None and event.watermark < prior:
                raise ValueError("market-data watermark must not move backwards")
        elif isinstance(event, SignalEvent):
            _identity("instrument_id", event.instrument_id)
            _identity("plan_id", event.plan_id)
            _aware("data_watermark", event.data_watermark)
            if event.data_watermark > event.occurred_at:
                raise ValueError("signal has a future watermark")
            if event.action not in {"ENTER_LONG", "EXIT"}:
                raise ValueError("signal action must be ENTER_LONG or EXIT")
            if event.quantity is not None and (
                isinstance(event.quantity, bool)
                or not isinstance(event.quantity, int)
                or event.quantity <= 0
            ):
                raise ValueError("signal quantity must be a positive integer")
        elif isinstance(event, FeedDisconnectEvent):
            _identity("feed_id", event.feed_id)
            if not isinstance(event.reason, str) or not event.reason.strip():
                raise ValueError("feed disconnect reason must not be blank")
        elif isinstance(event, FeedReconnectEvent):
            _identity("feed_id", event.feed_id)
        elif isinstance(event, FeedResetEvent):
            _identity("feed_id", event.feed_id)
            _identity("authorization_ref", event.authorization_ref)

    def _validate_stateful_event(
        self,
        event: SessionEvent,
        event_time: datetime,
        received_at: datetime,
    ) -> None:
        """Reject state-dependent commands before consuming their sequence."""

        if isinstance(event, FeedReconnectEvent):
            if event.feed_id not in self._disconnected_feeds:
                raise ValueError("feed reconnect requires a prior disconnect")
        elif isinstance(event, FeedResetEvent):
            if event.feed_id in self._disconnected_feeds:
                raise ValueError("cannot reset a disconnected feed")
            if event.feed_id not in self._awaiting_reset and not (
                self._entry_halts & self._DATA_HALT_REASONS
            ):
                raise ValueError("feed reset requires a latched feed or data halt")
            if self._latest_watermark is None:
                raise ValueError("feed reset requires fresh market data")
            self._require_post_reconnect_data(event.feed_id)
            age = received_at - self._latest_watermark
            if age < timedelta(0) or age > self._config.maximum_feed_age:
                raise ValueError("feed reset requires fresh market data")
            if received_at - event_time > self._config.maximum_event_latency:
                raise ValueError("late reset event cannot clear an entry halt")

    def _require_post_reconnect_data(self, feed_id: str) -> None:
        reconnected_at = self._reconnected_at.get(feed_id)
        if reconnected_at is None:
            return
        if (
            self._latest_market_data_received_at is None
            or self._latest_market_data_received_at <= reconnected_at
        ):
            raise ValueError("feed reset requires market data received after reconnect")
        baseline = self._reconnect_watermark_baseline.get(feed_id)
        if (
            baseline is not None
            and (
                self._latest_watermark is None
                or self._latest_watermark <= baseline
            )
        ):
            raise ValueError(
                "feed reset requires a watermark advance after reconnect"
            )

    def _directive(
        self,
        directive_type: SessionDirectiveType,
        event: SessionEvent,
        reason: str,
        event_time: datetime,
        received_at: datetime,
        *,
        quantity: int | None = None,
        maximum_quantity: int | None = None,
    ) -> SessionDirective:
        instrument_id = getattr(event, "instrument_id", None)
        plan_id = getattr(event, "plan_id", None)
        feed_id = getattr(event, "feed_id", None)
        watermark = getattr(event, "watermark", None)
        data_watermark = getattr(event, "data_watermark", None)
        material = {
            "type": directive_type.value,
            "mode": self._config.mode.value,
            "sequence": event.sequence,
            "event_time": event_time.isoformat(),
            "received_at": received_at.isoformat(),
            "instrument_id": instrument_id,
            "plan_id": plan_id,
            "feed_id": feed_id,
            "feed_reason": getattr(event, "reason", None),
            "authorization_ref": getattr(event, "authorization_ref", None),
            "watermark": watermark.isoformat() if watermark is not None else None,
            "data_watermark": (
                data_watermark.isoformat() if data_watermark is not None else None
            ),
            "action": getattr(event, "action", None),
            "reason": reason,
            "quantity": quantity,
            "maximum_quantity": maximum_quantity,
        }
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
        return SessionDirective(
            type=directive_type,
            directive_id=f"directive:{hashlib.sha256(encoded).hexdigest()}",
            instrument_id=instrument_id,
            plan_id=plan_id,
            feed_id=feed_id,
            reason=reason,
            quantity=quantity,
            maximum_quantity=maximum_quantity,
        )

    def _transition(
        self,
        event_time: datetime,
        received_at: datetime,
        latency: timedelta,
        directives: list[SessionDirective],
        reasons: tuple[str, ...],
    ) -> SessionTransition:
        data_fresh = (
            self._latest_watermark is not None
            and received_at - self._latest_watermark <= self._config.maximum_feed_age
        )
        return SessionTransition(
            state=self._state,
            directives=tuple(directives),
            reason_codes=reasons,
            new_entries_allowed=(
                self._state is SessionState.OPEN
                and data_fresh
                and not self._entry_halts
            ),
            protective_actions_allowed=True,
            event_time=event_time,
            received_at=received_at,
            latency=latency,
        )


def _aware(label: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _identity(label: str, value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{label} must be a non-empty identifier")


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique
