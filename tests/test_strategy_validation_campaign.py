from __future__ import annotations

import pandas as pd
import pytest

from sensei.backtest.campaign import (
    LockedConfirmationLedger,
    LockedConfirmationReuseError,
    ValidationThresholds,
    run_validation_campaign,
    validation_campaign_id,
)


def test_campaign_drawdown_includes_losses_from_initial_capital():
    frame = _frame("2020-01-01", [100, 100, 90, 90, 90, 90, 90, 90] * 4)
    report = run_validation_campaign(
        frames={"TEST": frame},
        strategies={"loss_probe": {
            "fn": lambda bars: bars.close.eq(100), "stop_pct": 5,
            "target_pct": 20, "max_hold_days": 3,
        }},
        folds=4, cost_pct=0, historical_membership_available=True,
    )
    result = report.strategies[0]
    assert [fold.metrics.trades for fold in result.folds] == [1] * 4
    assert [fold.metrics.trade_sequence_max_drawdown_pct for fold in result.folds] == [10] * 4
    assert result.total.trade_sequence_max_drawdown_pct == pytest.approx(34.39)


def test_campaign_fingerprint_covers_shared_execution_implementation(monkeypatch):
    import sensei.backtest.campaign as campaign
    from sensei.backtest import daily_execution

    frames = {"TEST": _frame("2020-01-01", [100] * 40)}
    strategies = {"probe": {
        "fn": _every_fifth, "stop_pct": 5, "target_pct": 10, "max_hold_days": 3,
    }}
    original = validation_campaign_id(frames=frames, strategies=strategies, folds=4, cost_pct=0)
    getsource = campaign.inspect.getsource
    monkeypatch.setattr(campaign.inspect, "getsource", lambda obj: (
        getsource(obj) + "\n# execution revision" if obj is daily_execution else getsource(obj)
    ))
    revised = validation_campaign_id(frames=frames, strategies=strategies, folds=4, cost_pct=0)
    assert revised != original


def _frame(start: str, closes: list[float]) -> pd.DataFrame:
    close = pd.Series(closes, index=pd.bdate_range(start, periods=len(closes)))
    return pd.DataFrame({
        "open": close,
        "high": close * 1.03,
        "low": close * 0.99,
        "close": close,
        "volume": 1_000_000,
    })


def _every_fifth(frame: pd.DataFrame) -> pd.Series:
    signal = pd.Series(False, index=frame.index)
    signal.iloc[::5] = True
    return signal


def test_campaign_uses_chronological_folds_and_reserves_last_as_holdout():
    report = run_validation_campaign(
        frames={"ONE": _frame("2020-01-01", [100 + i for i in range(80)])},
        strategies={"trend": {
            "fn": _every_fifth,
            "stop_pct": 10.0,
            "target_pct": 5.0,
            "max_hold_days": 4,
        }},
        folds=4,
        thresholds=ValidationThresholds(
            minimum_total_trades=4,
            minimum_holdout_trades=1,
            minimum_holdout_expectancy_pct=0.0,
            minimum_holdout_profit_factor=1.0,
            minimum_positive_fold_fraction=0.5,
        ),
        historical_membership_available=True,
    )

    result = report.strategies[0]
    assert [fold.name for fold in result.folds] == [
        "development-1", "development-2", "validation", "holdout"
    ]
    assert result.folds[-1].end > result.folds[-2].end
    assert result.total.trades == sum(fold.metrics.trades for fold in result.folds)
    assert not report.locked_confirmation_consumed
    assert result.verdict == "PROMISING"


def test_campaign_rejects_positive_average_without_locked_confirmation_edge():
    rising_then_falling = [100 + i for i in range(60)] + [160 - i * 2 for i in range(20)]
    report = run_validation_campaign(
        frames={"ONE": _frame("2020-01-01", rising_then_falling)},
        strategies={"regime_fragile": {
            "fn": _every_fifth,
            "stop_pct": 5.0,
            "target_pct": 5.0,
            "max_hold_days": 4,
        }},
        folds=4,
        thresholds=ValidationThresholds(
            minimum_total_trades=4,
            minimum_holdout_trades=1,
            minimum_holdout_expectancy_pct=0.0,
            minimum_holdout_profit_factor=1.0,
            minimum_positive_fold_fraction=0.5,
        ),
        historical_membership_available=True,
    )

    result = report.strategies[0]
    assert result.total.expectancy_pct > 0
    assert result.folds[-1].metrics.expectancy_pct < 0
    assert result.verdict == "NOT_VALIDATED"
    assert "HOLDOUT_EXPECTANCY_BELOW_THRESHOLD" in result.reason_codes


