"""Production composition root for one governed scheduled paper session."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from sensei.execution.nse import NseExecutionModel, NseMarketObservation

from sensei.agents.chain import ApprovalChain
from sensei.automation.governed_entry import AuthorizedPlan, CanonicalSignalPlanner
from sensei.automation.runner import TaskOutcome, TaskOutcomeState
from sensei.automation.scheduling import ScheduledTask
from sensei.governance.evidence import StageDossierRegistry
from sensei.governance.lifecycle import (
    AuthorityRole,
    LifecycleStage,
    StrategyLifecycle,
)
from sensei.kernel import (
    BrokerSnapshotAuthority,
    KernelAdmissionAuthority,
    RecordingPaperGateway,
    TradingKernel,
)
from sensei.learning.episodes import TradeEpisodeJournal
from sensei.learning.outcomes import OutcomeLearner
from sensei.operations import (
    ComponentState,
    HmacFactSigner,
    HmacFactVerifier,
    OperationsControlPlane,
)
from sensei.operations.health import OperationsMonitor
from sensei.operations.supervisor import (
    GovernedDeskSupervisor,
    SupervisorComposition,
    SupervisorSessionRequest,
    SupervisorState,
)
from sensei.orchestration import (
    ApprovalChainCommittee,
    CommitteeVerdictAuthority,
    DeskRuntime,
    EarningsReporter,
    ExecutableQuote,
    GovernedAnalyst,
    GovernedPaperCoordinator,
    OperationalSecretary,
    OutcomeCoach,
    PaperTrader,
    RegimeCrowdReader,
    StrategyEvidenceStats,
    StrategyHistorian,
    TradeCommitteeGate,
    TradeIntentFactory,
)
from sensei.portfolio_risk import (
    AccountSnapshotAuthority,
    PortfolioRisk,
    RiskLimits,
    SafetyControl,
    SafetyResetAuthority,
)
from sensei.provenance import ProvenanceCorpus
from sensei.reporting.operations import OperationalReporter
from sensei.risk.rails import RiskConfig, RiskRails
from sensei.runtime.account import PaperAccountProjector
from sensei.runtime.activation import (
    RuntimeSecretStore,
    RuntimeTrustError,
    SurveillanceSourceUnavailable,
    VerifiedSurveillanceSource,
)
from sensei.runtime.session_inputs import (
    ComponentCheckResult,
    PaperSessionInputs,
)
from sensei.strategy import (
    DecisionTraceAuthority,
    StrategyPlanCatalog,
    StrategyPlanEngine,
)


class ProductionPaperSession:
    """Build, own and close the exact governed graph for one scheduler task."""

    def __init__(
        self,
        *,
        journal_path: Path,
        scheduler_config,
        risk_path: Path = Path("config/risk.yaml"),
        playbook_path: Path = Path("data/playbook/current.json"),
        prices_path: Path = Path("data/prices"),
        provenance_path: Path = Path("data/provenance"),
        legacy_baseline=None,
    ) -> None:
        self._journal_path = Path(journal_path)
        self._config = scheduler_config
        self._risk_path = Path(risk_path)
        self._playbook_path = Path(playbook_path)
        self._prices_path = Path(prices_path)
        self._provenance_path = Path(provenance_path)
        self._legacy_baseline = legacy_baseline

    def __call__(self, task: ScheduledTask, now: datetime) -> TaskOutcome:
        secrets = RuntimeSecretStore.load(self._config.runtime_secrets_path)
        surveillance = VerifiedSurveillanceSource(
            self._config.surveillance_path,
            issuer_id="market-surveillance",
            secret=secrets["market-surveillance"],
            maximum_age=timedelta(days=4),
            clock=lambda: now,
        )
        instruments = self._instruments()
        snapshot_complete = bool(instruments) and all(
            surveillance(instrument.split(":")[-1], task.trading_date) is not None
            for instrument in instruments
        )
        if not snapshot_complete:
            raise SurveillanceSourceUnavailable(
                "signed pre-entry surveillance snapshot is missing, stale, or incomplete"
            )
        from sensei.automation.surveillance import require_surveillance_preflight

        require_surveillance_preflight(
            journal_path=self._journal_path,
            snapshot_path=self._config.surveillance_path,
            entry_task=task,
        )

        def compose(journal, gateway):
            composition, _inputs = self._compose(
                journal=journal,
                gateway=gateway,
                secrets=secrets,
                now=now,
                command_id=task.task_id,
            )
            return composition

        with GovernedDeskSupervisor.paper_only_from_gateway_factory(
            journal_path=self._journal_path,
            gateway_factory=lambda journal: RecordingPaperGateway(
                journal,
                execution_model=NseExecutionModel(
                    max_volume_participation_bps=100,
                    base_impact_bps=5,
                ),
                market_observation=lambda instrument_id: (
                    self._execution_observation(instrument_id, now)
                ),
                clock=lambda: now,
            ),
            compose=compose,
            clock=lambda: now,
        ) as supervisor:
            result = supervisor.run_session(
                SupervisorSessionRequest(now=now, command_id=task.task_id)
            )
        if result.state is not SupervisorState.COMPLETED:
            return TaskOutcome(
                TaskOutcomeState.HALTED,
                result.reason_codes or ("GOVERNED_SUPERVISOR_HALTED",),
                "governed paper Supervisor halted the bounded entry session",
            )
        if not result.cycles:
            return TaskOutcome(
                TaskOutcomeState.COMPLETED,
                ("NO_CANONICAL_SIGNAL",),
                "no exact PAPER plan produced an executable entry",
            )
        status = result.cycles[-1].status.value
        return TaskOutcome(
            TaskOutcomeState.COMPLETED,
            ("GOVERNED_" + status,),
            result.cycles[-1].reason,
        )

    def _compose(self, *, journal, gateway, secrets, now, command_id):
        risk_config = RiskConfig.load(self._risk_path)
        limits = _risk_limits(risk_config)
        component_secrets = {
            name: secrets[name]
            for name in ("market-data", "paper-gateway", "reconciliation")
        }
        reconciliation_signer = HmacFactSigner(
            "reconciliation", secrets["reconciliation"]
        )
        reset_authority = SafetyResetAuthority(
            journal,
            owner_verifier=HmacFactVerifier(
                {"owner": _derived_owner_verifier(secrets["desk-supervisor"])}
            ),
            reconciliation_verifier=HmacFactVerifier(
                {"reconciliation": secrets["reconciliation"]}
            ),
            expected_reconciliation_issuer_id="reconciliation",
        )
        safety = SafetyControl(journal, reset_authority=reset_authority)
        control_plane = OperationsControlPlane(
            journal, HmacFactVerifier(component_secrets)
        )
        required_components = {
            name: timedelta(minutes=2) for name in component_secrets
        }
        monitor = OperationsMonitor(
            journal,
            control_plane=control_plane,
            required_components=required_components,
            maximum_readiness_age=timedelta(minutes=2),
            signer=HmacFactSigner(
                "operations-monitor", secrets["operations-monitor"]
            ),
            verifier=HmacFactVerifier(
                {"operations-monitor": secrets["operations-monitor"]}
            ),
            safety_reset_authority=reset_authority,
        )
        account_authority = AccountSnapshotAuthority(
            journal,
            HmacFactVerifier({"paper-account": secrets["paper-account"]}),
            expected_issuer_id="paper-account",
        )
        broker_authority = BrokerSnapshotAuthority(
            journal,
            HmacFactVerifier({"paper-gateway": secrets["paper-gateway"]}),
            expected_issuer_id="paper-gateway",
        )
        admission = KernelAdmissionAuthority(
            journal,
            HmacFactVerifier({"paper-admission": secrets["paper-admission"]}),
        )
        risk = PortfolioRisk(journal, limits)
        supervisor_signer = HmacFactSigner(
            "desk-supervisor", secrets["desk-supervisor"]
        )
        kernel = TradingKernel(
            journal,
            risk,
            safety,
            gateway,
            admission_authority=admission,
            broker_snapshot_authority=broker_authority,
            safety_reset_authority=reset_authority,
            reconciliation_signer=reconciliation_signer,
            entry_authorization_verifier=HmacFactVerifier(
                {"desk-supervisor": secrets["desk-supervisor"]}
            ),
            expected_supervisor_issuer_id="desk-supervisor",
        )
        dossiers = StageDossierRegistry(
            journal,
            trusted_issuer_ids=frozenset({self._config.dossier_issuer_id}),
            trusted_producers_by_kind=self._config.producers_by_kind,
        )
        lifecycle = StrategyLifecycle(
            journal,
            evidence_verifier=dossiers.verify_transition,
            trusted_actor_roles={
                self._config.proposer_id: frozenset({AuthorityRole.PROPOSER}),
                self._config.governor_id: frozenset({AuthorityRole.GOVERNOR}),
            },
        )
        trace_authority = DecisionTraceAuthority(
            journal,
            HmacFactVerifier({"historian": secrets["historian"]}),
        )
        verdict_secrets = {
            name: secrets[name]
            for name in (
                "risk-officer", "devils-advocate", "compliance", "orchestrator"
            )
        }
        verdict_authority = CommitteeVerdictAuthority(
            journal, HmacFactVerifier(verdict_secrets)
        )
        coordinator = GovernedPaperCoordinator(
            journal=journal,
            lifecycle=lifecycle,
            intent_factory=TradeIntentFactory(
                limits, maximum_quote_age=timedelta(minutes=1)
            ),
            episodes=TradeEpisodeJournal(journal),
            kernel=kernel,
            safety=safety,
            committee_gate=TradeCommitteeGate(journal, verdict_authority),
            decision_trace_authority=trace_authority,
            admission_authority=admission,
            admission_signer=HmacFactSigner(
                "paper-admission", secrets["paper-admission"]
            ),
            operations_monitor=monitor,
            provenance=ProvenanceCorpus(journal, self._provenance_path),
        )
        surveillance = VerifiedSurveillanceSource(
            self._config.surveillance_path,
            issuer_id="market-surveillance",
            secret=secrets["market-surveillance"],
            maximum_age=timedelta(days=4),
            clock=lambda: now,
        )
        committee = ApprovalChainCommittee(
            ApprovalChain(RiskRails(risk_config)),
            verdict_authority,
            {
                name: HmacFactSigner(name, secret)
                for name, secret in verdict_secrets.items()
            },
        )
        desk = DeskRuntime(
            journal=journal,
            historian=StrategyHistorian(
                StrategyPlanEngine(),
                trace_authority,
                HmacFactSigner("historian", secrets["historian"]),
            ),
            reporter=EarningsReporter(surveillance=surveillance),
            crowd_reader=RegimeCrowdReader(reader=self._regime),
            analyst=GovernedAnalyst(),
            committee=committee,
            trader=PaperTrader(coordinator, kernel),
            coach=OutcomeCoach(OutcomeLearner(journal)),
            secretary=OperationalSecretary(
                OperationalReporter(journal), timezone=ZoneInfo("Asia/Kolkata")
            ),
        )
        planner = CanonicalSignalPlanner(
            plans=lambda: self._authorized_plans(journal, lifecycle),
            instruments=self._instruments,
            bars=self._bars,
            quote=self._quote,
            average_turnover=self._turnover,
            journal=journal,
        )
        baseline_source = None
        if self._legacy_baseline is not None:
            baseline_source = lambda captured_at, marks: self._legacy_baseline(
                captured_at
            )
        projector = PaperAccountProjector(
            gateway,
            starting_capital_paise=round(risk_config.capital * 100),
            high_water_mark_paise=round(risk_config.capital * 100),
            baseline_snapshot_source=baseline_source,
        )
        checks = {
            "market-data": lambda now: self._market_data_check(surveillance, now),
            "paper-gateway": lambda now: ComponentCheckResult(
                ComponentState.HEALTHY, "durable paper gateway is journal-bound"
            ),
            "reconciliation": lambda now: ComponentCheckResult(
                ComponentState.HEALTHY, "authenticated reconciliation is configured"
            ),
        }
        inputs = PaperSessionInputs(
            journal=journal,
            gateway=gateway,
            account_projector=projector,
            mark_price_source=self._marks,
            account_authority=account_authority,
            account_signer=HmacFactSigner("paper-account", secrets["paper-account"]),
            broker_authority=broker_authority,
            broker_signer=HmacFactSigner("paper-gateway", secrets["paper-gateway"]),
            control_plane=control_plane,
            operations_monitor=monitor,
            safety=safety,
            required_components=required_components,
            component_checks=checks,
            component_signers={
                name: HmacFactSigner(name, secret)
                for name, secret in component_secrets.items()
            },
            maximum_pin_age=timedelta(seconds=30),
        )
        inputs.prepare(
            now=now,
            command_id=command_id,
            cycle_builder=planner.build,
        )
        return SupervisorComposition(
            kernel=kernel,
            cycle_source=inputs,
            desk=desk,
            truth_source=inputs,
            account_verifier=account_authority,
            health_verifier=monitor,
            safety=safety,
            maximum_account_age=timedelta(minutes=2),
            maximum_health_age=timedelta(minutes=2),
            maximum_request_skew=timedelta(seconds=30),
            dispatch_signer=supervisor_signer,
        ), inputs

    def _authorized_plans(self, journal, lifecycle):
        stats = _playbook_stats(self._playbook_path)
        records = StrategyPlanCatalog(journal).plans_at_stage(
            lifecycle, LifecycleStage.PAPER
        )
        missing = tuple(
            record.source_rule_name
            for record in records
            if record.source_rule_name not in stats
        )
        if missing:
            raise RuntimeTrustError(
                "PAPER plans lack exact out-of-sample evidence statistics: "
                + ", ".join(sorted(missing))
            )
        return tuple(
            AuthorizedPlan(record.lineage_id, record.plan, stats[record.source_rule_name])
            for record in records
        )

    def _instruments(self):
        return tuple(sorted(path.stem for path in self._prices_path.glob("*.parquet")))

    def _bars(self, instrument_id):
        symbol = instrument_id.split(":")[-1]
        return pd.read_parquet(self._prices_path / f"{symbol}.parquet")

    def _quote(self, instrument_id, now):
        from sensei.loop.openexec import live_price

        symbol = instrument_id.split(":")[-1]
        price = live_price(symbol)
        if price is None or price <= 0:
            return None
        paise = round(price * 100)
        snapshot = "snapshot:" + hashlib.sha256(
            f"{instrument_id}:{paise}:{now.isoformat()}".encode()
        ).hexdigest()
        return ExecutableQuote(instrument_id, snapshot, paise, now)

    def _execution_observation(self, instrument_id, now):
        symbol = instrument_id.split(":")[-1]
        from sensei.loop.openexec import live_market_snapshot

        snapshot = live_market_snapshot(symbol)
        if snapshot is None or snapshot["last_price"] <= 0:
            raise RuntimeTrustError(
                f"fresh execution observation unavailable for {instrument_id}"
            )
        reference = round(snapshot["last_price"] * 100)
        volume = int(max(0, snapshot["session_volume"]))
        half_spread = max(5, round(reference * 0.0005))
        return NseMarketObservation(
            instrument_id=(
                instrument_id if instrument_id.startswith("NSE:")
                else f"NSE:{instrument_id}"
            ),
            observed_at=now,
            reference_price_paise=reference,
            best_bid_paise=max(1, reference - half_spread),
            best_ask_paise=reference,
            traded_volume=volume,
            lower_circuit_paise=max(1, round(reference * 0.8)),
            upper_circuit_paise=round(reference * 1.2),
            evidence_source="YAHOO_FAST_INFO_SESSION_SNAPSHOT",
            spread_is_estimated=True,
            circuit_is_estimated=True,
        )

    def _turnover(self, instrument_id):
        frame = self._bars(instrument_id)
        if "turnover" in frame:
            return float(frame["turnover"].tail(60).mean())
        return float((frame["close"] * frame["volume"]).tail(60).mean())

    def _marks(self, *, instrument_ids, now):
        marks = {}
        for instrument_id in instrument_ids:
            frame = self._bars(instrument_id)
            marks[instrument_id] = round(float(frame["close"].iloc[-1]) * 100)
        return marks

    def _regime(self):
        from sensei.data.regime import Regime

        above = golden = observed = 0
        for instrument in self._instruments():
            frame = self._bars(instrument)
            if len(frame) < 200:
                continue
            close = frame["close"]
            average_50 = close.rolling(50).mean().iloc[-1]
            average_200 = close.rolling(200).mean().iloc[-1]
            observed += 1
            above += int(close.iloc[-1] > average_200)
            golden += int(average_50 > average_200)
        return Regime(
            None,
            above / observed * 100 if observed else 0,
            golden / observed * 100 if observed else 0,
            observed,
        )

    def _market_data_check(self, surveillance, now):
        instruments = self._instruments()
        if not instruments:
            return ComponentCheckResult(ComponentState.DEGRADED, "no price data")
        expected_session = _previous_trading_session(
            now.date(), self._config.closed_dates
        )
        for instrument in instruments:
            frame = self._bars(instrument)
            if frame.empty or frame.index[-1].date() != expected_session:
                return ComponentCheckResult(
                    ComponentState.DEGRADED,
                    f"price data is not closed through {expected_session.isoformat()}",
                )
            symbol = instrument.split(":")[-1]
            if surveillance(symbol, now.date()) is None:
                return ComponentCheckResult(
                    ComponentState.DEGRADED, "surveillance observation unavailable"
                )
        return ComponentCheckResult(
            ComponentState.HEALTHY, "price and surveillance observations available"
        )


def _risk_limits(config: RiskConfig) -> RiskLimits:
    capital = round(config.capital * 100)
    return RiskLimits(
        max_total_notional_paise=capital,
        max_position_notional_paise=round(
            capital * config.max_position_pct / 100
        ),
        max_risk_per_trade_paise=round(
            capital * config.max_risk_per_trade_pct / 100
        ),
        max_total_risk_paise=round(capital * config.max_drawdown_pct / 100),
        max_open_positions=config.max_open_positions,
        snapshot_max_age=timedelta(minutes=2),
        max_daily_loss_paise=round(capital * config.daily_loss_halt_pct / 100),
        max_weekly_loss_paise=round(capital * config.weekly_loss_halt_pct / 100),
        max_drawdown_bps=round(config.max_drawdown_pct * 100),
    )


def _playbook_stats(path: Path) -> dict[str, StrategyEvidenceStats]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    result = {}
    for item in raw.get("strategies", ()):
        stats = item.get("out_of_sample", {})
        result[str(item["name"])] = StrategyEvidenceStats(
            expectancy_pct=float(stats["expectancy_pct"]),
            hit_rate=float(stats["hit_rate"]),
            trades=int(stats["trades"]),
            detail=dict(stats),
        )
    return result


def _derived_owner_verifier(secret: bytes) -> bytes:
    return hashlib.sha256(b"owner-reset-verifier:" + secret).digest()


def _previous_trading_session(day, closed_dates):
    candidate = day - timedelta(days=1)
    while candidate.weekday() >= 5 or candidate in closed_dates:
        candidate -= timedelta(days=1)
    return candidate


__all__ = ["ProductionPaperSession"]
