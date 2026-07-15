from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from sensei.backtest.rulespec import Condition, RuleSpec
from sensei.learning.outcomes import LearningScope, MistakeHypothesis
from sensei.operations.journal import (
    EventAppend,
    JournalIntegrityError,
    OperationalJournal,
)
from sensei.research import (
    EvaluationFold,
    ExaminationProtocol,
    HypothesisVersion,
    MarketDataSnapshot,
    Recommendation,
    ResearchBacktestLab,
    ResearchLabCandidate,
)
from sensei.reporting.research_lab import ResearchLabReporter

NOW = datetime(2026, 7, 15, 9, 30, tzinfo=timezone.utc)
CLAIM = "claim:" + "7" * 64


def target_trade_bars() -> pd.DataFrame:
    index = pd.bdate_range("2020-01-01", periods=10)
    return pd.DataFrame(
        {
            "open": [90, 90, 90, 100, 100, 100, 110, 110, 110, 110],
            "high": [91, 91, 91, 101, 101, 111, 111, 111, 111, 111],
            "low": [89, 89, 89, 99, 99, 99, 109, 109, 109, 109],
            "close": np.array([90, 90, 90, 100, 100, 110, 110, 110, 110, 110]),
            "volume": np.full(10, 1_000_000),
        },
        index=index,
    )


def coach_hypothesis() -> MistakeHypothesis:
    return MistakeHypothesis(
        hypothesis_id="hypothesis:" + "a" * 64,
        scope=LearningScope(
            strategy_lineage_id="breakout-lineage",
            plan_version_id="plan:baseline-v1",
            timeframe="1d",
            market_regime="trend",
            failure_type="late_entry",
        ),
        evidence_episode_ids=("EP-1", "EP-2", "EP-3"),
    )


def candidate() -> ResearchLabCandidate:
    bars = target_trade_bars()
    snapshot = MarketDataSnapshot._for_testing(
        bars_by_instrument={"NSE:TEST": bars},
        as_of=bars.index[-1].date(),
        universe_as_of=bars.index[-1].date(),
        point_in_time_universe=True,
        source="synthetic lab fixture",
    )
    strategy = RuleSpec(
        name="late_entry_filter",
        source="Coach hypothesis H plus researcher supplied executable rule.",
        principle="Avoid late entries by requiring a fresh two-day breakout.",
        conditions=(Condition(left="close", op=">", right="highest_2"),),
        stop_pct=5,
        target_pct=10,
        max_hold_days=5,
    )
    protocol = ExaminationProtocol(
        name="lab-foundation",
        version=1,
        folds=(EvaluationFold("oos", bars.index[0].date(), bars.index[-1].date()),),
        min_trades=1,
        min_symbols=1,
        min_expectancy_pct=1.0,
        round_trip_cost_pct=0.25,
    )
    return ResearchLabCandidate(
        coach_hypothesis=coach_hypothesis(),
        hypothesis=HypothesisVersion(
            hypothesis_id="H-LATE-ENTRY-FILTER",
            version=1,
            strategy=strategy,
            source_claim_ids=(CLAIM,),
        ),
        snapshot=snapshot,
        protocol=protocol,
        data_policy_id="synthetic-daily-pit-v1",
        minimum_effect_size=1.0,
        minimum_confidence_lower_bound=0.0,
        familywise_alpha=0.05,
    )


