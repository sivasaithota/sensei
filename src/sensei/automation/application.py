"""Default scheduler composition for unattended governed paper operations.

This composition deliberately exposes a safe entry seam.  Until a complete
paper Desk composition is supplied, entry tasks remain durable HALTED results;
the scheduler continues lifecycle, shadow, reporting, and recovery work and
never falls back to the legacy scanner.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
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
    news_snapshot_path: Path = Path("data/news-risk.json")
    news_secret_path: Path = Path("data/news-risk-secret")
    news_feeds: Mapping[str, str] = field(default_factory=lambda: {
        "FED": "https://www.federalreserve.gov/feeds/press_all.xml",
        "ECB": "https://www.ecb.europa.eu/rss/press.html",
        "BOE": "https://www.bankofengland.co.uk/rss/news",
        "PIB_INDIA": "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3",
        "RBI_RELEASES": "https://rbi.org.in/pressreleases_rss.xml",
        "RBI_NOTIFICATIONS": "https://rbi.org.in/notifications_rss.xml",
        "GOOGLE_NEWS_RISK": (
            "https://news.google.com/rss/search?q=war+OR+sanctions+OR+"
            "market+closure+OR+capital+controls+when:1d&hl=en-IN&gl=IN&ceid=IN:en"
        ),
        "GOOGLE_NEWS_NSE_SEBI": (
            "https://news.google.com/rss/search?q=(site:nseindia.com+OR+"
            "site:sebi.gov.in)+(trading+suspension+OR+accounting+fraud+OR+"
            "insolvency+OR+bankruptcy+OR+SEBI+order+OR+NSE+circular)+"
            "when:1d&hl=en-IN&gl=IN&ceid=IN:en"
        ),
    })
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
        runtime_secrets_path = Path(
            raw.get("runtime_secrets_path", str(cls.runtime_secrets_path))
        )
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
            runtime_secrets_path=runtime_secrets_path,
            surveillance_path=Path(
                raw.get("surveillance_path", str(cls.surveillance_path))
            ),
            news_snapshot_path=Path(
                raw.get(
                    "news_snapshot_path",
                    str(runtime_secrets_path.parent / "news-risk.json"),
                )
            ),
            news_secret_path=Path(
                raw.get(
                    "news_secret_path",
                    str(runtime_secrets_path.parent / "news-risk-secret"),
                )
            ),
            news_feeds={
                str(source): str(url)
                for source, url in raw.get("news_feeds", cls().news_feeds).items()
            },
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
        # Existing exposure is protect-first work. Broad research ingestion and
        # lifecycle maintenance may halt afterward, but can never suppress exits.
        paper_outcome = (
            self._paper_session(task, now) if self._paper_session is not None else None
        )
        if paper_outcome is not None and paper_outcome.state is TaskOutcomeState.HALTED:
            return paper_outcome
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
            from .paper_sessions import LegacyPaperSessions, refresh_held_position_bars
            from .migration import adopt_legacy_positions
            from sensei.data.store import (
                download_symbol,
                download_symbols,
                load_prices,
                load_universe,
            )
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

            def refresh_held_positions(trading_date: date) -> bool:
                return refresh_held_position_bars(
                    positions_path=config.legacy_positions_path,
                    session=trading_date,
                    refresh_batch=download_symbols,
                )

            sessions = LegacyPaperSessions(
                reconcile_positions=reconcile_positions,
                refresh_held_positions=refresh_held_positions,
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
            market_ingestion = MarketDataIngestionSession(
                journal=journal,
                universe=lambda: tuple(
                    str(value) for value in load_universe()["symbol"]
                ),
                refresh=download_symbol,
                refresh_batch=download_symbols,
                existing=load_prices,
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
        # Safety work always runs first. News refresh may fail closed for the
        # next entry, but can never delay or suppress exits/EOD maintenance.
        result = self.runner.run_once(now)
        try:
            self._refresh_news_if_due(now)
        except Exception as exc:
            self._record_news_refresh_failure(now, exc)
        return result

    def _record_news_refresh_failure(self, now: datetime, error: Exception) -> None:
        from sensei.data.news import record_news_refresh_failure

        record_news_refresh_failure(
            self.journal, occurred_at=now, error=error,
        )

    def _refresh_news_if_due(self, now: datetime) -> None:
        if self.config.execution_backend != "governed_paper":
            return
        from sensei.data.news import (
            NewsRiskBook,
            NewsSecretStore,
            RssNewsRefresher,
        )

        secret = NewsSecretStore.load_or_create(self.config.news_secret_path)
        book = NewsRiskBook(self.config.news_snapshot_path, secret=secret)
        try:
            latest = book.latest()
        except ValueError:
            latest = None
        if latest is not None and timedelta(0) <= now - latest.observed_at < timedelta(
            minutes=30
        ):
            return
        RssNewsRefresher(
            book=book,
            issuer_id="market-news",
            secret=secret,
            journal=self.journal,
        ).refresh(
            feeds=dict(self.config.news_feeds),
            known_instruments=tuple(
                f"NSE:{path.stem}"
                for path in self.config.prices_path.glob("*.parquet")
            ),
            observed_at=now,
        )


def _legacy_positions_exist(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False
    if not isinstance(payload, Mapping):
        return False
    positions = payload.get("positions")
    return isinstance(positions, list) and bool(positions)
