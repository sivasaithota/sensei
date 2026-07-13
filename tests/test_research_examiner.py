import json
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from sensei.backtest.rulespec import Condition, RuleSpec
from sensei.research import (
    DossierStatus,
    EvaluationFold,
    ExaminationProtocol,
    ExaminationRequest,
    HypothesisVersion,
    MarketDataSnapshot,
    Recommendation,
    ResearchExaminer,
    EvidenceWarningCode,
)


def target_trade_bars() -> pd.DataFrame:
    index = pd.bdate_range("2020-01-01", periods=10)
    close = np.array([90, 90, 90, 100, 100, 110, 110, 110, 110, 110], dtype=float)
    return pd.DataFrame(
        {
            "open": [90, 90, 90, 100, 100, 100, 110, 110, 110, 110],
            "high": [91, 91, 91, 101, 101, 111, 111, 111, 111, 111],
            "low": [89, 89, 89, 99, 99, 99, 109, 109, 109, 109],
            "close": close,
            "volume": np.full(10, 1_000_000),
        },
        index=index,
    )


def capture_synthetic_snapshot(
    bars_by_symbol: dict[str, pd.DataFrame],
    *,
    as_of: date | None = None,
    point_in_time_universe: bool = True,
    source: str = "synthetic",
) -> MarketDataSnapshot:
    snapshot_date = as_of or max(
        frame.index[-1].date() for frame in bars_by_symbol.values()
    )
    return MarketDataSnapshot.capture(
        bars_by_symbol=bars_by_symbol,
        as_of=snapshot_date,
        universe_as_of=snapshot_date,
        point_in_time_universe=point_in_time_universe,
        source=source,
    )


def target_trade_request() -> ExaminationRequest:
    bars = target_trade_bars()
    index = bars.index
    rule = RuleSpec(
        name="two_day_breakout",
        source="Synthetic fixture, claim C-1",
        principle="Buy the session after a close above the prior two-session high.",
        conditions=[Condition(left="close", op=">", right="highest_2")],
        stop_pct=5,
        target_pct=10,
        max_hold_days=5,
    )
    return ExaminationRequest(
        hypothesis=HypothesisVersion(
            hypothesis_id="H-1",
            version=1,
            strategy=rule,
            source_claim_ids=("C-1",),
        ),
        snapshot=capture_synthetic_snapshot({"TEST": bars}),
        protocol=ExaminationProtocol(
            name="foundation",
            version=1,
            folds=(EvaluationFold("oos-1", index[0].date(), index[-1].date()),),
            min_trades=1,
            min_symbols=1,
            min_expectancy_pct=1.0,
            round_trip_cost_pct=0.25,
        ),
    )


def single_breakout_bars(index: pd.DatetimeIndex, signal_date: str) -> pd.DataFrame:
    signal_index = index.get_loc(pd.Timestamp(signal_date))
    close = np.full(len(index), 90.0)
    close[signal_index:] = 100.0
    open_ = close.copy()
    open_[signal_index] = 90.0
    high = np.maximum(open_, close) + 1
    low = np.minimum(open_, close) - 1
    high[signal_index + 1] = 111.0
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(len(index), 1_000_000),
        },
        index=index,
    )


def overnight_gap_request() -> ExaminationRequest:
    request = target_trade_request()
    index = pd.bdate_range("2020-03-02", periods=8)
    bars = pd.DataFrame(
        {
            "open": [90, 90, 90, 100, 90, 90, 90, 90],
            "high": [91, 91, 101, 101, 91, 91, 91, 91],
            "low": [89, 89, 89, 99, 89, 89, 89, 89],
            "close": [90, 90, 100, 100, 90, 90, 90, 90],
            "volume": np.full(8, 1_000_000),
        },
        index=index,
    )
    gap_rule = request.hypothesis.strategy.model_copy(
        update={"stop_pct": 5.0, "target_pct": 40.0, "max_hold_days": 5}
    )
    return replace(
        request,
        hypothesis=replace(request.hypothesis, strategy=gap_rule),
        snapshot=capture_synthetic_snapshot({"GAP": bars}),
        protocol=replace(
            request.protocol,
            folds=(EvaluationFold("gap", index[0].date(), index[-1].date()),),
            min_expectancy_pct=-100,
        ),
    )