def test_campaign_marks_small_samples_inconclusive():
    report = run_validation_campaign(
        frames={"ONE": _frame("2020-01-01", [100] * 40)},
        strategies={"quiet": {
            "fn": lambda frame: pd.Series(False, index=frame.index),
            "stop_pct": 5.0,
            "target_pct": 10.0,
            "max_hold_days": 5,
        }},
        folds=4,
        historical_membership_available=True,
    )

    result = report.strategies[0]
    assert result.verdict == "INCONCLUSIVE"
    assert "INSUFFICIENT_TOTAL_TRADES" in result.reason_codes
    assert "INSUFFICIENT_HOLDOUT_TRADES" in result.reason_codes


def test_campaign_report_is_json_serializable():
    report = run_validation_campaign(
        frames={"ONE": _frame("2020-01-01", [100 + i for i in range(40)])},
        strategies={"trend": {
            "fn": _every_fifth,
            "stop_pct": 10.0,
            "target_pct": 5.0,
            "max_hold_days": 4,
        }},
        folds=4,
        historical_membership_available=True,
    )

    payload = report.to_dict()
    assert payload["schema_version"] == "1.0"
    assert str(payload["input_fingerprint"]).startswith("sha256:")
    assert payload["limitations"]
    assert payload["execution_fingerprint"].startswith("sha256:")
    assert not payload["locked_confirmation_consumed"]
    assert payload["strategies"][0]["folds"][-1]["kind"] == "holdout"


def test_known_survivorship_bias_blocks_unqualified_promising_label():
    report = run_validation_campaign(
        frames={"ONE": _frame("2020-01-01", [100 + i for i in range(80)])},
        strategies={"trend": {
            "fn": _every_fifth,
            "stop_pct": 10.0,
            "target_pct": 5.0,
            "max_hold_days": 4,
        }},
        folds=4,
        thresholds=ValidationThresholds(
            minimum_total_trades=4,
            minimum_holdout_trades=1,
            minimum_holdout_expectancy_pct=0.0,
            minimum_holdout_profit_factor=1.0,
            minimum_positive_fold_fraction=0.5,
        ),
    )

    assert report.data_quality_blockers == (
        "HISTORICAL_UNIVERSE_MEMBERSHIP_UNAVAILABLE",
    )
    assert report.strategies[0].verdict == "PRELIMINARY_PROMISING_DATA_BLOCKED"


def test_locked_confirmation_ledger_makes_one_input_identity_one_use(tmp_path):
    frame = _frame("2020-01-01", [100 + i for i in range(40)])
    strategies = {"trend": {
        "fn": _every_fifth,
        "stop_pct": 10.0,
        "target_pct": 5.0,
        "max_hold_days": 4,
    }}
    campaign_id = validation_campaign_id(
        frames={"ONE": frame},
        strategies=strategies,
        folds=4,
        cost_pct=0.25,
        locked_confirmation_consumed=True,
    )
    ledger = LockedConfirmationLedger(tmp_path / "locks.json")
    now = pd.Timestamp("2026-08-01", tz="UTC").to_pydatetime()

    ledger.preregister(campaign_id, registered_at=now)
    ledger.consume(campaign_id, consumed_at=now, status="COMPLETED")

    with pytest.raises(LockedConfirmationReuseError):
        ledger.preregister(campaign_id, registered_at=now)


def test_campaign_identity_distinguishes_holdout_from_locked_confirmation():
    frames = {"ONE": _frame("2020-01-01", [100 + i for i in range(40)])}
    strategies = {"trend": {
        "fn": _every_fifth,
        "stop_pct": 10.0,
        "target_pct": 5.0,
        "max_hold_days": 4,
    }}

    holdout = validation_campaign_id(
        frames=frames, strategies=strategies, folds=4, cost_pct=0.25,
    )
    locked = validation_campaign_id(
        frames=frames, strategies=strategies, folds=4, cost_pct=0.25,
        locked_confirmation_consumed=True,
    )

    assert holdout != locked
