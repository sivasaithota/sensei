"""Research-only assessment of repeated strategy validation campaigns.

This module turns a cost ladder into an explicit next research action.  It is
intentionally unable to write the Playbook, consume confirmation data, or
authorize trading.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import fcntl
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .campaign import StrategyValidationCampaignReport, StrategyValidationResult


class CycleDisposition(str, Enum):
    RETIRE_HYPOTHESIS = "retire_hypothesis"
    REVISE_HYPOTHESIS = "revise_hypothesis"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"
    ADVANCE_TO_PORTFOLIO_REPLAY = "advance_to_portfolio_replay"


@dataclass(frozen=True)
class StrategyCycleDecision:
    strategy: str
    disposition: CycleDisposition
    baseline_cost_pct: float
    stress_cost_pct: float
    baseline_expectancy_pct: float
    stress_expectancy_pct: float
    stress_profit_factor: float | None
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["disposition"] = self.disposition.value
        payload["reason_codes"] = list(self.reason_codes)
        return payload


@dataclass(frozen=True)
class ResearchCycleReport:
    cycle_id: str
    campaign_ids: tuple[str, ...]
    costs_pct: tuple[float, ...]
    variants_tested: int
    maximum_variants: int
    data_quality_blockers: tuple[str, ...]
    decisions: tuple[StrategyCycleDecision, ...]
    ready_for_portfolio_replay: bool
    ready_for_confirmation: bool
    locked_confirmation_consumed: bool = False
    can_change_playbook: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "campaign_ids": list(self.campaign_ids),
            "costs_pct": list(self.costs_pct),
            "variants_tested": self.variants_tested,
            "maximum_variants": self.maximum_variants,
            "data_quality_blockers": list(self.data_quality_blockers),
            "decisions": [decision.to_dict() for decision in self.decisions],
            "ready_for_portfolio_replay": self.ready_for_portfolio_replay,
            "ready_for_confirmation": self.ready_for_confirmation,
            "locked_confirmation_consumed": self.locked_confirmation_consumed,
            "can_change_playbook": self.can_change_playbook,
            "limitations": [
                "Research-cycle evidence cannot change the active Playbook.",
                "Cost-ladder runs reuse the same history and are not independent trials.",
                "Portfolio replay and one-use locked confirmation remain separate gates.",
            ],
        }


def assess_research_cycle(
    *,
    cycle_id: str,
    campaigns: tuple[StrategyValidationCampaignReport, ...],
    maximum_variants: int,
) -> ResearchCycleReport:
    """Classify fixed hypotheses after the same data is stressed for costs."""

    if not cycle_id.strip():
        raise ValueError("cycle_id is required")
    if len(campaigns) < 2:
        raise ValueError("at least two cost campaigns are required")
    ordered = tuple(sorted(campaigns, key=lambda campaign: campaign.cost_pct))
    costs = tuple(campaign.cost_pct for campaign in ordered)
    if len(set(costs)) != len(costs):
        raise ValueError("research-cycle costs must be unique")
    identity = (
        ordered[0].input_fingerprint,
        ordered[0].execution_fingerprint,
        ordered[0].folds,
        ordered[0].thresholds,
        ordered[0].locked_confirmation_consumed,
    )
    if any(
        (
            campaign.input_fingerprint,
            campaign.execution_fingerprint,
            campaign.folds,
            campaign.thresholds,
            campaign.locked_confirmation_consumed,
        ) != identity
        for campaign in ordered[1:]
    ):
        raise ValueError("cost campaigns must share the same input and execution identity")

    names = tuple(strategy.name for strategy in ordered[0].strategies)
    if any(
        tuple(strategy.name for strategy in campaign.strategies) != names
        for campaign in ordered[1:]
    ):
        raise ValueError("campaigns must contain the same strategy set and order")
    if maximum_variants < len(names):
        raise ValueError("research-cycle variant budget is exhausted")

    blockers = tuple(sorted({
        blocker
        for campaign in ordered
        for blocker in campaign.data_quality_blockers
    }))
    decisions = tuple(
        _decision(
            name,
            tuple(_strategy(campaign, name) for campaign in ordered),
            costs,
        )
        for name in names
    )
    ready_for_portfolio = (
        not blockers
        and bool(decisions)
        and all(
            decision.disposition is CycleDisposition.ADVANCE_TO_PORTFOLIO_REPLAY
            for decision in decisions
        )
    )
    return ResearchCycleReport(
        cycle_id=cycle_id,
        campaign_ids=tuple(campaign.campaign_id for campaign in ordered),
        costs_pct=costs,
        variants_tested=len(names),
        maximum_variants=maximum_variants,
        data_quality_blockers=blockers,
        decisions=decisions,
        ready_for_portfolio_replay=ready_for_portfolio,
        ready_for_confirmation=False,
    )


class ResearchCycleLedger:
    """Durable preregistration and cumulative family variant budget."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def preregister(
        self,
        *,
        family_id: str,
        cycle_id: str,
        variant_ids: tuple[str, ...],
        maximum_variants: int,
        costs_pct: tuple[float, ...],
        folds: int,
        input_fingerprint: str,
        execution_fingerprint: str,
        campaign_ids: tuple[str, ...] = (),
        success_criteria: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        if not family_id.strip() or not cycle_id.strip():
            raise ValueError("family_id and cycle_id are required")
        if len(costs_pct) < 2 or tuple(sorted(set(costs_pct))) != costs_pct:
            raise ValueError("cost ladder needs at least two unique ascending costs")
        if not variant_ids or len(set(variant_ids)) != len(variant_ids):
            raise ValueError("variant IDs must be non-empty and unique")
        payload = {
            "family_id": family_id,
            "cycle_id": cycle_id,
            "variant_ids": list(sorted(variant_ids)),
            "maximum_variants": maximum_variants,
            "costs_pct": list(costs_pct),
            "folds": folds,
            "input_fingerprint": input_fingerprint,
            "execution_fingerprint": execution_fingerprint,
            "campaign_ids": list(campaign_ids),
            "success_criteria": dict(success_criteria or {}),
        }
        with self._lock():
            return self._preregister_locked(payload, maximum_variants, variant_ids)

    def _preregister_locked(self, payload, maximum_variants, variant_ids):
        family_id, cycle_id = payload["family_id"], payload["cycle_id"]
        entries = self._read()
        existing = next(
            (
                entry for entry in entries
                if entry["family_id"] == family_id and entry["cycle_id"] == cycle_id
            ),
            None,
        )
        if existing is not None:
            comparable = {key: existing[key] for key in payload}
            if comparable != payload:
                raise ValueError("cycle identity cannot be reused with changed inputs")
            return existing
        family = [entry for entry in entries if entry["family_id"] == family_id]
        if family and any(
            int(entry["maximum_variants"]) != maximum_variants for entry in family
        ):
            raise ValueError("family maximum variant budget cannot change")
        attempted = {
            str(variant)
            for entry in family
            for variant in entry["variant_ids"]
        } | set(variant_ids)
        if len(attempted) > maximum_variants:
            raise ValueError("family variant budget is exhausted")
        record = {**payload, "status": "REGISTERED"}
        entries.append(record)
        self._write(entries)
        return record

    def complete(self, family_id: str, cycle_id: str) -> None:
        with self._lock():
            entries = self._read()
            record = next(
                (
                    entry for entry in entries
                    if entry["family_id"] == family_id and entry["cycle_id"] == cycle_id
                ),
                None,
            )
            if record is None:
                raise ValueError("research cycle was not preregistered")
            record["status"] = "COMPLETED"
            self._write(entries)

    @contextmanager
    def _lock(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        with lock_path.open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        value = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise ValueError("research cycle ledger must contain a list")
        return [dict(item) for item in value]

    def _write(self, entries: list[dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(entries, indent=2, sort_keys=True), encoding="utf-8"
        )
        temporary.replace(self._path)


def strategy_variant_ids(
    strategies: dict[str, dict[str, object]], *, universe_id: str,
) -> tuple[str, ...]:
    """Content identities for every attempted executable hypothesis."""

    identities = []
    for name, spec in sorted(strategies.items()):
        function = spec.get("fn")
        try:
            source = inspect.getsource(function)  # type: ignore[arg-type]
        except (OSError, TypeError):
            source = repr(function)
        payload = {
            "name": name,
            "universe_id": universe_id,
            "source": source,
            "stop_pct": spec["stop_pct"],
            "target_pct": spec["target_pct"],
            "max_hold_days": spec["max_hold_days"],
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        identities.append("variant:" + digest)
    return tuple(identities)


def _strategy(
    campaign: StrategyValidationCampaignReport, name: str,
) -> StrategyValidationResult:
    return next(strategy for strategy in campaign.strategies if strategy.name == name)


def _decision(
    name: str,
    results: tuple[StrategyValidationResult, ...],
    costs: tuple[float, ...],
) -> StrategyCycleDecision:
    baseline, stress = results[0], results[-1]
    reasons = tuple(sorted({code for result in results for code in result.reason_codes}))
    if any(_inconclusive(result) for result in results):
        disposition = CycleDisposition.NEEDS_MORE_EVIDENCE
    elif not _economic_pass(baseline):
        disposition = CycleDisposition.RETIRE_HYPOTHESIS
    elif not all(_economic_pass(result) for result in results[1:]):
        disposition = CycleDisposition.REVISE_HYPOTHESIS
    else:
        disposition = CycleDisposition.ADVANCE_TO_PORTFOLIO_REPLAY
    stress_holdout = stress.folds[-1].metrics
    return StrategyCycleDecision(
        strategy=name,
        disposition=disposition,
        baseline_cost_pct=costs[0],
        stress_cost_pct=costs[-1],
        baseline_expectancy_pct=baseline.folds[-1].metrics.expectancy_pct,
        stress_expectancy_pct=stress_holdout.expectancy_pct,
        stress_profit_factor=stress_holdout.profit_factor,
        reason_codes=reasons,
    )


def _inconclusive(result: StrategyValidationResult) -> bool:
    return result.verdict == "INCONCLUSIVE" or any(
        reason.startswith("INSUFFICIENT_") for reason in result.reason_codes
    )


def _economic_pass(result: StrategyValidationResult) -> bool:
    economic_failures = {
        reason for reason in result.reason_codes if reason != "DATA_QUALITY_BLOCKED"
    }
    return not economic_failures and result.verdict not in {
        "NOT_VALIDATED", "DATA_QUALITY_BLOCKED", "INCONCLUSIVE"
    }