def test_examine_returns_quarantined_serializable_dossier_for_target_trade():
    request = target_trade_request()

    dossier = ResearchExaminer().examine(request)

    assert dossier.status is DossierStatus.QUARANTINED
    assert dossier.recommendation is Recommendation.ELIGIBLE_FOR_SHADOW
    assert dossier.aggregate.trades == 1
    assert dossier.aggregate.expectancy_pct == 9.75
    assert dossier.folds[0].target_exits == 1
    assert dossier.round_trip_cost_pct == 0.25
    assert {warning.code for warning in dossier.warnings} == {
        EvidenceWarningCode.NO_PORTFOLIO_SIMULATION,
        EvidenceWarningCode.REGIME_NOT_EXAMINED,
        EvidenceWarningCode.MULTIPLE_TESTING_NOT_CORRECTED,
        EvidenceWarningCode.DAILY_DATA_ONLY,
    }
    assert dossier.experiment_id.startswith("sha256:")
    serialized = dossier.model_dump_json()
    assert request.snapshot.snapshot_id in serialized
    assert "bars_by_symbol" not in serialized
    assert "signal_fn" not in serialized


def test_experiment_identity_covers_hypothesis_snapshot_and_protocol_content():
    examiner = ResearchExaminer()
    request = target_trade_request()
    original_id = examiner.examine(request).experiment_id

    revised_rule = request.hypothesis.strategy.model_copy(update={"target_pct": 11.0})
    revised_hypothesis = replace(request.hypothesis, strategy=revised_rule)

    revised_bars = target_trade_bars()
    revised_bars.iloc[0, revised_bars.columns.get_loc("volume")] += 1
    revised_snapshot = capture_synthetic_snapshot(
        {"TEST": revised_bars},
        as_of=request.snapshot.as_of,
    )
    revised_protocol = replace(request.protocol, min_expectancy_pct=2.0)

    ids = {
        original_id,
        examiner.examine(replace(request, hypothesis=revised_hypothesis)).experiment_id,
        examiner.examine(replace(request, snapshot=revised_snapshot)).experiment_id,
        examiner.examine(replace(request, protocol=revised_protocol)).experiment_id,
    }

    assert len(ids) == 4


def test_examine_uses_common_calendar_folds_for_different_listing_histories():
    request = target_trade_request()
    old_index = pd.bdate_range("2020-01-01", "2020-02-14")
    recent_index = pd.bdate_range("2020-01-27", "2020-02-14")
    snapshot = capture_synthetic_snapshot(
        {
            "OLD": single_breakout_bars(old_index, "2020-01-30"),
            "RECENT": single_breakout_bars(recent_index, "2020-02-05"),
        },
        as_of=date(2020, 2, 14),
    )
    protocol = replace(
        request.protocol,
        folds=(EvaluationFold("common-oos", date(2020, 2, 3), date(2020, 2, 14)),),
    )

    dossier = ResearchExaminer().examine(
        replace(request, snapshot=snapshot, protocol=protocol)
    )

    assert dossier.aggregate.trades == 1
    assert dossier.aggregate.symbols_with_trades == 1
    assert dossier.folds[0].window_start == date(2020, 2, 3)


def test_examine_fills_an_overnight_stop_gap_at_the_worse_open():
    dossier = ResearchExaminer().examine(overnight_gap_request())

    assert dossier.aggregate.stop_exits == 1
    assert dossier.aggregate.expectancy_pct == -10.25


def test_examine_fails_closed_for_a_non_point_in_time_universe():
    request = target_trade_request()
    snapshot = capture_synthetic_snapshot(
        {"TEST": target_trade_bars()},
        as_of=request.snapshot.as_of,
        point_in_time_universe=False,
        source="current constituents backfilled through history",
    )

    dossier = ResearchExaminer().examine(replace(request, snapshot=snapshot))

    assert dossier.aggregate.expectancy_pct == 9.75
    assert dossier.recommendation is Recommendation.NEEDS_MORE_EVIDENCE
    assert any(issue.code == "universe.not_point_in_time" for issue in dossier.issues)


def test_examine_reports_and_excludes_invalid_ohlc_instead_of_silently_using_it():
    request = target_trade_request()
    invalid = target_trade_bars()
    invalid.loc[invalid.index[0], "high"] = invalid.loc[invalid.index[0], "close"] - 1
    snapshot = capture_synthetic_snapshot(
        {"GOOD": target_trade_bars(), "BAD": invalid},
        as_of=request.snapshot.as_of,
    )

    dossier = ResearchExaminer().examine(replace(request, snapshot=snapshot))

    assert dossier.aggregate.trades == 1
    assert dossier.recommendation is Recommendation.NEEDS_MORE_EVIDENCE
    assert any(
        issue.symbol == "BAD" and issue.code == "bars.invalid_ohlc"
        for issue in dossier.issues
    )


