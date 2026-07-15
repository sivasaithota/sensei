"""Canonical market-to-Desk cycle planning for scheduled paper entries."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from sensei.operations.health import OperationalHealth
from sensei.operations import EventAppend, OperationalJournal
from sensei.orchestration import (
    CommitteeInputs,
    DeskCycleRequest,
    DeskCycleResult,
    DeskCycleStatus,
    DeskRuntime,
    DispatchAuthorization,
    ExecutableQuote,
    StrategyEvidenceStats,
)
from sensei.portfolio_risk import AccountSnapshot
from sensei.risk.rails import PortfolioState
from sensei.strategy import DecisionAction, PlanEvaluationRequest, StrategyPlan, StrategyPlanEngine

from .runner import TaskOutcome, TaskOutcomeState
from .scheduling import ScheduledTask


@dataclass(frozen=True)
class AuthorizedPlan:
    lineage_id: str
    plan: StrategyPlan
    stats: StrategyEvidenceStats


class CanonicalSignalPlanner:
    """Choose at most one exact PAPER signal using canonical plan semantics."""

    def __init__(
        self,
        *,
        plans: Callable[[], Sequence[AuthorizedPlan]],
        instruments: Callable[[], Sequence[str]],
        bars: Callable[[str], pd.DataFrame],
        quote: Callable[[str, datetime], ExecutableQuote | None],
        average_turnover: Callable[[str], float],
        journal: OperationalJournal | None = None,
        engine: StrategyPlanEngine | None = None,
    ) -> None:
        self._plans = plans
        self._instruments = instruments
        self._bars = bars
        self._quote = quote
        self._average_turnover = average_turnover
        self._engine = engine or StrategyPlanEngine()
        self._journal = journal

    def build(
        self,
        *,
        account_snapshot: AccountSnapshot,
        operational_health: OperationalHealth,
        now: datetime,
        command_id: str,
    ) -> DeskCycleRequest | None:
        if not operational_health.new_entries_allowed:
            return None
        candidates = []
        for authorized in sorted(self._plans(), key=lambda item: item.plan.name):
            for instrument_id in sorted(self._instruments()):
                frame = self._bars(instrument_id)
                if frame.empty:
                    continue
                evaluation_session = frame.index[-1].date()
                trace = self._engine.evaluate(PlanEvaluationRequest(
                    plan=authorized.plan,
                    instrument_id=instrument_id,
                    bars=frame,
                    evaluation_session=evaluation_session,
                ))
                if trace.action is not DecisionAction.ENTER_LONG:
                    continue
                executable = self._quote(instrument_id, now)
                if executable is None:
                    continue
                snapshot_payload = _market_snapshot_payload(
                    authorized.plan, instrument_id, frame, evaluation_session
                )
                snapshot_id = _market_snapshot_id(snapshot_payload)
                if self._journal is not None:
                    self._record_market_snapshot(
                        snapshot_id=snapshot_id,
                        plan=authorized.plan,
                        instrument_id=instrument_id,
                        evaluation_session=evaluation_session,
                        snapshot_payload=snapshot_payload,
                        observed_at=now,
                    )
                candidates.append((
                    -authorized.stats.expectancy_pct,
                    authorized.plan.name,
                    instrument_id,
                    DeskCycleRequest(
                        lineage_id=authorized.lineage_id,
                        plan=authorized.plan,
                        bars=frame,
                        evaluation_session=evaluation_session,
                        decision_market_snapshot_id=snapshot_id,
                        quote=executable,
                        account_snapshot=account_snapshot,
                        operational_health=operational_health,
                        signal_observed_at=now,
                        now=now,
                        command_id=f"{command_id}:{authorized.plan.plan_id}:{instrument_id}",
                        strategy_stats=authorized.stats,
                        committee_context=CommitteeInputs(
                            portfolio_state=_portfolio_state(account_snapshot),
                            average_daily_turnover_inr=float(
                                self._average_turnover(instrument_id)
                            ),
                        ),
                    ),
                ))
        return min(candidates, default=(None, None, None, None))[-1]

    def _record_market_snapshot(
        self, *, snapshot_id: str, plan: StrategyPlan, instrument_id: str,
        evaluation_session, snapshot_payload: Mapping[str, object],
        observed_at: datetime,
    ) -> None:
        suffix = snapshot_id.removeprefix("snapshot:")
        stream = f"decision-market-snapshot:{suffix}"
        if self._journal.read_stream(stream):
            return
        self._journal.append(EventAppend(
            stream_id=stream,
            event_type="DecisionMarketSnapshotRecorded",
            payload={
                "schema_version": "1.0",
                "snapshot_id": snapshot_id,
                "plan_id": plan.plan_id,
                "instrument_id": instrument_id,
                "evaluation_session": evaluation_session.isoformat(),
                "authority": "OBSERVATION_ONLY",
                "snapshot": snapshot_payload,
            },
            idempotency_key=f"decision-market-snapshot:{suffix}",
            expected_version=0,
            occurred_at=observed_at,
            correlation_id=plan.plan_id,
        ))


class GovernedPaperEntrySession:
    """Invoke the nine-role Desk and map its terminal result to scheduler truth."""

    def __init__(
        self,
        *,
        planner: CanonicalSignalPlanner,
        desk: DeskRuntime,
        account_and_health: Callable[[datetime, str], tuple[AccountSnapshot, OperationalHealth]],
        authorize_dispatch: Callable[[DeskCycleRequest, object], DispatchAuthorization],
    ) -> None:
        self._planner = planner
        self._desk = desk
        self._account_and_health = account_and_health
        self._authorize_dispatch = authorize_dispatch

    def __call__(self, task: ScheduledTask, now: datetime) -> TaskOutcome:
        account, health = self._account_and_health(now, task.task_id)
        request = self._planner.build(
            account_snapshot=account,
            operational_health=health,
            now=now,
            command_id=task.task_id,
        )
        if request is None:
            return TaskOutcome(
                TaskOutcomeState.COMPLETED,
                ("NO_CANONICAL_SIGNAL",),
                "no exact PAPER plan produced an executable entry",
            )
        result = self._desk.run_cycle(
            request,
            authorize_dispatch=self._authorize_dispatch,
        )
        return _scheduler_outcome(result)


def _scheduler_outcome(result: DeskCycleResult) -> TaskOutcome:
    completed = {
        DeskCycleStatus.PAPER_DISPATCHED,
        DeskCycleStatus.NO_SIGNAL,
        DeskCycleStatus.EVENT_BLOCKED,
        DeskCycleStatus.ANALYST_DECLINED,
        DeskCycleStatus.COMMITTEE_VETOED,
    }
    if result.status not in completed:
        return TaskOutcome(TaskOutcomeState.HALTED, ("GOVERNED_DESK_FAILED",), result.reason)
    return TaskOutcome(
        TaskOutcomeState.COMPLETED,
        ("GOVERNED_" + result.status.value.upper(),),
        result.reason,
    )


def _market_snapshot_payload(
    plan: StrategyPlan,
    instrument_id: str,
    frame: pd.DataFrame,
    evaluation_session,
) -> Mapping[str, object]:
    retained = frame.loc[:str(evaluation_session), ["open", "high", "low", "close", "volume"]].tail(500)
    return {
        "plan_id": plan.plan_id,
        "instrument_id": instrument_id,
        "evaluation_session": evaluation_session.isoformat(),
        "bars": [
            {"session": index.date().isoformat(), **{key: float(row[key]) for key in retained.columns}}
            for index, row in retained.iterrows()
        ],
    }


def _market_snapshot_id(payload: Mapping[str, object]) -> str:
    return "snapshot:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _portfolio_state(snapshot: AccountSnapshot) -> PortfolioState:
    return PortfolioState(
        cash=snapshot.available_cash_paise / 100,
        open_positions=len(snapshot.positions),
        day_pnl=snapshot.day_pnl_paise / 100,
        week_pnl=snapshot.week_pnl_paise / 100,
        peak_equity=snapshot.high_water_mark_paise / 100,
        equity=snapshot.marked_equity_paise / 100,
        halted=False,
    )


__all__ = ["AuthorizedPlan", "CanonicalSignalPlanner", "GovernedPaperEntrySession"]
