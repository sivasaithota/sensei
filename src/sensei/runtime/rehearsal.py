"""Disposable end-to-end rehearsal of the governed paper-entry path."""

from __future__ import annotations

import json
import hashlib
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path

import pandas as pd

from sensei.automation import (
    GovernedSchedulerApplication,
    SchedulerApplicationConfig,
    SchedulerLedger,
)
from sensei.automation.scheduling import SchedulerTaskKind, SwingSessionPolicy
from sensei.execution.nse import NseMarketObservation
from sensei.data.events import CACHE_FILE, in_no_trade_window
from sensei.operations import EventAppend, OperationalJournal
from sensei.orchestration import ExecutableQuote
from sensei.runtime.activation import (
    RuntimeSecretStore,
    RuntimeTrustError,
    VerifiedSurveillanceSource,
)
from sensei.runtime.production import ProductionPaperSession, _entry_limit_paise


class RehearsalState(StrEnum):
    WOULD_TRADE = "WOULD_TRADE"
    NO_SIGNAL = "NO_SIGNAL"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class RehearsalReport:
    as_of: datetime
    effective_entry_at: datetime | None
    state: RehearsalState
    reason_codes: tuple[str, ...]
    detail: str
    production_events_before: int
    production_events_after: int
    sandbox_events_added: int
    production_state_unchanged: bool
    real_order_submitted: bool = False
    diagnostics: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "as_of": self.as_of.isoformat(),
            "effective_entry_at": (
                self.effective_entry_at.isoformat()
                if self.effective_entry_at is not None else None
            ),
            "state": self.state.value,
            "reason_codes": list(self.reason_codes),
            "detail": self.detail,
            "production_events_before": self.production_events_before,
            "production_events_after": self.production_events_after,
            "sandbox_events_added": self.sandbox_events_added,
            "production_state_unchanged": self.production_state_unchanged,
            "real_order_submitted": self.real_order_submitted,
            "diagnostics": self.diagnostics or {},
        }