def test_examine_censors_a_trade_that_cannot_finish_inside_its_fold():
    request = target_trade_request()
    index = pd.bdate_range("2020-04-01", periods=10)
    bars = single_breakout_bars(index, index[-3].strftime("%Y-%m-%d"))
    bars.loc[index[-2]:, "high"] = 101.0
    long_hold_rule = request.hypothesis.strategy.model_copy(
        update={"stop_pct": 15.0, "target_pct": 40.0, "max_hold_days": 5}
    )
    snapshot = capture_synthetic_snapshot({"CENSORED": bars})
    protocol = replace(
        request.protocol,
        folds=(EvaluationFold("edge", index[0].date(), index[-1].date()),),
    )

    dossier = ResearchExaminer().examine(
        replace(
            request,
            hypothesis=replace(request.hypothesis, strategy=long_hold_rule),
            snapshot=snapshot,
            protocol=protocol,
        )
    )

    assert dossier.aggregate.trades == 0
    assert dossier.censored_trades == 1
    assert dossier.recommendation is Recommendation.NEEDS_MORE_EVIDENCE


def test_examine_preserves_pre_fold_bars_for_indicator_warmup():
    request = target_trade_request()
    index = pd.bdate_range("2020-05-01", periods=12)
    close = np.array([90, 90, 90, 90, 90, 100, 100, 100, 100, 100, 100, 100], dtype=float)
    bars = pd.DataFrame(
        {
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": np.full(len(index), 1_000_000),
        },
        index=index,
    )
    bars.loc[index[6], "high"] = 111.0
    warmup_rule = RuleSpec(
        name="five_day_average_breakout",
        source="Synthetic fixture, claim C-2",
        principle="Buy above the five-session average.",
        conditions=[Condition(left="close", op=">", right="sma_5")],
        stop_pct=5,
        target_pct=10,
        max_hold_days=5,
    )
    snapshot = capture_synthetic_snapshot({"WARM": bars})
    protocol = replace(
        request.protocol,
        folds=(EvaluationFold("oos", index[5].date(), index[-1].date()),),
    )

    dossier = ResearchExaminer().examine(
        replace(
            request,
            hypothesis=HypothesisVersion(
                hypothesis_id="H-2",
                version=1,
                strategy=warmup_rule,
                source_claim_ids=("C-2",),
            ),
            snapshot=snapshot,
            protocol=protocol,
        )
    )

    assert dossier.aggregate.target_exits == 1
    assert dossier.aggregate.expectancy_pct == 9.75


def test_examine_treats_too_few_positive_trades_as_insufficient_not_passing():
    request = target_trade_request()
    stricter_protocol = replace(request.protocol, min_trades=2)

    dossier = ResearchExaminer().examine(
        replace(request, protocol=stricter_protocol)
    )

    assert dossier.aggregate.expectancy_pct == 9.75
    assert dossier.recommendation is Recommendation.NEEDS_MORE_EVIDENCE
    assert "evidence minimums" in dossier.reasons[0]


def test_examine_rejects_sufficient_negative_evidence():
    request = overnight_gap_request()
    rejecting_protocol = replace(request.protocol, min_expectancy_pct=0.0)

    dossier = ResearchExaminer().examine(
        replace(request, protocol=rejecting_protocol)
    )

    assert dossier.aggregate.trades == 1
    assert dossier.aggregate.expectancy_pct == -10.25
    assert dossier.recommendation is Recommendation.REJECT


def test_examine_persists_one_immutable_idempotent_artifact_when_configured(tmp_path):
    examiner = ResearchExaminer(artifact_dir=tmp_path)
    request = target_trade_request()

    first = examiner.examine(request)
    second = examiner.examine(request)

    artifacts = list(tmp_path.glob("*.json"))
    assert first == second
    assert [artifact.name for artifact in artifacts] == [
        f"{first.experiment_id.removeprefix('sha256:')}.json"
    ]
    assert json.loads(artifacts[0].read_text()) == first.model_dump(mode="json")


