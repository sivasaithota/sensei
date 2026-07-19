"""Typed, evaluation-only records for measuring desk-agent value."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from sensei.memory import AgentMemoryRole


class AgentOutcome(str, Enum):
    PROCEED = "proceed"
    ABSTAIN = "abstain"
    VETO = "veto"
    ERROR = "error"


@dataclass(frozen=True)
class AgentInvocation:
    cycle_id: str
    episode_id: str | None
    role: AgentMemoryRole
    context_pack_id: str
    context_pack_audit_event_id: str
    prompt_id: str
    model_id: str
    outcome: AgentOutcome
    confidence: float | None
    latency_ms: int
    cost_microunits: int
    occurred_at: datetime

    def __post_init__(self) -> None:
        for label, value in (
            ("cycle_id", self.cycle_id),
            ("context_pack_id", self.context_pack_id),
            ("context_pack_audit_event_id", self.context_pack_audit_event_id),
            ("prompt_id", self.prompt_id),
            ("model_id", self.model_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label} is required")
        if not isinstance(self.role, AgentMemoryRole):
            raise TypeError("role must be an AgentMemoryRole")
        if not isinstance(self.outcome, AgentOutcome):
            raise TypeError("outcome must be an AgentOutcome")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between zero and one")
        if type(self.latency_ms) is not int or self.latency_ms < 0:
            raise ValueError("latency_ms must be a non-negative integer")
        if type(self.cost_microunits) is not int or self.cost_microunits < 0:
            raise ValueError("cost_microunits must be a non-negative integer")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        if self.episode_id is not None and not self.episode_id.strip():
            raise ValueError("episode_id must be non-empty when supplied")

    def to_payload(self) -> dict[str, object]:
        return {
            "cycle_id": self.cycle_id,
            "episode_id": self.episode_id,
            "role": self.role.value,
            "context_pack_id": self.context_pack_id,
            "context_pack_audit_event_id": self.context_pack_audit_event_id,
            "prompt_id": self.prompt_id,
            "model_id": self.model_id,
            "outcome": self.outcome.value,
            "confidence": self.confidence,
            "latency_ms": self.latency_ms,
            "cost_microunits": self.cost_microunits,
            "authority": "EVALUATION_ONLY",
        }


@dataclass(frozen=True)
class RoleEvaluation:
    invocations: int
    abstentions: int
    vetoes: int
    errors: int
    false_vetoes: int
    false_approvals: int
    average_latency_ms: int
    total_cost_microunits: int
    brier_score: float | None
    counterfactual_labels: int = 0


@dataclass(frozen=True)
class AgentEvaluationReport:
    as_of: datetime
    roles: Mapping[AgentMemoryRole, RoleEvaluation]
    authority: str = "EVALUATION_ONLY"
    can_authorize_trading: bool = False
    can_mutate_strategy: bool = False
    can_mutate_risk: bool = False

    def __post_init__(self) -> None:
        if self.authority != "EVALUATION_ONLY":
            raise ValueError("agent evaluation authority must be EVALUATION_ONLY")
        if self.can_authorize_trading or self.can_mutate_strategy or self.can_mutate_risk:
            raise ValueError("agent evaluation cannot carry mutation authority")
        object.__setattr__(self, "roles", MappingProxyType(dict(self.roles)))


@dataclass(frozen=True)
class AgentVariantReport:
    as_of: datetime
    variants: Mapping[str, RoleEvaluation]
    authority: str = "EVALUATION_ONLY"

    def __post_init__(self) -> None:
        if self.authority != "EVALUATION_ONLY":
            raise ValueError("agent variant reports are evaluation-only")
        object.__setattr__(self, "variants", MappingProxyType(dict(self.variants)))


@dataclass(frozen=True)
class CounterfactualReplayResult:
    simulated_net_pnl: Decimal
    horizon_closed_at: datetime
    evidence_event_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.simulated_net_pnl.is_finite():
            raise ValueError("counterfactual P&L must be finite")
        if self.horizon_closed_at.tzinfo is None or self.horizon_closed_at.utcoffset() is None:
            raise ValueError("counterfactual horizon must be timezone-aware")
        if not self.evidence_event_ids:
            raise ValueError("counterfactual replay requires market evidence")


@dataclass(frozen=True)
class AgentVariantDecision:
    prompt_id: str
    model_id: str
    outcome: AgentOutcome
    confidence: float | None = None
    cost_microunits: int = 0

    def __post_init__(self) -> None:
        if not self.prompt_id.strip() or not self.model_id.strip():
            raise ValueError("variant prompt and model IDs are required")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("variant confidence must be between zero and one")
        if type(self.cost_microunits) is not int or self.cost_microunits < 0:
            raise ValueError("variant cost must be a non-negative integer")
