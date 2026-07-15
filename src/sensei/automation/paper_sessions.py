"""Scheduler adapters for the existing paper-trading workflow.

This is an explicit compatibility boundary: it automates paper fills and the
daily research/approval loop, while the durable scheduler owns timing,
idempotency and safety.  It never connects a live broker.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Mapping

from .runner import TaskOutcome, TaskOutcomeState
from .scheduling import ScheduledTask


class LegacyPaperSessions:
    """Run the proven paper executor and EOD loop inside scheduler tasks."""

    def __init__(
        self,
        *,
        run_day: Callable[..., Mapping[str, object]] | None = None,
        reconcile_positions: Callable[[datetime], None] | None = None,
    ) -> None:
        if run_day is None:
            from sensei.loop.daily import run_day as daily_run

            run_day = daily_run
        self._run_day = run_day
        self._reconcile_positions = reconcile_positions

    def entry(self, task: ScheduledTask, now: datetime) -> TaskOutcome:
        if self._reconcile_positions is not None:
            self._reconcile_positions(now)
        return TaskOutcome(
            TaskOutcomeState.COMPLETED,
            ("LEGACY_ENTRY_PATH_DISABLED",),
            "legacy pending orders cannot create new entries after governed cutover",
        )

    def eod(self, task: ScheduledTask, now: datetime) -> TaskOutcome:
        adopted = ()
        summary = self._run_day(
            today=task.trading_date,
            adopted_entries=adopted,
        )
        if self._reconcile_positions is not None:
            self._reconcile_positions(now)
        signals = int(summary.get("signals", 0))
        return TaskOutcome(
            TaskOutcomeState.COMPLETED,
            ("PAPER_EOD_SESSION_COMPLETED",),
            f"legacy position maintenance processed; entry signals={signals}; queued=0",
        )


__all__ = ["LegacyPaperSessions"]