class PaperEntryRehearsal:
    """Run production composition against a verified disposable journal copy."""

    def __init__(
        self,
        *,
        journal_path: Path,
        config_path: Path,
    ) -> None:
        self._journal_path = Path(journal_path)
        self._config_path = Path(config_path)

    def run(self, *, as_of: datetime) -> RehearsalReport:
        if as_of.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        if not self._journal_path.is_file() or not self._config_path.is_file():
            return self._blocked(
                as_of, "REHEARSAL_CONFIGURATION_UNAVAILABLE",
                "Governed journal or scheduler configuration is missing",
            )
        try:
            raw = json.loads(self._config_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("scheduler config must be a JSON object")
            config = SchedulerApplicationConfig.from_json(self._config_path)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return self._blocked(
                as_of, "REHEARSAL_CONFIGURATION_UNAVAILABLE",
                f"Scheduler configuration cannot be loaded: {exc}",
            )
        if config.execution_backend != "governed_paper":
            return self._blocked(
                as_of, "REHEARSAL_REQUIRES_GOVERNED_PAPER_BACKEND",
                "Entry rehearsal requires execution_backend=governed_paper",
            )

        try:
            source = OperationalJournal.open_read_only(self._journal_path)
            source_digest = _sha256(self._journal_path)
            artifact_digests = _artifact_digests(config)
            verification = source.verify()
        except (OSError, ValueError) as exc:
            return self._blocked(
                as_of, "REHEARSAL_PRODUCTION_ARTIFACT_UNREADABLE",
                f"Production state cannot be fingerprinted: {exc}",
                unchanged=False,
            )
        before = verification.events_checked
        if not verification.ok:
            return self._blocked(
                as_of, "JOURNAL_INTEGRITY_FAILED",
                "Production journal integrity verification failed", before=before,
            )
        policy = SwingSessionPolicy(closed_dates=config.closed_dates)
        effective_at = policy.next_entry_at(as_of) + timedelta(minutes=1)

        try:
            with tempfile.TemporaryDirectory(prefix="sensei-rehearsal-") as directory:
                root = Path(directory)
                sandbox_journal = root / "operations.sqlite3"
                source.backup_to(sandbox_journal)
                sandbox_surveillance = root / "surveillance.json"
                if config.surveillance_path.is_file():
                    shutil.copy2(config.surveillance_path, sandbox_surveillance)
                raw["surveillance_path"] = str(sandbox_surveillance)
                sandbox_positions = root / "positions.json"
                if config.legacy_positions_path.is_file():
                    shutil.copy2(config.legacy_positions_path, sandbox_positions)
                raw["legacy_positions_path"] = str(sandbox_positions)
                sandbox_provenance = root / "provenance"
                if config.provenance_path.is_dir():
                    shutil.copytree(config.provenance_path, sandbox_provenance)
                raw["provenance_path"] = str(sandbox_provenance)
                sandbox_earnings = root / "earnings_cache.json"
                if CACHE_FILE.is_file():
                    shutil.copy2(CACHE_FILE, sandbox_earnings)
                sandbox_config = root / "scheduler.json"
                sandbox_config.write_text(
                    json.dumps(raw, sort_keys=True), encoding="utf-8"
                )
                _prepare_sandbox_surveillance(
                    journal_path=sandbox_journal,
                    config_path=sandbox_config,
                    effective_at=effective_at,
                )
                result = _run_governed_scheduler(
                    sandbox_journal, sandbox_config, effective_at
                )
                sandbox_event_log = OperationalJournal.open_read_only(
                    sandbox_journal
                ).read_all()
                sandbox_events = len(sandbox_event_log)
                diagnostics = _diagnostics(sandbox_event_log[before:])
                state, reasons, detail = classify_rehearsal_outcome(
                    result,
                    gateway_commands=int(
                        diagnostics["sandbox_gateway_commands"]
                    ),
                )
        except Exception as exc:  # fail closed; diagnostic must never escape unsafe
            state = RehearsalState.BLOCKED
            reasons = ("REHEARSAL_RUNTIME_FAILED",)
            detail = f"{type(exc).__name__}: {exc}"
            sandbox_events = before
            diagnostics = {}

        try:
            after = len(
                OperationalJournal.open_read_only(self._journal_path).read_all()
            )
            unchanged = (
                after == before
                and _sha256(self._journal_path) == source_digest
                and _artifact_digests(config) == artifact_digests
            )
        except (OSError, ValueError) as exc:
            return self._blocked(
                as_of, "REHEARSAL_PRODUCTION_ARTIFACT_UNREADABLE",
                f"Production state cannot be re-fingerprinted: {exc}",
                before=before, unchanged=False,
            )
        if not unchanged:
            return RehearsalReport(
                as_of, effective_at, RehearsalState.BLOCKED,
                ("PRODUCTION_STATE_CHANGED_DURING_REHEARSAL",),
                "Production journal event count changed during rehearsal",
                before, after, max(0, sandbox_events - before), False, False,
                diagnostics,
            )
        return RehearsalReport(
            as_of, effective_at, state, reasons, detail,
            before, after, max(0, sandbox_events - before), True, False,
            diagnostics,
        )

    def _blocked(
        self, as_of: datetime, reason: str, detail: str, *, before: int = 0,
        unchanged: bool = True,
    ) -> RehearsalReport:
        return RehearsalReport(
            as_of, None, RehearsalState.BLOCKED, (reason,), detail,
            before, before, 0, unchanged, False,
        )


def _run_governed_scheduler(
    journal_path: Path, config_path: Path, effective_at: datetime
) -> dict:
    config = SchedulerApplicationConfig.from_json(config_path)
    legacy_baseline = _legacy_baseline_source(journal_path, config)
    entry = _HistoricalProductionPaperSession(
        journal_path=journal_path,
        scheduler_config=config,
        risk_path=config.risk_path,
        playbook_path=config.playbook_path,
        prices_path=config.prices_path,
        provenance_path=config.provenance_path,
        legacy_baseline=legacy_baseline,
        event_window=lambda symbol, on: in_no_trade_window(
            symbol, on, cache_file=config_path.parent / "earnings_cache.json"
        ),
    )
    return GovernedSchedulerApplication.open(
        journal_path,
        config_path=config_path,
        entry_session=entry,
        manages_legacy_positions=config.legacy_positions_path.is_file(),
    ).run_once(effective_at).to_dict()


def _legacy_baseline_source(journal_path, config):
    if not config.legacy_positions_path.is_file():
        return None
    from sensei.runtime.adoption import LegacyPositionAdoptionRegistry

    payload = json.loads(
        config.legacy_positions_path.read_text(encoding="utf-8")
    )
    symbols = tuple(str(item["symbol"]) for item in payload.get("positions", ()))

    def baseline(captured_at):
        marks = {
            symbol: round(
                float(pd.read_parquet(
                    config.prices_path / f"{symbol}.parquet"
                )["close"].iloc[-1])
                * 100
            )
            for symbol in symbols
        }
        return LegacyPositionAdoptionRegistry(
            OperationalJournal(journal_path),
            positions_path=config.legacy_positions_path,
        ).reconcile(
            mark_prices_paise=marks,
            captured_at=captured_at,
            command_id=f"rehearsal-legacy-baseline:{captured_at.isoformat()}",
        ).account_snapshot

    return baseline


class _HistoricalProductionPaperSession(ProductionPaperSession):
    """Production composition with deterministic local-bar market adapters."""

    def _quote(self, instrument_id, now):
        frame = self._bars(instrument_id)
        if frame.empty:
            return None
        paise = _entry_limit_paise(
            round(float(frame["close"].iloc[-1]) * 100)
        )
        snapshot = "snapshot:" + hashlib.sha256(
            f"rehearsal:{instrument_id}:{paise}:{now.isoformat()}".encode()
        ).hexdigest()
        return ExecutableQuote(instrument_id, snapshot, paise, now)

    def _execution_observation(self, instrument_id, now):
        frame = self._bars(instrument_id)
        row = frame.iloc[-1]
        reference = round(float(row["close"]) * 100)
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
            traded_volume=int(max(0, float(row["volume"]))),
            lower_circuit_paise=max(1, round(reference * 0.8)),
            upper_circuit_paise=round(reference * 1.2),
            evidence_source="LOCAL_DAILY_BAR_REHEARSAL_ONLY",
            spread_is_estimated=True,
            circuit_is_estimated=True,
        )


