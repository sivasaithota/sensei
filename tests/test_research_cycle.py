from __future__ import annotations

from dataclasses import replace

import pandas as pd

from sensei.backtest.campaign import ValidationThresholds, run_validation_campaign
from sensei.backtest.research_cycle import (
    CycleDisposition,
    ResearchCycleLedger,
    assess_research_cycle,
)


def _frame() -> pd.DataFrame:
    index = pd.bdate_range("2020-01-01", periods=120)
    close = pd.Series([100 + index * 0.4 for index in range(120)], index=index)
    return pd.DataFrame({
        "open": close,
        "high": close * 1.03,
        "low": close * 0.995,
        "close": close,
        "volume": 1_000_000,
    })


def _every_tenth(frame: pd.DataFrame) -> pd.Series:
    signal = pd.Series(False, index=frame.index)
    signal.iloc[::10] = True
    return signal


def _report(cost_pct: float):
    return run_validation_campaign(
        frames={"ONE": _frame()},
        strategies={
            "robust": {
                "fn": _every_tenth,
                "stop_pct": 10.0,
                "target_pct": 2.0,
                "max_hold_days": 8,
            }
        },
        folds=4,
        cost_pct=cost_pct,
        historical_membership_available=True,
        thresholds=ValidationThresholds(
            minimum_total_trades=4,
            minimum_holdout_trades=1,
            minimum_holdout_expectancy_pct=0.0,
            minimum_holdout_profit_factor=1.0,
            minimum_positive_fold_fraction=0.5,
        ),
    )


def test_cycle_advances_only_an_edge_that_survives_the_cost_ladder():
    report = assess_research_cycle(
        cycle_id="cycle-1",
        campaigns=(_report(0.25), _report(1.0)),
        maximum_variants=10,
    )

    decision = report.decisions[0]
    assert decision.strategy == "robust"
    assert decision.disposition is CycleDisposition.ADVANCE_TO_PORTFOLIO_REPLAY
    assert decision.baseline_expectancy_pct > decision.stress_expectancy_pct > 0
    assert report.can_change_playbook is False
    assert report.locked_confirmation_consumed is False
    assert report.ready_for_portfolio_replay is True
    assert report.ready_for_confirmation is False


def test_cycle_revises_cost_fragile_evidence_and_preserves_data_blockers():
    baseline = _report(0.25)
    stress = _report(1.0)
    fragile = replace(
        stress.strategies[0],
        verdict="NOT_VALIDATED",
        reason_codes=("HOLDOUT_EXPECTANCY_BELOW_THRESHOLD",),
    )
    stress = replace(
        stress,
        strategies=(fragile,),
        data_quality_blockers=("HISTORICAL_UNIVERSE_MEMBERSHIP_UNAVAILABLE",),
    )

    report = assess_research_cycle(
        cycle_id="cycle-2",
        campaigns=(baseline, stress),
        maximum_variants=10,
    )

    assert report.decisions[0].disposition is CycleDisposition.REVISE_HYPOTHESIS
    assert report.data_quality_blockers == (
        "HISTORICAL_UNIVERSE_MEMBERSHIP_UNAVAILABLE",
    )
    assert report.ready_for_confirmation is False


def test_cycle_rejects_mismatched_strategy_sets_and_exhausted_trial_budget():
    import pytest

    baseline = _report(0.25)
    missing = replace(_report(1.0), strategies=())
    with pytest.raises(ValueError, match="same strategy set"):
        assess_research_cycle(
            cycle_id="cycle-3",
            campaigns=(baseline, missing),
            maximum_variants=10,
        )

    with pytest.raises(ValueError, match="variant budget"):
        assess_research_cycle(
            cycle_id="cycle-4",
            campaigns=(baseline, _report(1.0)),
            maximum_variants=0,
        )


def test_cycle_requires_comparable_campaigns_and_a_real_cost_ladder():
    import pytest

    baseline = _report(0.25)
    with pytest.raises(ValueError, match="at least two"):
        assess_research_cycle(
            cycle_id="one-cost",
            campaigns=(baseline,),
            maximum_variants=10,
        )
    changed_input = replace(_report(1.0), input_fingerprint="sha256:different")
    with pytest.raises(ValueError, match="same input and execution identity"):
        assess_research_cycle(
            cycle_id="mixed-inputs",
            campaigns=(baseline, changed_input),
            maximum_variants=10,
        )


def test_family_ledger_preregisters_and_enforces_a_cumulative_budget(tmp_path):
    import pytest

    ledger = ResearchCycleLedger(tmp_path / "cycles.json")
    first = ledger.preregister(
        family_id="momentum",
        cycle_id="cycle-1",
        variant_ids=("variant:a", "variant:b"),
        maximum_variants=3,
        costs_pct=(0.25, 1.0),
        folds=5,
        input_fingerprint="sha256:input",
        execution_fingerprint="sha256:execution",
    )
    assert first["status"] == "REGISTERED"
    assert ledger.preregister(
        family_id="momentum",
        cycle_id="cycle-1",
        variant_ids=("variant:a", "variant:b"),
        maximum_variants=3,
        costs_pct=(0.25, 1.0),
        folds=5,
        input_fingerprint="sha256:input",
        execution_fingerprint="sha256:execution",
    ) == first
    ledger.complete("momentum", "cycle-1")

    with pytest.raises(ValueError, match="budget"):
        ledger.preregister(
            family_id="momentum",
            cycle_id="cycle-2",
            variant_ids=("variant:c", "variant:d"),
            maximum_variants=3,
            costs_pct=(0.25, 1.0),
            folds=5,
            input_fingerprint="sha256:input",
            execution_fingerprint="sha256:execution",
        )
    with pytest.raises(ValueError, match="cannot change"):
        ledger.preregister(
            family_id="momentum",
            cycle_id="cycle-3",
            variant_ids=("variant:c",),
            maximum_variants=4,
            costs_pct=(0.25, 1.0),
            folds=5,
            input_fingerprint="sha256:input",
            execution_fingerprint="sha256:execution",
        )
