"""Durable pre-shadow market-data refresh and universe hygiene."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Sequence

import pandas as pd

from sensei.operations import EventAppend, OperationalJournal

from .runner import TaskOutcome, TaskOutcomeState
from .scheduling import ScheduledTask


@dataclass(frozen=True)
class MarketDataIngestionSnapshot:
    session: date
    eligible_symbols: tuple[str, ...]
    failed_symbols: tuple[str, ...]
    excluded_symbols: tuple[str, ...]
    completeness: float
    event_id: str


class MarketDataIngestionLedger:
    def __init__(self, journal: OperationalJournal) -> None:
        self._journal = journal

    def for_session(self, session: date) -> MarketDataIngestionSnapshot:
        events = self._journal.read_stream(_stream(session))
        if len(events) != 1 or events[0].event_type != "MarketDataIngestionCompleted":
            raise KeyError(f"no complete market ingestion exists for {session}")
        event = events[0]
        payload = event.payload
        return MarketDataIngestionSnapshot(
            session=date.fromisoformat(str(payload["session"])),
            eligible_symbols=tuple(str(value) for value in payload["eligible_symbols"]),
            failed_symbols=tuple(str(value) for value in payload["failed_symbols"]),
            excluded_symbols=tuple(str(value) for value in payload["excluded_symbols"]),
            completeness=float(payload["completeness"]),
            event_id=event.event_id,
        )


class MarketDataIngestionSession:
    """Refresh every active universe member before shadow evaluation."""

    def __init__(
        self,
        *,
        journal: OperationalJournal,
        universe: Callable[[], Sequence[str]],
        refresh: Callable[[str], pd.DataFrame | None],
        existing: Callable[[str], pd.DataFrame],
        maximum_attempts: int = 3,
        minimum_completeness: float = 0.99,
        stale_exclusion_age: timedelta = timedelta(days=30),
        maximum_exclusion_fraction: float = 0.01,
    ) -> None:
        if maximum_attempts < 1:
            raise ValueError("maximum_attempts must be positive")
        if not 0 < minimum_completeness <= 1:
            raise ValueError("minimum_completeness must be in (0, 1]")
        if stale_exclusion_age <= timedelta(0):
            raise ValueError("stale_exclusion_age must be positive")
        if not 0 <= maximum_exclusion_fraction < 1:
            raise ValueError("maximum_exclusion_fraction must be in [0, 1)")
        self._journal = journal
        self._universe = universe
        self._refresh = refresh
        self._existing = existing
        self._maximum_attempts = maximum_attempts
        self._minimum_completeness = minimum_completeness
        self._stale_exclusion_age = stale_exclusion_age
        self._maximum_exclusion_fraction = maximum_exclusion_fraction

    def __call__(self, task: ScheduledTask, now: datetime) -> TaskOutcome:
        try:
            existing = MarketDataIngestionLedger(self._journal).for_session(
                task.trading_date
            )
        except KeyError:
            existing = None
        if existing is not None:
            return _outcome(
                existing,
                self._minimum_completeness,
                self._maximum_exclusion_fraction,
            )

        symbols = tuple(sorted({str(value).strip() for value in self._universe()}))
        if not symbols or any(not symbol for symbol in symbols):
            return TaskOutcome(
                TaskOutcomeState.HALTED,
                ("MARKET_DATA_UNIVERSE_UNAVAILABLE",),
                "market-data universe is empty or invalid",
            )
        eligible, failed, excluded, attempts = [], [], [], {}
        for symbol in symbols:
            refreshed = None
            used = 0
            for used in range(1, self._maximum_attempts + 1):
                try:
                    candidate = self._refresh(symbol)
                except Exception:
                    candidate = None
                if _covers(candidate, task.trading_date):
                    refreshed = candidate
                    break
            attempts[symbol] = used
            if refreshed is not None:
                eligible.append(symbol)
                continue
            previous = _safe_existing(self._existing, symbol)
            latest = _latest_session(previous)
            if (
                latest is not None
                and task.trading_date - latest >= self._stale_exclusion_age
            ):
                excluded.append(symbol)
            else:
                failed.append(symbol)

        denominator = len(symbols) - len(excluded)
        completeness = len(eligible) / denominator if denominator else 0.0
        event = self._journal.append(
            EventAppend(
                stream_id=_stream(task.trading_date),
                event_type="MarketDataIngestionCompleted",
                payload={
                    "schema_version": "1.0",
                    "authority": "OPERATIONAL_INGESTION_ONLY",
                    "session": task.trading_date.isoformat(),
                    "universe_symbols": list(symbols),
                    "eligible_symbols": eligible,
                    "failed_symbols": failed,
                    "excluded_symbols": excluded,
                    "exclusion_reason": "STALE_AFTER_REFRESH_FAILURE",
                    "attempts": attempts,
                    "minimum_completeness": self._minimum_completeness,
                    "maximum_exclusion_fraction": self._maximum_exclusion_fraction,
                    "completeness": round(completeness, 8),
                    "can_authorize_trading": False,
                    "can_authorize_lifecycle": False,
                },
                idempotency_key="market-ingestion:" + hashlib.sha256(
                    task.task_id.encode()
                ).hexdigest(),
                expected_version=0,
                occurred_at=now,
                correlation_id=task.task_id,
            )
        )
        snapshot = MarketDataIngestionSnapshot(
            session=task.trading_date,
            eligible_symbols=tuple(eligible),
            failed_symbols=tuple(failed),
            excluded_symbols=tuple(excluded),
            completeness=round(completeness, 8),
            event_id=event.event_id,
        )
        return _outcome(
            snapshot,
            self._minimum_completeness,
            self._maximum_exclusion_fraction,
        )


def _outcome(snapshot, minimum, maximum_exclusion_fraction):
    universe_size = (
        len(snapshot.eligible_symbols)
        + len(snapshot.failed_symbols)
        + len(snapshot.excluded_symbols)
    )
    exclusion_fraction = (
        len(snapshot.excluded_symbols) / universe_size if universe_size else 1.0
    )
    if exclusion_fraction > maximum_exclusion_fraction:
        return TaskOutcome(
            TaskOutcomeState.HALTED,
            ("MARKET_DATA_UNIVERSE_HYGIENE_UNRESOLVED",),
            f"excluded universe fraction={exclusion_fraction:.4f}; allowed={maximum_exclusion_fraction:.4f}",
        )
    if snapshot.completeness < minimum:
        return TaskOutcome(
            TaskOutcomeState.HALTED,
            ("MARKET_DATA_COMPLETENESS_BELOW_POLICY",),
            f"market-data completeness={snapshot.completeness:.4f}; required={minimum:.4f}",
        )
    return TaskOutcome(
        TaskOutcomeState.COMPLETED,
        ("MARKET_DATA_INGESTION_COMPLETED",),
        f"eligible={len(snapshot.eligible_symbols)}; failed={len(snapshot.failed_symbols)}; excluded={len(snapshot.excluded_symbols)}",
    )


def _covers(frame, session):
    return isinstance(frame, pd.DataFrame) and not frame.empty and _latest_session(frame) == session


def _safe_existing(source, symbol):
    try:
        return source(symbol)
    except Exception:
        return None


def _latest_session(frame):
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return None
    value = frame.index[-1]
    return value.date() if hasattr(value, "date") else date.fromisoformat(str(value))


def _stream(session):
    return f"market-data-ingestion:{session.isoformat()}"


__all__ = [
    "MarketDataIngestionLedger",
    "MarketDataIngestionSession",
    "MarketDataIngestionSnapshot",
]
