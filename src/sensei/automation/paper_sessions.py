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
        execute_open: Callable[..., Mapping[str, object]] | None = None,
        run_day: Callable[..., Mapping[str, object]] | None = None,
        load_playbook: Callable[[], Mapping[str, object]] | None = None,
    ) -> None:
        if execute_open is None:
            from sensei.loop.openexec import execute_pending

            execute_open = execute_pending
        if run_day is None:
            from sensei.loop.daily import run_day as daily_run

            run_day = daily_run
        if load_playbook is None:
            from sensei.backtest.playbook import load_current_playbook

            load_playbook = load_current_playbook
        self._execute_open = execute_open
        self._run_day = run_day
        self._load_playbook = load_playbook

    def entry(self, task: ScheduledTask, now: datetime) -> TaskOutcome:
        summary = self._execute_open(today=task.trading_date)
        filled = len(summary.get("filled", ()))
        skipped = len(summary.get("skipped", ()))
        return TaskOutcome(
            TaskOutcomeState.COMPLETED,
            ("PAPER_ENTRY_SESSION_COMPLETED",),
            f"paper open processed; filled={filled}; skipped={skipped}",
        )

    def eod(self, task: ScheduledTask, now: datetime) -> TaskOutcome:
        playbook = self._load_playbook()
        strategies = playbook.get("strategies", ())
        adopted = tuple(
            item for item in strategies
            if isinstance(item, Mapping) and item.get("adopted") is True
        )
        if not adopted:
            return TaskOutcome(
                TaskOutcomeState.HALTED,
                ("NO_BACKTEST_ADOPTED_STRATEGIES",),
                "paper EOD refused because the current playbook has no adopted strategy",
            )
        summary = self._run_day(
            today=task.trading_date,
            adopted_entries=adopted,
        )
        opened = len(summary.get("opened", ()))
        signals = int(summary.get("signals", 0))
        return TaskOutcome(
            TaskOutcomeState.COMPLETED,
            ("PAPER_EOD_SESSION_COMPLETED",),
            f"paper EOD processed; signals={signals}; queued={opened}",
        )


__all__ = ["LegacyPaperSessions"]
