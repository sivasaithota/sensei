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
    closed_dates: frozenset[date] = frozenset()
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
            closed_dates=frozenset(
                date.fromisoformat(str(value))
                for value in raw.get("closed_dates", ())
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
    ) -> None:
        self._autopilot = autopilot
        self._paper_session = paper_session

    def handle(self, task: ScheduledTask, *, now: datetime) -> TaskOutcome:
        paper_outcome = (
            self._paper_session(task, now) if self._paper_session is not None else None
        )
        if paper_outcome is not None and paper_outcome.state is TaskOutcomeState.HALTED:
            return paper_outcome
        report = self._autopilot.reconcile(
            now=now,
            command_id=f"scheduler:{task.task_id}:lifecycle",
        )
        if not report.results:
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
        manages_legacy_positions: bool = False,
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
                    self.autopilot, eod_session
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
        eod_session = None
        manages_legacy_positions = False
        if entry_session is None and config.execution_backend == "legacy_paper":
            from .paper_sessions import LegacyPaperSessions

            sessions = LegacyPaperSessions()
            entry_session = sessions.entry
            eod_session = sessions.eod
            manages_legacy_positions = True
        elif config.execution_backend != "disabled":
            raise SchedulerConfigurationError(
                f"unsupported execution_backend: {config.execution_backend}"
            )
        return cls(
            journal=journal,
            config=config,
            entry_session=entry_session,
            eod_session=eod_session,
            manages_legacy_positions=manages_legacy_positions,
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
