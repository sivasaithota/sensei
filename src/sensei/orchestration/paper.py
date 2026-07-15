"""Governed, side-effect-free admission into the durable paper kernel."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from sensei.agents.thesis import ApprovalRecord
from sensei.governance.lifecycle import LifecycleStage, StrategyLifecycle
from sensei.kernel import KernelAdmissionAuthority, TradingKernel
from sensei.learning.episodes import (
    EpisodeCommand,
    EpisodeEventType,
    TradeEpisode,
    TradeEpisodeJournal,
)
from sensei.operations.health import HealthState, OperationalHealth, OperationsMonitor
from sensei.operations import HmacFactSigner
from sensei.operations.journal import OperationalJournal
from sensei.portfolio_risk import (
    AccountSnapshot,
    SafetyAction,
    SafetyBlocked,
    SafetyControl,
    TradeIntent,
)
from sensei.provenance import ProvenanceCorpus
from sensei.strategy import (
    DecisionTraceAuthority,
    PlanDecisionTrace,
    StrategyPlan,
    assess_strategy_conformance,
)

from .committee import TradeCommitteeGate
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
    committee_event_id: str
    committee_approval_id: str
    thesis_id: str
    trace_attestation_event_id: str
    admission_event_id: str
    admission_id: str


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
        committee_gate: TradeCommitteeGate,
        decision_trace_authority: DecisionTraceAuthority,
        admission_authority: KernelAdmissionAuthority,
        admission_signer: HmacFactSigner,
        operations_monitor: OperationsMonitor,
        provenance: ProvenanceCorpus,
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
        self._committee_gate = committee_gate
        self._decision_trace_authority = decision_trace_authority
        self._admission_authority = admission_authority
        self._admission_signer = admission_signer
        self._operations_monitor = operations_monitor
        self._provenance = provenance
        self._maximum_health_age = maximum_health_age

    def is_bound_to_kernel_runtime(
        self,
        *,
        journal: OperationalJournal,
        kernel: TradingKernel,
        safety: SafetyControl,
        operations_monitor: OperationsMonitor,
    ) -> bool:
        """Return whether admission targets the exact journal and kernel."""

        return (
            self._kernel is kernel
            and self._safety is safety
            and self._operations_monitor is operations_monitor
            and self.is_bound_to_journal(journal)
        )

    def is_bound_to_journal(self, journal: OperationalJournal) -> bool:
        """Check every durable admission collaborator against one journal."""

        lifecycle = getattr(self, "_lifecycle", None)
        episodes = getattr(self, "_episodes", None)
        kernel = getattr(self, "_kernel", None)
        safety = getattr(self, "_safety", None)
        committee_gate = getattr(self, "_committee_gate", None)
        trace_authority = getattr(self, "_decision_trace_authority", None)
        admission_authority = getattr(self, "_admission_authority", None)
        operations_monitor = getattr(self, "_operations_monitor", None)
        provenance = getattr(self, "_provenance", None)
        return (
            self._journal is journal
            and type(lifecycle) is StrategyLifecycle
            and StrategyLifecycle.is_bound_to_journal(
                lifecycle,
                journal,
            )
            and type(episodes) is TradeEpisodeJournal
            and TradeEpisodeJournal.is_bound_to_journal(
                episodes,
                journal,
            )
            and type(kernel) is TradingKernel
            and type(safety) is SafetyControl
            and TradingKernel.is_bound_to_runtime(
                kernel,
                journal=journal,
                safety=safety,
            )
            and type(committee_gate) is TradeCommitteeGate
            and TradeCommitteeGate.is_bound_to_journal(
                committee_gate,
                journal,
            )
            and type(trace_authority) is DecisionTraceAuthority
            and DecisionTraceAuthority.is_bound_to_journal(
                trace_authority,
                journal,
            )
            and type(admission_authority) is KernelAdmissionAuthority
            and KernelAdmissionAuthority.is_bound_to_journal(
                admission_authority,
                journal,
            )
            and type(operations_monitor) is OperationsMonitor
            and OperationsMonitor.is_bound_to_journal(
                operations_monitor,
                journal,
            )
            and type(provenance) is ProvenanceCorpus
            and ProvenanceCorpus.is_bound_to_journal(
                provenance,
                journal,
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
    ) -> IntentBuildResult:
        """Derive exact thesis numbers without granting admission or dispatch."""

        try:
            return self._intent_factory.build(
                plan=plan,
                trace=trace,
                quote=quote,
                account_snapshot=account_snapshot,
                now=now,
            )
        except IntentBuildError as exc:
            raise PaperAdmissionRejected(str(exc)) from exc

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
        approval_record: ApprovalRecord,
        decision_market_snapshot_id: str,
        trace_attestation_event_id: str,
        verdict_evidence_event_ids: tuple[str, ...],
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
        if not self._decision_trace_authority.verify(
            trace_attestation_event_id,
            trace=trace,
            market_snapshot_id=decision_market_snapshot_id,
            no_later_than=now,
        ):
            raise PaperAdmissionRejected(
                "decision trace requires authenticated market-snapshot evidence"
            )
        self._validate_health(operational_health, now)
        try:
            self._safety.assert_allowed(SafetyAction.ENTRY)
            sizing = self.derive_candidate(
                plan=plan,
                trace=trace,
                quote=quote,
                account_snapshot=account_snapshot,
                now=now,
            )
        except (SafetyBlocked, IntentBuildError) as exc:
            raise PaperAdmissionRejected(str(exc)) from exc

        intent = sizing.intent
        claim_ids = frozenset(plan.source_claim_ids)
        if not claim_ids:
            raise PaperAdmissionRejected(
                "paper admission requires provenance-backed plan claims"
            )
        if any(not self._provenance.has_claim(claim_id) for claim_id in claim_ids):
            raise PaperAdmissionRejected(
                "every plan source claim must exist in the verified provenance corpus"
            )
        command_digest = hashlib.sha256(command_id.encode("utf-8")).hexdigest()
        try:
            committee = self._committee_gate.record(
                approval_record,
                intent=intent,
                lineage_id=lineage_id,
                allowed_claim_ids=claim_ids,
                maximum_holding_sessions=plan.exits.max_hold_sessions.value,
                signal_observed_at=signal_observed_at,
                occurred_at=now,
                command_id=f"paper-committee:{command_digest}",
                verdict_evidence_event_ids=verdict_evidence_event_ids,
            )
        except (TypeError, ValueError, RuntimeError) as exc:
            raise PaperAdmissionRejected(
                f"trade committee approval rejected: {exc}"
            ) from exc

        try:
            admission = self._admission_authority.issue(
                intent,
                lineage_id=lineage_id,
                trace_attestation_event_id=trace_attestation_event_id,
                lifecycle_event_id=plan_state.last_record.event_id,
                health_event_id=operational_health.event_id,
                committee_event_id=committee.event_id,
                committee_approval_id=committee.approval_id,
                verdict_evidence_event_ids=committee.verdict_evidence_event_ids,
                provenance_claim_ids=tuple(sorted(claim_ids)),
                signer=self._admission_signer,
                occurred_at=now,
                command_id=f"paper-admission:{command_digest}",
            )
        except (TypeError, ValueError, RuntimeError) as exc:
            raise PaperAdmissionRejected(
                f"kernel admission authorization rejected: {exc}"
            ) from exc

        suffix = intent.intent_id.removeprefix("intent:")
        episode_id = f"EP-{suffix}"
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
                    "authority": "L1_L4_TRADE_COMMITTEE",
                    "committee_event_id": committee.event_id,
                    "committee_approval_id": committee.approval_id,
                    "thesis_id": committee.thesis_id,
                    "lifecycle_event_id": plan_state.last_record.event_id,
                    "health_event_id": operational_health.event_id,
                    "trace_attestation_event_id": trace_attestation_event_id,
                    "verdict_evidence_event_ids": (
                        committee.verdict_evidence_event_ids
                    ),
                    "admission_event_id": admission.event_id,
                    "admission_id": admission.admission_id,
                },
                occurred_at=now,
                command_id=f"paper-approval:{command_digest}",
            )
        )
        self._kernel.accept(
            intent,
            admission_event_id=admission.event_id,
            occurred_at=now,
        )
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
            committee_event_id=committee.event_id,
            committee_approval_id=committee.approval_id,
            thesis_id=committee.thesis_id,
            trace_attestation_event_id=trace_attestation_event_id,
            admission_event_id=admission.event_id,
            admission_id=admission.admission_id,
        )

    def _validate_health(
        self, health: OperationalHealth, now: datetime
    ) -> None:
        if not self._operations_monitor.verify(health, no_later_than=now):
            raise PaperAdmissionRejected(
                "operational health evidence is not authenticated"
            )
        if (
            health.state is not HealthState.HEALTHY
            or not health.new_entries_allowed
        ):
            raise PaperAdmissionRejected("operational health does not allow entries")
        age = now - health.assessed_at
        if age < timedelta(0) or age > self._maximum_health_age:
            raise PaperAdmissionRejected("operational health assessment is stale")


def _aware(label: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
