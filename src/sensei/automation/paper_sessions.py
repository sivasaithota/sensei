"""Scheduler adapters for the existing paper-trading workflow.

This is an explicit compatibility boundary: it automates paper fills and the
daily research/approval loop, while the durable scheduler owns timing,
idempotency and safety.  It never connects a live broker.
"""

from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
import time
from typing import Callable, Mapping

import pandas as pd

from .runner import TaskOutcome, TaskOutcomeState
from .scheduling import ScheduledTask


class LegacyPaperSessions:
    """Run the proven paper executor and EOD loop inside scheduler tasks."""

    def __init__(
        self,
        *,
        run_day: Callable[..., Mapping[str, object]] | None = None,
        reconcile_positions: Callable[[datetime], None] | None = None,
        refresh_held_positions: Callable[[date], bool] | None = None,
    ) -> None:
        if run_day is None:
            from sensei.loop.daily import run_day as daily_run

            run_day = daily_run
        self._run_day = run_day
        self._reconcile_positions = reconcile_positions
        self._refresh_held_positions = refresh_held_positions

    def entry(self, task: ScheduledTask, now: datetime) -> TaskOutcome:
        if self._reconcile_positions is not None:
            self._reconcile_positions(now)
        return TaskOutcome(
            TaskOutcomeState.COMPLETED,
            ("LEGACY_ENTRY_PATH_DISABLED",),
            "legacy pending orders cannot create new entries after governed cutover",
        )

    def eod(self, task: ScheduledTask, now: datetime) -> TaskOutcome:
        if (
            self._refresh_held_positions is not None
            and not self._refresh_held_positions(task.trading_date)
        ):
            return TaskOutcome(
                TaskOutcomeState.HALTED,
                ("LEGACY_POSITION_DATA_UNAVAILABLE",),
                "held-position bars are not fresh for exit maintenance",
            )
        adopted = ()
        summary = self._run_day(
            today=task.trading_date,
            adopted_entries=adopted,
            refresh=False,
        )
        if self._reconcile_positions is not None:
            self._reconcile_positions(now)
        signals = int(summary.get("signals", 0))
        return TaskOutcome(
            TaskOutcomeState.COMPLETED,
            ("PAPER_EOD_SESSION_COMPLETED",),
            f"legacy position maintenance processed; entry signals={signals}; queued=0",
        )


def refresh_held_position_bars(
    *,
    positions_path: Path,
    session: date,
    refresh_batch: Callable[[tuple[str, ...]], Mapping[str, pd.DataFrame | None]],
    maximum_attempts: int = 3,
    retry_backoff_seconds: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Refresh safety-critical held symbols with bounded failed-only retries."""

    if not positions_path.is_file():
        return True
    payload = json.loads(positions_path.read_text(encoding="utf-8"))
    pending = tuple(str(item["symbol"]) for item in payload.get("positions", ()))
    if not pending:
        return True
    for attempt in range(maximum_attempts):
        try:
            refreshed = refresh_batch(pending)
        except Exception:
            refreshed = {}
        pending = tuple(
            symbol
            for symbol in pending
            if not _covers_session(refreshed.get(symbol), session)
        )
        if not pending:
            return True
        if attempt + 1 < maximum_attempts and retry_backoff_seconds:
            sleep(retry_backoff_seconds * (2**attempt))
    return False


def _covers_session(frame: pd.DataFrame | None, session: date) -> bool:
    return frame is not None and not frame.empty and frame.index[-1].date() == session


__all__ = ["LegacyPaperSessions", "refresh_held_position_bars"]
