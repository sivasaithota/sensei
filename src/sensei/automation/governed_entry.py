"""Canonical market-to-Desk cycle planning for scheduled paper entries."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime

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


@dataclass(frozen=True)
class _RankedSignal:
    authorized: AuthorizedPlan
    instrument_id: str
    frame: pd.DataFrame
    evaluation_session: date
    average_turnover_inr: float
    score: _CandidateScore

    @property
    def tie_breaker(self) -> str:
        economic_identity = (
            f"{self.authorized.plan.plan_id}:{self.instrument_id}"
        ).encode()
        return hashlib.sha256(economic_identity).hexdigest()


@dataclass(frozen=True)
class _CandidateScore:
    momentum_20: float
    momentum_63: float
    range_position: float
    volume_confirmation: float
    reward_risk: float
    liquidity: float
    expectancy: float
    hit_rate: float
    evidence_depth: float
    total: float


@dataclass(frozen=True)
class _SignalRankingPolicy:
    version: str = "full-universe-market-quality-v1"
    maximum_reward_risk: float = 5.0
    maximum_expectancy_pct: float = 3.0
    evidence_depth_log_scale: float = 4.0
    liquidity_log_floor: float = 6.0
    liquidity_log_span: float = 4.0
    momentum_floor: float = -0.20
    momentum_span: float = 0.60
    weight_momentum_20: float = 0.20
    weight_momentum_63: float = 0.20
    weight_range_position: float = 0.15
    weight_volume_confirmation: float = 0.10
    weight_reward_risk: float = 0.10
    weight_liquidity: float = 0.10
    weight_expectancy: float = 0.10
    weight_hit_rate: float = 0.025
    weight_evidence_depth: float = 0.025

    def score(
        self, *, authorized: AuthorizedPlan, frame: pd.DataFrame,
        average_turnover_inr: float,
    ) -> _CandidateScore:
        closes = frame["close"].astype(float)
        volumes = frame["volume"].astype(float)
        latest = float(closes.iloc[-1])
        components = {
            "momentum_20": self._return_score(latest, closes, 21),
            "momentum_63": self._return_score(latest, closes, 64),
            "range_position": _range_position(closes.tail(252), latest),
            "volume_confirmation": _volume_confirmation(volumes),
            "reward_risk": min(
                1.0,
                (
                    authorized.plan.exits.take_profit_pct.value
                    / authorized.plan.exits.stop_loss_pct.value
                ) / self.maximum_reward_risk,
            ),
            "liquidity": _clamp(
                (
                    math.log10(max(1.0, average_turnover_inr))
                    - self.liquidity_log_floor
                ) / self.liquidity_log_span
            ),
            "expectancy": _clamp(
                authorized.stats.expectancy_pct / self.maximum_expectancy_pct
            ),
            "hit_rate": _clamp(authorized.stats.hit_rate),
            "evidence_depth": _clamp(
                math.log10(authorized.stats.trades + 1)
                / self.evidence_depth_log_scale
            ),
        }
        total = (
            components["momentum_20"] * self.weight_momentum_20
            + components["momentum_63"] * self.weight_momentum_63
            + components["range_position"] * self.weight_range_position
            + components["volume_confirmation"] * self.weight_volume_confirmation
            + components["reward_risk"] * self.weight_reward_risk
            + components["liquidity"] * self.weight_liquidity
            + components["expectancy"] * self.weight_expectancy
            + components["hit_rate"] * self.weight_hit_rate
            + components["evidence_depth"] * self.weight_evidence_depth
        )
        return _CandidateScore(**components, total=total)

    def _return_score(
        self, latest: float, closes: pd.Series, offset: int
    ) -> float:
        if len(closes) < offset:
            return 0.5
        prior = float(closes.iloc[-offset])
        if prior <= 0 or not math.isfinite(prior) or not math.isfinite(latest):
            return 0.0
        change = latest / prior - 1.0
        return _clamp(
            (change - self.momentum_floor) / self.momentum_span
        )


_RANKING_POLICY = _SignalRankingPolicy()


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
        candidates: list[_RankedSignal] = []
        frames: dict[str, pd.DataFrame] = {}
        turnovers: dict[str, float] = {}
        instruments = tuple(dict.fromkeys(self._instruments()))
        held_instruments = {
            position.instrument_id.split(":")[-1]
            for position in account_snapshot.positions
        }
        for authorized in sorted(self._plans(), key=lambda item: item.plan.name):
            for instrument_id in instruments:
                frame = frames.get(instrument_id)
                if frame is None:
                    frame = self._bars(instrument_id)
                    frames[instrument_id] = frame
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
                if instrument_id.split(":")[-1] in held_instruments:
                    continue
                average_turnover = turnovers.get(instrument_id)
                if average_turnover is None:
                    average_turnover = float(
                        self._average_turnover(instrument_id)
                    )
                    turnovers[instrument_id] = average_turnover
                candidates.append(_RankedSignal(
                    authorized=authorized,
                    instrument_id=instrument_id,
                    frame=frame,
                    evaluation_session=evaluation_session,
                    average_turnover_inr=average_turnover,
                    score=_RANKING_POLICY.score(
                        authorized=authorized,
                        frame=frame,
                        average_turnover_inr=average_turnover,
                    ),
                ))
        ranked = sorted(
            candidates,
            key=lambda candidate: (-candidate.score.total, candidate.tie_breaker),
        )
        selected = None
        quote_attempts = 0
        for rank, candidate in enumerate(ranked, start=1):
            quote_attempts += 1
            executable = self._quote(candidate.instrument_id, now)
            if executable is None:
                continue
            selected = (rank, candidate, executable)
            break
        if self._journal is not None:
            self._record_ranking(
                command_id=command_id,
                ranked=ranked,
                selected_rank=selected[0] if selected else None,
                quote_attempts=quote_attempts,
                observed_at=now,
            )
        if selected is None:
            return None
        _, candidate, executable = selected
        snapshot_payload = _market_snapshot_payload(
            candidate.authorized.plan,
            candidate.instrument_id,
            candidate.frame,
            candidate.evaluation_session,
        )
        snapshot_id = _market_snapshot_id(snapshot_payload)
        if self._journal is not None:
            self._record_market_snapshot(
                snapshot_id=snapshot_id,
                plan=candidate.authorized.plan,
                instrument_id=candidate.instrument_id,
                evaluation_session=candidate.evaluation_session,
                snapshot_payload=snapshot_payload,
                observed_at=now,
            )
        return DeskCycleRequest(
            lineage_id=candidate.authorized.lineage_id,
            plan=candidate.authorized.plan,
            bars=candidate.frame,
            evaluation_session=candidate.evaluation_session,
            decision_market_snapshot_id=snapshot_id,
            quote=executable,
            account_snapshot=account_snapshot,
            operational_health=operational_health,
            signal_observed_at=now,
            now=now,
            command_id=(
                f"{command_id}:{candidate.authorized.plan.plan_id}:"
                f"{candidate.instrument_id}"
            ),
            strategy_stats=candidate.authorized.stats,
            committee_context=CommitteeInputs(
                portfolio_state=_portfolio_state(account_snapshot),
                average_daily_turnover_inr=candidate.average_turnover_inr,
            ),
        )

    def _record_ranking(
        self, *, command_id: str, ranked: Sequence[_RankedSignal],
        selected_rank: int | None, quote_attempts: int, observed_at: datetime,
    ) -> None:
        payload = {
            "schema_version": "1.0",
            "command_id": command_id,
            "policy": asdict(_RANKING_POLICY),
            "signal_candidate_count": len(ranked),
            "selected_signal_rank": selected_rank,
            "quote_attempts": quote_attempts,
            "candidates": [
                {
                    "rank": rank,
                    "plan_id": candidate.authorized.plan.plan_id,
                    "instrument_id": candidate.instrument_id,
                    "score": asdict(candidate.score),
                }
                for rank, candidate in enumerate(ranked, start=1)
            ],
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        stream = f"signal-ranking:{hashlib.sha256(command_id.encode()).hexdigest()}"
        existing = self._journal.read_stream(stream)
        if existing:
            if existing[-1].payload.get("ranking_digest") != digest:
                raise RuntimeError(
                    "same entry command produced a different signal ranking"
                )
            return
        self._journal.append(EventAppend(
            stream_id=stream,
            event_type="SignalRankingRecorded",
            payload={**payload, "ranking_digest": digest},
            idempotency_key=f"signal-ranking:{digest}",
            expected_version=0,
            occurred_at=observed_at,
            correlation_id=command_id,
        ))

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


def _range_position(closes: pd.Series, latest: float) -> float:
    low = float(closes.min())
    high = float(closes.max())
    if not all(math.isfinite(value) for value in (low, high, latest)):
        return 0.0
    if high <= low:
        return 0.5
    return _clamp((latest - low) / (high - low))


def _volume_confirmation(volumes: pd.Series) -> float:
    history = volumes.iloc[-21:-1]
    if history.empty:
        return 0.5
    average = float(history.mean())
    latest = float(volumes.iloc[-1])
    if average <= 0 or not all(math.isfinite(value) for value in (average, latest)):
        return 0.0
    return _clamp((latest / average - 0.5) / 1.5)


def _clamp(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))


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
