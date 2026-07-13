"""Production adapters for the specialized roles coordinated by DeskRuntime."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, tzinfo

from sensei.agents.thesis import ApprovalRecord, PlaybookCitation, TradeThesis
from sensei.data.events import in_no_trade_window
from sensei.data.regime import Regime, compute_regime
from sensei.learning.outcomes import LearningObservation, OutcomeLearner
from sensei.operations import HmacFactSigner
from sensei.reporting.operations import OperationalReporter
from sensei.strategy import (
    DecisionTraceAuthority,
    PlanEvaluationRequest,
    StrategyPlanEngine,
)

from .desk import (
    AnalystBrief,
    AuthenticatedCommitteeDecision,
    CoachReflection,
    CommitteeInputs,
    CommitteeReviewContext,
    EventBrief,
    HistoricalDecision,
    HistoricalRequest,
    MarketMood,
)
from .verdicts import CommitteeVerdictAuthority


@dataclass(frozen=True)
class AnalystJudgment:
    proceed: bool
    narrative: str
    invalidation: str
    decline_reason: str = ""


class StrategyHistorian:
    """Historian: run canonical semantics and attest the exact data snapshot."""

    def __init__(
        self,
        engine: StrategyPlanEngine,
        authority: DecisionTraceAuthority,
        signer: HmacFactSigner,
    ) -> None:
        self._engine = engine
        self._authority = authority
        self._signer = signer

    def evaluate(self, request: HistoricalRequest) -> HistoricalDecision:
        trace = self._engine.evaluate(
            PlanEvaluationRequest(
                plan=request.plan,
                instrument_id=request.instrument_id,
                bars=request.bars,
                evaluation_session=request.evaluation_session,
            )
        )
        evidence = self._authority.record(
            trace,
            market_snapshot_id=request.market_snapshot_id,
            signer=self._signer,
            occurred_at=request.occurred_at,
            command_id=request.command_id,
        )
        return HistoricalDecision(
            trace=trace,
            trace_attestation_event_id=evidence.event_id,
        )


class EarningsReporter:
    """Reporter: earnings window plus verified exchange-surveillance status."""

    def __init__(
        self,
        *,
        event_window: Callable[[str, date], tuple[bool, str]] = in_no_trade_window,
        surveillance: Callable[[str, date], int | None] | None = None,
    ) -> None:
        self._event_window = event_window
        self._surveillance = surveillance or (lambda _symbol, _day: None)

    def report(self, instrument_id: str, *, as_of: datetime) -> EventBrief:
        _aware(as_of)
        symbol = instrument_id.split(":")[-1]
        blocked, event_reason = self._event_window(symbol, as_of.date())
        stage = self._surveillance(symbol, as_of.date())
        if stage is None:
            blocked = True
            reason = f"{event_reason}; surveillance status unknown"
        elif isinstance(stage, bool) or not isinstance(stage, int) or stage < 0:
            blocked = True
            reason = f"{event_reason}; surveillance status invalid"
            stage = None
        else:
            reason = f"{event_reason}; surveillance stage {stage}"
        return EventBrief(
            instrument_id=instrument_id,
            blocked=blocked,
            reason=reason,
            surveillance_stage=stage,
        )


class RegimeCrowdReader:
    """Crowd Reader: turn deterministic breadth/VIX facts into bounded context."""

    def __init__(self, reader: Callable[[], Regime] = compute_regime) -> None:
        self._reader = reader

    def read(self, *, as_of: datetime) -> MarketMood:
        _aware(as_of)
        regime = self._reader()
        confidence = min(1.0, regime.n_symbols / 100) if regime.n_symbols else 0.0
        return MarketMood(
            label=regime.label,
            summary=regime.summary(),
            confidence=confidence,
        )


class GovernedAnalyst:
    """Analyst: explain a candidate without changing its executable numbers."""

    def __init__(
        self,
        judgment: Callable[[AnalystBrief], AnalystJudgment] | None = None,
    ) -> None:
        self._judgment = judgment or self._default_judgment

    def draft(self, brief: AnalystBrief) -> TradeThesis | str:
        if brief.events.blocked:
            return brief.events.reason
        if not brief.plan.source_claim_ids:
            return "plan has no verified provenance claims"
        judgment = self._judgment(brief)
        if not judgment.proceed:
            return judgment.decline_reason or "analyst declined without reason"
        if not judgment.narrative.strip() or not judgment.invalidation.strip():
            raise ValueError(
                "a proceeding analyst judgment needs narrative and invalidation"
            )
        intent = brief.candidate.intent
        stats = brief.strategy_stats
        detail = dict(stats.detail or {})
        return TradeThesis(
            id="TH-" + intent.intent_id.removeprefix("intent:")[:20].upper(),
            created_at=brief.created_at,
            symbol=intent.instrument_id,
            direction="BUY",
            entry_zone_low=intent.limit_price_paise / 100,
            entry_zone_high=intent.limit_price_paise / 100,
            quantity=intent.quantity,
            stop_loss=intent.stop_price_paise / 100,
            targets=[intent.target_price_paise / 100],
            time_horizon_days=brief.plan.exits.max_hold_sessions.value,
            invalidation=judgment.invalidation.strip(),
            evidence=list(brief.plan.source_claim_ids),
            playbook_citations=[
                PlaybookCitation(
                    strategy=brief.plan.plan_id,
                    oos_expectancy_pct=stats.expectancy_pct,
                    oos_hit_rate=stats.hit_rate,
                    oos_trades=stats.trades,
                    oos_detail=detail,
                )
            ],
            narrative=judgment.narrative.strip(),
        )

    @staticmethod
    def _default_judgment(brief: AnalystBrief) -> AnalystJudgment:
        intent = brief.candidate.intent
        return AnalystJudgment(
            proceed=True,
            narrative=(
                f"The exact governed plan generated a long entry for "
                f"{intent.instrument_id}. {brief.events.reason}. "
                f"Crowd context: {brief.mood.summary}"
            ),
            invalidation=(
                f"The thesis is invalid at the governed stop "
                f"₹{intent.stop_price_paise / 100:.2f} or when the exact plan "
                "no longer applies."
            ),
        )


class ApprovalChainCommittee:
    """Committee: invoke the existing L1-L4 chain and attest each producer."""

    def __init__(
        self,
        chain,
        authority: CommitteeVerdictAuthority,
        signers: Mapping[str, HmacFactSigner],
    ) -> None:
        self._chain = chain
        self._authority = authority
        self._signers = dict(signers)

    def review(
        self,
        thesis: TradeThesis,
        context: object,
        *,
        now: datetime,
        command_id: str,
    ) -> AuthenticatedCommitteeDecision:
        if not isinstance(context, CommitteeReviewContext):
            raise TypeError("committee requires a CommitteeReviewContext")
        if not isinstance(context.inputs, CommitteeInputs):
            raise TypeError("committee context requires CommitteeInputs")
        _aware(now)
        if hasattr(self._chain, "regime_context"):
            self._chain.regime_context = context.mood.summary
        approval = self._chain.run(
            thesis,
            context.inputs.portfolio_state,
            turnover=context.inputs.average_daily_turnover_inr,
            surveillance_stage=context.events.surveillance_stage,
        )
        if approval.thesis != thesis:
            raise ValueError("approval chain returned a different thesis")
        normalized = ApprovalRecord(
            thesis=approval.thesis,
            verdicts=[
                verdict.model_copy(update={"checked_at": now})
                for verdict in approval.verdicts
            ],
        )
        evidence: list[str] = []
        for verdict in normalized.verdicts:
            signer = self._signers.get(verdict.agent)
            if signer is None:
                raise ValueError(f"missing signer for committee role {verdict.agent}")
            evidence.append(
                self._authority.record(
                    normalized.thesis,
                    verdict,
                    signer=signer,
                    occurred_at=now,
                    command_id=f"{command_id}:{verdict.level}",
                ).event_id
            )
        return AuthenticatedCommitteeDecision(
            approval=normalized,
            verdict_evidence_event_ids=tuple(evidence),
        )


class OutcomeCoach:
    """Coach: record scoped observations and propose recurrence-gated research."""

    def __init__(self, learner: OutcomeLearner) -> None:
        self._learner = learner

    def reflect(
        self,
        observations: tuple[LearningObservation, ...],
        *,
        now: datetime,
        command_id: str,
    ) -> CoachReflection:
        _aware(now)
        scopes = {}
        for observation in observations:
            if observation.occurred_at > now:
                raise ValueError("learning observation cannot be from the future")
            self._learner.record(
                observation,
                command_id=(
                    "coach-observation:"
                    + _digest(
                        f"{command_id}:{observation.episode_id}:"
                        f"{observation.scope.scope_id}"
                    )
                ),
            )
            scopes[observation.scope.scope_id] = observation.scope
        discovered = self._learner.record_pending_reviews(
            no_later_than=now,
            command_id=f"{command_id}:discover",
        )
        for observation in discovered:
            scopes[observation.scope.scope_id] = observation.scope
        hypotheses: list[str] = []
        for scope_id, scope in sorted(scopes.items()):
            hypothesis = self._learner.propose(
                scope,
                command_id="coach-hypothesis:" + _digest(f"{command_id}:{scope_id}"),
                now=now,
            )
            if hypothesis is not None:
                hypotheses.append(hypothesis.hypothesis_id)
        return CoachReflection(
            observations_recorded=len(observations) + len(discovered),
            hypotheses_proposed=tuple(hypotheses),
        )


class OperationalSecretary:
    """Secretary: produce a read-only journal projection for the owner."""

    def __init__(
        self,
        reporter: OperationalReporter,
        *,
        timezone: tzinfo,
    ) -> None:
        self._reporter = reporter
        self._timezone = timezone

    def report(self, day: date):
        return self._reporter.daily(day, tz=self._timezone)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("role timestamps must be timezone-aware")
