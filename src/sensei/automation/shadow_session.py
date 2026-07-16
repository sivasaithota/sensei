"""Production EOD driver for forward-only canonical shadow evidence."""

from __future__ import annotations

import hashlib
import json
import math
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


class AdoptedOosEvidenceCatalog:
    """Resolve threshold-bound historical evidence for one exact strategy name."""

    MINIMUM_TRADES = 30
    MINIMUM_EXPECTANCY_PCT = 0.30
    MINIMUM_HIT_RATE = 0.35
    MINIMUM_UNIVERSE_SIZE = 10

    def __init__(self, playbook_path: Path) -> None:
        self._path = Path(playbook_path)

    def for_strategy(self, strategy_name: str) -> dict[str, object] | None:
        try:
            content = self._path.read_bytes()
            playbook = json.loads(content.decode("utf-8"))
            thresholds = playbook["thresholds"]
            strategies = playbook["strategies"]
            universe_size = int(playbook["universe_size"])
            minimum_trades = int(thresholds["min_trades_oos"])
            minimum_expectancy = float(thresholds["min_expectancy_pct"])
            minimum_hit_rate = float(thresholds["min_hit_rate"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if (
            universe_size < self.MINIMUM_UNIVERSE_SIZE
            or minimum_trades < self.MINIMUM_TRADES
            or not math.isfinite(minimum_expectancy)
            or minimum_expectancy < self.MINIMUM_EXPECTANCY_PCT
            or not math.isfinite(minimum_hit_rate)
            or minimum_hit_rate < self.MINIMUM_HIT_RATE
        ):
            return None
        for item in strategies if isinstance(strategies, list) else ():
            if not isinstance(item, dict) or item.get("name") != strategy_name:
                continue
            stats = item.get("out_of_sample")
            if not item.get("adopted") or not isinstance(stats, dict):
                return None
            try:
                trades = int(stats["trades"])
                expectancy = float(stats["expectancy_pct"])
                hit_rate = float(stats["hit_rate"])
                satisfied = (
                    trades >= minimum_trades
                    and math.isfinite(expectancy)
                    and expectancy >= minimum_expectancy
                    and math.isfinite(hit_rate)
                    and hit_rate >= minimum_hit_rate
                )
            except (KeyError, TypeError, ValueError):
                return None
            if not satisfied:
                return None
            return {
                "evidence_type": "adopted_walk_forward_out_of_sample",
                "playbook_content_id": "sha256:"
                + hashlib.sha256(content).hexdigest(),
                "playbook_version": str(playbook.get("version", "unknown")),
                "strategy_name": strategy_name,
                "universe_size": universe_size,
                "out_of_sample": dict(stats),
                "thresholds": dict(thresholds),
                "thresholds_satisfied": True,
            }
        return None


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
        playbook_path: Path = Path("data/playbook/current.json"),
        ingestion_ledger: MarketDataIngestionLedger | None = None,
    ) -> None:
        self._catalog = catalog
        self._lifecycle = lifecycle
        self._ledger = ShadowTrialLedger(journal)
        self._runner = CanonicalShadowRunner(lifecycle=lifecycle, ledger=self._ledger)
        self._policy = policy or ShadowTrialPolicy()
        self._historical_evidence = AdoptedOosEvidenceCatalog(playbook_path)
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
        historical_unready = 0
        for record in records:
            historical = self._historical_evidence.for_strategy(
                record.source_rule_name
            )
            if historical is None:
                historical_unready += 1
                continue
            self._ledger.register_policy(
                lineage_id=record.lineage_id,
                plan_id=record.plan_id,
                policy=self._policy,
                historical_oos=historical,
                occurred_at=now,
                command_id=f"{task.task_id}:shadow-policy:{record.plan_id}",
            )
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
                evidence = assessment.to_artifact()
                evidence.update(
                    {
                        "assessment_type": "accelerated_paper_readiness",
                        "evidence_model": (
                            "adopted historical OOS coverage plus forward operational shadow"
                        ),
                        "historical_oos": historical,
                    }
                )
                self._publisher.publish(
                    lineage_id=record.lineage_id,
                    plan_version_id=record.plan_id,
                    evidence_kind=EvidenceKind.SHADOW_TRIAL,
                    outcome=DossierOutcome.PASSED,
                    evidence=evidence,
                    occurred_at=now,
                )
                promoted_ready += 1
        return TaskOutcome(
            TaskOutcomeState.COMPLETED,
            ("SHADOW_SESSION_COMPLETED",),
            f"shadow observations={observed}; paper-ready evidence={promoted_ready}; "
            f"historical OOS unready={historical_unready}",
        )


__all__ = ["AdoptedOosEvidenceCatalog", "DailyCanonicalShadowSession"]
