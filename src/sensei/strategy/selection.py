"""Stock selection mathematics shared by paper and portfolio research."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass(frozen=True)
class RankingEvidence:
    expectancy_pct: float = 0.0
    hit_rate: float = 0.0
    trades: int = 0
    available_as_of: date | None = None

    def __post_init__(self):
        if type(self.trades) is not int or self.trades < 0:
            raise ValueError("evidence trade count must be nonnegative")
        if not math.isfinite(self.expectancy_pct) or not math.isfinite(self.hit_rate) or not 0 <= self.hit_rate <= 1:
            raise ValueError("invalid ranking evidence")


def selection_tie_breaker(plan_id: str, instrument_id: str) -> str:
    symbol = instrument_id if instrument_id.startswith("NSE:") else f"NSE:{instrument_id}"
    return hashlib.sha256(f"{plan_id}:{symbol}".encode()).hexdigest()


def average_turnover(frame: pd.DataFrame) -> float:
    """Use reported turnover when supplied, otherwise close times volume."""
    frame = current_identity_history(frame)
    values = frame["turnover"] if "turnover" in frame else frame["close"] * frame["volume"]
    return float(values.tail(60).mean())


def current_identity_history(frame: pd.DataFrame) -> pd.DataFrame:
    """Research frames may explicitly reset history after identity/unit changes.

    The caller supplies an as-of prefix. Legacy frames have no epoch column and
    retain identical behavior. No return crosses an explicitly recorded reset.
    """
    if frame.empty or "research_history_epoch" not in frame:
        return frame
    epochs = frame["research_history_epoch"]
    if (epochs.isna().any() or not epochs.is_monotonic_increasing
            or not pd.api.types.is_integer_dtype(epochs.dtype)):
        raise ValueError("research history epochs must be ordered integers")
    return frame.loc[epochs == epochs.iloc[-1]]


@dataclass(frozen=True)
class CandidateScore:
    momentum_20: float
    momentum_63: float
    range_position: float
    volume_confirmation: float
    reward_risk: float
    liquidity: float
    expectancy: float
    hit_rate: float
    evidence_depth: float
    total: float


@dataclass(frozen=True)
class SignalRankingPolicy:
    version: str = "full-universe-market-quality-dated-evidence-v2"
    maximum_reward_risk: float = 5.0
    maximum_expectancy_pct: float = 3.0
    evidence_depth_log_scale: float = 4.0
    liquidity_log_floor: float = 6.0
    liquidity_log_span: float = 4.0
    momentum_floor: float = -0.20
    momentum_span: float = 0.60
    correlation_lookback_sessions: int = 60
    maximum_pairwise_correlation: float = 0.85
    weight_momentum_20: float = 0.20
    weight_momentum_63: float = 0.20
    weight_range_position: float = 0.15
    weight_volume_confirmation: float = 0.10
    weight_reward_risk: float = 0.10
    weight_liquidity: float = 0.10
    weight_expectancy: float = 0.10
    weight_hit_rate: float = 0.025
    weight_evidence_depth: float = 0.025

    def score(
        self, *, frame: pd.DataFrame, average_turnover_inr: float,
        stop_pct: float, target_pct: float, as_of: date,
        evidence: RankingEvidence = RankingEvidence(),
    ) -> CandidateScore:
        frame = frame.loc[frame.index.date <= as_of]
        frame = current_identity_history(frame)
        if frame.empty:
            raise ValueError("ranking needs observations available as of the decision")
        if evidence.available_as_of is None or evidence.available_as_of > as_of:
            evidence = RankingEvidence()
        closes = frame["close"].astype(float)
        volumes = frame["volume"].astype(float)
        latest = float(closes.iloc[-1])
        components = {
            "momentum_20": self._return_score(latest, closes, 21),
            "momentum_63": self._return_score(latest, closes, 64),
            "range_position": _range_position(closes.tail(252), latest),
            "volume_confirmation": _volume_confirmation(volumes),
            "reward_risk": min(
                1.0,
                (
                    target_pct / stop_pct
                ) / self.maximum_reward_risk,
            ),
            "liquidity": _clamp(
                (
                    math.log10(max(1.0, average_turnover_inr))
                    - self.liquidity_log_floor
                ) / self.liquidity_log_span
            ),
            "expectancy": _clamp(
                evidence.expectancy_pct / self.maximum_expectancy_pct
            ),
            "hit_rate": _clamp(evidence.hit_rate),
            "evidence_depth": _clamp(
                math.log10(evidence.trades + 1)
                / self.evidence_depth_log_scale
            ),
        }
        total = (
            components["momentum_20"] * self.weight_momentum_20
            + components["momentum_63"] * self.weight_momentum_63
            + components["range_position"] * self.weight_range_position
            + components["volume_confirmation"] * self.weight_volume_confirmation
            + components["reward_risk"] * self.weight_reward_risk
            + components["liquidity"] * self.weight_liquidity
            + components["expectancy"] * self.weight_expectancy
            + components["hit_rate"] * self.weight_hit_rate
            + components["evidence_depth"] * self.weight_evidence_depth
        )
        return CandidateScore(**components, total=total)

    def _return_score(
        self, latest: float, closes: pd.Series, offset: int
    ) -> float:
        if len(closes) < offset:
            return 0.5
        prior = float(closes.iloc[-offset])
        if prior <= 0 or not math.isfinite(prior) or not math.isfinite(latest):
            return 0.0
        change = latest / prior - 1.0
        return _clamp(
            (change - self.momentum_floor) / self.momentum_span
        )


def _range_position(closes: pd.Series, latest: float) -> float:
    low = float(closes.min())
    high = float(closes.max())
    if not all(math.isfinite(value) for value in (low, high, latest)):
        return 0.0
    if high <= low:
        return 0.5
    return _clamp((latest - low) / (high - low))


def return_correlation(
    left: pd.DataFrame, right: pd.DataFrame, *, lookback: int,
) -> float:
    left, right = current_identity_history(left), current_identity_history(right)
    left_returns = (
        left["close"].astype(float).pct_change(fill_method=None).iloc[:-1].tail(
            lookback
        )
    )
    right_returns = (
        right["close"].astype(float).pct_change(fill_method=None).iloc[:-1].tail(
            lookback
        )
    )
    paired = pd.concat(
        (left_returns.rename("left"), right_returns.rename("right")),
        axis=1,
        join="inner",
    ).dropna()
    if len(paired) < max(10, lookback // 2) or (paired.std() == 0).any():
        return 0.0
    correlation = float(paired["left"].corr(paired["right"]))
    return correlation if math.isfinite(correlation) else 0.0


def _volume_confirmation(volumes: pd.Series) -> float:
    history = volumes.iloc[-21:-1]
    if history.empty:
        return 0.5
    average = float(history.mean())
    latest = float(volumes.iloc[-1])
    if average <= 0 or not all(math.isfinite(value) for value in (average, latest)):
        return 0.0
    return _clamp((latest / average - 0.5) / 1.5)


def _clamp(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))
