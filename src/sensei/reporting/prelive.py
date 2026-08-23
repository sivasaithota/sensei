"""Fail-closed certification of the governed paper desk before live capital."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import stat

from sensei.automation.application import SchedulerApplicationConfig
from sensei.backtest.playbook import all_strategies, evaluate_strategy
from sensei.data.store import available_symbols
from sensei.governance.evidence import DossierError, StageDossierRegistry
from sensei.governance.lifecycle import EvidenceKind
from sensei.kernel.commands import CommandKind
from sensei.operations import OperationalJournal
from sensei.research import (
    ManifestMarketDataCatalog,
    SnapshotIntegrityError,
    SnapshotRequest,
)


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
_MINIMUM_USABLE_UNIVERSE_RATIO = 0.90
_CAPITAL_EVIDENCE_FLAGS = (
    "portfolio_level",
    "point_in_time_universe",
    "corporate_actions_adjusted",
    "purged_walk_forward",
    "multiple_testing_controlled",
    "locked_holdout_passed",
)
_MAX_GOVERNANCE_ARTIFACT_BYTES = 1_000_000
_CAPITAL_CONTROL_METRIC_KEYS = {
    "portfolio_level": {
        "portfolio_path_content_id", "shared_cash", "sizing_rails",
        "cost_model_id", "max_drawdown_pct", "cagr_pct", "observations",
    },
    "point_in_time_universe": {
        "snapshot_id", "eligible_sessions", "instrument_count",
    },
    "corporate_actions_adjusted": {
        "snapshot_id", "adjustment_policies", "corporate_action_artifact_ids",
    },
    "purged_walk_forward": {
        "folds", "purge_sessions", "embargo_sessions", "median_fold_cagr_pct",
    },
    "multiple_testing_controlled": {
        "hypotheses_tested", "method", "adjusted_alpha", "passed",
    },
    "locked_holdout_passed": {
        "holdout_id", "access_ledger_content_id", "access_count",
        "threshold", "observed", "passed",
    },
}


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
    ready_for_unattended_paper: bool
    eligible_for_live_canary_review: bool
    ready_for_live_capital: bool
    checks: tuple[CertificationCheck, ...]

    @property
    def blockers(self) -> tuple[str, ...]:
        return tuple(check.name for check in self.checks if not check.passed)

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "ready_for_unattended_paper": self.ready_for_unattended_paper,
            "eligible_for_live_canary_review": (
                self.eligible_for_live_canary_review
            ),
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
        config_path: Path = Path("config/scheduler.json"),
        governance_artifact_path: Path = Path("data/governance-artifacts"),
        trusted_market_data_manifest_ids: frozenset[str] = frozenset(),
        trusted_market_data_issuers: frozenset[str] = frozenset(),
        strategy_study: Callable[[], Sequence[Mapping[str, object]]] | None = None,
        rehearsal_run: Callable[[], Mapping[str, object]] | None = None,
    ) -> None:
        self._journal_path = Path(journal_path)
        self._playbook_path = Path(playbook_path)
        self._rehearsal_path = (
            Path(rehearsal_path) if rehearsal_path is not None else None
        )
        self._strategy_study = strategy_study
        self._config_path = Path(config_path)
        self._governance_artifact_path = Path(governance_artifact_path)
        if any(
            not _is_content_id(content_id)
            for content_id in trusted_market_data_manifest_ids
        ):
            raise ValueError("trusted market-data manifest IDs must be SHA-256 IDs")
        self._trusted_market_data_manifest_ids = frozenset(
            trusted_market_data_manifest_ids
        )
        self._trusted_market_data_issuers = frozenset(
            str(issuer) for issuer in trusted_market_data_issuers if str(issuer)
        )
        self._rehearsal_run = rehearsal_run

    def run(self, *, generated_at: datetime | None = None) -> PreLiveCertificationReport:
        now = generated_at or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        journal = OperationalJournal.open_read_only(self._journal_path)
        verification = journal.verify()
        events = journal.read_all()
        if self._rehearsal_run is not None:
            rehearsal = self._rehearsal_run()
        else:
            loaded = (
                _load_rehearsal(self._rehearsal_path)
                if self._rehearsal_path is not None else {}
            )
            rehearsal = (
                loaded
                if _rehearsal_matches(
                    loaded,
                    journal_path=self._journal_path,
                    config_path=self._config_path,
                    now=now,
                    event_count=len(events),
                )
                else {}
            )
        study = tuple(
            self._strategy_study()
            if self._strategy_study is not None
            else _fresh_strategy_study(self._playbook_path)
        )
        try:
            scheduler_config = SchedulerApplicationConfig.from_json(
                self._config_path
            )
            dossier_registry = StageDossierRegistry(
                journal,
                trusted_issuer_ids=frozenset(
                    {scheduler_config.dossier_issuer_id}
                ),
                trusted_producers_by_kind=(
                    scheduler_config.producers_by_kind
                ),
            )
            dossier_configuration_error = None
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            dossier_registry = None
            dossier_configuration_error = (
                f"dossier_configuration_invalid:{type(exc).__name__}"
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
            _closed_learning_check(events, rehearsal),
            _capital_strategy_evidence_check(
                events,
                self._governance_artifact_path,
                dossier_registry=dossier_registry,
                configuration_error=dossier_configuration_error,
                trusted_manifest_ids=self._trusted_market_data_manifest_ids,
                trusted_manifest_issuers=self._trusted_market_data_issuers,
            ),
            _paper_soak_check(events),
            _live_execution_backend_check(),
        )
        paper_checks = tuple(
            check for check in checks
            if check.name not in {
                "capital_strategy_evidence",
                "paper_soak_evidence",
                "live_execution_backend",
            }
        )
        canary_checks = tuple(
            check for check in checks
            if check.name != "live_execution_backend"
        )
        return PreLiveCertificationReport(
            generated_at=now,
            ready_for_unattended_paper=all(
                check.passed for check in paper_checks
            ),
            eligible_for_live_canary_review=all(
                check.passed for check in canary_checks
            ),
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
    usable = 0
    from sensei.data.store import load_prices
    for symbol in symbols:
        try:
            usable += int(len(load_prices(symbol)) >= 500)
        except (FileNotFoundError, OSError, ValueError):
            pass
    results = []
    for name in adopted_names:
        strategy = strategies.get(name)
        if strategy is None:
            results.append({
                "name": name,
                "adopted": False,
                "missing_definition": True,
                "out_of_sample": {},
            })
            continue
        result = evaluate_strategy(name, strategy, symbols)
        result["universe_requested"] = len(symbols)
        result["universe_usable"] = usable
        results.append(result)
    return tuple(results)


def _strategy_check(study) -> CertificationCheck:
    adopted = tuple(item for item in study if item.get("adopted") is True)
    failures = tuple(
        str(item.get("name", "unknown"))
        for item in study
        if item.get("adopted") is not True
    )
    coverage_failures = tuple(
        str(item.get("name", "unknown"))
        for item in study
        if item.get("universe_requested", 500) != 500
        or (
            int(item.get("universe_usable", 500))
            / max(1, int(item.get("universe_requested", 500)))
            < _MINIMUM_USABLE_UNIVERSE_RATIO
        )
        or item.get("missing_definition") is True
    )
    passed = (
        bool(study) and len(adopted) >= 1
        and not failures and not coverage_failures
    )
    return CertificationCheck(
        "fresh_historical_strategy_replay",
        passed,
        (
            (
                f"{len(adopted)} strategies passed across "
                f"{study[0].get('universe_requested', 'unknown')} requested / "
                f"{study[0].get('universe_usable', 'unknown')} eligible symbols"
            )
            if passed
            else "One or more configured strategies failed fresh replay"
        ),
        {
            "evaluated": len(study),
            "adopted": len(adopted),
            "failed_names": list(failures),
            "coverage_failures": list(coverage_failures),
            "results": [
                {
                    "name": item.get("name"),
                    "adopted": item.get("adopted"),
                    "out_of_sample": item.get("out_of_sample"),
                    "universe_requested": item.get("universe_requested"),
                    "universe_usable": item.get("universe_usable"),
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
    commands_by_intent: dict[str, list[tuple[str, bool, int]]] = {}
    for event in events:
        if event.event_type != "PaperGatewayCommandExecuted":
            continue
        command = event.payload.get("command", {})
        receipt = event.payload.get("receipt", {})
        kind = str(command.get("kind"))
        intent_id = str(command.get("intent_id"))
        kinds.append(kind)
        commands_by_intent.setdefault(intent_id, []).append((
            kind,
            receipt.get("accepted") is True,
            int(receipt.get("cumulative_fill_quantity", 0)),
        ))
    qualifying_intents = []
    for intent_id, commands in commands_by_intent.items():
        entry_index = next(
            (
                index for index, (kind, accepted, filled) in enumerate(commands)
                if kind == "ENTRY" and accepted and filled > 0
            ),
            None,
        )
        protection_index = next(
            (
                index for index, (kind, accepted, _filled) in enumerate(commands)
                if kind == "PROTECTION" and accepted
            ),
            None,
        )
        if (
            entry_index is not None
            and protection_index is not None
            and entry_index < protection_index
        ):
            qualifying_intents.append(intent_id)
    passed = bool(qualifying_intents)
    rehearsal_commands = int(
        rehearsal.get("diagnostics", {}).get("sandbox_gateway_commands", 0)
    )
    rehearsal_kinds = tuple(
        rehearsal.get("diagnostics", {}).get("gateway_command_kinds", ())
    )
    rehearsal_intents = tuple(
        rehearsal.get("diagnostics", {}).get(
            "gateway_command_intent_ids", ()
        )
    )
    rehearsal_passed = (
        rehearsal.get("state") == "WOULD_TRADE"
        and rehearsal_commands >= 2
        and "ENTRY" in rehearsal_kinds
        and "PROTECTION" in rehearsal_kinds
        and len(set(rehearsal_intents)) == 1
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
            "qualifying_live_intent_ids": qualifying_intents,
            "rehearsal_gateway_commands": rehearsal_commands,
            "rehearsal_gateway_command_kinds": list(rehearsal_kinds),
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


def _closed_learning_check(events, rehearsal) -> CertificationCheck:
    required = (
        "ExitFillRecorded", "EpisodeClosed", "CostsReconciled",
        "OutcomeAttributed", "ReviewRecorded",
    )
    qualifying = []
    for stream_id in {
        event.stream_id for event in events if event.stream_id.startswith("episode:")
    }:
        episode = [event for event in events if event.stream_id == stream_id]
        positions = {
            event.event_type: index for index, event in enumerate(episode)
            if event.event_type in required
        }
        episode_id = stream_id.removeprefix("episode:")
        learning = [
            event for event in events
            if event.event_type == "LearningObservationRecorded"
            and event.correlation_id == episode_id
        ]
        if (
            set(required) <= set(positions)
            and positions["ExitFillRecorded"] < positions["EpisodeClosed"]
            < positions["CostsReconciled"] < positions["OutcomeAttributed"]
            and positions["EpisodeClosed"] < positions["ReviewRecorded"]
            and learning
            and max(
                episode[positions["OutcomeAttributed"]].occurred_at,
                episode[positions["ReviewRecorded"]].occurred_at,
            ) <= learning[-1].occurred_at
        ):
            qualifying.append(episode_id)
    rehearsal_qualifying = tuple(
        rehearsal.get("diagnostics", {}).get(
            "closed_learning_episode_ids", ()
        )
    )
    passed = bool(qualifying or rehearsal_qualifying)
    missing = (
        [] if passed else list(required) + ["LearningObservationRecorded"]
    )
    return CertificationCheck(
        "closed_episode_learning_chain",
        passed,
        "A closed governed episode reached reviewed learning" if passed
        else "No complete governed exit-to-learning chain is proven",
        {
            "missing_event_types": missing,
            "qualifying_episode_ids": qualifying,
            "rehearsal_qualifying_episode_ids": list(rehearsal_qualifying),
        },
    )


def _paper_soak_check(events) -> CertificationCheck:
    closed = [
        event for event in events
        if event.event_type == "EpisodeClosed"
        and event.stream_id.startswith("episode:")
    ]
    sessions = {
        event.occurred_at.astimezone().date().isoformat() for event in closed
    }
    completed_episode_ids = {
        event.stream_id.removeprefix("episode:") for event in closed
    }
    learned_episode_ids = {
        event.correlation_id
        for event in events
        if event.event_type == "LearningObservationRecorded"
    }
    learned_closed = completed_episode_ids & learned_episode_ids
    passed = len(learned_closed) >= 10 and len(sessions) >= 3
    return CertificationCheck(
        "paper_soak_evidence",
        passed,
        (
            "At least 10 governed paper episodes closed and learned across "
            "3 sessions"
            if passed
            else "Real capital requires 10 governed paper closures across 3 sessions"
        ),
        {
            "required_closed_episodes": 10,
            "actual_closed_and_learned_episodes": len(learned_closed),
            "required_sessions": 3,
            "actual_sessions": len(sessions),
        },
    )


def _capital_strategy_evidence_check(
    events,
    artifact_root: Path,
    *,
    dossier_registry: StageDossierRegistry | None,
    configuration_error: str | None,
    trusted_manifest_ids: frozenset[str],
    trusted_manifest_issuers: frozenset[str],
) -> CertificationCheck:
    """Require stronger, content-verified evidence before CANARY review.

    PAPER remains a learning stage. Capital-bearing review requires every exact
    PAPER plan to name an examination artifact whose schema explicitly proves
    the portfolio and data-quality controls that legacy trade-level studies did
    not provide.
    """

    current_stage_by_plan: dict[str, tuple[str, str]] = {}
    events_by_id = {event.event_id: event for event in events}
    examination_by_plan: dict[str, tuple[str, str]] = {}
    for event in events:
        if event.event_type == "StrategyLifecycleTransitioned":
            plan_id = str(event.payload.get("plan_version_id", ""))
            lineage_id = str(event.payload.get("lineage_id", ""))
            target_stage = str(event.payload.get("target_stage", ""))
            current_stage_by_plan[plan_id] = (lineage_id, target_stage)
            if target_stage == "examined":
                examination_by_plan.pop(plan_id, None)
                raw_refs = event.payload.get("evidence_refs", ())
                refs = [
                    str(item.get("ref_id", ""))
                    for item in raw_refs
                    if isinstance(item, Mapping)
                    and item.get("kind") == "examination_dossier"
                ] if isinstance(raw_refs, Sequence) and not isinstance(
                    raw_refs, (str, bytes)
                ) else []
                if len(refs) == 1:
                    examination_by_plan[plan_id] = (lineage_id, refs[0])

    paper_plans = sorted(
        plan_id
        for plan_id, (_lineage_id, stage) in current_stage_by_plan.items()
        if stage == "paper"
    )
    ready: list[str] = []
    failures: dict[str, list[str]] = {}
    for plan_id in paper_plans:
        reasons: list[str] = []
        examination = examination_by_plan.get(plan_id)
        dossier = None
        if configuration_error is not None:
            reasons.append(configuration_error)
        elif dossier_registry is None or examination is None:
            reasons.append("missing_passed_examination_dossier")
        else:
            lineage_id, dossier_id = examination
            current_lineage_id = current_stage_by_plan[plan_id][0]
            if lineage_id != current_lineage_id:
                reasons.append("lifecycle_lineage_mismatch")
            try:
                dossier = dossier_registry.get(dossier_id)
            except (DossierError, TypeError, ValueError):
                reasons.append("untrusted_examination_dossier")
            if dossier is None:
                reasons.append("missing_passed_examination_dossier")
            elif (
                dossier.plan_version_id != plan_id
                or dossier.lineage_id != lineage_id
                or dossier.evidence_kind is not EvidenceKind.EXAMINATION_DOSSIER
                or dossier.outcome.value != "passed"
            ):
                reasons.append("invalid_examination_dossier_binding")
            elif len(dossier.supporting_event_ids) != 1:
                reasons.append("invalid_examination_evidence_lineage")
            else:
                support = events_by_id.get(dossier.supporting_event_ids[0])
                if support is None:
                    reasons.append("invalid_examination_evidence_lineage")
                else:
                    artifact, artifact_reasons = (
                        _load_capital_evidence_artifact(
                            support.payload.get("artifact_content_id"),
                            artifact_root,
                            plan_id=plan_id,
                            lineage_id=lineage_id,
                            producer_id=dossier.producer_id,
                        )
                    )
                    reasons.extend(artifact_reasons)
                    if artifact is not None:
                        reasons.extend(
                            _verify_capital_control_evidence(
                                artifact,
                                artifact_root,
                                events=events,
                                evidence_recorded_at=support.recorded_at,
                                plan_id=plan_id,
                                producer_id=dossier.producer_id,
                                verifier_id=dossier.issuer_id,
                                trusted_manifest_ids=trusted_manifest_ids,
                                trusted_manifest_issuers=(
                                    trusted_manifest_issuers
                                ),
                            )
                        )
        if reasons:
            failures[plan_id] = sorted(set(reasons))
        else:
            ready.append(plan_id)

    passed = bool(paper_plans) and not failures
    return CertificationCheck(
        "capital_strategy_evidence",
        passed,
        (
            f"{len(ready)} PAPER plan(s) have hash-verified capital evidence"
            if passed
            else "One or more PAPER plans lack capital-grade strategy evidence"
        ),
        {
            "required_controls": list(_CAPITAL_EVIDENCE_FLAGS),
            "paper_plan_ids": paper_plans,
            "capital_ready_plan_ids": ready,
            "non_capital_ready_plan_ids": sorted(failures),
            "failure_reasons_by_plan": failures,
        },
    )


def _load_capital_evidence_artifact(
    content_id: object,
    artifact_root: Path,
    *,
    plan_id: str,
    lineage_id: str,
    producer_id: str,
) -> tuple[dict[str, object] | None, list[str]]:
    artifact, reasons = _read_json_artifact(content_id, artifact_root)
    if artifact is None:
        return None, reasons
    if (
        artifact.get("plan_version_id") != plan_id
        or artifact.get("lineage_id") != lineage_id
        or artifact.get("evidence_kind") != "examination_dossier"
        or artifact.get("outcome") != "passed"
        or artifact.get("producer_id") != producer_id
        or artifact.get("schema_version") != "1.0"
    ):
        return None, ["governance_artifact_binding_mismatch"]
    return artifact, []


def _verify_capital_control_evidence(
    examination_artifact: Mapping[str, object],
    artifact_root: Path,
    *,
    events: Sequence[object],
    evidence_recorded_at: datetime,
    plan_id: str,
    producer_id: str,
    verifier_id: str,
    trusted_manifest_ids: frozenset[str],
    trusted_manifest_issuers: frozenset[str],
) -> list[str]:
    evidence = examination_artifact.get("evidence")
    if not isinstance(evidence, Mapping):
        return ["capital_readiness_declaration_missing"]
    declaration = evidence.get("capital_readiness")
    if not isinstance(declaration, Mapping):
        return ["capital_readiness_declaration_missing"]
    if set(declaration) != set(_CAPITAL_EVIDENCE_FLAGS):
        return ["capital_control_evidence_set_incomplete"]
    references = [str(declaration[control]) for control in _CAPITAL_EVIDENCE_FLAGS]
    if len(set(references)) != len(references):
        return ["capital_control_evidence_not_independent"]

    reasons: list[str] = []
    protocol_ids: set[str] = set()
    result_ids: set[str] = set()
    for control, content_id in zip(_CAPITAL_EVIDENCE_FLAGS, references):
        result_ids.add(content_id)
        result, artifact_reasons = _read_json_artifact(
            content_id, artifact_root
        )
        reasons.extend(
            f"{reason}:{control}" for reason in artifact_reasons
        )
        if result is None:
            continue
        expected_result_keys = {
            "artifact_type",
            "schema_version",
            "plan_version_id",
            "control",
            "outcome",
            "producer_id",
            "verifier_id",
            "protocol_content_id",
            "dataset_manifest_content_id",
            "dataset_request",
            "evaluated_at",
            "metrics",
        }
        if set(result) != expected_result_keys or (
            result.get("artifact_type") != "capital_control_result"
            or result.get("schema_version") != "1.0"
            or result.get("plan_version_id") != plan_id
            or result.get("control") != control
            or result.get("outcome") != "passed"
            or result.get("producer_id") != producer_id
            or result.get("verifier_id") != verifier_id
            or not isinstance(result.get("metrics"), Mapping)
            or not _valid_control_metrics(control, result.get("metrics"))
        ):
            reasons.append(f"capital_control_binding_mismatch:{control}")
            continue

        protocol_id = str(result.get("protocol_content_id", ""))
        dataset_id = str(result.get("dataset_manifest_content_id", ""))
        protocol_ids.add(protocol_id)
        protocol, protocol_reasons = _read_json_artifact(
            protocol_id, artifact_root
        )
        reasons.extend(
            f"capital_protocol_{reason}:{control}"
            for reason in protocol_reasons
        )
        if protocol is None:
            continue
        expected_protocol = {
            "artifact_type": "capital_control_protocol",
            "schema_version": "1.0",
            "plan_version_id": plan_id,
            "control": control,
            "producer_id": producer_id,
            "registered_at": "2026-01-01T00:00:00+00:00",
            "criteria": {"minimum_outcome": "passed"},
        }
        if set(protocol) != set(expected_protocol) or any(
            protocol.get(key) != value
            for key, value in expected_protocol.items()
            if key not in {"registered_at", "criteria"}
        ) or not _valid_preregistered_protocol(
            protocol,
            result,
            result_content_id=content_id,
            protocol_content_id=protocol_id,
            events=events,
            evidence_recorded_at=evidence_recorded_at,
        ):
            reasons.append(f"capital_protocol_binding_mismatch:{control}")

        dataset, dataset_reasons = _read_json_artifact(
            dataset_id, artifact_root
        )
        reasons.extend(
            f"capital_dataset_{reason}:{control}"
            for reason in dataset_reasons
        )
        if dataset is None:
            continue
        request_payload = result.get("dataset_request")
        snapshot = _materialize_trusted_snapshot(
            dataset_id,
            artifact_root,
            request_payload=request_payload,
            trusted_manifest_ids=trusted_manifest_ids,
            trusted_manifest_issuers=trusted_manifest_issuers,
        )
        if snapshot is None:
            reasons.append(f"capital_dataset_not_admissible:{control}")
        elif control in {
            "point_in_time_universe", "corporate_actions_adjusted"
        } and result["metrics"].get("snapshot_id") != snapshot.snapshot_id:
            reasons.append(f"capital_dataset_snapshot_mismatch:{control}")
        if snapshot is not None:
            reasons.extend(
                _verify_control_support_artifacts(
                    control,
                    result["metrics"],
                    artifact_root,
                    plan_id=plan_id,
                    producer_id=producer_id,
                    verifier_id=verifier_id,
                    snapshot=snapshot,
                    events=events,
                )
            )
    if len(protocol_ids) != len(_CAPITAL_EVIDENCE_FLAGS):
        reasons.append("capital_control_protocols_not_independent")
    if len(result_ids) != len(_CAPITAL_EVIDENCE_FLAGS):
        reasons.append("capital_control_results_not_independent")
    return sorted(set(reasons))


def _read_json_artifact(
    content_id: object,
    artifact_root: Path,
) -> tuple[dict[str, object] | None, list[str]]:
    encoded, reasons = _read_artifact_bytes(content_id, artifact_root)
    if encoded is None:
        return None, reasons
    try:
        artifact = json.loads(
            encoded,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-standard JSON constant: {value}")
            ),
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return None, ["governance_artifact_invalid_json"]
    if not isinstance(artifact, dict):
        return None, ["governance_artifact_invalid_shape"]
    return artifact, []


def _read_artifact_bytes(
    content_id: object,
    artifact_root: Path,
) -> tuple[bytes | None, list[str]]:
    value = str(content_id or "")
    if not value.startswith("sha256:") or len(value) != 71:
        return None, ["invalid_artifact_content_id"]
    digest = value.removeprefix("sha256:")
    if any(character not in "0123456789abcdef" for character in digest):
        return None, ["invalid_artifact_content_id"]
    path = artifact_root / f"{digest}.json"
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            return None, ["governance_artifact_not_regular_file"]
        with path.open("rb") as source:
            encoded = source.read(_MAX_GOVERNANCE_ARTIFACT_BYTES + 1)
    except OSError:
        return None, ["governance_artifact_missing"]
    if len(encoded) > _MAX_GOVERNANCE_ARTIFACT_BYTES:
        return None, ["governance_artifact_too_large"]
    if hashlib.sha256(encoded).hexdigest() != digest:
        return None, ["governance_artifact_hash_mismatch"]
    return encoded, []


def _materialize_trusted_snapshot(
    dataset_content_id: str,
    artifact_root: Path,
    *,
    request_payload: object,
    trusted_manifest_ids: frozenset[str],
    trusted_manifest_issuers: frozenset[str],
):
    if not isinstance(request_payload, Mapping) or set(request_payload) != {
        "universe", "history_start", "as_of", "frequency"
    }:
        return None
    try:
        request = SnapshotRequest(
            universe=str(request_payload["universe"]),
            history_start=date.fromisoformat(str(request_payload["history_start"])),
            as_of=date.fromisoformat(str(request_payload["as_of"])),
            frequency=str(request_payload["frequency"]),
        )
        manifest_path = artifact_root / (
            dataset_content_id.removeprefix("sha256:") + ".json"
        )
        snapshot = ManifestMarketDataCatalog(
            manifest_path=manifest_path,
            trusted_issuers=trusted_manifest_issuers,
            trusted_manifest_ids=trusted_manifest_ids,
        ).snapshot(request)
    except (OSError, TypeError, ValueError, SnapshotIntegrityError):
        return None
    if not snapshot.point_in_time_universe:
        return None
    if any(
        policy not in {"split_adjusted", "split_and_dividend_adjusted"}
        for policy in snapshot.lineage.adjustment_policies
    ):
        return None
    return snapshot


def _valid_preregistered_protocol(
    protocol: Mapping[str, object],
    result: Mapping[str, object],
    *,
    protocol_content_id: str,
    result_content_id: str,
    events: Sequence[object],
    evidence_recorded_at: datetime,
) -> bool:
    criteria = protocol.get("criteria")
    control = str(protocol.get("control", ""))
    metrics = result.get("metrics")
    if not isinstance(criteria, Mapping) or not isinstance(metrics, Mapping):
        return False
    try:
        criteria_valid = _criteria_bind_result(control, criteria, metrics)
    except (TypeError, ValueError):
        return False
    if not criteria_valid:
        return False
    try:
        registered_at = datetime.fromisoformat(str(protocol.get("registered_at")))
        evaluated_at = datetime.fromisoformat(str(result.get("evaluated_at")))
    except ValueError:
        return False
    all_protocol_events = [
        event for event in events
        if getattr(event, "event_type", "") == "CapitalProtocolRegistered"
        and event.payload.get("plan_version_id") == protocol.get("plan_version_id")
        and event.payload.get("control") == control
    ]
    protocol_events = [
        event for event in all_protocol_events
        if event.payload.get("protocol_content_id") == protocol_content_id
    ]
    evaluation_events = [
        event for event in events
        if getattr(event, "event_type", "") == "CapitalControlEvaluated"
        and event.payload.get("plan_version_id") == protocol.get("plan_version_id")
        and event.payload.get("control") == control
        and event.payload.get("result_content_id") == result_content_id
    ]
    return (
        registered_at.tzinfo is not None
        and evaluated_at.tzinfo is not None
        and registered_at < evaluated_at
        and len(protocol_events) == 1
        and len(all_protocol_events) == 1
        and len(evaluation_events) == 1
        and protocol_events[0].recorded_at < evaluation_events[0].recorded_at
        and evaluation_events[0].recorded_at < evidence_recorded_at
    )


def _criteria_bind_result(
    control: str,
    criteria: Mapping[str, object],
    metrics: Mapping[str, object],
) -> bool:
    if control == "portfolio_level":
        return set(criteria) == {"cost_model_id", "max_drawdown_limit_pct"} and (
            criteria["cost_model_id"] == metrics.get("cost_model_id")
            and _finite_number(criteria["max_drawdown_limit_pct"])
            and float(metrics.get("max_drawdown_pct", float("inf")))
            <= float(criteria["max_drawdown_limit_pct"])
        )
    if control == "point_in_time_universe":
        return set(criteria) == {"minimum_sessions", "minimum_instruments"} and (
            metrics.get("eligible_sessions", 0) >= criteria["minimum_sessions"]
            and metrics.get("instrument_count", 0) >= criteria["minimum_instruments"]
        )
    if control == "corporate_actions_adjusted":
        return set(criteria) == {"accepted_adjustment_policies", "require_action_lineage"} and (
            criteria["require_action_lineage"] is True
            and set(metrics.get("adjustment_policies", ()))
            <= set(criteria["accepted_adjustment_policies"])
        )
    if control == "purged_walk_forward":
        return set(criteria) == {
            "folds", "purge_sessions", "embargo_sessions", "minimum_median_fold_cagr_pct"
        } and (
            metrics.get("folds") == criteria["folds"]
            and metrics.get("purge_sessions") == criteria["purge_sessions"]
            and metrics.get("embargo_sessions") == criteria["embargo_sessions"]
            and float(metrics.get("median_fold_cagr_pct", float("-inf")))
            >= float(criteria["minimum_median_fold_cagr_pct"])
        )
    if control == "multiple_testing_controlled":
        return set(criteria) == {"hypotheses_tested", "method", "adjusted_alpha"} and all(
            metrics.get(key) == criteria[key]
            for key in ("hypotheses_tested", "method", "adjusted_alpha")
        )
    return set(criteria) == {"holdout_id", "threshold", "maximum_access_count"} and (
        metrics.get("holdout_id") == criteria["holdout_id"]
        and metrics.get("threshold") == criteria["threshold"]
        and metrics.get("access_count", 0) <= criteria["maximum_access_count"] == 1
    )


def _verify_control_support_artifacts(
    control: str,
    metrics: Mapping[str, object],
    artifact_root: Path,
    *,
    plan_id: str,
    producer_id: str,
    verifier_id: str,
    snapshot,
    events: Sequence[object],
) -> list[str]:
    if control == "portfolio_level":
        artifact, reasons = _read_json_artifact(
            metrics["portfolio_path_content_id"], artifact_root
        )
        if reasons:
            return reasons
        return [] if artifact is not None and _portfolio_artifact_matches(
            artifact,
            metrics,
            plan_id=plan_id,
            producer_id=producer_id,
            verifier_id=verifier_id,
            snapshot=snapshot,
        ) else ["capital_portfolio_path_invalid"]
    if control == "corporate_actions_adjusted":
        lineage_ids = {
            item.sha256 for item in snapshot.lineage.artifacts
            if item.role.startswith("corporate-actions:")
        }
        policies_match = set(metrics["adjustment_policies"]) == set(
            snapshot.lineage.adjustment_policies
        )
        return [] if (
            set(metrics["corporate_action_artifact_ids"]) == lineage_ids
            and lineage_ids
            and policies_match
        ) else [
            "capital_corporate_action_lineage_mismatch"
        ]
    if control == "point_in_time_universe":
        eligible_sessions = {
            timestamp.date()
            for instrument_id in snapshot.instrument_ids
            for timestamp in snapshot.frame(instrument_id).index
            if snapshot.entry_eligible_on(instrument_id, timestamp.date())
        }
        return [] if (
            metrics["instrument_count"] == len(snapshot.instrument_ids)
            and metrics["eligible_sessions"] == len(eligible_sessions)
        ) else ["capital_point_in_time_metrics_mismatch"]
    if control == "locked_holdout_passed":
        artifact, reasons = _read_json_artifact(
            metrics["access_ledger_content_id"], artifact_root
        )
        expected = {
            "artifact_type": "locked_holdout_access_ledger",
            "schema_version": "1.0",
            "plan_version_id": plan_id,
            "holdout_id": metrics["holdout_id"],
            "access_count": 1,
            "verifier_id": verifier_id,
        }
        access_events = [
            event for event in events
            if getattr(event, "event_type", "") == "LockedHoldoutAccessed"
            and event.payload.get("plan_version_id") == plan_id
            and event.payload.get("holdout_id") == metrics["holdout_id"]
        ]
        protocol_events = [
            event for event in events
            if getattr(event, "event_type", "") == "CapitalProtocolRegistered"
            and event.payload.get("plan_version_id") == plan_id
            and event.payload.get("control") == control
        ]
        evaluation_events = [
            event for event in events
            if getattr(event, "event_type", "") == "CapitalControlEvaluated"
            and event.payload.get("plan_version_id") == plan_id
            and event.payload.get("control") == control
        ]
        if reasons:
            return reasons
        return [] if (
            artifact == expected
            and len(access_events) == 1
            and access_events[0].payload.get("access_ledger_content_id")
            == metrics["access_ledger_content_id"]
            and len(protocol_events) == 1
            and protocol_events[0].recorded_at < access_events[0].recorded_at
            and len(evaluation_events) == 1
            and access_events[0].recorded_at < evaluation_events[0].recorded_at
        ) else [
            "capital_holdout_access_ledger_invalid"
        ]
    return []


def _portfolio_artifact_matches(
    artifact: Mapping[str, object],
    metrics: Mapping[str, object],
    *,
    plan_id: str,
    producer_id: str,
    verifier_id: str,
    snapshot,
) -> bool:
    expected_keys = {
        "artifact_type", "schema_version", "plan_version_id", "producer_id",
        "verifier_id", "shared_cash", "sizing_rails", "cost_model_id",
        "initial_cash", "total_costs", "equity_path", "trades",
    }
    if set(artifact) != expected_keys or any((
        artifact.get("artifact_type") != "capital_portfolio_path",
        artifact.get("schema_version") != "1.0",
        artifact.get("plan_version_id") != plan_id,
        artifact.get("producer_id") != producer_id,
        artifact.get("verifier_id") != verifier_id,
        artifact.get("shared_cash") is not True,
        not isinstance(artifact.get("sizing_rails"), Mapping),
        artifact.get("cost_model_id") != metrics["cost_model_id"],
    )):
        return False
    path = artifact.get("equity_path")
    trades = artifact.get("trades")
    if (
        not isinstance(path, list) or len(path) < 2 or len(path) > 100_000
        or not isinstance(trades, list) or not trades or len(trades) > 100_000
        or metrics["observations"] != len(path)
    ):
        return False
    try:
        if any(
            set(item) != {"session", "cash", "positions", "equity"}
            for item in path
        ):
            return False
        trade_keys = {
            "trade_id", "instrument_id", "entry_session", "exit_session", "quantity",
            "entry_price", "exit_price", "costs",
        }
        if any(set(item) != trade_keys for item in trades):
            return False
        sessions = [date.fromisoformat(str(item["session"])) for item in path]
        equities = [float(item["equity"]) for item in path]
        ordered_trades = sorted(trades, key=lambda item: (
            date.fromisoformat(str(item["entry_session"])), str(item["trade_id"])
        ))
        trade_costs = [float(item["costs"]) for item in ordered_trades]
    except (KeyError, TypeError, ValueError):
        return False
    if (
        sessions != sorted(set(sessions))
        or any(not _finite_number(value) or value <= 0 for value in equities)
        or any(not _finite_number(value) or value < 0 for value in trade_costs)
        or not _finite_number(artifact.get("initial_cash"))
        or float(artifact["initial_cash"]) != equities[0]
        or not _finite_number(artifact.get("total_costs"))
        or abs(float(artifact["total_costs"]) - sum(trade_costs)) > 1e-9
    ):
        return False
    rails = artifact["sizing_rails"]
    if set(rails) != {"max_positions", "max_position_pct"} or (
        not _positive_int(rails["max_positions"])
        or not _finite_number(rails["max_position_pct"])
        or not 0 < float(rails["max_position_pct"]) <= 1
    ):
        return False
    close_by_instrument: dict[str, dict[date, float]] = {}
    market_sessions: set[date] = set()
    for instrument_id in snapshot.instrument_ids:
        frame = snapshot.frame(instrument_id)
        closes = {
            timestamp.date(): float(value)
            for timestamp, value in frame["close"].items()
        }
        close_by_instrument[instrument_id] = closes
        market_sessions.update(closes)
    if sessions != sorted(market_sessions):
        return False
    entries: dict[date, list[Mapping[str, object]]] = {}
    exits: dict[date, list[Mapping[str, object]]] = {}
    seen_trade_ids: set[str] = set()
    for trade in ordered_trades:
        try:
            trade_id = str(trade["trade_id"])
            instrument_id = str(trade["instrument_id"])
            entry_session = date.fromisoformat(str(trade["entry_session"]))
            exit_session = date.fromisoformat(str(trade["exit_session"]))
            quantity = trade["quantity"]
            entry_price = float(trade["entry_price"])
            exit_price = float(trade["exit_price"])
            costs = float(trade["costs"])
        except (TypeError, ValueError):
            return False
        if (
            not trade_id or trade_id in seen_trade_ids
            or instrument_id not in close_by_instrument
            or not _positive_int(quantity)
            or not _finite_number(entry_price) or entry_price <= 0
            or not _finite_number(exit_price) or exit_price <= 0
            or not _finite_number(costs) or costs < 0
            or exit_session <= entry_session
            or entry_session not in close_by_instrument[instrument_id]
            or exit_session not in close_by_instrument[instrument_id]
            or not snapshot.entry_eligible_on(instrument_id, entry_session)
            or any(
                market_session not in close_by_instrument[instrument_id]
                for market_session in sessions
                if entry_session <= market_session <= exit_session
            )
            or abs(entry_price - close_by_instrument[instrument_id][entry_session]) > 1e-9
            or abs(exit_price - close_by_instrument[instrument_id][exit_session]) > 1e-9
        ):
            return False
        seen_trade_ids.add(trade_id)
        entries.setdefault(entry_session, []).append(trade)
        exits.setdefault(exit_session, []).append(trade)
    cash = float(artifact["initial_cash"])
    active: dict[str, Mapping[str, object]] = {}
    replay_equities: list[float] = []
    for session, supplied in zip(sessions, path):
        for trade in exits.get(session, ()):
            trade_id = str(trade["trade_id"])
            if trade_id not in active:
                return False
            cash += (
                int(trade["quantity"]) * float(trade["exit_price"])
                - float(trade["costs"])
            )
            if cash < 0:
                return False
            active.pop(trade_id)
        for trade in entries.get(session, ()):
            instrument_id = str(trade["instrument_id"])
            quantity = int(trade["quantity"])
            cost = quantity * float(trade["entry_price"])
            marked_equity = cash + sum(
                int(item["quantity"])
                * close_by_instrument[str(item["instrument_id"])][session]
                for item in active.values()
            )
            active_instruments = {
                str(item["instrument_id"]) for item in active.values()
            }
            existing_instrument_exposure = sum(
                int(item["quantity"])
                * close_by_instrument[instrument_id][session]
                for item in active.values()
                if str(item["instrument_id"]) == instrument_id
            )
            if (
                cost > cash
                or len(active_instruments | {instrument_id})
                > int(rails["max_positions"])
                or (existing_instrument_exposure + cost) / marked_equity
                > float(rails["max_position_pct"])
            ):
                return False
            cash -= cost
            active[str(trade["trade_id"])] = trade
        positions = {
            trade_id: int(trade["quantity"])
            * close_by_instrument[str(trade["instrument_id"])][session]
            for trade_id, trade in sorted(active.items())
        }
        equity = cash + sum(positions.values())
        supplied_positions = supplied["positions"]
        try:
            supplied_cash = float(supplied["cash"])
            supplied_equity = float(supplied["equity"])
            positions_match = (
                isinstance(supplied_positions, Mapping)
                and set(supplied_positions) == set(positions)
                and all(
                    _finite_number(float(supplied_positions[key]))
                    and abs(float(supplied_positions[key]) - value) <= 1e-9
                    for key, value in positions.items()
                )
            )
        except (TypeError, ValueError):
            return False
        if (
            not _finite_number(supplied_cash)
            or supplied_cash < 0
            or not _finite_number(supplied_equity)
            or not positions_match
            or abs(supplied_cash - cash) > 1e-9
            or abs(supplied_equity - equity) > 1e-9
        ):
            return False
        replay_equities.append(equity)
    if active or any(
        abs(actual - expected) > 1e-9
        for actual, expected in zip(equities, replay_equities)
    ):
        return False
    peak = equities[0]
    max_drawdown_pct = 0.0
    for equity in equities:
        peak = max(peak, equity)
        max_drawdown_pct = max(max_drawdown_pct, (peak - equity) / peak * 100)
    elapsed_years = (sessions[-1] - sessions[0]).days / 365.25
    if elapsed_years <= 0:
        return False
    try:
        cagr_pct = (
            (equities[-1] / equities[0]) ** (1 / elapsed_years) - 1
        ) * 100
    except (OverflowError, ValueError, ZeroDivisionError):
        return False
    if not _finite_number(cagr_pct):
        return False
    return (
        abs(float(metrics["max_drawdown_pct"]) - max_drawdown_pct) <= 1e-9
        and abs(float(metrics["cagr_pct"]) - cagr_pct) <= 1e-9
    )


def _valid_control_metrics(control: str, value: object) -> bool:
    if not isinstance(value, Mapping) or set(value) != _CAPITAL_CONTROL_METRIC_KEYS[control]:
        return False
    if control == "portfolio_level":
        return (
            _is_content_id(value["portfolio_path_content_id"])
            and value["shared_cash"] is True
            and value["sizing_rails"] is True
            and bool(str(value["cost_model_id"]))
            and _finite_number(value["max_drawdown_pct"])
            and _finite_number(value["cagr_pct"])
            and _positive_int(value["observations"])
        )
    if control == "point_in_time_universe":
        return (
            _is_content_id(value["snapshot_id"])
            and _positive_int(value["eligible_sessions"])
            and _positive_int(value["instrument_count"])
        )
    if control == "corporate_actions_adjusted":
        policies = value["adjustment_policies"]
        artifacts = value["corporate_action_artifact_ids"]
        return (
            _is_content_id(value["snapshot_id"])
            and isinstance(policies, list) and bool(policies)
            and set(policies) <= {"split_adjusted", "split_and_dividend_adjusted"}
            and isinstance(artifacts, list) and bool(artifacts)
            and all(_is_content_id(item) for item in artifacts)
        )
    if control == "purged_walk_forward":
        return (
            isinstance(value["folds"], int) and value["folds"] >= 3
            and _positive_int(value["purge_sessions"])
            and _positive_int(value["embargo_sessions"])
            and _finite_number(value["median_fold_cagr_pct"])
        )
    if control == "multiple_testing_controlled":
        return (
            _positive_int(value["hypotheses_tested"])
            and value["method"] in {"bonferroni", "holm", "fdr_bh"}
            and _finite_number(value["adjusted_alpha"])
            and 0 < float(value["adjusted_alpha"]) <= 0.05
            and value["passed"] is True
        )
    return (
        bool(str(value["holdout_id"]))
        and _is_content_id(value["access_ledger_content_id"])
        and value["access_count"] == 1
        and _finite_number(value["threshold"])
        and _finite_number(value["observed"])
        and float(value["observed"]) >= float(value["threshold"])
        and value["passed"] is True
    )


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value == value
        and value not in {float("inf"), float("-inf")}
    )


def _is_content_id(value: object) -> bool:
    text = str(value)
    return (
        len(text) == 71
        and text.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in text[7:])
    )


def _live_execution_backend_check() -> CertificationCheck:
    return CertificationCheck(
        "live_execution_backend",
        False,
        (
            "No live broker adapter, canary interlock, or live reconciliation "
            "rehearsal is implemented"
        ),
        {
            "implemented_backend": "governed_paper",
            "live_orders_authorized": False,
        },
    )
def _rehearsal_matches(
    rehearsal: Mapping[str, object],
    *,
    journal_path: Path,
    config_path: Path,
    now: datetime,
    event_count: int,
) -> bool:
    try:
        generated = datetime.fromisoformat(str(rehearsal["as_of"]))
        binding = rehearsal["diagnostics"]["evidence_binding"]
        return (
            generated.tzinfo is not None
            and timedelta(0) <= now - generated <= timedelta(hours=24)
            and binding["source_journal_sha256"] == _file_digest(journal_path)
            and binding["scheduler_config_sha256"] == _file_digest(config_path)
            and binding["source_code_sha256"] == _tree_digest(
                Path(__file__).resolve().parents[1]
            )
            and int(binding["source_events"]) == event_count
        )
    except (KeyError, TypeError, ValueError, OSError):
        return False


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*.py")):
        digest.update(str(item.relative_to(path)).encode())
        digest.update(item.read_bytes())
    return digest.hexdigest()


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
