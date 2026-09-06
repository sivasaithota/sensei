from dataclasses import replace
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from sensei.backtest.portfolio_campaign import PortfolioCampaignConfig, run_portfolio_campaign
from sensei.backtest.strategy_diagnostic_matrix import DiagnosticScenario, run_strategy_diagnostic_matrix
from sensei.operations import OperationalJournal
from sensei.research.exposure import ResearchDataAlreadyExposed, ResearchExposureLedger
from sensei.research.exposure import record_development_frames
from sensei.strategy.selection import RankingEvidence, SignalRankingPolicy


def bars():
    return pd.DataFrame({"open": [100.] * 5, "close": [100.] * 5,
                         "high": [101.] * 5, "low": [99.] * 5, "volume": [1e6] * 5},
                        index=pd.bdate_range("2020-01-01", periods=5))


def strategy():
    return {"fn": lambda f: pd.Series(f.index == pd.Timestamp("2020-01-01"), index=f.index),
            "stop_pct": 5, "target_pct": 10, "max_hold_days": 10}


def test_ranking_ignores_future_or_undated_performance_evidence():
    policy = SignalRankingPolicy()
    args = dict(frame=bars(), average_turnover_inr=1e8, stop_pct=5, target_pct=10,
                as_of=date(2020, 1, 3))
    neutral = policy.score(**args)
    future = RankingEvidence(3, 1, 10000, date(2026, 1, 1))
    assert policy.score(**args, evidence=future) == neutral
    assert policy.score(**args, evidence=replace(future, available_as_of=None)) == neutral
    assert policy.score(**args, evidence=replace(future, available_as_of=date(2019, 1, 1))).total > neutral.total
    extended = bars()
    extended.loc[extended.index[-1], "close"] = 1e6
    assert policy.score(**{**args, "frame": extended}) == neutral


def test_missing_future_bar_does_not_remove_a_traded_instrument():
    full = bars()
    incomplete = full.drop(full.index[3])
    with pytest.raises(ValueError, match="missing held-position bar"):
        run_strategy_diagnostic_matrix(
            frames={"A": incomplete, "B": full}, strategies={"swing": strategy()},
            scenarios=(DiagnosticScenario("only", ("swing",)),), windows=(5,), costs=(0,),
            base_config=PortfolioCampaignConfig(max_positions_per_strategy=2),
        )


def test_membership_governs_new_entries_but_does_not_force_held_exit():
    frame = bars()
    eligibility = pd.Series([True, True, False, False, False], index=frame.index)
    report = run_portfolio_campaign(
        frames={"TEST": frame}, strategies={"swing": strategy()},
        config=PortfolioCampaignConfig(liquidate_at_end=True),
        entry_eligibility={"TEST": eligibility},
    )
    assert len(report.trades) == 1
    assert report.trades[0].exit_date == str(frame.index[-1].date())
    assert report.trades[0].exit_reason == "final_session"
    denied = run_portfolio_campaign(
        frames={"TEST": frame}, strategies={"swing": strategy()},
        config=PortfolioCampaignConfig(liquidate_at_end=True),
        entry_eligibility={"TEST": pd.Series(False, index=frame.index)},
    )
    assert not denied.trades
    assert report.experiment_id != denied.experiment_id


def test_exposure_follows_dates_across_vendors_and_campaigns(tmp_path):
    ledger = ResearchExposureLedger(OperationalJournal(tmp_path / "research.sqlite3"))
    kwargs = dict(start=date(2017, 1, 1), end=date(2017, 1, 31),
                  now=datetime(2026, 9, 6, tzinfo=timezone.utc))
    ledger.record(**kwargs, campaign_id="original", snapshot_id="vendor-A", purpose="discovery")
    with pytest.raises(ResearchDataAlreadyExposed):
        ledger.record(**kwargs, campaign_id="new-hash", snapshot_id="vendor-B", purpose="confirmation")
    with pytest.raises(ResearchDataAlreadyExposed, match="known stock"):
        ledger.record(**{**kwargs, "start": date(2024, 1, 1), "end": date(2025, 1, 1)},
                      campaign_id="new-hash", snapshot_id="new-provider", purpose="confirmation")


def test_policy_is_claimed_across_campaigns_even_if_resolution_failed(tmp_path):
    ledger = ResearchExposureLedger(OperationalJournal(tmp_path / "research.sqlite3"))
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    ledger.claim_policy("opaque-history", "original", now)
    with pytest.raises(ResearchDataAlreadyExposed):
        ledger.claim_policy("opaque-history", "new-campaign", now)


def test_discovery_entrypoint_records_warmup_and_survives_retry(tmp_path):
    journal = OperationalJournal(tmp_path / "research.sqlite3")
    frame = bars()
    frame.index = pd.bdate_range("2017-01-01", periods=len(frame))
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    record_development_frames({"A": frame}, journal=journal, campaign_id="diagnostic", now=now)
    record_development_frames({"A": frame}, journal=journal, campaign_id="diagnostic", now=now)
    with pytest.raises(ResearchDataAlreadyExposed, match="previous experiment"):
        ResearchExposureLedger(journal).record(start=frame.index[0].date(), end=frame.index[1].date(),
            campaign_id="fresh-label", snapshot_id="another-vendor", purpose="confirmation", now=now)
