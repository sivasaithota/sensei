"""Canonical, source-attributed strategy plans.

The models in this module deliberately make strategy authors spell out time.
There is no implicit "today" or "yesterday" in an entry rule: every market
observation carries a session offset.  Every configurable semantic value is
also paired with an authority classification, so a citation, a research
choice, and a safety limit cannot be silently blended together.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from enum import Enum
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

_CLAIM_ID = re.compile(r"claim:[0-9a-f]{64}\Z")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class FieldAuthority(str, Enum):
    """The authority under which a material plan value was introduced."""

    SOURCE_CLAIM = "source_claim"
    RESEARCH_ASSUMPTION = "research_assumption"
    SAFETY_OVERRIDE = "safety_override"


class FieldAttribution(_FrozenModel):
    """Lineage for one material value or one indivisible condition."""

    authority: FieldAuthority
    claim_ids: tuple[str, ...] = ()
    rationale: str | None = None

    @field_validator("claim_ids")
    @classmethod
    def _normalize_claim_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted({value.strip() for value in values if value.strip()}))
        if len(normalized) != len(values):
            raise ValueError("claim IDs must be non-empty and unique")
        if any(_CLAIM_ID.fullmatch(value) is None for value in normalized):
            raise ValueError("claim IDs must be content-addressed provenance claims")
        return normalized

    @field_validator("rationale")
    @classmethod
    def _normalize_rationale(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("rationale must not be blank")
        return normalized

    @model_validator(mode="after")
    def _require_source_lineage(self) -> FieldAttribution:
        if self.authority is FieldAuthority.SOURCE_CLAIM and not self.claim_ids:
            raise ValueError("source-claim attribution requires at least one claim ID")
        if self.authority is not FieldAuthority.SOURCE_CLAIM and self.rationale is None:
            raise ValueError("research assumptions and safety overrides require a rationale")
        return self


ValueT = TypeVar("ValueT")


class AttributedValue(_FrozenModel, Generic[ValueT]):
    """A configurable value that cannot exist without declared authority."""

    value: ValueT
    attribution: FieldAttribution


class ObservableField(str, Enum):
    OPEN = "open"
    HIGH = "high"
    LOW = "low"
    CLOSE = "close"
    VOLUME = "volume"
    HAMMER = "hammer"


class TemporalReference(_FrozenModel):
    """A market observation at an explicit offset from the evaluation session."""

    field: ObservableField
    sessions_ago: int = Field(ge=0, le=5_000)


class ComparisonOperator(str, Enum):
    GT = ">"
    GE = ">="
    LT = "<"
    LE = "<="
    EQ = "=="


class EntryCondition(_FrozenModel):
    """One fully attributed, deterministic comparison."""

    condition_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{2,79}$")
    left: TemporalReference
    operator: ComparisonOperator
    right: TemporalReference | float
    attribution: FieldAttribution

    @field_validator("right")
    @classmethod
    def _finite_constant(
        cls, value: TemporalReference | float
    ) -> TemporalReference | float:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("condition constants must be finite")
        return value


class EntryPolicy(_FrozenModel):
    """Daily foundation entry grammar: every listed condition must pass."""

    conditions: tuple[EntryCondition, ...] = Field(min_length=1, max_length=16)

    @field_validator("conditions")
    @classmethod
    def _unique_condition_ids(
        cls, conditions: tuple[EntryCondition, ...]
    ) -> tuple[EntryCondition, ...]:
        ids = [condition.condition_id for condition in conditions]
        if len(ids) != len(set(ids)):
            raise ValueError("entry condition IDs must be unique")
        return conditions


PositivePct = Annotated[float, Field(gt=0.0, le=100.0)]
PositiveSessions = Annotated[int, Field(ge=1, le=5_000)]
PositivePrice = Annotated[float, Field(gt=0.0)]
NonNegativeFloat = Annotated[float, Field(ge=0.0)]
RiskFraction = Annotated[float, Field(gt=0.0, le=0.10)]
PositionFraction = Annotated[float, Field(gt=0.0, le=1.0)]


class ExitPolicy(_FrozenModel):
    stop_loss_pct: AttributedValue[PositivePct]
    take_profit_pct: AttributedValue[PositivePct]
    max_hold_sessions: AttributedValue[PositiveSessions]


class TimingPolicy(_FrozenModel):
    """The first plan contract intentionally supports one honest daily timing."""

    decision_point: AttributedValue[Literal["session_close"]]
    entry_point: AttributedValue[Literal["next_session_open"]]


class SizingPolicy(_FrozenModel):
    """Risk-budget intent; this is not an order quantity calculation."""

    risk_budget_fraction: AttributedValue[RiskFraction]
    max_position_fraction: AttributedValue[PositionFraction]


class ApplicabilityPolicy(_FrozenModel):
    min_price: AttributedValue[PositivePrice]
    max_price: AttributedValue[PositivePrice]
    min_average_volume: AttributedValue[NonNegativeFloat]
    average_volume_lookback_sessions: AttributedValue[PositiveSessions]

    @model_validator(mode="after")
    def _ordered_prices(self) -> ApplicabilityPolicy:
        if self.min_price.value > self.max_price.value:
            raise ValueError("minimum price must not exceed maximum price")
        return self


class StrategyPlan(_FrozenModel):
    """An immutable, content-addressed daily long-only strategy definition.

    ``name`` is deliberately excluded from the content identity.  It is a
    display label, while ``plan_id`` identifies executable semantics and their
    lineage.
    """

    schema_version: Literal["1.0"] = "1.0"
    name: str = Field(min_length=3, max_length=120)
    strategy_family: AttributedValue[str]
    entry: EntryPolicy
    exits: ExitPolicy
    timing: TimingPolicy
    sizing: SizingPolicy
    applicability: ApplicabilityPolicy

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("strategy plan name must not be blank")
        return normalized

    @field_validator("strategy_family")
    @classmethod
    def _strategy_family_not_blank(
        cls, value: AttributedValue[str]
    ) -> AttributedValue[str]:
        if not value.value.strip():
            raise ValueError("strategy family must not be blank")
        return value

    def identity_payload(self) -> dict[str, object]:
        """Return all and only semantics that can change an engine decision."""

        return {
            "schema_version": self.schema_version,
            "engine_contract": "daily-long-only-v1",
            "side": "long",
            "bar_interval": "1d",
            "strategy_family": self.strategy_family.model_dump(mode="json"),
            "entry": self.entry.model_dump(mode="json"),
            "exits": self.exits.model_dump(mode="json"),
            "timing": self.timing.model_dump(mode="json"),
            "sizing": self.sizing.model_dump(mode="json"),
            "applicability": self.applicability.model_dump(mode="json"),
        }

    @property
    def plan_id(self) -> str:
        canonical = json.dumps(
            self.identity_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(canonical).hexdigest()}"

    @property
    def source_claim_ids(self) -> tuple[str, ...]:
        """Return the exact provenance claims carried by executable semantics."""

        claims: set[str] = set()

        def collect(value: object) -> None:
            if isinstance(value, dict):
                if value.get("authority") == FieldAuthority.SOURCE_CLAIM.value:
                    claims.update(str(item) for item in value.get("claim_ids", ()))
                for child in value.values():
                    collect(child)
            elif isinstance(value, (list, tuple)):
                for child in value:
                    collect(child)

        collect(self.identity_payload())
        return tuple(sorted(claims))


class DecisionAction(str, Enum):
    NO_ACTION = "no_action"
    ENTER_LONG = "enter_long"


class ConditionOutcome(_FrozenModel):
    condition_id: str
    left_reference: TemporalReference
    operator: ComparisonOperator
    right_reference: TemporalReference | None
    left_value: float | None
    right_value: float | None
    passed: bool


class ApplicabilityOutcome(_FrozenModel):
    check: Literal["price_range", "average_volume"]
    observed_value: float | None
    minimum: float | None = None
    maximum: float | None = None
    lookback_sessions: int | None = None
    passed: bool


class PlanSizingIntent(_FrozenModel):
    """A capital-allocation request, intentionally without units or quantity."""

    risk_budget_fraction: float
    max_position_fraction: float


class PlanExitIntent(_FrozenModel):
    stop_loss_pct: float
    take_profit_pct: float
    max_hold_sessions: int


class PlanDecisionTrace(_FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    plan_id: str
    instrument_id: str
    evaluation_session: str
    decision_point: Literal["session_close"] = "session_close"
    intended_entry_point: Literal["next_session_open"] = "next_session_open"
    action: DecisionAction
    applicability_outcomes: tuple[ApplicabilityOutcome, ...]
    condition_outcomes: tuple[ConditionOutcome, ...]
    reason_codes: tuple[str, ...]
    sizing_intent: PlanSizingIntent | None
    exit_intent: PlanExitIntent | None

    @property
    def trace_id(self) -> str:
        """Content identity propagated into every resulting Trade Intent."""

        canonical = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return f"trace:{hashlib.sha256(canonical).hexdigest()}"