def test_examine_quarantines_a_reserved_strategy_name_collision():
    request = target_trade_request()
    unreserved = ResearchExaminer().examine(request)
    collision_protocol = replace(
        request.protocol, reserved_strategy_names=("two_day_breakout",)
    )

    dossier = ResearchExaminer().examine(
        replace(request, protocol=collision_protocol)
    )

    assert dossier.recommendation is Recommendation.NEEDS_MORE_EVIDENCE
    assert any(issue.code == "strategy.name_collision" for issue in dossier.issues)
    assert dossier.experiment_id != unreserved.experiment_id


def test_examine_cannot_mutate_playbook_or_studied_rules(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    playbook = tmp_path / "data" / "playbook" / "current.json"
    studied = tmp_path / "data" / "studied_rules.json"
    playbook.parent.mkdir(parents=True)
    playbook.write_text('{"sentinel":"active"}')
    studied.write_text('[{"sentinel":"candidate"}]')

    ResearchExaminer(artifact_dir=tmp_path / "evidence").examine(
        target_trade_request()
    )

    assert playbook.read_text() == '{"sentinel":"active"}'
    assert studied.read_text() == '[{"sentinel":"candidate"}]'


def test_examine_rejects_a_protocol_that_reaches_past_the_snapshot_as_of():
    request = target_trade_request()
    fold = request.protocol.folds[0]
    future_fold = replace(fold, end=request.snapshot.as_of + timedelta(days=1))
    protocol = replace(request.protocol, folds=(future_fold,))

    with pytest.raises(ValueError, match="snapshot as-of"):
        ResearchExaminer().examine(replace(request, protocol=protocol))


def test_hypothesis_rule_definition_is_immutable():
    request = target_trade_request()

    with pytest.raises(ValidationError, match="frozen"):
        request.hypothesis.strategy.target_pct = 11


def test_hypothesis_rule_conditions_are_immutable():
    request = target_trade_request()

    with pytest.raises(AttributeError):
        request.hypothesis.strategy.conditions.append(
            Condition(left="close", op=">", right="sma_10")
        )


def test_examine_detects_internal_snapshot_content_mutation():
    request = target_trade_request()
    captured_frames = object.__getattribute__(
        request.snapshot, "_MarketDataSnapshot__bars_by_symbol"
    )
    captured_frame = captured_frames["TEST"]
    captured_frame.iloc[0, captured_frame.columns.get_loc("volume")] += 1

    with pytest.raises(ValueError, match="snapshot content"):
        ResearchExaminer().examine(request)


def test_examine_fails_closed_when_a_fold_lacks_minimum_session_coverage():
    request = target_trade_request()
    coverage_protocol = replace(request.protocol, min_sessions_per_fold=11)

    dossier = ResearchExaminer().examine(
        replace(request, protocol=coverage_protocol)
    )

    assert dossier.recommendation is Recommendation.NEEDS_MORE_EVIDENCE
    assert any(
        issue.code == "bars.insufficient_fold_coverage"
        for issue in dossier.issues
    )


def test_failed_artifact_finalization_leaves_no_valid_looking_dossier(
    tmp_path, monkeypatch
):
    def fail_chmod(self, mode):
        raise OSError("simulated artifact finalization failure")

    monkeypatch.setattr(Path, "chmod", fail_chmod)

    with pytest.raises(OSError, match="finalization failure"):
        ResearchExaminer(artifact_dir=tmp_path).examine(target_trade_request())

    assert list(tmp_path.glob("*.json")) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("round_trip_cost_pct", float("nan")),
        ("round_trip_cost_pct", float("inf")),
        ("min_expectancy_pct", float("nan")),
        ("min_expectancy_pct", float("-inf")),
    ],
)
def test_protocol_rejects_non_finite_numeric_policy(field, value):
    request = target_trade_request()

    with pytest.raises(ValueError, match="finite"):
        replace(request.protocol, **{field: value})


def test_fold_includes_first_day_entry_from_previous_session_signal():
    request = target_trade_request()
    index = pd.bdate_range("2020-06-01", periods=10)
    bars = single_breakout_bars(index, index[3].strftime("%Y-%m-%d"))
    snapshot = capture_synthetic_snapshot({"EDGE": bars})
    protocol = replace(
        request.protocol,
        folds=(EvaluationFold("oos", index[4].date(), index[-1].date()),),
    )

    dossier = ResearchExaminer().examine(
        replace(request, snapshot=snapshot, protocol=protocol)
    )

    assert dossier.aggregate.trades == 1
    assert dossier.aggregate.target_exits == 1
