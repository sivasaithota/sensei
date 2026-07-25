"""Safe primitives for chronological, point-in-time desk replay."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd


ALL_DESK_ROLES = frozenset({
    "orchestrator", "historian", "reporter", "crowd-reader", "analyst",
    "committee", "trader", "coach", "secretary",
})
ALL_COMMITTEE_LEVELS = frozenset({"L1", "L2", "L3", "L4"})


class PointInTimePriceView:
    """Read-only price view whose maximum observable timestamp is fixed."""

    def __init__(self, prices_path: Path, *, as_of: date) -> None:
        self._prices_path = Path(prices_path)
        self.as_of = as_of

    def load(self, instrument_id: str) -> pd.DataFrame:
        symbol = instrument_id.split(":")[-1]
        frame = pd.read_parquet(self._prices_path / f"{symbol}.parquet")
        index = pd.to_datetime(frame.index)
        visible = frame.loc[index.date <= self.as_of].copy()
        if not visible.empty and visible.index.max().date() > self.as_of:
            raise RuntimeError("point-in-time view exposed a future bar")
        return visible


@dataclass(frozen=True)
class ReplaySessionResult:
    session: date
    completed: bool
    role_names: tuple[str, ...]
    committee_levels: tuple[str, ...]
    gateway_commands: tuple[str, ...]
    open_positions: int
    closed_episodes: int
    learned_episodes: int
    blockers: tuple[str, ...]
    coherent_agent_cycle: bool = False
    coherent_trade_lifecycle: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "session": self.session.isoformat(),
            "completed": self.completed,
            "role_names": list(self.role_names),
            "committee_levels": list(self.committee_levels),
            "gateway_commands": list(self.gateway_commands),
            "open_positions": self.open_positions,
            "closed_episodes": self.closed_episodes,
            "learned_episodes": self.learned_episodes,
            "blockers": list(self.blockers),
            "coherent_agent_cycle": self.coherent_agent_cycle,
            "coherent_trade_lifecycle": self.coherent_trade_lifecycle,
        }


@dataclass(frozen=True)
class HistoricalDeskReplayReport:
    generated_at: datetime
    requested_sessions: int
    sessions: tuple[ReplaySessionResult, ...]
    production_state_unchanged: bool
    blockers: tuple[str, ...]

    @property
    def completed_sessions(self) -> int:
        return sum(result.completed for result in self.sessions)

    @property
    def certified(self) -> bool:
        return (
            self.production_state_unchanged
            and self.completed_sessions == self.requested_sessions
            and not self.blockers
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "requested_sessions": self.requested_sessions,
            "completed_sessions": self.completed_sessions,
            "certified": self.certified,
            "production_state_unchanged": self.production_state_unchanged,
            "blockers": list(self.blockers),
            "sessions": [session.to_dict() for session in self.sessions],
        }


class HistoricalDeskReplay:
    """Drive ordered sessions while enforcing point-in-time market visibility."""

    def __init__(
        self,
        *,
        prices_path: Path,
        sessions: Sequence[date],
        execute_session: Callable[
            [date, PointInTimePriceView], ReplaySessionResult
        ],
        production_fingerprints: Callable[[], Mapping[str, str]],
    ) -> None:
        ordered = tuple(sessions)
        if not ordered or tuple(sorted(set(ordered))) != ordered:
            raise ValueError("sessions must be non-empty, unique, and chronological")
        self._prices_path = Path(prices_path)
        self._sessions = ordered
        self._execute_session = execute_session
        self._production_fingerprints = production_fingerprints

    def run(self) -> HistoricalDeskReplayReport:
        before = dict(self._production_fingerprints())
        results = []
        for session in self._sessions:
            try:
                result = self._execute_session(
                    session,
                    PointInTimePriceView(self._prices_path, as_of=session),
                )
            except Exception as exc:
                result = ReplaySessionResult(
                    session=session,
                    completed=False,
                    role_names=(),
                    committee_levels=(),
                    gateway_commands=(),
                    open_positions=0,
                    closed_episodes=0,
                    learned_episodes=0,
                    blockers=(
                        f"SESSION_EXCEPTION:{type(exc).__name__}:{exc}",
                    ),
                )
            results.append(result)
        unchanged = before == dict(self._production_fingerprints())
        blockers = {
            blocker for result in results for blocker in result.blockers
        }
        if not any(result.coherent_agent_cycle for result in results):
            blockers.add("COHERENT_NINE_AGENT_L1_L4_CYCLE_NOT_OBSERVED")
        if not any(result.coherent_trade_lifecycle for result in results):
            blockers.add("TRADE_LIFECYCLE_INCOMPLETE")
        if sum(result.learned_episodes for result in results) < 1:
            blockers.add("CLOSED_EPISODE_LEARNING_NOT_OBSERVED")
        if any(not result.completed for result in results):
            blockers.add("SESSION_REPLAY_INCOMPLETE")
        if not unchanged:
            blockers.add("PRODUCTION_STATE_CHANGED")
        return HistoricalDeskReplayReport(
            generated_at=datetime.now(timezone.utc),
            requested_sessions=len(self._sessions),
            sessions=tuple(results),
            production_state_unchanged=unchanged,
            blockers=tuple(sorted(blockers)),
        )


__all__ = [
    "HistoricalDeskReplay",
    "HistoricalDeskReplayReport",
    "PointInTimePriceView",
    "ReplaySessionResult",
]