def test_lab_preregisters_examines_and_records_a_research_only_verdict(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    lab = ResearchBacktestLab(
        journal,
        artifact_dir=tmp_path / "evidence",
    )

    result = lab.run(candidate(), command_id="lab-run-1", occurred_at=NOW)

    assert result.registration.trial_number == 1
    assert result.dossier.recommendation is Recommendation.ELIGIBLE_FOR_SHADOW
    assert result.dossier.aggregate.expectancy_pct == 9.75
    assert result.shadow_eligible is True
    assert result.playbook_changed is False

    events = journal.read_stream(
        f"research_lab:{candidate().coach_hypothesis.hypothesis_id.removeprefix('hypothesis:')}"
    )
    assert [event.event_type for event in events] == ["ResearchLabDossierRecorded"]
    payload = events[0].payload
    assert payload["coach_hypothesis_id"] == candidate().coach_hypothesis.hypothesis_id
    assert payload["candidate_hypothesis_id"] == "H-LATE-ENTRY-FILTER"
    assert payload["examiner_recommendation"] == "eligible_for_shadow"
    assert payload["recommendation"] == "eligible_for_shadow"
    assert payload["authority"] == "RESEARCH_ONLY"
    assert payload["playbook_changed"] is False
    assert payload["artifact_recorded"] is True
    assert payload["effect_size"] == 9.75
    assert payload["minimum_effect_size"] == 1.0

    artifact_files = list((tmp_path / "evidence").glob("*.json"))
    assert len(artifact_files) == 1

    summary = ResearchLabReporter(journal).latest(limit=1)[0]
    assert summary.coach_hypothesis_id == candidate().coach_hypothesis.hypothesis_id
    assert summary.candidate_hypothesis_id == "H-LATE-ENTRY-FILTER"
    assert summary.recommendation == "eligible_for_shadow"
    assert summary.shadow_eligible is True
    assert summary.trades == 1
    assert summary.expectancy_pct == 9.75


def test_lab_replay_is_idempotent_and_rejects_command_reuse(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    lab = ResearchBacktestLab(journal)
    first = lab.run(candidate(), command_id="lab-run-1", occurred_at=NOW)

    assert lab.run(candidate(), command_id="lab-run-1", occurred_at=NOW) == first

    revised = candidate().hypothesis.strategy.model_copy(update={"target_pct": 11.0})
    changed_candidate = candidate().with_hypothesis(
        HypothesisVersion(
            hypothesis_id="H-LATE-ENTRY-FILTER",
            version=1,
            strategy=revised,
            source_claim_ids=(CLAIM,),
        )
    )
    with pytest.raises(JournalIntegrityError, match="reused"):
        lab.run(changed_candidate, command_id="lab-run-1", occurred_at=NOW)


def test_lab_records_one_verdict_per_registration_even_with_new_command(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    lab = ResearchBacktestLab(journal)

    first = lab.run(candidate(), command_id="lab-run-1", occurred_at=NOW)
    second = lab.run(candidate(), command_id="lab-run-2", occurred_at=NOW)

    assert second.event_id == first.event_id
    events = [
        event
        for event in journal.read_all()
        if event.event_type == "ResearchLabDossierRecorded"
    ]
    assert len(events) == 1


def test_lab_effect_gate_can_reject_an_examiner_eligible_candidate(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    high_bar = candidate()
    blocked = ResearchLabCandidate(
        coach_hypothesis=high_bar.coach_hypothesis,
        hypothesis=high_bar.hypothesis,
        snapshot=high_bar.snapshot,
        protocol=high_bar.protocol,
        data_policy_id=high_bar.data_policy_id,
        minimum_effect_size=20.0,
        minimum_confidence_lower_bound=0.0,
        familywise_alpha=high_bar.familywise_alpha,
    )

    result = ResearchBacktestLab(journal).run(
        blocked,
        command_id="lab-run-high-bar",
        occurred_at=NOW,
    )

    assert result.dossier.recommendation is Recommendation.ELIGIBLE_FOR_SHADOW
    assert result.shadow_eligible is False
    summary = ResearchLabReporter(journal).latest(limit=1)[0]
    assert summary.recommendation == "reject"
    assert summary.shadow_eligible is False


def test_lab_records_needs_more_evidence_when_required_statistics_are_missing(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    base = candidate()
    blocked = ResearchLabCandidate(
        coach_hypothesis=base.coach_hypothesis,
        hypothesis=base.hypothesis,
        snapshot=base.snapshot,
        protocol=base.protocol,
        data_policy_id=base.data_policy_id,
        minimum_effect_size=1.0,
        minimum_confidence_lower_bound=0.01,
        familywise_alpha=base.familywise_alpha,
    )

    result = ResearchBacktestLab(journal).run(
        blocked,
        command_id="lab-run-confidence-required",
        occurred_at=NOW,
    )

    assert result.dossier.recommendation is Recommendation.ELIGIBLE_FOR_SHADOW
    assert result.shadow_eligible is False
    summary = ResearchLabReporter(journal).latest(limit=1)[0]
    assert summary.recommendation == "needs_more_evidence"
    assert summary.shadow_eligible is False


def test_lab_rejects_hypotheses_that_are_not_research_only(tmp_path):
    bad = MistakeHypothesis(
        hypothesis_id="hypothesis:" + "b" * 64,
        scope=coach_hypothesis().scope,
        evidence_episode_ids=("EP-1", "EP-2"),
        authority="TRADE_AUTHORITY",
        requires_examination=True,
        can_veto_trades=False,
    )
    with pytest.raises(ValueError, match="research-only"):
        ResearchBacktestLab(OperationalJournal(tmp_path / "journal.sqlite3")).run(
            candidate().with_coach_hypothesis(bad),
            command_id="bad-lab-run",
            occurred_at=NOW,
        )


def test_lab_reporter_rejects_non_bool_shadow_eligibility(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    journal.append(
        EventAppend(
            stream_id="research_lab:malformed",
            event_type="ResearchLabDossierRecorded",
            payload={
                "coach_hypothesis_id": "hypothesis:bad",
                "candidate_hypothesis_id": "H-BAD",
                "recommendation": "reject",
                "shadow_eligible": "false",
                "experiment_id": "sha256:" + "1" * 64,
                "registration_id": "experiment:" + "2" * 64,
                "aggregate": {
                    "trades": 0,
                    "expectancy_pct": None,
                    "hit_rate": None,
                },
            },
            idempotency_key="malformed-lab-event",
            expected_version=0,
            occurred_at=NOW,
        )
    )

    with pytest.raises(ValueError, match="shadow_eligible"):
        ResearchLabReporter(journal).latest(limit=1)
