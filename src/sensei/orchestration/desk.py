"""One durable paper-desk cycle connecting the nine PRD roles."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum, StrEnum
from time import perf_counter_ns
from typing import Protocol

import pandas as pd

from sensei.agents.thesis import ApprovalRecord, TradeThesis
from sensei.kernel import (
    EntryAuthorizationInvalid,
    EntryDispatchAuthorization,
    TradingKernel,
)
from sensei.learning.outcomes import LearningObservation
from sensei.evaluation import AgentInvocation, AgentInvocationLedger, AgentOutcome
from sensei.memory import (
    AgentMemoryRole,
    DeskMemoryContexts,
    DeskMemoryCoordinator,
    DeskMemoryScope,
    MemoryContextPack,
)
from sensei.operations import EventAppend, OperationalJournal
from sensei.operations.health import OperationalHealth, OperationsMonitor
from sensei.portfolio_risk import AccountSnapshot, SafetyControl, TradeIntent
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
    memory_context: MemoryContextPack | None = None


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
    memory_context: MemoryContextPack | None = None


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


class _RoleCallFailed(RuntimeError):
    def __init__(self, role, durations, original):
        self.role = role
        self.durations = dict(durations)
        self.original = original
        super().__init__(str(original))


@dataclass(frozen=True)
class DispatchAuthorization:
    """One trusted supervisor decision made at the Trader boundary."""

    observed_at: datetime
    evidence_event_id: str
    intent_id: str
    cycle_request_id: str
    issuer_id: str
    signature: str
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("dispatch authorization time must be timezone-aware")
        if (
            not isinstance(self.evidence_event_id, str)
            or not self.evidence_event_id.startswith("event:")
        ):
            raise ValueError("dispatch authorization evidence_event_id is required")
        if not isinstance(self.intent_id, str) or not self.intent_id.startswith(
            "intent:"
        ):
            raise ValueError("dispatch authorization intent_id is required")
        if not isinstance(
            self.cycle_request_id, str
        ) or not self.cycle_request_id.startswith("desk-request:"):
            raise ValueError("dispatch authorization cycle_request_id is required")
        if not isinstance(self.issuer_id, str) or not self.issuer_id.strip():
            raise ValueError("dispatch authorization issuer_id is required")
        if not isinstance(self.signature, str) or not self.signature.strip():
            raise ValueError("dispatch authorization signature is required")
        reasons = tuple(self.reason_codes)
        if any(
            not isinstance(reason, str) or not reason.strip()
            for reason in reasons
        ):
            raise ValueError("dispatch authorization reason codes must be text")
        if len(reasons) != len(set(reasons)):
            raise ValueError("dispatch authorization reason codes must be unique")
        object.__setattr__(self, "reason_codes", reasons)


class DispatchAuthorizationRejected(RuntimeError):
    """The supervisor rejected admission before any paper gateway dispatch."""

    def __init__(self, authorization: DispatchAuthorization) -> None:
        if not authorization.reason_codes:
            raise ValueError(
                "rejected dispatch authorization requires reason codes"
            )
        self.authorization = authorization
        self.reason_codes = authorization.reason_codes
        self.observed_at = authorization.observed_at
        super().__init__("; ".join(self.reason_codes))


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
    authorize_dispatch: (
        Callable[[DeskCycleRequest, TradeIntent], DispatchAuthorization] | None
    ) = None


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
    def evaluate(
        self, request: HistoricalRequest, *, memory_context: MemoryContextPack
    ) -> HistoricalDecision: ...


class ReporterRole(Protocol):
    def report(
        self, instrument_id: str, *, as_of: datetime, memory_context: MemoryContextPack
    ) -> EventBrief: ...


class CrowdReaderRole(Protocol):
    def read(
        self, *, as_of: datetime, memory_context: MemoryContextPack
    ) -> MarketMood: ...


class AnalystRole(Protocol):
    def draft(
        self, brief: AnalystBrief, *, memory_context: MemoryContextPack
    ) -> TradeThesis | str: ...


class CommitteeRole(Protocol):
    def review(
        self,
        thesis: TradeThesis,
        context: object,
        *,
        now: datetime,
        command_id: str,
        memory_context: MemoryContextPack | None = None,
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
        memory_context: MemoryContextPack,
    ) -> IntentBuildResult: ...

    def execute(
        self,
        request: PaperExecutionRequest,
        *,
        memory_context: MemoryContextPack | None = None,
    ) -> PaperAcceptance: ...


class CoachRole(Protocol):
    def reflect(
        self,
        observations: tuple[LearningObservation, ...],
        *,
        now: datetime,
        command_id: str,
        memory_context: MemoryContextPack,
    ) -> CoachReflection: ...


class SecretaryRole(Protocol):
    def report(self, day: date, *, memory_context: MemoryContextPack) -> object: ...


class PaperTrader:
    """Execution Agent: admit and dispatch only through the governed paper path."""

    def __init__(
        self,
        coordinator: GovernedPaperCoordinator,
        kernel: TradingKernel,
    ) -> None:
        self._coordinator = coordinator
        self._kernel = kernel

    def is_bound_to_governed_paper_runtime(
        self,
        *,
        journal: OperationalJournal,
        kernel: TradingKernel,
        safety: SafetyControl,
        operations_monitor: OperationsMonitor,
    ) -> bool:
        """Return whether execution traverses the exact governed paper path."""

        return (
            self._kernel is kernel
            and type(self._coordinator) is GovernedPaperCoordinator
            and GovernedPaperCoordinator.is_bound_to_kernel_runtime(
                self._coordinator,
                journal=journal,
                kernel=kernel,
                safety=safety,
                operations_monitor=operations_monitor,
            )
        )

    def derive_candidate(
        self,
        *,
        plan: StrategyPlan,
        trace: PlanDecisionTrace,
        quote: ExecutableQuote,
        account_snapshot: AccountSnapshot,
        now: datetime,
        memory_context: MemoryContextPack | None = None,
    ) -> IntentBuildResult:
        _require_role_memory(memory_context, AgentMemoryRole.TRADER)
        return self._coordinator.derive_candidate(
            plan=plan,
            trace=trace,
            quote=quote,
            account_snapshot=account_snapshot,
            now=now,
        )

    def execute(
        self,
        request: PaperExecutionRequest,
        *,
        memory_context: MemoryContextPack | None = None,
    ) -> PaperAcceptance:
        _require_role_memory(memory_context, AgentMemoryRole.TRADER)
        cycle = request.cycle
        if request.authorize_dispatch is None:
            raise RuntimeError(
                "paper entry requires a Supervisor dispatch authorizer"
            )
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
        authorization_returned = False
        entry_was_prepared = self._kernel.has_prepared_entry(
            accepted.intent.intent_id
        )
        quarantine_evidence_event_id = accepted.admission_event_id
        quarantine_time = cycle.now

        def authorize_entry(intent):
            nonlocal authorization_returned
            nonlocal quarantine_evidence_event_id
            nonlocal quarantine_time
            if intent.intent_id != accepted.intent.intent_id:
                raise RuntimeError("Kernel requested authorization for another intent")
            authorization = request.authorize_dispatch(cycle, intent)
            if type(authorization) is not DispatchAuthorization:
                raise TypeError(
                    "dispatch gate must return an exact DispatchAuthorization"
                )
            quarantine_evidence_event_id = authorization.evidence_event_id
            quarantine_time = authorization.observed_at
            if authorization.reason_codes:
                raise DispatchAuthorizationRejected(authorization)
            entry_authorization = EntryDispatchAuthorization(
                account_snapshot=cycle.account_snapshot,
                authorized_at=authorization.observed_at,
                evidence_event_id=authorization.evidence_event_id,
                intent_id=authorization.intent_id,
                cycle_request_id=authorization.cycle_request_id,
                issuer_id=authorization.issuer_id,
                signature=authorization.signature,
            )
            authorization_returned = True
            return entry_authorization

        try:
            self._kernel.run_once(
                cycle.account_snapshot,
                now=cycle.now,
                intent_id=accepted.intent.intent_id,
                authorize_entry=authorize_entry,
            )
        except DispatchAuthorizationRejected as exc:
            if not entry_was_prepared:
                self._kernel.quarantine_intent(
                    accepted.intent.intent_id,
                    reason_codes=exc.reason_codes,
                    evidence_event_id=exc.authorization.evidence_event_id,
                    occurred_at=exc.observed_at,
                )
            raise
        except EntryAuthorizationInvalid as exc:
            if not entry_was_prepared:
                self._kernel.quarantine_intent(
                    accepted.intent.intent_id,
                    reason_codes=(exc.reason_code,),
                    evidence_event_id=quarantine_evidence_event_id,
                    occurred_at=quarantine_time,
                )
            raise
        except Exception:
            if not authorization_returned and not entry_was_prepared:
                self._kernel.quarantine_intent(
                    accepted.intent.intent_id,
                    reason_codes=("DISPATCH_AUTHORIZATION_FAILED",),
                    evidence_event_id=quarantine_evidence_event_id,
                    occurred_at=quarantine_time,
                )
            raise
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
        self._memory = DeskMemoryCoordinator(journal)
        self._invocations = AgentInvocationLedger(journal)
        self.historian = historian
        self.reporter = reporter
        self.crowd_reader = crowd_reader
        self.analyst = analyst
        self.committee = committee
        self.trader = trader
        self.coach = coach
        self.secretary = secretary

    def is_bound_to_governed_paper_runtime(
        self,
        *,
        journal: OperationalJournal,
        kernel: TradingKernel,
        safety: SafetyControl,
        operations_monitor: OperationsMonitor,
    ) -> bool:
        """Return whether this desk routes through the exact paper runtime."""

        return (
            self._journal is journal
            and type(self.trader) is PaperTrader
            and PaperTrader.is_bound_to_governed_paper_runtime(
                self.trader,
                journal=journal,
                kernel=kernel,
                safety=safety,
                operations_monitor=operations_monitor,
            )
        )

    def run_cycle(
        self,
        request: DeskCycleRequest,
        *,
        authorize_dispatch: (
            Callable[[DeskCycleRequest, TradeIntent], DispatchAuthorization] | None
        ) = None,
    ) -> DeskCycleResult:
        cycle_id = "cycle:" + _digest(request.command_id)
        stream = "desk-cycle:" + cycle_id.removeprefix("cycle:")
        try:
            terminal = _terminal_event(self._journal.read_stream(stream))
            if terminal is not None:
                # Re-append the start command to prove this is the exact same
                # request before returning a previously recorded terminal result.
                started = next(
                    event
                    for event in self._journal.read_stream(stream)
                    if event.event_type == "DeskCycleStarted"
                )
                self._append(
                    stream,
                    request,
                    event_type="DeskCycleStarted",
                    suffix="start",
                    payload={
                        **_start_payload(request, cycle_id),
                        "memory_context_pack_ids": _identity_value(
                            started.payload["memory_context_pack_ids"]
                        ),
                        "memory_audit_event_ids": _identity_value(
                            started.payload["memory_audit_event_ids"]
                        ),
                    },
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
            return self._run_cycle(
                request,
                authorize_dispatch=authorize_dispatch,
            )
        except DispatchAuthorizationRejected as exc:
            try:
                memory = self._memory.prepare_cycle_contexts(
                    cycle_id=cycle_id,
                    as_of=request.now,
                    occurred_at=request.now,
                    scope=DeskMemoryScope(
                        instrument_id=request.quote.instrument_id,
                        plan_version_id=request.plan.plan_id,
                        strategy_lineage_id=request.lineage_id,
                    ),
                )
                self._record_failed_invocations(
                    request=request,
                    cycle_id=cycle_id,
                    memory=memory,
                    failed_role=AgentMemoryRole.TRADER,
                    latency_ms=getattr(exc, "_desk_durations", {}),
                )
            except Exception:
                pass
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
                            "reason_codes": exc.reason_codes,
                            "new_entries_allowed": False,
                        },
                        occurred_at=exc.observed_at,
                    )
            except Exception:
                pass
            raise
        except DeskCycleFailed:
            raise
        except Exception as exc:
            detail_exc = exc
            if isinstance(exc, _RoleCallFailed):
                try:
                    memory = self._memory.prepare_cycle_contexts(
                        cycle_id=cycle_id,
                        as_of=request.now,
                        occurred_at=request.now,
                        scope=DeskMemoryScope(
                            instrument_id=request.quote.instrument_id,
                            plan_version_id=request.plan.plan_id,
                            strategy_lineage_id=request.lineage_id,
                        ),
                    )
                    self._record_failed_invocations(
                        request=request,
                        cycle_id=cycle_id,
                        memory=memory,
                        failed_role=exc.role,
                        latency_ms=exc.durations,
                    )
                except Exception:
                    pass
                detail_exc = exc.original
            try:
                if _terminal_event(self._journal.read_stream(stream)) is None:
                    self._append(
                        stream,
                        request,
                        event_type="DeskCycleFailed",
                        suffix="failed",
                        payload={
                            "cycle_id": cycle_id,
                            "error_type": type(detail_exc).__name__,
                            "detail": str(detail_exc),
                            "new_entries_allowed": False,
                        },
                    )
            except Exception:
                pass
            raise DeskCycleFailed(cycle_id, str(detail_exc)) from detail_exc

    def _run_cycle(
        self,
        request: DeskCycleRequest,
        *,
        authorize_dispatch: (
            Callable[[DeskCycleRequest, TradeIntent], DispatchAuthorization] | None
        ),
    ) -> DeskCycleResult:
        cycle_id = "cycle:" + _digest(request.command_id)
        stream = "desk-cycle:" + cycle_id.removeprefix("cycle:")
        role_events: list[str] = []
        latency_ms: dict[AgentMemoryRole, int] = {}
        memory = self._memory.prepare_cycle_contexts(
            cycle_id=cycle_id,
            as_of=request.now,
            occurred_at=request.now,
            scope=DeskMemoryScope(
                instrument_id=request.quote.instrument_id,
                plan_version_id=request.plan.plan_id,
                strategy_lineage_id=request.lineage_id,
            ),
        )
        self._append(
            stream,
            request,
            event_type="DeskCycleStarted",
            suffix="start",
            payload={
                **_start_payload(request, cycle_id),
                "memory_context_pack_ids": {
                    role.value: pack.context_pack_id
                    for role, pack in memory.contexts.items()
                },
                "memory_audit_event_ids": {
                    role.value: event_id
                    for role, event_id in memory.audit_event_ids.items()
                },
            },
        )

        history = self._timed(
            AgentMemoryRole.HISTORIAN,
            latency_ms,
            lambda: self.historian.evaluate(
                HistoricalRequest(
                plan=request.plan,
                instrument_id=request.quote.instrument_id,
                bars=request.bars,
                evaluation_session=request.evaluation_session,
                market_snapshot_id=request.decision_market_snapshot_id,
                occurred_at=request.signal_observed_at,
                command_id=f"{request.command_id}:historian",
                ),
                memory_context=memory.contexts[AgentMemoryRole.HISTORIAN],
            ),
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
        events = self._timed(
            AgentMemoryRole.REPORTER,
            latency_ms,
            lambda: self.reporter.report(
                request.quote.instrument_id,
                as_of=request.now,
                memory_context=memory.contexts[AgentMemoryRole.REPORTER],
            ),
        )
        role_events.append(
            self._role(
                stream,
                request,
                cycle_id,
                "reporter",
                {"blocked": events.blocked, "reason": events.reason},
            )
        )
        mood = self._timed(
            AgentMemoryRole.CROWD_READER,
            latency_ms,
            lambda: self.crowd_reader.read(
                as_of=request.now,
                memory_context=memory.contexts[AgentMemoryRole.CROWD_READER],
            ),
        )
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
                memory,
                latency_ms,
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
                memory,
                latency_ms,
            )

        candidate = self._timed(
            AgentMemoryRole.TRADER,
            latency_ms,
            lambda: self.trader.derive_candidate(
                plan=request.plan,
                trace=history.trace,
                quote=request.quote,
                account_snapshot=request.account_snapshot,
                now=request.now,
                memory_context=memory.contexts[AgentMemoryRole.TRADER],
            ),
        )
        thesis = self._timed(
            AgentMemoryRole.ANALYST,
            latency_ms,
            lambda: self.analyst.draft(
                AnalystBrief(
                plan=request.plan,
                candidate=candidate,
                history=history,
                events=events,
                mood=mood,
                strategy_stats=request.strategy_stats,
                created_at=request.now,
                memory_context=memory.contexts[AgentMemoryRole.ANALYST],
                ),
                memory_context=memory.contexts[AgentMemoryRole.ANALYST],
            ),
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
                memory,
                latency_ms,
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

        decision = self._timed(
            AgentMemoryRole.COMMITTEE,
            latency_ms,
            lambda: self.committee.review(
                thesis,
                CommitteeReviewContext(
                    inputs=request.committee_context,
                    events=events,
                    mood=mood,
                    memory_context=memory.contexts[AgentMemoryRole.COMMITTEE],
                ),
                now=request.now,
                command_id=f"{request.command_id}:committee",
                memory_context=memory.contexts[AgentMemoryRole.COMMITTEE],
            ),
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
                memory,
                latency_ms,
            )

        acceptance = self._timed(
            AgentMemoryRole.TRADER,
            latency_ms,
            lambda: self.trader.execute(
                PaperExecutionRequest(
                cycle=request,
                history=history,
                decision=decision,
                authorize_dispatch=authorize_dispatch,
                ),
                memory_context=memory.contexts[AgentMemoryRole.TRADER],
            ),
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
            memory,
            latency_ms,
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
        memory: DeskMemoryContexts,
        latency_ms: dict[AgentMemoryRole, int],
    ) -> DeskCycleResult:
        reflection = self._timed(
            AgentMemoryRole.COACH,
            latency_ms,
            lambda: self.coach.reflect(
                request.closed_observations,
                now=request.now,
                command_id=f"{request.command_id}:coach",
                memory_context=memory.contexts[AgentMemoryRole.COACH],
            ),
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
        report = self._timed(
            AgentMemoryRole.SECRETARY,
            latency_ms,
            lambda: self.secretary.report(
                request.now.date(),
                memory_context=memory.contexts[AgentMemoryRole.SECRETARY],
            ),
        )
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
        self._record_invocations(
            request=request,
            cycle_id=cycle_id,
            role_event_ids=tuple(role_events),
            memory=memory,
            latency_ms=latency_ms,
            episode_id=(
                acceptance.episode.episode_id if acceptance is not None else None
            ),
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

    def _record_invocations(
        self,
        *,
        request: DeskCycleRequest,
        cycle_id: str,
        role_event_ids: tuple[str, ...],
        memory: DeskMemoryContexts,
        latency_ms: Mapping[AgentMemoryRole, int],
        episode_id: str | None,
    ) -> None:
        events = {
            event.event_id: event
            for event in self._journal.read_all()
            if event.event_id in role_event_ids
        }
        role_names = {
            "orchestrator": AgentMemoryRole.DESK_HEAD,
            "historian": AgentMemoryRole.HISTORIAN,
            "reporter": AgentMemoryRole.REPORTER,
            "crowd-reader": AgentMemoryRole.CROWD_READER,
            "analyst": AgentMemoryRole.ANALYST,
            "committee": AgentMemoryRole.COMMITTEE,
            "trader": AgentMemoryRole.TRADER,
            "coach": AgentMemoryRole.COACH,
            "secretary": AgentMemoryRole.SECRETARY,
        }
        by_role = {
            role_names[str(event.payload["role"])]: event
            for event in events.values()
        }
        if set(by_role) != set(AgentMemoryRole):
            raise RuntimeError("desk invocation ledger requires all nine role outcomes")
        audit_events = {
            event.event_id: event
            for event in self._journal.read_all()
            if event.event_id in set(memory.audit_event_ids.values())
        }
        for role in AgentMemoryRole:
            role_event = by_role[role]
            details = role_event.payload.get("details", {})
            if role_event.event_type == "DeskRoleSkipped":
                outcome = AgentOutcome.ABSTAIN
            elif role is AgentMemoryRole.COMMITTEE and not bool(
                details.get("approved")
            ):
                outcome = AgentOutcome.VETO
            elif role is AgentMemoryRole.ANALYST and not bool(
                details.get("proceed", True)
            ):
                outcome = AgentOutcome.ABSTAIN
            else:
                outcome = AgentOutcome.PROCEED
            audit_id = memory.audit_event_ids[role]
            audit = audit_events[audit_id]
            occurred_at = max(request.now, audit.occurred_at, audit.recorded_at)
            methods = None
            if role_event.event_type == "DeskRoleSkipped":
                methods = (
                    ("derive_candidate",)
                    if role is AgentMemoryRole.TRADER and latency_ms.get(role, 0)
                    else ()
                )
            elif role is AgentMemoryRole.TRADER:
                methods = ("derive_candidate", "execute")
            prompt_id, model_id = self._runtime_identity(role, methods)
            self._invocations.record(
                AgentInvocation(
                    cycle_id=cycle_id,
                    episode_id=episode_id,
                    role=role,
                    context_pack_id=memory.contexts[role].context_pack_id,
                    context_pack_audit_event_id=audit_id,
                    prompt_id=prompt_id,
                    model_id=model_id,
                    outcome=outcome,
                    confidence=None,
                    latency_ms=latency_ms.get(role, 0),
                    cost_microunits=0,
                    occurred_at=occurred_at,
                ),
                command_id=f"{cycle_id}:{role.value}:invocation",
            )

    @staticmethod
    def _timed(role, durations, operation):
        started = perf_counter_ns()
        try:
            result = operation()
        except Exception as exc:
            elapsed_ms = (perf_counter_ns() - started + 999_999) // 1_000_000
            durations[role] = durations.get(role, 0) + elapsed_ms
            if isinstance(exc, DispatchAuthorizationRejected):
                setattr(exc, "_desk_durations", dict(durations))
                raise
            raise _RoleCallFailed(role, durations, exc) from exc
        elapsed_ms = (perf_counter_ns() - started + 999_999) // 1_000_000
        durations[role] = durations.get(role, 0) + elapsed_ms
        return result

    def _record_failed_invocations(
        self,
        *,
        request: DeskCycleRequest,
        cycle_id: str,
        memory: DeskMemoryContexts,
        failed_role: AgentMemoryRole,
        latency_ms: Mapping[AgentMemoryRole, int],
    ) -> None:
        role_names = {
            "orchestrator": AgentMemoryRole.DESK_HEAD,
            "historian": AgentMemoryRole.HISTORIAN,
            "reporter": AgentMemoryRole.REPORTER,
            "crowd-reader": AgentMemoryRole.CROWD_READER,
            "analyst": AgentMemoryRole.ANALYST,
            "committee": AgentMemoryRole.COMMITTEE,
            "trader": AgentMemoryRole.TRADER,
            "coach": AgentMemoryRole.COACH,
            "secretary": AgentMemoryRole.SECRETARY,
        }
        observed = {}
        for event in self._journal.read_all():
            if (
                event.correlation_id == cycle_id
                and event.event_type in {"DeskRoleCompleted", "DeskRoleSkipped"}
            ):
                observed[role_names[str(event.payload["role"])]] = event
        roles = tuple(AgentMemoryRole)
        audit_by_id = {
            event.event_id: event
            for event in self._journal.read_all()
            if event.event_id in set(memory.audit_event_ids.values())
        }
        for role in roles:
            details = (
                observed[role].payload.get("details", {})
                if role in observed
                else {}
            )
            if role in {failed_role, AgentMemoryRole.DESK_HEAD}:
                outcome = AgentOutcome.ERROR
            elif role not in observed or observed[role].event_type == "DeskRoleSkipped":
                outcome = AgentOutcome.ABSTAIN
            elif role is AgentMemoryRole.COMMITTEE and not bool(
                details.get("approved")
            ):
                outcome = AgentOutcome.VETO
            elif role is AgentMemoryRole.ANALYST and not bool(
                details.get("proceed", True)
            ):
                outcome = AgentOutcome.ABSTAIN
            else:
                outcome = AgentOutcome.PROCEED
            audit_id = memory.audit_event_ids[role]
            audit = audit_by_id[audit_id]
            if role not in observed and role not in {
                failed_role,
                AgentMemoryRole.DESK_HEAD,
            }:
                methods = ()
            elif role is AgentMemoryRole.TRADER and role in observed:
                methods = ("derive_candidate", "execute")
            else:
                methods = None
            prompt_id, model_id = self._runtime_identity(role, methods)
            self._invocations.record(
                AgentInvocation(
                    cycle_id=cycle_id,
                    episode_id=None,
                    role=role,
                    context_pack_id=memory.contexts[role].context_pack_id,
                    context_pack_audit_event_id=audit_id,
                    prompt_id=prompt_id,
                    model_id=model_id,
                    outcome=outcome,
                    confidence=None,
                    latency_ms=latency_ms.get(role, 0),
                    cost_microunits=0,
                    occurred_at=max(request.now, audit.occurred_at, audit.recorded_at),
                ),
                command_id=f"{cycle_id}:{role.value}:invocation",
            )

    def _runtime_identity(
        self, role: AgentMemoryRole, methods: tuple[str, ...] | None = None
    ) -> tuple[str, str]:
        targets = {
            AgentMemoryRole.DESK_HEAD: (self, "run_cycle"),
            AgentMemoryRole.HISTORIAN: (self.historian, "evaluate"),
            AgentMemoryRole.REPORTER: (self.reporter, "report"),
            AgentMemoryRole.CROWD_READER: (self.crowd_reader, "read"),
            AgentMemoryRole.ANALYST: (self.analyst, "draft"),
            AgentMemoryRole.COMMITTEE: (self.committee, "review"),
            AgentMemoryRole.TRADER: (self.trader, "execute"),
            AgentMemoryRole.COACH: (self.coach, "reflect"),
            AgentMemoryRole.SECRETARY: (self.secretary, "report"),
        }
        target, method_name = targets[role]
        selected = (method_name,) if methods is None else methods
        if not selected:
            return f"not-invoked:{role.value}", "none"
        kind = type(target)
        implementation = (
            f"{kind.__module__}.{kind.__qualname__}." + "+".join(selected)
        )
        return f"callable:{implementation}", f"python:{implementation}"

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
        occurred_at: datetime | None = None,
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
                occurred_at=occurred_at or request.now,
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
        "request_id": desk_cycle_request_id(request),
        "lineage_id": request.lineage_id,
        "plan_id": request.plan.plan_id,
        "instrument_id": request.quote.instrument_id,
        "mode": "paper",
    }


def desk_cycle_request_id(request: DeskCycleRequest) -> str:
    """Return the content identity of every decision-bearing cycle input."""

    if not isinstance(request, DeskCycleRequest):
        raise TypeError("request must be a DeskCycleRequest")
    identity = {
        "command_id": request.command_id,
        "lineage_id": request.lineage_id,
        "plan_id": request.plan.plan_id,
        "bars": _identity_value(request.bars),
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
    if isinstance(value, pd.DataFrame):
        if not value.columns.is_unique or not value.index.is_unique:
            raise ValueError(
                "desk request identity requires unique DataFrame axes"
            )
        if not all(isinstance(column, str) for column in value.columns):
            raise TypeError(
                "desk request identity requires string DataFrame columns"
            )
        digest = hashlib.sha256()
        digest.update(repr(tuple(value.columns)).encode("utf-8"))
        digest.update(
            repr(tuple(str(dtype) for dtype in value.dtypes)).encode("utf-8")
        )
        digest.update(str(value.index.dtype).encode("utf-8"))
        digest.update(
            pd.util.hash_pandas_object(value, index=True).values.tobytes()
        )
        return {
            "schema": "pandas-dataframe-v1",
            "rows": len(value),
            "content_sha256": digest.hexdigest(),
        }
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError(
                "desk request identity requires string mapping keys"
            )
        return {
            key: _identity_value(child)
            for key, child in sorted(value.items())
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


def _require_role_memory(
    context: MemoryContextPack | None, role: AgentMemoryRole
) -> None:
    if context is None:
        return
    if context.authority != "CONTEXT_ONLY" or context.query.role is not role:
        raise ValueError("role received an invalid memory context pack")
    tuple(context.source_event_ids)
