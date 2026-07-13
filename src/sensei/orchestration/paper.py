"""Governed, side-effect-free admission into the durable paper kernel."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from sensei.governance.lifecycle import LifecycleStage, StrategyLifecycle
from sensei.kernel import TradingKernel
from sensei.learning.episodes import (
    EpisodeCommand,
    EpisodeEventType,
    TradeEpisode,
    TradeEpisodeJournal,
)
from sensei.operations.health import HealthState, OperationalHealth
from sensei.operations.journal import OperationalJournal
from sensei.portfolio_risk import (
    AccountSnapshot,
    SafetyAction,
    SafetyBlocked,
    SafetyControl,
    TradeIntent,
)
from sensei.strategy import PlanDecisionTrace, StrategyPlan, assess_strategy_conformance

from .intents import (
    ExecutableQuote,
    IntentBuildError,
    IntentBuildResult,
    TradeIntentFactory,
)


class PaperAdmissionRejected(RuntimeError):
    """A governed plan cannot safely enter the paper kernel."""


@dataclass(frozen=True)
class PaperAcceptance:
    intent: TradeIntent
    sizing: IntentBuildResult
    episode: TradeEpisode
    lifecycle_event_id: str
    health_event_id: str


class GovernedPaperCoordinator:
    """The only composition seam from a plan trace to paper intent acceptance.

    Acceptance writes facts but never calls the broker gateway. Dispatch remains
    an explicit ``TradingKernel.run_once`` operation after portfolio reservation.
    """

    def __init__(
        self,
        *,
        journal: OperationalJournal,
        lifecycle: StrategyLifecycle,
        intent_factory: TradeIntentFactory,
        episodes: TradeEpisodeJournal,
        kernel: TradingKernel,
        safety: SafetyControl,
        maximum_health_age: timedelta = timedelta(minutes=2),
    ) -> None:
        if maximum_health_age <= timedelta(0):
            raise ValueError("maximum_health_age must be positive")
        self._journal = journal
        self._lifecycle = lifecycle
        self._intent_factory = intent_factory
        self._episodes = episodes
        self._kernel = kernel
        self._safety = safety
        self._maximum_health_age = maximum_health_age

    def accept(
        self,
        *,
        lineage_id: str,
        plan: StrategyPlan,
        trace: PlanDecisionTrace,
        quote: ExecutableQuote,
        account_snapshot: AccountSnapshot,
        operational_health: OperationalHealth,
        signal_observed_at: datetime,
        now: datetime,
        command_id: str,
    ) -> PaperAcceptance:
        _aware("signal_observed_at", signal_observed_at)
        _aware("now", now)
        if not command_id.strip():
            raise ValueError("command_id is required")
        conformance = assess_strategy_conformance(plan)
        if not conformance.conformant or conformance.plan_id != plan.plan_id:
            raise PaperAdmissionRejected("canonical Strategy Plan is required")

        try:
            lifecycle_view = self._lifecycle.view(lineage_id)
            plan_state = next(
                state
                for state in lifecycle_view.plans
                if state.plan_version_id == plan.plan_id
            )
        except (KeyError, StopIteration) as exc:
            raise PaperAdmissionRejected(
                "exact plan version is absent from the governed lifecycle"
            ) from exc
        if plan_state.stage is not LifecycleStage.PAPER:
            raise PaperAdmissionRejected(
                "exact plan version must be in the paper stage"
            )
        self._validate_health(operational_health, now)
        try:
            self._safety.assert_allowed(SafetyAction.ENTRY)
            sizing = self._intent_factory.build(
                plan=plan,
                trace=trace,
                quote=quote,
                account_snapshot=account_snapshot,
                now=now,
            )
        except (SafetyBlocked, IntentBuildError) as exc:
            raise PaperAdmissionRejected(str(exc)) from exc

        intent = sizing.intent
        suffix = intent.intent_id.removeprefix("intent:")
        episode_id = f"EP-{suffix}"
        command_digest = hashlib.sha256(command_id.encode("utf-8")).hexdigest()
        self._episodes.start(
            episode_id=episode_id,
            strategy_lineage_id=lineage_id,
            plan_version_id=plan.plan_id,
            decision_trace_id=trace.trace_id,
            market_snapshot_id=intent.market_snapshot_id,
            account_snapshot_id=intent.account_snapshot_id,
            intent_id=intent.intent_id,
            instrument_id=intent.instrument_id,
            timeframe="1d",
            planned_entry_price_paise=intent.limit_price_paise,
            planned_exit_price_paise=intent.target_price_paise,
            signal_time=signal_observed_at,
            command_id=f"paper-start:{command_digest}",
        )
        self._episodes.record(
            EpisodeCommand(
                episode_id=episode_id,
                event_type=EpisodeEventType.APPROVAL_RECORDED,
                payload={
                    "approved": True,
                    "authority": "STRATEGY_LIFECYCLE",
                    "lifecycle_event_id": plan_state.last_record.event_id,
                    "health_event_id": operational_health.event_id,
                },
                occurred_at=now,
                command_id=f"paper-approval:{command_digest}",
            )
        )
        self._kernel.accept(intent, occurred_at=now)
        self._episodes.record(
            EpisodeCommand(
                episode_id=episode_id,
                event_type=EpisodeEventType.INTENT_ACCEPTED,
                payload={"intent_id": intent.intent_id},
                occurred_at=now,
                command_id=f"paper-intent:{command_digest}",
            )
        )
        return PaperAcceptance(
            intent=intent,
            sizing=sizing,
            episode=self._episodes.get(episode_id),
            lifecycle_event_id=plan_state.last_record.event_id,
            health_event_id=operational_health.event_id,
        )

    def _validate_health(
        self, health: OperationalHealth, now: datetime
    ) -> None:
        if (
            health.state is not HealthState.HEALTHY
            or not health.new_entries_allowed
        ):
            raise PaperAdmissionRejected("operational health does not allow entries")
        age = now - health.assessed_at
        if age < timedelta(0) or age > self._maximum_health_age:
            raise PaperAdmissionRejected("operational health assessment is stale")
        event = next(
            (
                candidate
                for candidate in self._journal.read_all()
                if candidate.event_id == health.event_id
            ),
            None,
        )
        if (
            event is None
            or event.event_type != "OperationalHealthAssessed"
            or event.payload.get("state") != HealthState.HEALTHY.value
            or event.payload.get("new_entries_allowed") is not True
            or event.occurred_at != health.assessed_at
        ):
            raise PaperAdmissionRejected(
                "operational health must be backed by a durable healthy assessment"
            )


def _aware(label: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
