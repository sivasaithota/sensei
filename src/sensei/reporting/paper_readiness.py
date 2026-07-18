"""Passive, fail-closed paper-entry readiness certification."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from sensei.operations import OperationalJournal
from sensei.automation.application import SchedulerApplicationConfig
from sensei.automation.scheduling import SwingSessionPolicy

AUTHORIZED_STAGES = frozenset({"paper", "canary", "active"})


class ReadinessState(str, Enum):
    READY = "READY"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class ReadinessCheck:
    code: str
    label: str
    passed: bool
    detail: str
    evidence_event_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "code": self.code, "label": self.label, "passed": self.passed,
            "detail": self.detail, "evidence_event_id": self.evidence_event_id,
        }


@dataclass(frozen=True)
class PaperReadinessReport:
    as_of: datetime
    state: ReadinessState
    checks: tuple[ReadinessCheck, ...]
    blockers: tuple[str, ...]
    next_entry_at: datetime

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of.isoformat(), "state": self.state.value,
            "blockers": list(self.blockers),
            "next_entry_at": self.next_entry_at.isoformat(),
            "checks": [check.to_dict() for check in self.checks],
        }


def build_readiness_report(
    journal_path: Path,
    *,
    as_of: datetime,
    config_path: Path = Path("config/scheduler.json"),
    kill_switch_path: Path = Path("data/KILL"),
    positions_path: Path | None = None,
) -> PaperReadinessReport:
    """Derive readiness without claiming tasks or writing operational state."""

    if as_of.tzinfo is None:
        raise ValueError("as_of must include a timezone")
    checks: list[ReadinessCheck] = []
    try:
        config = SchedulerApplicationConfig.from_json(Path(config_path))
        policy = SwingSessionPolicy(closed_dates=config.closed_dates)
        config_ok = True
        config_detail = f"Loaded {Path(config_path)}"
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        config = SchedulerApplicationConfig()
        policy = SwingSessionPolicy()
        config_ok = False
        config_detail = f"Scheduler configuration unavailable: {exc}"
    checks.append(ReadinessCheck(
        "SCHEDULER_CONFIG_VALID" if config_ok else "SCHEDULER_CONFIG_UNAVAILABLE",
        "Scheduler configuration", config_ok, config_detail,
    ))
    minimum = config.shadow_trial.minimum_data_completeness
    if not Path(journal_path).is_file():
        checks.append(ReadinessCheck("GOVERNED_JOURNAL_MISSING", "Journal integrity", False, "Governed journal is missing"))
        return _report(as_of, checks, policy)

    journal = OperationalJournal.open_read_only(Path(journal_path))
    verification = journal.verify()
    checks.append(ReadinessCheck(
        "JOURNAL_INTEGRITY_OK" if verification.ok else "JOURNAL_INTEGRITY_FAILED",
        "Journal integrity", verification.ok,
        f"Verified {verification.events_checked} events" if verification.ok else "; ".join(verification.errors),
    ))
    events = journal.read_all() if verification.ok else ()
    stages: dict[str, str] = {}
    terminal = ingestion = adoption = reconciliation = None
    for event in events:
        if event.event_type == "StrategyLifecycleTransitioned":
            stages[str(event.payload["plan_version_id"])] = str(event.payload["target_stage"])
        elif event.event_type in {"SchedulerTaskCompleted", "SchedulerTaskHalted"}:
            terminal = event
        elif event.event_type == "MarketDataIngestionCompleted":
            ingestion = event
        elif event.event_type == "LegacyPaperPositionsAdopted":
            adoption = event
        elif event.event_type == "LegacyPaperPositionsReconciled":
            reconciliation = event

    authorized = sum(stage in AUTHORIZED_STAGES for stage in stages.values())
    checks.append(ReadinessCheck(
        "PAPER_STRATEGY_AUTHORIZED" if authorized else "NO_AUTHORIZED_PAPER_STRATEGY",
        "Strategy authorization", authorized > 0,
        f"{authorized} strategy plan(s) authorized for paper entry",
    ))
    scheduler_ok = terminal is not None and terminal.event_type == "SchedulerTaskCompleted"
    checks.append(ReadinessCheck(
        "SCHEDULER_HEALTHY" if scheduler_ok else (
            "LATEST_SCHEDULER_TASK_HALTED" if terminal is not None else "NO_SCHEDULER_RESULT"
        ),
        "Scheduler health", scheduler_ok,
        "Latest scheduler task completed" if scheduler_ok else "No successful latest scheduler result",
        terminal.event_id if terminal else None,
    ))
    expected_session = policy.latest_eod_open_session(as_of)
    ingestion_session = None if ingestion is None else str(ingestion.payload.get("session", ""))
    fresh = ingestion is not None and ingestion_session == expected_session.isoformat()
    checks.append(ReadinessCheck(
        "MARKET_DATA_FRESH" if fresh else "MARKET_DATA_STALE_OR_MISSING",
        "Market-data freshness", fresh,
        f"Expected completed NSE session {expected_session}; observed {ingestion_session or 'none'}",
        ingestion.event_id if ingestion else None,
    ))
    completeness = 0.0 if ingestion is None else float(ingestion.payload.get("completeness", 0))
    checks.append(ReadinessCheck(
        "MARKET_DATA_COMPLETE" if completeness >= minimum else "MARKET_DATA_COMPLETENESS_BELOW_POLICY",
        "Market-data completeness",
        completeness >= minimum, f"{completeness:.3%} observed; {minimum:.3%} required",
        ingestion.event_id if ingestion else None,
    ))
    kill_clear = not Path(kill_switch_path).exists()
    checks.append(ReadinessCheck(
        "KILL_SWITCH_CLEAR" if kill_clear else "KILL_SWITCH_ACTIVE",
        "Owner kill switch", kill_clear,
        "Kill switch clear" if kill_clear else "Kill switch is active",
    ))
    account_path = Path(positions_path) if positions_path else Path(kill_switch_path).parent / "paper" / "positions.json"
    account_ok, protected, open_positions, account_detail = _account_state(account_path)
    checks.append(ReadinessCheck(
        "ACCOUNT_STATE_AVAILABLE" if account_ok else "ACCOUNT_STATE_UNAVAILABLE",
        "Paper account state", account_ok, account_detail,
    ))
    checks.append(ReadinessCheck(
        "OPEN_POSITIONS_PROTECTED" if protected else "UNPROTECTED_OPEN_POSITION",
        "Position protection", protected,
        "Every open position has a coherent protective stop" if protected else "One or more open positions lack a coherent protective stop",
    ))
    reconciled = open_positions == 0 or (
        adoption is not None and reconciliation is not None
        and reconciliation.global_sequence > adoption.global_sequence
    )
    checks.append(ReadinessCheck(
        "POSITIONS_RECONCILED" if reconciled else "LEGACY_POSITIONS_NOT_RECONCILED",
        "Existing-position reconciliation", reconciled,
        "No open exposure" if open_positions == 0 else (
            "Open exposure has adoption and reconciliation evidence" if reconciled
            else "Open exposure lacks adoption and later reconciliation evidence"
        ), reconciliation.event_id if reconciliation else None,
    ))
    return _report(as_of, checks, policy)


def _report(as_of: datetime, checks: list[ReadinessCheck], policy: SwingSessionPolicy) -> PaperReadinessReport:
    blockers = tuple(check.code for check in checks if not check.passed)
    return PaperReadinessReport(
        as_of=as_of,
        state=ReadinessState.BLOCKED if blockers else ReadinessState.READY,
        checks=tuple(checks), blockers=blockers,
        next_entry_at=policy.next_entry_at(as_of),
    )


def _account_state(path: Path) -> tuple[bool, bool, int, str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        cash = float(raw["cash"])
        positions = raw["positions"]
        if cash < 0 or not isinstance(positions, list):
            raise ValueError
        protected = all(_protected_position(item) for item in positions)
        return True, protected, len(positions), f"₹{cash:,.0f} cash; {len(positions)} open position(s)"
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False, False, 0, "Paper account state is missing or invalid"


def _protected_position(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    try:
        direction = str(value.get("direction", "BUY")).upper()
        quantity = int(value["quantity"])
        entry = float(value["entry_price"])
        stop = float(value["stop_loss"])
        return quantity > 0 and entry > 0 and stop > 0 and (
            (direction == "BUY" and stop < entry)
            or (direction == "SELL" and stop > entry)
        )
    except (KeyError, TypeError, ValueError):
        return False
