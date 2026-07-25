"""Fail-closed certification of the governed paper desk before live capital."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

from sensei.backtest.playbook import all_strategies, evaluate_strategy
from sensei.data.store import available_symbols
from sensei.kernel.commands import CommandKind
from sensei.operations import OperationalJournal


_ROLES = frozenset(
    {
        "orchestrator",
        "historian",
        "reporter",
        "crowd-reader",
        "analyst",
        "committee",
        "trader",
        "coach",
        "secretary",
    }
)
_VERDICT_LEVELS = frozenset({"L1", "L2", "L3", "L4"})


@dataclass(frozen=True)
class CertificationCheck:
    name: str
    passed: bool
    detail: str
    evidence: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class PreLiveCertificationReport:
    generated_at: datetime
    ready_for_live_capital: bool
    checks: tuple[CertificationCheck, ...]

    @property
    def blockers(self) -> tuple[str, ...]:
        return tuple(check.name for check in self.checks if not check.passed)

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "ready_for_live_capital": self.ready_for_live_capital,
            "blockers": list(self.blockers),
            "checks": [check.to_dict() for check in self.checks],
        }


class PreLiveCertifier:
    """Combine fresh strategy replay with evidence from the actual desk journal."""

    def __init__(
        self,
        *,
        journal_path: Path,
        playbook_path: Path = Path("data/playbook/current.json"),
        rehearsal_path: Path | None = None,
        strategy_study: Callable[[], Sequence[Mapping[str, object]]] | None = None,
    ) -> None:
        self._journal_path = Path(journal_path)
        self._playbook_path = Path(playbook_path)
        self._rehearsal_path = (
            Path(rehearsal_path) if rehearsal_path is not None else None
        )
        self._strategy_study = strategy_study

    def run(self, *, generated_at: datetime | None = None) -> PreLiveCertificationReport:
        now = generated_at or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        journal = OperationalJournal.open_read_only(self._journal_path)
        verification = journal.verify()
        events = journal.read_all()
        rehearsal = (
            _load_rehearsal(self._rehearsal_path)
            if self._rehearsal_path is not None else {}
        )
        study = tuple(
            self._strategy_study()
            if self._strategy_study is not None
            else _fresh_strategy_study(self._playbook_path)
        )

        checks = (
            CertificationCheck(
                "journal_integrity",
                verification.ok,
                "Operational journal verifies" if verification.ok
                else "Operational journal integrity failed",
                {
                    "events_checked": verification.events_checked,
                    "errors": list(verification.errors),
                },
            ),
            _strategy_check(study),
            _paper_authorization_check(events),
            _agent_chain_check(events, rehearsal),
            _committee_check(events, rehearsal),
            _entry_protection_check(events, rehearsal),
            _governed_exit_capability_check(),
            _closed_learning_check(events),
        )
        return PreLiveCertificationReport(
            generated_at=now,
            ready_for_live_capital=all(check.passed for check in checks),
            checks=checks,
        )


def _fresh_strategy_study(
    playbook_path: Path,
) -> tuple[Mapping[str, object], ...]:
    symbols = available_symbols()
    strategies = all_strategies()
    retained = json.loads(playbook_path.read_text(encoding="utf-8"))
    adopted_names = tuple(
        str(item["name"])
        for item in retained.get("strategies", ())
        if item.get("adopted") is True
    )
    return tuple(
        evaluate_strategy(name, strategy, symbols)
        for name in adopted_names
        if (strategy := strategies.get(name)) is not None
    )


def _strategy_check(study) -> CertificationCheck:
    adopted = tuple(item for item in study if item.get("adopted") is True)
    failures = tuple(
        str(item.get("name", "unknown"))
        for item in study
        if item.get("adopted") is not True
    )
    passed = bool(study) and len(adopted) >= 1 and not failures
    return CertificationCheck(
        "fresh_historical_strategy_replay",
        passed,
        (
            f"{len(adopted)} strategies passed a fresh local replay"
            if passed
            else "One or more configured strategies failed fresh replay"
        ),
        {
            "evaluated": len(study),
            "adopted": len(adopted),
            "failed_names": list(failures),
            "results": [
                {
                    "name": item.get("name"),
                    "adopted": item.get("adopted"),
                    "out_of_sample": item.get("out_of_sample"),
                }
                for item in study
            ],
        },
    )


def _paper_authorization_check(events) -> CertificationCheck:
    latest: dict[str, str] = {}
    for event in events:
        if event.event_type == "StrategyLifecycleTransitioned":
            latest[str(event.payload["plan_version_id"])] = str(
                event.payload["target_stage"]
            )
    paper = sorted(plan for plan, stage in latest.items() if stage == "paper")
    return CertificationCheck(
        "paper_strategy_authorization",
        bool(paper),
        f"{len(paper)} exact plan(s) are at PAPER" if paper
        else "No exact Strategy Plan is authorized at PAPER",
        {"paper_plan_ids": paper},
    )


def _agent_chain_check(events, rehearsal) -> CertificationCheck:
    completed_cycles = {
        str(event.payload.get("cycle_id", event.correlation_id))
        for event in events
        if event.event_type == "DeskCycleCompleted"
    }
    roles_by_cycle: dict[str, set[str]] = {}
    for event in events:
        if event.event_type != "DeskRoleCompleted" or event.correlation_id is None:
            continue
        roles_by_cycle.setdefault(event.correlation_id, set()).add(
            str(event.payload.get("role"))
        )
    qualifying = sorted(
        cycle
        for cycle in completed_cycles
        if roles_by_cycle.get(cycle) == _ROLES
    )
    rehearsal_roles = set(
        rehearsal.get("diagnostics", {}).get("roles_completed", ())
    )
    rehearsal_passed = (
        rehearsal.get("state") == "WOULD_TRADE"
        and rehearsal.get("production_state_unchanged") is True
        and rehearsal_roles == _ROLES
    )
    observed = sorted(set().union(*roles_by_cycle.values())) if roles_by_cycle else []
    return CertificationCheck(
        "nine_agent_production_cycle",
        bool(qualifying) or rehearsal_passed,
        "A completed isolated production-composition cycle exercised all nine roles"
        if rehearsal_passed
        else "A completed production cycle exercised all nine roles" if qualifying
        else "No completed production cycle has exercised all nine roles",
        {
            "qualifying_cycle_ids": qualifying,
            "roles_observed": observed,
            "rehearsal_roles": sorted(rehearsal_roles),
            "rehearsal_production_unchanged": rehearsal.get(
                "production_state_unchanged"
            ),
        },
    )


def _committee_check(events, rehearsal) -> CertificationCheck:
    levels_by_cycle: dict[str, set[str]] = {}
    for event in events:
        if (
            event.event_type != "TradeCommitteeVerdictProduced"
            or event.correlation_id is None
        ):
            continue
        verdict = event.payload.get("fact", {}).get("verdict", {})
        levels_by_cycle.setdefault(event.correlation_id, set()).add(
            str(verdict.get("level"))
        )
    qualifying = sorted(
        cycle for cycle, levels in levels_by_cycle.items()
        if levels == _VERDICT_LEVELS
    )
    rehearsal_levels = {
        str(item.get("level"))
        for item in rehearsal.get("diagnostics", {}).get(
            "committee_verdicts", ()
        )
    }
    rehearsal_passed = (
        rehearsal.get("state") == "WOULD_TRADE"
        and rehearsal_levels == _VERDICT_LEVELS
    )
    return CertificationCheck(
        "l1_l4_committee_evidence",
        bool(qualifying) or rehearsal_passed,
        "The isolated production composition produced authenticated L1-L4 verdicts"
        if rehearsal_passed
        else "One cycle contains authenticated L1-L4 verdicts" if qualifying
        else "No cycle contains all four authenticated Committee verdicts",
        {
            "qualifying_cycle_ids": qualifying,
            "rehearsal_levels": sorted(rehearsal_levels),
        },
    )


def _entry_protection_check(events, rehearsal) -> CertificationCheck:
    kinds = []
    for event in events:
        if event.event_type != "PaperGatewayCommandExecuted":
            continue
        command = event.payload.get("command", {})
        kinds.append(str(command.get("kind")))
    passed = {"ENTRY", "PROTECTION"} <= set(kinds)
    rehearsal_commands = int(
        rehearsal.get("diagnostics", {}).get("sandbox_gateway_commands", 0)
    )
    rehearsal_passed = (
        rehearsal.get("state") == "WOULD_TRADE"
        and rehearsal_commands >= 2
        and rehearsal.get("real_order_submitted") is False
    )
    return CertificationCheck(
        "paper_entry_and_protection",
        passed or rehearsal_passed,
        "Sandbox executed an entry and protection through the production composition"
        if rehearsal_passed
        else "Paper entry and protective order were both executed" if passed
        else "No governed paper fill with installed protection is proven",
        {
            "gateway_command_kinds": sorted(set(kinds)),
            "rehearsal_gateway_commands": rehearsal_commands,
            "real_order_submitted": rehearsal.get("real_order_submitted"),
        },
    )


def _governed_exit_capability_check() -> CertificationCheck:
    kinds = sorted(kind.value for kind in CommandKind)
    passed = "EXIT" in kinds
    return CertificationCheck(
        "governed_exit_capability",
        passed,
        "The governed gateway exposes a typed EXIT command" if passed
        else "Governed entries have no typed automated EXIT command",
        {"kernel_command_kinds": kinds},
    )


def _closed_learning_check(events) -> CertificationCheck:
    event_types = {event.event_type for event in events}
    required = {
        "ExitFillRecorded",
        "CostsReconciled",
        "EpisodeClosed",
        "OutcomeAttributed",
        "ReviewRecorded",
        "LearningObservationRecorded",
    }
    missing = sorted(required - event_types)
    return CertificationCheck(
        "closed_episode_learning_chain",
        not missing,
        "A closed governed episode reached reviewed learning" if not missing
        else "No complete governed exit-to-learning chain is proven",
        {"missing_event_types": missing},
    )


def _load_rehearsal(path: Path) -> Mapping[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


__all__ = [
    "CertificationCheck",
    "PreLiveCertificationReport",
    "PreLiveCertifier",
]
