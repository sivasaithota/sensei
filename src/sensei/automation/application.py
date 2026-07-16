"""Default scheduler composition for unattended governed paper operations.

This composition deliberately exposes a safe entry seam.  Until a complete
paper Desk composition is supplied, entry tasks remain durable HALTED results;
the scheduler continues lifecycle, shadow, reporting, and recovery work and
never falls back to the legacy scanner.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Mapping

from sensei.governance.evidence import StageDossierRegistry
from sensei.governance.lifecycle import (
    Authority,
    AuthorityRole,
    EvidenceKind,
    LifecycleStage,
    StrategyLifecycle,
)
from sensei.operations import OperationalJournal
from sensei.portfolio_risk import SafetyControl
from sensei.strategy import StrategyPlanCatalog

from .autopilot import (
    ExistingDossierEvidenceProvider,
    StrategyAutopilot,
    StrategyAutomationState,
)
from .runner import (
    SchedulerRunResult,
    SchedulerTaskHandler,
    TaskOutcome,
    TaskOutcomeState,
    UnattendedSchedulerRunner,
)
from .scheduling import SchedulerTaskKind, SwingSessionPolicy, ScheduledTask
from .shadow import ShadowTrialPolicy


DEFAULT_PRODUCER_IDS = {
    kind: (f"producer:{kind.value}",) for kind in EvidenceKind
}


@dataclass(frozen=True)
class SchedulerApplicationConfig:
    proposer_id: str = "strategy-proposer"
    governor_id: str = "strategy-governor"
    dossier_issuer_id: str = "governance-dossier-service"
    producers_by_kind: Mapping[EvidenceKind, frozenset[str]] = field(
        default_factory=lambda: {
            kind: frozenset(values)
            for kind, values in DEFAULT_PRODUCER_IDS.items()
        }
    )
    legacy_positions_path: Path = Path("data/paper/positions.json")
    runtime_secrets_path: Path = Path("data/runtime-secrets.json")
    surveillance_path: Path = Path("data/surveillance.json")
    risk_path: Path = Path("config/risk.yaml")
    playbook_path: Path = Path("data/playbook/current.json")
    prices_path: Path = Path("data/prices")
    provenance_path: Path = Path("data/provenance")
    closed_dates: frozenset[date] = frozenset()
    shadow_trial: ShadowTrialPolicy = field(default_factory=ShadowTrialPolicy)
    require_adopted_oos_evidence: bool = True
    execution_backend: str = "disabled"

    @classmethod
    def from_json(cls, path: Path | None) -> "SchedulerApplicationConfig":
        if path is None:
            return cls(
                producers_by_kind={
                    kind: frozenset(values)
                    for kind, values in DEFAULT_PRODUCER_IDS.items()
                }
            )
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("scheduler config must be a JSON object")
        producers = {
            kind: frozenset(
                str(value)
                for value in raw.get("producers", {}).get(kind.value, values)
            )
            for kind, values in DEFAULT_PRODUCER_IDS.items()
        }
        shadow_raw = raw.get("shadow_trial", {})
        if not isinstance(shadow_raw, dict):
            raise ValueError("shadow_trial must be a JSON object")
        if shadow_raw.get("require_adopted_oos_evidence", True) is not True:
            raise ValueError("adopted OOS evidence cannot be disabled")
        return cls(
            proposer_id=str(raw.get("proposer_id", cls.proposer_id)),
            governor_id=str(raw.get("governor_id", cls.governor_id)),
            dossier_issuer_id=str(
                raw.get("dossier_issuer_id", cls.dossier_issuer_id)
            ),
            producers_by_kind=producers,
            legacy_positions_path=Path(
                raw.get("legacy_positions_path", str(cls.legacy_positions_path))
            ),
            runtime_secrets_path=Path(
                raw.get("runtime_secrets_path", str(cls.runtime_secrets_path))
            ),
            surveillance_path=Path(
                raw.get("surveillance_path", str(cls.surveillance_path))
            ),
            risk_path=Path(raw.get("risk_path", str(cls.risk_path))),
            playbook_path=Path(raw.get("playbook_path", str(cls.playbook_path))),
            prices_path=Path(raw.get("prices_path", str(cls.prices_path))),
            provenance_path=Path(
                raw.get("provenance_path", str(cls.provenance_path))
            ),
            closed_dates=frozenset(
                date.fromisoformat(str(value))
                for value in raw.get("closed_dates", ())
            ),
            shadow_trial=ShadowTrialPolicy(
                minimum_sessions=int(shadow_raw.get("minimum_sessions", 5)),
                minimum_signals=int(shadow_raw.get("minimum_signals", 0)),
                minimum_signal_instruments=int(
                    shadow_raw.get("minimum_signal_instruments", 0)
                ),
                minimum_data_completeness=float(
                    shadow_raw.get("minimum_data_completeness", 0.99)
                ),
                require_zero_errors=shadow_raw.get("require_zero_errors", True),
            ),
            require_adopted_oos_evidence=shadow_raw.get(
                "require_adopted_oos_evidence", True
            ),
            execution_backend=str(raw.get("execution_backend", "disabled")),
        )


class SchedulerConfigurationError(RuntimeError):
    """The unattended scheduler cannot be safely composed."""


class _LifecycleMaintenanceHandler:
    def __init__(
        self,
        autopilot: StrategyAutopilot,
        paper_session: Callable[[ScheduledTask, datetime], TaskOutcome] | None = None,
        shadow_session: Callable[[ScheduledTask, datetime], TaskOutcome] | None = None,
        market_ingestion: Callable[[ScheduledTask, datetime], TaskOutcome] | None = None,
    ) -> None:
        self._autopilot = autopilot
        self._paper_session = paper_session
        self._shadow_session = shadow_session
        self._market_ingestion = market_ingestion

    def handle(self, task: ScheduledTask, *, now: datetime) -> TaskOutcome:
        ingestion_outcome = (
            self._market_ingestion(task, now)
            if self._market_ingestion is not None
            else None
        )
        if (
            ingestion_outcome is not None
            and ingestion_outcome.state is TaskOutcomeState.HALTED
        ):
            return ingestion_outcome
        shadow_outcome = (
            self._shadow_session(task, now) if self._shadow_session is not None else None
        )
        if shadow_outcome is not None and shadow_outcome.state is TaskOutcomeState.HALTED:
            return shadow_outcome
        report = self._autopilot.reconcile(
            now=now,
            command_id=f"scheduler:{task.task_id}:lifecycle",
        )
        if not report.results:
            paper_outcome = (
                self._paper_session(task, now)
                if self._paper_session is not None else None
            )
            return paper_outcome or TaskOutcome(
                TaskOutcomeState.COMPLETED, ("NO_CANONICAL_PLANS",),
                "lifecycle checked; no immutable plans are registered")
        failed = tuple(
            result
            for result in report.results
            if result.state is StrategyAutomationState.EVIDENCE_FAILED
        )
        if failed:
            return TaskOutcome(
                TaskOutcomeState.HALTED,
                tuple(
                    sorted(
                        {
                            reason
                            for result in failed
                            for reason in result.reason_codes
                        }
                    )
                ),
                "one or more strategy evidence checks failed",
            )
        waiting = sum(
            result.state is StrategyAutomationState.WAITING_EVIDENCE
            for result in report.results
        )
        reason = "LIFECYCLE_RECONCILED" if not waiting else "LIFECYCLE_WAITING_EVIDENCE"
        paper_outcome = (
            self._paper_session(task, now) if self._paper_session is not None else None
        )
        if paper_outcome is not None:
            return paper_outcome
        return TaskOutcome(
            TaskOutcomeState.COMPLETED,
            (reason,),
            f"checked {len(report.results)} plan(s); {waiting} waiting for evidence",
        )


class _EntryPreflightHandler:
    def __init__(
        self,
        *,
        journal: OperationalJournal,
        catalog: StrategyPlanCatalog,
        lifecycle: StrategyLifecycle,
        autopilot: StrategyAutopilot,
        legacy_positions_path: Path,
        entry_session: Callable[[ScheduledTask, datetime], TaskOutcome] | None,
        manages_legacy_positions: bool = False,
    ) -> None:
        self._journal = journal
        self._catalog = catalog
        self._lifecycle = lifecycle
        self._autopilot = autopilot
        self._legacy_positions_path = legacy_positions_path
        self._entry_session = entry_session
        self._manages_legacy_positions = manages_legacy_positions

    def handle(self, task: ScheduledTask, *, now: datetime) -> TaskOutcome:
        safety = SafetyControl(self._journal).state()
        if safety.latched:
            return TaskOutcome(
                TaskOutcomeState.HALTED,
                tuple(sorted({reason.reason_code for reason in safety.reasons}))
                or ("SAFETY_LATCHED",),
                "new entries remain blocked by the durable safety state",
            )
        if (not self._manages_legacy_positions
                and _legacy_positions_exist(self._legacy_positions_path)):
            return TaskOutcome(
                TaskOutcomeState.HALTED,
                ("LEGACY_EXPOSURE_UNRESOLVED",),
                "legacy paper positions require an explicit adoption or closure workflow",
            )
        if self._entry_session is not None:
            return self._entry_session(task, now)
        report = self._autopilot.reconcile(
            now=now,
            command_id=f"scheduler:{task.task_id}:entry-preflight",
        )
        if not report.paper_plan_ids:
            return TaskOutcome(
                TaskOutcomeState.HALTED,
                ("NO_AUTHORIZED_PLANS",),
                "no exact Strategy Plan is currently at PAPER",
            )
        return TaskOutcome(
            TaskOutcomeState.HALTED,
            ("GOVERNED_PAPER_RUNTIME_NOT_CONFIGURED",),
            "PAPER plans exist but no production Desk composition was supplied",
        )


class GovernedSchedulerApplication:
    """Open the durable scheduler and its fail-closed default handlers."""

    def __init__(
        self,
        *,
        journal: OperationalJournal,
        config: SchedulerApplicationConfig,
        entry_session: Callable[[ScheduledTask, datetime], TaskOutcome] | None = None,
        eod_session: Callable[[ScheduledTask, datetime], TaskOutcome] | None = None,
        shadow_session: Callable[[ScheduledTask, datetime], TaskOutcome] | None = None,
        manages_legacy_positions: bool = False,
        journal_path: Path | None = None,
    ) -> None:
        self.journal = journal
        self.config = config
        self.catalog = StrategyPlanCatalog(journal)
        self.dossiers = StageDossierRegistry(
            journal,
            trusted_issuer_ids=frozenset({config.dossier_issuer_id}),
            trusted_producers_by_kind=config.producers_by_kind,
        )
        self.lifecycle = StrategyLifecycle(
            journal,
            evidence_verifier=self.dossiers.verify_transition,
            trusted_actor_roles={
                config.proposer_id: frozenset({AuthorityRole.PROPOSER}),
                config.governor_id: frozenset({AuthorityRole.GOVERNOR}),
            },
        )
        provider = ExistingDossierEvidenceProvider(journal, self.dossiers)
        self.autopilot = StrategyAutopilot(
            catalog=self.catalog,
            lifecycle=self.lifecycle,
            evidence_provider=provider,
            proposer=Authority(config.proposer_id, AuthorityRole.PROPOSER),
            governor=Authority(config.governor_id, AuthorityRole.GOVERNOR),
        )
        market_ingestion = None
        if entry_session is None and config.execution_backend in {
            "legacy_paper", "governed_paper"
        }:
            from .paper_sessions import LegacyPaperSessions
            from .migration import adopt_legacy_positions
            from sensei.data.store import load_prices
            from sensei.runtime import LegacyPositionAdoptionRegistry

            def reconcile_positions(now: datetime):
                if not config.legacy_positions_path.is_file():
                    return None
                positions = adopt_legacy_positions(
                    journal,
                    positions_path=config.legacy_positions_path,
                    occurred_at=now,
                )
                marks = {
                    item.symbol: round(
                        float(load_prices(item.symbol)["close"].iloc[-1]) * 100
                    )
                    for item in positions
                }
                return LegacyPositionAdoptionRegistry(
                    journal, positions_path=config.legacy_positions_path
                ).reconcile(
                    mark_prices_paise=marks,
                    captured_at=now,
                    command_id=f"scheduler-position-reconciliation:{now.isoformat()}",
                )

            sessions = LegacyPaperSessions(
                reconcile_positions=reconcile_positions,
            )
            eod_session = sessions.eod
            manages_legacy_positions = True
            if config.execution_backend == "legacy_paper":
                entry_session = sessions.entry
            elif journal_path is not None:
                from sensei.runtime.production import ProductionPaperSession

                def legacy_baseline(captured_at: datetime):
                    truth = reconcile_positions(captured_at)
                    return truth.account_snapshot if truth is not None else None

                entry_session = ProductionPaperSession(
                    journal_path=journal_path,
                    scheduler_config=config,
                    risk_path=config.risk_path,
                    playbook_path=config.playbook_path,
                    prices_path=config.prices_path,
                    provenance_path=config.provenance_path,
                    legacy_baseline=(
                        legacy_baseline
                        if config.legacy_positions_path.is_file()
                        else None
                    ),
                )
            from .shadow_session import DailyCanonicalShadowSession

            from .market_ingestion import (
                MarketDataIngestionLedger,
                MarketDataIngestionSession,
            )

            shadow_session = DailyCanonicalShadowSession(
                journal=journal,
                catalog=self.catalog,
                lifecycle=self.lifecycle,
                dossiers=self.dossiers,
                issuer_id=config.dossier_issuer_id,
                shadow_trial_producer_id=next(
                    iter(config.producers_by_kind[EvidenceKind.SHADOW_TRIAL])
                ),
                artifact_root=Path("data/governance-artifacts"),
                policy=config.shadow_trial,
                playbook_path=config.playbook_path,
                ingestion_ledger=MarketDataIngestionLedger(journal),
            )
            from sensei.data.store import (
                download_symbol,
                load_prices as load_ingestion_prices,
                load_universe,
            )

            market_ingestion = MarketDataIngestionSession(
                journal=journal,
                universe=lambda: tuple(
                    str(value) for value in load_universe()["symbol"]
                ),
                refresh=download_symbol,
                existing=load_ingestion_prices,
            )
        self.runner = UnattendedSchedulerRunner(
            journal=journal,
            policy=SwingSessionPolicy(closed_dates=config.closed_dates),
            handlers={
                SchedulerTaskKind.ENTRY_SESSION: _EntryPreflightHandler(
                    journal=journal,
                    catalog=self.catalog,
                    lifecycle=self.lifecycle,
                    autopilot=self.autopilot,
                    legacy_positions_path=config.legacy_positions_path,
                    entry_session=entry_session,
                    manages_legacy_positions=manages_legacy_positions,
                ),
                SchedulerTaskKind.END_OF_DAY_SESSION: _LifecycleMaintenanceHandler(
                    self.autopilot,
                    eod_session,
                    shadow_session,
                    market_ingestion if config.execution_backend == "governed_paper" else None,
                ),
            },
        )

    @classmethod
    def open(
        cls,
        journal_path: Path,
        *,
        config_path: Path | None = None,
        entry_session: Callable[[ScheduledTask, datetime], TaskOutcome] | None = None,
    ) -> "GovernedSchedulerApplication":
        path = Path(journal_path)
        if not path.is_file():
            raise SchedulerConfigurationError(f"governed journal does not exist: {path}")
        journal = OperationalJournal(path)
        if not journal.verify().ok:
            raise SchedulerConfigurationError("governed journal failed integrity verification")
        config = SchedulerApplicationConfig.from_json(config_path)
        if config.execution_backend not in {
            "disabled", "legacy_paper", "governed_paper"
        }:
            raise SchedulerConfigurationError(
                f"unsupported execution_backend: {config.execution_backend}"
            )
        return cls(
            journal=journal,
            config=config,
            entry_session=entry_session,
            journal_path=path,
        )

    def run_once(self, now: datetime) -> SchedulerRunResult:
        return self.runner.run_once(now)


def _legacy_positions_exist(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False
    if not isinstance(payload, Mapping):
        return False
    positions = payload.get("positions")
    return isinstance(positions, list) and bool(positions)
