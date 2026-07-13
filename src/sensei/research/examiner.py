"""Coordination of deterministic, quarantined strategy examination."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sensei.backtest.rulespec import compile_spec
from sensei.research.artifacts import ImmutableEvidenceStore
from sensei.research.market_data import MarketDataSnapshot
from sensei.research.models import (
    DossierStatus,
    EvidenceDossier,
    EvidenceIssue,
    EvidenceIssueCode,
    EvidenceSummary,
    ExaminationProtocol,
    FoldEvidence,
    HypothesisVersion,
    Recommendation,
    content_id,
)
from sensei.research.simulation import ResearchTrade, simulate_fold, summarize

EXAMINER_VERSION = "1.0"


@dataclass(frozen=True)
class ExaminationRequest:
    hypothesis: HypothesisVersion
    snapshot: MarketDataSnapshot
    protocol: ExaminationProtocol


class ResearchExaminer:
    """Produce evidence for a hypothesis without promotion side effects."""

    def __init__(self, *, artifact_dir: Path | None = None) -> None:
        self._store = (
            ImmutableEvidenceStore(artifact_dir) if artifact_dir is not None else None
        )

    def examine(self, request: ExaminationRequest) -> EvidenceDossier:
        if any(fold.end > request.snapshot.as_of for fold in request.protocol.folds):
            raise ValueError("evaluation folds must end on or before the snapshot as-of")

        identity = {
            "examiner_version": EXAMINER_VERSION,
            "hypothesis": request.hypothesis.identity_payload(),
            "snapshot_id": request.snapshot.snapshot_id,
            "protocol": request.protocol.identity_payload(),
        }
        valid_frames, snapshot_issues = request.snapshot.validated_frames(
            request.protocol
        )
        issues = list(snapshot_issues)
        if (
            request.hypothesis.strategy.name
            in request.protocol.reserved_strategy_names
        ):
            issues.insert(
                0,
                EvidenceIssue(
                    code=EvidenceIssueCode.STRATEGY_NAME_COLLISION,
                    detail=(
                        "The candidate name collides with an existing strategy; "
                        "names are not strategy identity."
                    ),
                ),
            )

        signal_fn = compile_spec(request.hypothesis.strategy)
        signals_by_symbol = {
            symbol: signal_fn(frame) for symbol, frame in valid_frames.items()
        }
        fold_evidence: list[FoldEvidence] = []
        all_trades: list[ResearchTrade] = []
        total_censored = 0

        for fold in request.protocol.folds:
            fold_trades: list[ResearchTrade] = []
            fold_censored = 0
            for symbol, frame in valid_frames.items():
                simulation = simulate_fold(
                    symbol,
                    frame,
                    signals_by_symbol[symbol],
                    fold,
                    request.hypothesis.strategy,
                    request.protocol.round_trip_cost_pct,
                )
                fold_trades.extend(simulation.trades)
                fold_censored += simulation.censored_trades

            summary = summarize(fold_trades)
            fold_evidence.append(
                FoldEvidence(
                    name=fold.name,
                    window_start=fold.start,
                    window_end=fold.end,
                    censored_trades=fold_censored,
                    **summary.model_dump(),
                )
            )
            all_trades.extend(fold_trades)
            total_censored += fold_censored

        aggregate = summarize(all_trades)
        recommendation, reasons = _recommend(request.protocol, aggregate, issues)
        dossier = EvidenceDossier(
            experiment_id=content_id(identity),
            hypothesis_id=request.hypothesis.hypothesis_id,
            hypothesis_version=request.hypothesis.version,
            strategy_name=request.hypothesis.strategy.name,
            snapshot_id=request.snapshot.snapshot_id,
            protocol_id=request.protocol.protocol_id,
            round_trip_cost_pct=request.protocol.round_trip_cost_pct,
            status=DossierStatus.QUARANTINED,
            recommendation=recommendation,
            folds=tuple(fold_evidence),
            aggregate=aggregate,
            censored_trades=total_censored,
            issues=tuple(issues),
            reasons=reasons,
            limitations=(
                "Portfolio cash, concurrency, drawdown, and correlation were not simulated.",
                "Regime dependence was not examined.",
                "Multiple-hypothesis and parameter-selection bias were not corrected.",
                "Daily bars do not validate an intraday strategy.",
            ),
        )
        if self._store is not None:
            self._store.record(dossier)
        return dossier


def _recommend(
    protocol: ExaminationProtocol,
    evidence: EvidenceSummary,
    issues: Sequence[EvidenceIssue],
) -> tuple[Recommendation, tuple[str, ...]]:
    if issues:
        return (
            Recommendation.NEEDS_MORE_EVIDENCE,
            ("Evidence admissibility checks must pass before shadow eligibility.",),
        )
    if (
        evidence.trades < protocol.min_trades
        or evidence.symbols_with_trades < protocol.min_symbols
    ):
        return (
            Recommendation.NEEDS_MORE_EVIDENCE,
            ("The examined sample does not meet the protocol's evidence minimums.",),
        )
    failed_expectancy = (
        evidence.expectancy_pct is None
        or evidence.expectancy_pct < protocol.min_expectancy_pct
    )
    failed_hit_rate = protocol.min_hit_rate is not None and (
        evidence.hit_rate is None or evidence.hit_rate < protocol.min_hit_rate
    )
    if failed_expectancy or failed_hit_rate:
        return (
            Recommendation.REJECT,
            ("The evidence fails at least one configured performance threshold.",),
        )
    return (
        Recommendation.ELIGIBLE_FOR_SHADOW,
        ("The evidence clears the foundation protocol for a shadow trial only.",),
    )
