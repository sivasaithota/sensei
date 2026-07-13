"""One durable paper-desk cycle connecting the nine PRD roles."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Protocol

from sensei.agents.thesis import ApprovalRecord, TradeThesis
from sensei.kernel import TradingKernel
from sensei.learning.outcomes import LearningObservation
from sensei.operations import EventAppend, OperationalJournal
from sensei.operations.health import OperationalHealth
from sensei.portfolio_risk import AccountSnapshot
from sensei.strategy import PlanDecisionTrace, StrategyPlan

from .intents import ExecutableQuote, IntentBuildResult
from .paper import GovernedPaperCoordinator, PaperAcceptance


@dataclass(frozen=True)
class StrategyEvidenceStats:
    expectancy_pct: float
    hit_rate: float
    trades: int
    detail: dict[str, object] | None = None

    def __post_init__(self) -> None:
        if isinstance(self.trades, bool) or not isinstance(self.trades, int):
            raise TypeError("strategy evidence trades must be an integer")
        if self.trades <= 0:
            raise ValueError("strategy evidence needs at least one trade")
        if not math.isfinite(self.expectancy_pct):
            raise ValueError("expectancy_pct must be finite")
        if not math.isfinite(self.hit_rate) or not 0 <= self.hit_rate <= 1:
            raise ValueError("hit_rate must be a fraction in [0, 1]")


@dataclass(frozen=True)
class EventBrief:
    instrument_id: str
    blocked: bool
    reason: str
    surveillance_stage: int | None


@dataclass(frozen=True)
class MarketMood:
    label: str
    summary: str
    confidence: float

    def __post_init__(self) -> None:
        if not self.label.strip() or not self.summary.strip():
            raise ValueError("market mood label and summary are required")
        if not 0 <= self.confidence <= 1:
            raise ValueError("market mood confidence must be in [0, 1]")


@dataclass(frozen=True)
class CommitteeInputs:
    portfolio_state: object
    average_daily_turnover_inr: float

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.average_daily_turnover_inr)
            or self.average_daily_turnover_inr < 0
        ):
            raise ValueError(
                "average_daily_turnover_inr must be finite and nonnegative"
            )


@dataclass(frozen=True)
class CommitteeReviewContext:
    inputs: object
    events: EventBrief
    mood: MarketMood


@dataclass(frozen=True)
class HistoricalRequest:
    plan: StrategyPlan
    instrument_id: str
    bars: object
    evaluation_session: date
    market_snapshot_id: str
    occurred_at: datetime
    command_id: str


@dataclass(frozen=True)
class HistoricalDecision:
    trace: PlanDecisionTrace
    trace_attestation_event_id: str


@dataclass(frozen=True)
class AnalystBrief:
    plan: StrategyPlan
    candidate: IntentBuildResult
    history: HistoricalDecision
    events: EventBrief
    mood: MarketMood
    strategy_stats: StrategyEvidenceStats
    created_at: datetime


@dataclass(frozen=True)
class AuthenticatedCommitteeDecision:
    approval: ApprovalRecord
    verdict_evidence_event_ids: tuple[str, ...]


@dataclass(frozen=True)
class CoachReflection:
    observations_recorded: int
    hypotheses_proposed: tuple[str, ...]


class DeskCycleStatus(StrEnum):
    EVENT_BLOCKED = "EVENT_BLOCKED"
    NO_SIGNAL = "NO_SIGNAL"
    ANALYST_DECLINED = "ANALYST_DECLINED"
    COMMITTEE_VETOED = "COMMITTEE_VETOED"
    PAPER_DISPATCHED = "PAPER_DISPATCHED"


class DeskCycleFailed(RuntimeError):
    def __init__(self, cycle_id: str, detail: str) -> None:
        super().__init__(f"desk cycle {cycle_id} failed closed: {detail}")
        self.cycle_id = cycle_id


@dataclass(frozen=True)
class DeskCycleRequest:
    lineage_id: str
    plan: StrategyPlan
    bars: object
    evaluation_session: date
    decision_market_snapshot_id: str
    quote: ExecutableQuote
    account_snapshot: AccountSnapshot
    operational_health: OperationalHealth
    signal_observed_at: datetime
    now: datetime
    command_id: str
    strategy_stats: StrategyEvidenceStats
    committee_context: object
    closed_observations: tuple[LearningObservation, ...] = ()

    def __post_init__(self) -> None:
        if not self.lineage_id.strip() or not self.command_id.strip():
            raise ValueError("lineage_id and command_id are required")
        for label, value in (
            ("signal_observed_at", self.signal_observed_at),
            ("now", self.now),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{label} must be timezone-aware")
        object.__setattr__(
            self, "closed_observations", tuple(self.closed_observations)
        )


@dataclass(frozen=True)
class PaperExecutionRequest:
    cycle: DeskCycleRequest
    history: HistoricalDecision
    decision: AuthenticatedCommitteeDecision


@dataclass(frozen=True)
class DeskCycleResult:
    cycle_id: str
    status: DeskCycleStatus
    reason: str
    trace_id: str
    thesis_id: str | None
    intent_id: str | None
    episode_id: str | None
    role_event_ids: tuple[str, ...]


class HistorianRole(Protocol):
    def evaluate(self, request: HistoricalRequest) -> HistoricalDecision: ...


class ReporterRole(Protocol):
    def report(self, instrument_id: str, *, as_of: datetime) -> EventBrief: ...


class CrowdReaderRole(Protocol):
    def read(self, *, as_of: datetime) -> MarketMood: ...


class AnalystRole(Protocol):
    def draft(self, brief: AnalystBrief) -> TradeThesis | str: ...


class CommitteeRole(Protocol):
    def review(
        self,
        thesis: TradeThesis,
        context: object,
        *,
        now: datetime,
        command_id: str,
    ) -> AuthenticatedCommitteeDecision: ...


class TraderRole(Protocol):
    def derive_candidate(
        self,
        *,
        plan: StrategyPlan,
        trace: PlanDecisionTrace,
        quote: ExecutableQuote,
        account_snapshot: AccountSnapshot,
        now: datetime,
    ) -> IntentBuildResult: ...

    def execute(self, request: PaperExecutionRequest) -> PaperAcceptance: ...


class CoachRole(Protocol):
    def reflect(
        self,
        observations: tuple[LearningObservation, ...],
        *,
        now: datetime,
        command_id: str,
    ) -> CoachReflection: ...


class SecretaryRole(Protocol):
    def report(self, day: date) -> object: ...


class PaperTrader:
    """Execution Agent: admit and dispatch only through the governed paper path."""

    def __init__(
        self,
        coordinator: GovernedPaperCoordinator,
        kernel: TradingKernel,
    ) -> None:
        self._coordinator = coordinator
        self._kernel = kernel

    def derive_candidate(
        self,
        *,
        plan: StrategyPlan,
        trace: PlanDecisionTrace,
        quote: ExecutableQuote,
        account_snapshot: AccountSnapshot,
        now: datetime,
    ) -> IntentBuildResult:
        return self._coordinator.derive_candidate(
            plan=plan,
            trace=trace,
            quote=quote,
            account_snapshot=account_snapshot,
            now=now,
        )

    def execute(self, request: PaperExecutionRequest) -> PaperAcceptance:
        cycle = request.cycle
        accepted = self._coordinator.accept(
            lineage_id=cycle.lineage_id,
            plan=cycle.plan,
            trace=request.history.trace,
            quote=cycle.quote,
            account_snapshot=cycle.account_snapshot,
            operational_health=cycle.operational_health,
            signal_observed_at=cycle.signal_observed_at,
            now=cycle.now,
            command_id=cycle.command_id,
            approval_record=request.decision.approval,
            decision_market_snapshot_id=cycle.decision_market_snapshot_id,
            trace_attestation_event_id=(
                request.history.trace_attestation_event_id
            ),
            verdict_evidence_event_ids=(
                request.decision.verdict_evidence_event_ids
            ),
        )
        self._kernel.run_once(cycle.account_snapshot, now=cycle.now)
        return accepted


class DeskRuntime:
    """Desk Head: route one exact paper cycle and preserve every role outcome."""

    def __init__(
        self,
        *,
        journal: OperationalJournal,
        historian: HistorianRole,
        reporter: ReporterRole,
        crowd_reader: CrowdReaderRole,
        analyst: AnalystRole,
        committee: CommitteeRole,
        trader: TraderRole,
        coach: CoachRole,
        secretary: SecretaryRole,
    ) -> None:
        self._journal = journal
        self.historian = historian
        self.reporter = reporter
        self.crowd_reader = crowd_reader
        self.analyst = analyst
        self.committee = committee
        self.trader = trader
        self.coach = coach
        self.secretary = secretary

    def run_cycle(self, request: DeskCycleRequest) -> DeskCycleResult:
        cycle_id = "cycle:" + _digest(request.command_id)
        stream = "desk-cycle:" + cycle_id.removeprefix("cycle:")
        try:
            terminal = _terminal_event(self._journal.read_stream(stream))
            if terminal is not None:
                # Re-append the start command to prove this is the exact same
                # request before returning a previously recorded terminal result.
                self._append(
                    stream,
                    request,
                    event_type="DeskCycleStarted",
                    suffix="start",
                    payload=_start_payload(request, cycle_id),
                )
                if not self._journal.verify().ok:
                    raise RuntimeError(
                        "completed desk cycle has failed journal integrity"
                    )
                if terminal.event_type == "DeskCycleFailed":
                    raise DeskCycleFailed(
                        cycle_id, str(terminal.payload["detail"])
                    )
                return _result_from_terminal(
                    cycle_id,
                    terminal,
                    self._journal.read_stream(stream),
                )
            return self._run_cycle(request)
        except DeskCycleFailed:
            raise
        except Exception as exc:
            try:
                if _terminal_event(self._journal.read_stream(stream)) is None:
                    self._append(
                        stream,
                        request,
                        event_type="DeskCycleFailed",
                        suffix="failed",
                        payload={
                            "cycle_id": cycle_id,
                            "error_type": type(exc).__name__,
                            "detail": str(exc),
                            "new_entries_allowed": False,
                        },
                    )
            except Exception:
                pass
            raise DeskCycleFailed(cycle_id, str(exc)) from exc

    def _run_cycle(self, request: DeskCycleRequest) -> DeskCycleResult:
        cycle_id = "cycle:" + _digest(request.command_id)
        stream = "desk-cycle:" + cycle_id.removeprefix("cycle:")
        role_events: list[str] = []
        self._append(
            stream,
            request,
            event_type="DeskCycleStarted",
            suffix="start",
            payload=_start_payload(request, cycle_id),
        )

        history = self.historian.evaluate(
            HistoricalRequest(
                plan=request.plan,
                instrument_id=request.quote.instrument_id,
                bars=request.bars,
                evaluation_session=request.evaluation_session,
                market_snapshot_id=request.decision_market_snapshot_id,
                occurred_at=request.signal_observed_at,
                command_id=f"{request.command_id}:historian",
            )
        )
        role_events.append(
            self._role(
                stream,
                request,
                cycle_id,
                "historian",
                {
                    "trace_id": history.trace.trace_id,
                    "action": history.trace.action.value,
                    "attestation_event_id": history.trace_attestation_event_id,
                },
            )
        )
        events = self.reporter.report(request.quote.instrument_id, as_of=request.now)
        role_events.append(
            self._role(
                stream,
                request,
                cycle_id,
                "reporter",
                {"blocked": events.blocked, "reason": events.reason},
            )
        )
        mood = self.crowd_reader.read(as_of=request.now)
        role_events.append(
            self._role(
                stream,
                request,
                cycle_id,
                "crowd-reader",
                {"label": mood.label, "confidence": mood.confidence},
            )
        )

        if events.blocked:
            self._skip_many(
                stream,
                request,
                cycle_id,
                ("analyst", "committee", "trader"),
                events.reason,
                role_events,
            )
            return self._finish(
                stream,
                request,
                cycle_id,
                DeskCycleStatus.EVENT_BLOCKED,
                events.reason,
                history,
                None,
                None,
                role_events,
            )
        if history.trace.action.value != "enter_long":
            self._skip_many(
                stream,
                request,
                cycle_id,
                ("analyst", "committee", "trader"),
                "strategy emitted no entry",
                role_events,
            )
            return self._finish(
                stream,
                request,
                cycle_id,
                DeskCycleStatus.NO_SIGNAL,
                "strategy emitted no entry",
                history,
                None,
                None,
                role_events,
            )

        candidate = self.trader.derive_candidate(
            plan=request.plan,
            trace=history.trace,
            quote=request.quote,
            account_snapshot=request.account_snapshot,
            now=request.now,
        )
        thesis = self.analyst.draft(
            AnalystBrief(
                plan=request.plan,
                candidate=candidate,
                history=history,
                events=events,
                mood=mood,
                strategy_stats=request.strategy_stats,
                created_at=request.now,
            )
        )
        if isinstance(thesis, str):
            role_events.append(
                self._role(
                    stream,
                    request,
                    cycle_id,
                    "analyst",
                    {"proceed": False, "reason": thesis},
                )
            )
            self._skip_many(
                stream,
                request,
                cycle_id,
                ("committee", "trader"),
                "analyst declined",
                role_events,
            )
            return self._finish(
                stream,
                request,
                cycle_id,
                DeskCycleStatus.ANALYST_DECLINED,
                thesis,
                history,
                None,
                None,
                role_events,
            )
        if not isinstance(thesis, TradeThesis):
            raise TypeError("analyst must return a TradeThesis or decline reason")
        role_events.append(
            self._role(
                stream,
                request,
                cycle_id,
                "analyst",
                {"proceed": True, "thesis_id": thesis.id},
            )
        )

        decision = self.committee.review(
            thesis,
            CommitteeReviewContext(
                inputs=request.committee_context,
                events=events,
                mood=mood,
            ),
            now=request.now,
            command_id=f"{request.command_id}:committee",
        )
        if decision.approval.thesis != thesis:
            raise ValueError("committee decision does not belong to the analyst thesis")
        role_events.append(
            self._role(
                stream,
                request,
                cycle_id,
                "committee",
                {
                    "approved": decision.approval.approved,
                    "vetoed_by": decision.approval.vetoed_by,
                    "verdict_count": len(decision.approval.verdicts),
                },
            )
        )
        if not decision.approval.approved:
            role_events.append(
                self._skipped(
                    stream,
                    request,
                    cycle_id,
                    "trader",
                    "committee veto",
                )
            )
            return self._finish(
                stream,
                request,
                cycle_id,
                DeskCycleStatus.COMMITTEE_VETOED,
                "committee veto",
                history,
                thesis,
                None,
                role_events,
            )

        acceptance = self.trader.execute(
            PaperExecutionRequest(
                cycle=request,
                history=history,
                decision=decision,
            )
        )
        role_events.append(
            self._role(
                stream,
                request,
                cycle_id,
                "trader",
                {
                    "intent_id": acceptance.intent.intent_id,
                    "episode_id": acceptance.episode.episode_id,
                    "execution_mode": "paper",
                },
            )
        )
        return self._finish(
            stream,
            request,
            cycle_id,
            DeskCycleStatus.PAPER_DISPATCHED,
            "unanimous governed paper admission dispatched",
            history,
            thesis,
            acceptance,
            role_events,
        )

    def _finish(
        self,
        stream: str,
        request: DeskCycleRequest,
        cycle_id: str,
        status: DeskCycleStatus,
        reason: str,
        history: HistoricalDecision,
        thesis: TradeThesis | None,
        acceptance: PaperAcceptance | None,
        role_events: list[str],
    ) -> DeskCycleResult:
        reflection = self.coach.reflect(
            request.closed_observations,
            now=request.now,
            command_id=f"{request.command_id}:coach",
        )
        role_events.append(
            self._role(
                stream,
                request,
                cycle_id,
                "coach",
                {
                    "observations_recorded": reflection.observations_recorded,
                    "hypotheses_proposed": reflection.hypotheses_proposed,
                },
            )
        )
        report = self.secretary.report(request.now.date())
        role_events.append(
            self._role(
                stream,
                request,
                cycle_id,
                "secretary",
                {"report_type": type(report).__name__},
            )
        )
        role_events.append(
            self._role(
                stream,
                request,
                cycle_id,
                "orchestrator",
                {"status": status.value, "reason": reason},
            )
        )
        self._append(
            stream,
            request,
            event_type="DeskCycleCompleted",
            suffix="complete",
            payload={
                "cycle_id": cycle_id,
                "status": status.value,
                "reason": reason,
                "trace_id": history.trace.trace_id,
                "thesis_id": thesis.id if thesis is not None else None,
                "intent_id": (
                    acceptance.intent.intent_id
                    if acceptance is not None
                    else None
                ),
                "role_event_ids": tuple(role_events),
            },
        )
        return DeskCycleResult(
            cycle_id=cycle_id,
            status=status,
            reason=reason,
            trace_id=history.trace.trace_id,
            thesis_id=thesis.id if thesis is not None else None,
            intent_id=(
                acceptance.intent.intent_id if acceptance is not None else None
            ),
            episode_id=(
                acceptance.episode.episode_id if acceptance is not None else None
            ),
            role_event_ids=tuple(role_events),
        )

    def _skip_many(
        self,
        stream: str,
        request: DeskCycleRequest,
        cycle_id: str,
        roles: tuple[str, ...],
        reason: str,
        role_events: list[str],
    ) -> None:
        for role in roles:
            role_events.append(
                self._skipped(stream, request, cycle_id, role, reason)
            )

    def _role(
        self,
        stream: str,
        request: DeskCycleRequest,
        cycle_id: str,
        role: str,
        details: dict[str, object],
    ) -> str:
        return self._append(
            stream,
            request,
            event_type="DeskRoleCompleted",
            suffix=f"role:{role}",
            payload={
                "cycle_id": cycle_id,
                "role": role,
                "details": details,
            },
        )

    def _skipped(
        self,
        stream: str,
        request: DeskCycleRequest,
        cycle_id: str,
        role: str,
        reason: str,
    ) -> str:
        return self._append(
            stream,
            request,
            event_type="DeskRoleSkipped",
            suffix=f"role:{role}",
            payload={"cycle_id": cycle_id, "role": role, "reason": reason},
        )

    def _append(
        self,
        stream: str,
        request: DeskCycleRequest,
        *,
        event_type: str,
        suffix: str,
        payload: dict[str, object],
    ) -> str:
        events = self._journal.read_stream(stream)
        event = self._journal.append(
            EventAppend(
                stream_id=stream,
                event_type=event_type,
                payload=payload,
                idempotency_key=(
                    f"desk:{_digest(request.command_id)}:{suffix}"
                ),
                expected_version=len(events),
                occurred_at=request.now,
                correlation_id="cycle:" + _digest(request.command_id),
            )
        )
        return event.event_id


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _start_payload(
    request: DeskCycleRequest,
    cycle_id: str,
) -> dict[str, object]:
    return {
        "cycle_id": cycle_id,
        "request_id": _request_id(request),
        "lineage_id": request.lineage_id,
        "plan_id": request.plan.plan_id,
        "instrument_id": request.quote.instrument_id,
        "mode": "paper",
    }


def _request_id(request: DeskCycleRequest) -> str:
    identity = {
        "lineage_id": request.lineage_id,
        "plan_id": request.plan.plan_id,
        "evaluation_session": request.evaluation_session.isoformat(),
        "decision_market_snapshot_id": request.decision_market_snapshot_id,
        "quote": _identity_value(request.quote),
        "account_snapshot_id": request.account_snapshot.snapshot_id,
        "operational_health": _identity_value(request.operational_health),
        "signal_observed_at": request.signal_observed_at.isoformat(),
        "now": request.now.isoformat(),
        "strategy_stats": _identity_value(request.strategy_stats),
        "committee_context": _identity_value(request.committee_context),
        "closed_observations": _identity_value(request.closed_observations),
    }
    canonical = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return "desk-request:" + _digest(canonical)


def _identity_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("desk request identity requires finite numbers")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("desk request identity requires finite numbers")
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("desk request identity requires aware timestamps")
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return _identity_value(value.value)
    if isinstance(value, Mapping):
        return {
            str(key): _identity_value(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_identity_value(child) for child in value]
    if isinstance(value, (set, frozenset)):
        children = [_identity_value(child) for child in value]
        return sorted(
            children,
            key=lambda child: json.dumps(child, sort_keys=True),
        )
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _identity_value(getattr(value, field.name))
            for field in fields(value)
        }
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _identity_value(model_dump(mode="json"))
    raise TypeError(
        f"unsupported desk request identity value {type(value).__name__}"
    )


def _terminal_event(events):
    terminal = tuple(
        event
        for event in events
        if event.event_type in {"DeskCycleCompleted", "DeskCycleFailed"}
    )
    if len(terminal) > 1:
        raise RuntimeError("desk cycle has multiple terminal events")
    return terminal[0] if terminal else None


def _result_from_terminal(cycle_id: str, terminal, events) -> DeskCycleResult:
    if terminal.event_type != "DeskCycleCompleted":
        raise RuntimeError("desk cycle terminal event is not completed")
    payload = terminal.payload
    if payload.get("cycle_id") != cycle_id:
        raise RuntimeError("desk cycle terminal identity is invalid")
    role_event_ids = tuple(str(value) for value in payload["role_event_ids"])
    roles_by_id = {
        event.event_id: event
        for event in events
        if event.event_type in {"DeskRoleCompleted", "DeskRoleSkipped"}
    }
    if any(event_id not in roles_by_id for event_id in role_event_ids):
        raise RuntimeError("desk cycle terminal references missing role evidence")
    trader = next(
        (
            roles_by_id[event_id]
            for event_id in role_event_ids
            if roles_by_id[event_id].event_type == "DeskRoleCompleted"
            and roles_by_id[event_id].payload.get("role") == "trader"
        ),
        None,
    )
    trader_details = trader.payload.get("details") if trader is not None else None
    episode_id = (
        str(trader_details["episode_id"])
        if isinstance(trader_details, Mapping)
        and trader_details.get("episode_id") is not None
        else None
    )
    return DeskCycleResult(
        cycle_id=cycle_id,
        status=DeskCycleStatus(str(payload["status"])),
        reason=str(payload["reason"]),
        trace_id=str(payload["trace_id"]),
        thesis_id=_optional_text(payload.get("thesis_id")),
        intent_id=_optional_text(payload.get("intent_id")),
        episode_id=episode_id,
        role_event_ids=role_event_ids,
    )


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)