def _prepare_sandbox_surveillance(
    *,
    journal_path: Path,
    config_path: Path,
    effective_at: datetime,
) -> None:
    """Date-bind the already verified source snapshot inside the sandbox."""

    config = SchedulerApplicationConfig.from_json(config_path)
    raw = json.loads(config.surveillance_path.read_text(encoding="utf-8"))
    stages = raw.get("stages")
    if not isinstance(stages, dict) or not stages:
        raise RuntimeTrustError("rehearsal surveillance snapshot has no stages")
    secrets = RuntimeSecretStore.load(config.runtime_secrets_path)
    source_session = datetime.fromisoformat(
        str(raw["source_session"])
    ).date()
    source_snapshot_session = datetime.fromisoformat(str(raw["session"])).date()
    verifier = VerifiedSurveillanceSource(
        config.surveillance_path,
        issuer_id="market-surveillance",
        secret=secrets["market-surveillance"],
        maximum_age=timedelta(days=7),
        clock=lambda: effective_at,
    )
    first_symbol = next(iter(stages))
    if verifier(first_symbol, source_snapshot_session) is None:
        raise RuntimeTrustError("rehearsal source surveillance is not trustworthy")

    policy = SwingSessionPolicy(closed_dates=config.closed_dates)
    preflight_at = effective_at.replace(hour=8, minute=41, second=0, microsecond=0)
    preflight = max(
        (
            task
            for task in policy.due_tasks(preflight_at).tasks
            if task.kind is SchedulerTaskKind.SURVEILLANCE_PREFLIGHT
        ),
        key=lambda task: task.due_at,
    )
    VerifiedSurveillanceSource.publish(
        config.surveillance_path,
        stages={str(symbol): int(stage) for symbol, stage in stages.items()},
        session=effective_at.date(),
        observed_at=preflight_at,
        issuer_id="market-surveillance",
        secret=secrets["market-surveillance"],
        source_session=source_session,
        source_report_type=str(raw["source_report_type"]),
        source_content_sha256=str(raw["source_content_sha256"]),
    )
    snapshot_sha = hashlib.sha256(config.surveillance_path.read_bytes()).hexdigest()
    journal = OperationalJournal(journal_path)
    ledger = SchedulerLedger(journal)
    claim = ledger.claim(preflight, occurred_at=preflight_at)
    completed = journal.append(
        EventAppend(
            stream_id=f"rehearsal-surveillance:{preflight.task_id}",
            event_type="SurveillancePreflightCompleted",
            payload={
                "schema_version": "1.0",
                "trading_date": effective_at.date().isoformat(),
                "symbols": len(stages),
                "snapshot_sha256": snapshot_sha,
                "source_session": source_session.isoformat(),
                "source_report_type": str(raw["source_report_type"]),
                "source_content_sha256": str(raw["source_content_sha256"]),
                "snapshot_ready": True,
                "can_authorize_trading": False,
                "authority": "REHEARSAL_TRUST_INPUT_ONLY",
            },
            idempotency_key=f"rehearsal-surveillance:{preflight.task_id}",
            expected_version=0,
            occurred_at=preflight_at,
            correlation_id=preflight.task_id,
        )
    )
    ledger.complete(
        preflight.task_id,
        claimant_id=claim.record.claimant_id,
        occurred_at=preflight_at + timedelta(seconds=1),
        detail=f"rehearsal snapshot {completed.event_id}",
        reason_codes=("SURVEILLANCE_PREFLIGHT_READY",),
    )


