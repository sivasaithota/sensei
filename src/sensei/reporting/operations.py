"""Read-only daily and weekly projections of the operational journal."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from enum import Enum
from typing import Mapping

from sensei.operations.journal import (
    JournalEvent,
    JournalVerification,
    OperationalJournal,
)

_MONEY = Decimal("0.01")
_HYPOTHESIS_EVENTS = frozenset(
    {
        "MistakeHypothesisProposed",
        "HypothesisProposed",
        "HypothesisRegistered",
    }
)
_KERNEL_COMMAND_EVENTS = frozenset(
    {
        "BrokerCommandPrepared",
        "KernelCommandPrepared",
    }
)
_DIRECT_ALERT_EVENTS = frozenset(
    {
        "OperationalAlertRaised",
        "QuarantineRaised",
        "SafetyLatched",
    }
)


class ReportingPeriod(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"


@dataclass(frozen=True)
class OperationalCounts:
    """Non-overlapping operational activity counters.

    Episodes count starts, risk counts all `Risk*` events, and kernel commands
    count prepared commands rather than counting completion a second time.
    """

    episodes: int
    lifecycle: int
    risk: int
    alerts: int
    hypotheses: int
    kernel_commands: int


@dataclass(frozen=True)
class OperationalReport:
    period: ReportingPeriod
    window_start: datetime
    window_end: datetime
    counts: OperationalCounts
    event_type_counts: Mapping[str, int]
    pnl_by_currency: Mapping[str, str]
    attributed_pnl_events: int
    excluded_pnl_events: int
    journal_integrity: JournalVerification

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible projection for dashboards or report files."""

        return {
            "period": self.period.value,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "counts": {
                "episodes": self.counts.episodes,
                "lifecycle": self.counts.lifecycle,
                "risk": self.counts.risk,
                "alerts": self.counts.alerts,
                "hypotheses": self.counts.hypotheses,
                "kernel_commands": self.counts.kernel_commands,
            },
            "event_type_counts": dict(self.event_type_counts),
            "pnl_by_currency": dict(self.pnl_by_currency),
            "attributed_pnl_events": self.attributed_pnl_events,
            "excluded_pnl_events": self.excluded_pnl_events,
            "journal_integrity": {
                "ok": self.journal_integrity.ok,
                "events_checked": self.journal_integrity.events_checked,
                "errors": list(self.journal_integrity.errors),
            },
        }


class OperationalReporter:
    """Project facts without mutating journal state or inferring accounting."""

    def __init__(self, journal: OperationalJournal) -> None:
        self._journal = journal

    def daily(
        self,
        day: date,
        *,
        tz: tzinfo = timezone.utc,
    ) -> OperationalReport:
        start = _start_of_day(day, tz)
        return self._project(
            ReportingPeriod.DAILY,
            start,
            start + timedelta(days=1),
        )

    def weekly(
        self,
        week_containing: date,
        *,
        tz: tzinfo = timezone.utc,
    ) -> OperationalReport:
        monday = week_containing - timedelta(days=week_containing.weekday())
        start = _start_of_day(monday, tz)
        return self._project(
            ReportingPeriod.WEEKLY,
            start,
            start + timedelta(days=7),
        )

    def _project(
        self,
        period: ReportingPeriod,
        start: datetime,
        end: datetime,
    ) -> OperationalReport:
        verification = self._journal.verify()
        events = tuple(
            event
            for event in self._journal.read_all()
            if start <= event.occurred_at.astimezone(start.tzinfo) < end
        )
        event_types = Counter(event.event_type for event in events)
        counts = OperationalCounts(
            episodes=event_types["EpisodeStarted"],
            lifecycle=event_types["StrategyLifecycleTransitioned"],
            risk=sum(
                count
                for event_type, count in event_types.items()
                if event_type.startswith("Risk")
            ),
            alerts=sum(1 for event in events if _is_alert(event)),
            hypotheses=sum(event_types[name] for name in _HYPOTHESIS_EVENTS),
            kernel_commands=sum(
                event_types[name] for name in _KERNEL_COMMAND_EVENTS
            ),
        )

        pnl_totals: dict[str, Decimal] = {}
        attributed = 0
        excluded = 0
        for event in events:
            if event.event_type != "OutcomeAttributed":
                continue
            parsed = _attributed_pnl(event)
            if parsed is None:
                excluded += 1
                continue
            currency, amount = parsed
            pnl_totals[currency] = pnl_totals.get(currency, Decimal("0")) + amount
            attributed += 1

        # A report may expose diagnostic counts from a corrupt journal, but it
        # must not present accounting totals as trusted truth.
        if not verification.ok:
            excluded += attributed
            attributed = 0
            pnl_totals = {}

        return OperationalReport(
            period=period,
            window_start=start,
            window_end=end,
            counts=counts,
            event_type_counts=dict(sorted(event_types.items())),
            pnl_by_currency={
                currency: str(amount.quantize(_MONEY, rounding=ROUND_HALF_EVEN))
                for currency, amount in sorted(pnl_totals.items())
            },
            attributed_pnl_events=attributed,
            excluded_pnl_events=excluded,
            journal_integrity=verification,
        )


def _start_of_day(day: date, tz: tzinfo) -> datetime:
    if tz is None:
        raise ValueError("report timezone must not be None")
    start = datetime.combine(day, time.min, tzinfo=tz)
    if start.utcoffset() is None:
        raise ValueError("report timezone must be timezone-aware")
    return start


def _is_alert(event: JournalEvent) -> bool:
    if event.event_type in _DIRECT_ALERT_EVENTS:
        return True
    if event.event_type == "OperationalHealthAssessed":
        return str(event.payload.get("state", "")).upper() in {"HALTED", "UNKNOWN"}
    if event.event_type == "OperationsReadinessAssessed":
        return event.payload.get("ready") is not True
    if event.event_type == "DriftAssessed":
        return str(event.payload.get("state", "")).upper() == "DRIFTED"
    return False


def _attributed_pnl(event: JournalEvent) -> tuple[str, Decimal] | None:
    payload = event.payload
    episode_id = payload.get("episode_id")
    currency = payload.get("currency")
    evidence_refs = payload.get("evidence_refs")
    amount = payload.get("realized_net_pnl")
    if not isinstance(episode_id, str) or not episode_id.strip():
        return None
    if not isinstance(currency, str) or not currency.strip():
        return None
    if not isinstance(evidence_refs, (list, tuple)) or not evidence_refs:
        return None
    if any(not isinstance(reference, str) or not reference.strip() for reference in evidence_refs):
        return None
    if payload.get("reconciles") is not True:
        return None
    if not isinstance(amount, str):
        return None
    try:
        decimal_amount = Decimal(amount)
    except (InvalidOperation, ValueError):
        return None
    if not decimal_amount.is_finite():
        return None
    return currency.strip().upper(), decimal_amount
