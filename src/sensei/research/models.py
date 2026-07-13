"""Stable domain records for governed strategy examination."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from sensei.backtest.rulespec import RuleSpec

_CLAIM_ID = re.compile(r"claim:[0-9a-f]{64}\Z")


def content_id(payload: object) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


@dataclass(frozen=True)
class HypothesisVersion:
    hypothesis_id: str
    version: int
    strategy: RuleSpec
    source_claim_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.hypothesis_id.strip():
            raise ValueError("hypothesis_id must not be empty")
        if self.version < 1:
            raise ValueError("hypothesis version must be positive")
        if not self.source_claim_ids:
            raise ValueError("at least one source claim is required")
        if any(
            _CLAIM_ID.fullmatch(claim_id) is None
            for claim_id in self.source_claim_ids
        ):
            raise ValueError("source claims must use content-addressed claim IDs")

    def identity_payload(self) -> dict:
        return {
            "hypothesis_id": self.hypothesis_id,
            "version": self.version,
            "strategy": self.strategy.model_dump(mode="json"),
            "source_claim_ids": list(self.source_claim_ids),
        }


@dataclass(frozen=True)
class EvaluationFold:
    name: str
    start: date
    end: date

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("fold name must not be empty")
        if self.start > self.end:
            raise ValueError("fold start must not be after its end")

    def identity_payload(self) -> dict:
        return {
            "name": self.name,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
        }


@dataclass(frozen=True)
class ExaminationProtocol:
    name: str
    version: int
    folds: tuple[EvaluationFold, ...]
    min_trades: int
    min_symbols: int
    min_expectancy_pct: float
    round_trip_cost_pct: float = 0.25
    min_hit_rate: float | None = None
    reserved_strategy_names: tuple[str, ...] = ()
    min_sessions_per_fold: int = 1

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("protocol name must not be empty")
        if self.version < 1:
            raise ValueError("protocol version must be positive")
        if not self.folds:
            raise ValueError("at least one evaluation fold is required")
        if self.min_trades < 1 or self.min_symbols < 1:
            raise ValueError("evidence minimums must be positive")
        if not math.isfinite(self.round_trip_cost_pct):
            raise ValueError("round-trip cost must be finite")
        if self.round_trip_cost_pct < 0:
            raise ValueError("round-trip cost must not be negative")
        if not math.isfinite(self.min_expectancy_pct):
            raise ValueError("minimum expectancy must be finite")
        if self.min_hit_rate is not None:
            if not math.isfinite(self.min_hit_rate):
                raise ValueError("minimum hit rate must be finite")
            if not 0 <= self.min_hit_rate <= 1:
                raise ValueError("minimum hit rate must be between zero and one")
        if self.min_sessions_per_fold < 1:
            raise ValueError("minimum sessions per fold must be positive")
        if any(not name.strip() for name in self.reserved_strategy_names):
            raise ValueError("reserved strategy names must not be empty")
        object.__setattr__(
            self,
            "reserved_strategy_names",
            tuple(sorted(set(self.reserved_strategy_names))),
        )

        previous_end: date | None = None
        for fold in self.folds:
            if previous_end is not None and fold.start <= previous_end:
                raise ValueError("evaluation folds must be chronological and non-overlapping")
            previous_end = fold.end

    def identity_payload(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "folds": [fold.identity_payload() for fold in self.folds],
            "min_trades": self.min_trades,
            "min_symbols": self.min_symbols,
            "min_expectancy_pct": self.min_expectancy_pct,
            "round_trip_cost_pct": self.round_trip_cost_pct,
            "min_hit_rate": self.min_hit_rate,
            "reserved_strategy_names": list(self.reserved_strategy_names),
            "min_sessions_per_fold": self.min_sessions_per_fold,
        }

    @property
    def protocol_id(self) -> str:
        return content_id(self.identity_payload())


class DossierStatus(str, Enum):
    QUARANTINED = "quarantined"


class Recommendation(str, Enum):
    REJECT = "reject"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"
    ELIGIBLE_FOR_SHADOW = "eligible_for_shadow"


class EvidenceIssueCode(str, Enum):
    STRATEGY_NAME_COLLISION = "strategy.name_collision"
    UNIVERSE_NOT_POINT_IN_TIME = "universe.not_point_in_time"
    MISSING_COLUMNS = "bars.missing_columns"
    INVALID_INDEX = "bars.invalid_index"
    EMPTY = "bars.empty"
    AFTER_SNAPSHOT_AS_OF = "bars.after_snapshot_as_of"
    NON_NUMERIC = "bars.non_numeric"
    NON_FINITE = "bars.non_finite"
    NON_POSITIVE_PRICE = "bars.non_positive_price"
    INVALID_OHLC = "bars.invalid_ohlc"
    NEGATIVE_VOLUME = "bars.negative_volume"
    INSUFFICIENT_FOLD_COVERAGE = "bars.insufficient_fold_coverage"


class EvidenceWarningCode(str, Enum):
    NO_PORTFOLIO_SIMULATION = "evidence.no_portfolio_simulation"
    REGIME_NOT_EXAMINED = "evidence.regime_not_examined"
    MULTIPLE_TESTING_NOT_CORRECTED = "evidence.multiple_testing_not_corrected"
    DAILY_DATA_ONLY = "evidence.daily_data_only"


class EvidenceSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    trades: int
    symbols_with_trades: int
    hit_rate: float | None
    expectancy_pct: float | None
    avg_win_pct: float | None
    avg_loss_pct: float | None
    worst_trade_pct: float | None
    stop_exits: int
    target_exits: int
    time_exits: int


class FoldEvidence(EvidenceSummary):
    name: str
    window_start: date
    window_end: date
    censored_trades: int


class EvidenceIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: EvidenceIssueCode
    detail: str
    symbol: str | None = None


class EvidenceWarning(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: EvidenceWarningCode
    detail: str


class EvidenceDossier(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    examiner_version: Literal["1.0"] = "1.0"
    experiment_id: str
    hypothesis_id: str
    hypothesis_version: int
    strategy_name: str
    snapshot_id: str
    protocol_id: str
    round_trip_cost_pct: float
    status: DossierStatus
    recommendation: Recommendation
    folds: tuple[FoldEvidence, ...]
    aggregate: EvidenceSummary
    censored_trades: int
    issues: tuple[EvidenceIssue, ...]
    warnings: tuple[EvidenceWarning, ...]
    reasons: tuple[str, ...]