def classify_rehearsal_outcome(
    result: dict, *, gateway_commands: int
) -> tuple[RehearsalState, tuple[str, ...], str]:
    tasks = result.get("task_results", ())
    if not tasks:
        return RehearsalState.BLOCKED, ("ENTRY_TASK_NOT_EXERCISED",), "No entry task ran in the sandbox"
    entry_task = next(
        (
            item
            for item in tasks
            if item.get("task", {}).get("kind") == "ENTRY_SESSION"
        ),
        None,
    )
    if entry_task is None and len(tasks) == 1 and "task" not in tasks[0]:
        entry_task = tasks[0]
    if entry_task is None:
        return (
            RehearsalState.BLOCKED,
            ("ENTRY_TASK_NOT_EXERCISED",),
            "No entry task ran in the sandbox",
        )
    outcome = entry_task.get("outcome", {})
    reasons = tuple(str(value) for value in outcome.get("reason_codes", ()))
    detail = str(outcome.get("detail", "Rehearsal produced no detail"))
    if "GOVERNED_PAPER_DISPATCHED" in reasons:
        if gateway_commands < 1:
            return (
                RehearsalState.BLOCKED,
                ("REHEARSAL_GATEWAY_EVIDENCE_MISSING",),
                "Dispatch outcome lacked a recording-gateway command",
            )
        return RehearsalState.WOULD_TRADE, reasons, detail
    if set(reasons) & {"NO_CANONICAL_SIGNAL", "GOVERNED_NO_SIGNAL"}:
        return RehearsalState.NO_SIGNAL, reasons, detail
    return RehearsalState.BLOCKED, reasons or ("REHEARSAL_BLOCKED",), detail


def _diagnostics(events) -> dict[str, object]:
    intent = None
    cycle = None
    supervisor_terminal = None
    verdicts = []
    roles = []
    risk_reservations = 0
    gateway_commands = 0
    for event in events:
        if event.event_type == "TradeIntentAccepted":
            intent = dict(event.payload.get("intent", {}))
        elif event.event_type == "DeskCycleCompleted":
            cycle = {
                "status": event.payload.get("status"),
                "reason": event.payload.get("reason"),
            }
        elif event.event_type in {
            "DeskSupervisorCompleted",
            "DeskSupervisorHalted",
            "DeskSupervisorFailed",
        }:
            supervisor_terminal = {
                "event_type": event.event_type,
                "reason_codes": list(event.payload.get("reason_codes", ())),
                "error_type": event.payload.get("error_type"),
                "detail": event.payload.get("detail"),
            }
        elif event.event_type == "TradeCommitteeVerdictProduced":
            fact = event.payload.get("fact", {})
            verdict = fact.get("verdict", {})
            verdicts.append({
                "level": verdict.get("level"), "agent": verdict.get("agent"),
                "approved": verdict.get("approved"),
                "reasoning": verdict.get("reasoning"),
            })
        elif event.event_type == "DeskRoleCompleted":
            roles.append(str(event.payload.get("role")))
        elif event.event_type == "RiskReserved":
            risk_reservations += 1
        elif event.event_type == "PaperGatewayCommandExecuted":
            gateway_commands += 1
    return {
        "cycle": cycle, "intent": intent, "committee_verdicts": verdicts,
        "roles_completed": sorted(set(roles)),
        "risk_reservations": risk_reservations,
        "sandbox_gateway_commands": gateway_commands,
        "supervisor_terminal": supervisor_terminal,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact_digests(config: SchedulerApplicationConfig) -> dict[str, str | None]:
    """Fingerprint production artifacts the entry composition may update."""

    files = {
        str(path): _sha256(path) if path.is_file() else None
        for path in (
            config.legacy_positions_path, config.surveillance_path, CACHE_FILE
        )
    }
    files[str(config.provenance_path)] = (
        _tree_digest(config.provenance_path)
        if config.provenance_path.is_dir() else None
    )
    return files


def _tree_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if not item.is_file():
            continue
        digest.update(str(item.relative_to(path)).encode("utf-8"))
        digest.update(item.read_bytes())
    return digest.hexdigest()


__all__ = [
    "PaperEntryRehearsal", "RehearsalReport", "RehearsalState",
    "classify_rehearsal_outcome",
]
