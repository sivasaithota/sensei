"""Boundary check for code paths that require canonical strategy semantics."""

from __future__ import annotations

from dataclasses import dataclass

from .models import StrategyPlan


@dataclass(frozen=True)
class StrategyConformance:
    conformant: bool
    plan_id: str | None
    issues: tuple[str, ...]


def assess_strategy_conformance(candidate: object) -> StrategyConformance:
    """Accept only canonical plans; legacy/free-form rule records never qualify."""

    if not isinstance(candidate, StrategyPlan):
        return StrategyConformance(
            conformant=False,
            plan_id=None,
            issues=("canonical_strategy_plan_required",),
        )
    return StrategyConformance(
        conformant=True,
        plan_id=candidate.plan_id,
        issues=(),
    )
