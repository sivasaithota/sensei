"""Production EOD driver for forward-only canonical shadow evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from sensei.data.store import available_symbols, load_prices
from sensei.governance.evidence import DossierOutcome, StageDossierRegistry
from sensei.governance.lifecycle import EvidenceKind, LifecycleStage, StrategyLifecycle
from sensei.operations import OperationalJournal
from sensei.strategy import StrategyPlanCatalog

from .evidence import ImmutableJsonArtifactStore, StageEvidencePublisher
from .market_ingestion import MarketDataIngestionLedger
from .runner import TaskOutcome, TaskOutcomeState
from .scheduling import ScheduledTask
from .shadow import CanonicalShadowRunner, ShadowTrialLedger, ShadowTrialPolicy


class DailyCanonicalShadowSession:
    """Evaluate every SHADOW plan once per new market session."""

    def __init__(
        self,
        *,
        journal: OperationalJournal,
        catalog: StrategyPlanCatalog,
        lifecycle: StrategyLifecycle,
        dossiers: StageDossierRegistry,
        issuer_id: str,
        shadow_trial_producer_id: str,
        artifact_root: Path,
        policy: ShadowTrialPolicy | None = None,
        ingestion_ledger: MarketDataIngestionLedger | None = None,
    ) -> None:
        self._catalog = catalog
        self._lifecycle = lifecycle
        self._ledger = ShadowTrialLedger(journal)
        self._runner = CanonicalShadowRunner(lifecycle=lifecycle, ledger=self._ledger)
        self._policy = policy or ShadowTrialPolicy()
        self._ingestion_ledger = ingestion_ledger
        self._publisher = StageEvidencePublisher(
            journal,
            dossiers,
            ImmutableJsonArtifactStore(artifact_root),
            issuer_id=issuer_id,
            producer_ids_by_kind={EvidenceKind.SHADOW_TRIAL: shadow_trial_producer_id},
        )

    def __call__(self, task: ScheduledTask, now: datetime) -> TaskOutcome:
        records = self._catalog.plans_at_stage(self._lifecycle, LifecycleStage.SHADOW)
        if not records:
            return TaskOutcome(TaskOutcomeState.COMPLETED, ("NO_SHADOW_PLANS",), "no plans require shadow evaluation")
        ingestion = (
            self._ingestion_ledger.for_session(task.trading_date)
            if self._ingestion_ledger is not None
            else None
        )
        symbols = (
            ingestion.eligible_symbols
            if ingestion is not None
            else tuple(sorted(available_symbols()))
        )
        bars = {}
        latest_dates = set()
        for symbol in symbols:
            try:
                frame = load_prices(symbol)
            except (FileNotFoundError, ValueError):
                continue
            bars[symbol] = frame
            latest_dates.add(frame.index[-1].date())
        if (
            not bars
            or len(bars) != len(symbols)
            or len(latest_dates) != 1
            or next(iter(latest_dates)) != task.trading_date
        ):
            return TaskOutcome(TaskOutcomeState.HALTED, ("SHADOW_MARKET_SNAPSHOT_INCOMPLETE",), "shadow universe has no single complete evaluation session")
        evaluation_session = next(iter(latest_dates))
        snapshot_payload = {
            "ingestion_event_id": ingestion.event_id if ingestion else None,
            "ingestion_completeness": ingestion.completeness if ingestion else 1.0,
            "excluded_symbols": list(ingestion.excluded_symbols) if ingestion else [],
            "failed_symbols": list(ingestion.failed_symbols) if ingestion else [],
            "bars": {symbol: {
                "session": frame.index[-1].date().isoformat(),
                "bar": {key: float(frame.iloc[-1][key]) for key in ("open", "high", "low", "close", "volume")},
            }
            for symbol, frame in sorted(bars.items())},
        }
        snapshot_id = "snapshot:" + hashlib.sha256(
            json.dumps(snapshot_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        observed = 0
        promoted_ready = 0
        for record in records:
            started = self._lifecycle.view(record.lineage_id).plans[0].last_record.occurred_at
            if evaluation_session <= started.astimezone(now.tzinfo).date():
                continue
            self._runner.run_session(
                record=record,
                expected_instrument_ids=symbols,
                bars_by_instrument=bars,
                evaluation_session=evaluation_session,
                market_snapshot_id=snapshot_id,
                observed_at=now,
                command_id=f"{task.task_id}:shadow:{record.plan_id}",
            )
            observed += 1
            assessment = self._ledger.assess(
                lineage_id=record.lineage_id,
                plan_id=record.plan_id,
                policy=self._policy,
                no_later_than=now,
            )
            if assessment.passed:
                self._publisher.publish(
                    lineage_id=record.lineage_id,
                    plan_version_id=record.plan_id,
                    evidence_kind=EvidenceKind.SHADOW_TRIAL,
                    outcome=DossierOutcome.PASSED,
                    evidence=assessment.to_artifact(),
                    occurred_at=now,
                )
                promoted_ready += 1
        return TaskOutcome(
            TaskOutcomeState.COMPLETED,
            ("SHADOW_SESSION_COMPLETED",),
            f"shadow observations={observed}; paper-ready evidence={promoted_ready}",
        )


__all__ = ["DailyCanonicalShadowSession"]
