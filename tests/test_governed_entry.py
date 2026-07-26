from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from sensei.automation.governed_entry import AuthorizedPlan, CanonicalSignalPlanner
from sensei.operations.health import HealthState, OperationalHealth
from sensei.orchestration import ExecutableQuote, StrategyEvidenceStats
from sensei.portfolio_risk import AccountPosition, AccountSnapshot
from sensei.operations import OperationalJournal
from sensei.strategy import DecisionAction
from tests.test_strategy_plan import hammer_bars, hammer_follow_through_plan


NOW = datetime(2025, 2, 1, 9, 20, tzinfo=timezone.utc)


def account():
    return AccountSnapshot(
        available_cash_paise=10_000_000,
        marked_equity_paise=10_000_000,
        high_water_mark_paise=10_000_000,
        day_pnl_paise=0,
        week_pnl_paise=0,
        positions=(),
        included_reservation_ids=(),
        reconciled=True,
        captured_at=NOW,
    )


def health(*, allowed=True):
    return OperationalHealth(
        state=HealthState.HEALTHY if allowed else HealthState.HALTED,
        assessed_at=NOW,
        reason_codes=() if allowed else ("TEST_HALT",),
        new_entries_allowed=allowed,
        protective_actions_allowed=True,
        readiness_event_id="event:" + "a" * 64,
        readiness_evidence_event_ids=("event:" + "b" * 64,),
        event_id="event:" + "c" * 64,
    )


def test_planner_builds_one_exact_canonical_cycle_from_authorized_signal(tmp_path):
    plan = hammer_follow_through_plan(source_claim_id="claim:" + "d" * 64)
    bars = hammer_bars()
    quote_time = datetime.combine(
        bars.index[-1].date() + timedelta(days=1),
        NOW.timetz(),
    )
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    planner = CanonicalSignalPlanner(
        plans=lambda: (AuthorizedPlan(
            lineage_id="hammer-lineage",
            plan=plan,
            stats=StrategyEvidenceStats(expectancy_pct=1.2, hit_rate=0.45, trades=100),
        ),),
        instruments=lambda: ("NSE:TEST",),
        bars=lambda _instrument: bars,
        quote=lambda instrument, _now: ExecutableQuote(
            instrument_id=instrument,
            snapshot_id="snapshot:" + "e" * 64,
            worst_entry_price_paise=10_000,
            observed_at=quote_time,
        ),
        average_turnover=lambda _instrument: 100_000_000.0,
        journal=journal,
    )

    request = planner.build(
        account_snapshot=account(),
        operational_health=health(),
        now=quote_time,
        command_id="scheduled-entry",
    )

    assert request is not None
    assert request.plan is plan
    assert request.decision_market_snapshot_id.startswith("snapshot:")
    assert request.account_snapshot is not None
    assert request.committee_context.average_daily_turnover_inr == 100_000_000.0
    assert any(
        event.event_type == "DecisionMarketSnapshotRecorded"
        for event in journal.read_all()
    )


def test_planner_emits_no_work_when_health_blocks_entries():
    planner = CanonicalSignalPlanner(
        plans=lambda: (), instruments=lambda: (), bars=lambda _: None,
        quote=lambda *_: None, average_turnover=lambda _: 0.0,
    )

    assert planner.build(
        account_snapshot=account(), operational_health=health(allowed=False),
        now=NOW, command_id="halted-entry",
    ) is None


def test_planner_does_not_pyramid_into_an_instrument_already_held():
    plan = hammer_follow_through_plan()
    bars = hammer_bars()
    held = account().__class__(
        available_cash_paise=9_000_000,
        marked_equity_paise=10_000_000,
        high_water_mark_paise=10_000_000,
        day_pnl_paise=0,
        week_pnl_paise=0,
        positions=(AccountPosition(
            instrument_id="TEST",
            quantity=1,
            notional_paise=1_000_000,
            risk_to_stop_paise=50_000,
        ),),
        included_reservation_ids=(),
        reconciled=True,
        captured_at=NOW,
    )
    planner = CanonicalSignalPlanner(
        plans=lambda: (AuthorizedPlan(
            "lineage", plan, StrategyEvidenceStats(1.0, 0.5, 100)
        ),),
        instruments=lambda: ("NSE:TEST",),
        bars=lambda _instrument: bars,
        quote=lambda instrument, _now: ExecutableQuote(
            instrument, "snapshot:" + "e" * 64, 10_000, NOW
        ),
        average_turnover=lambda _instrument: 100_000_000.0,
    )

    assert planner.build(
        account_snapshot=held,
        operational_health=health(),
        now=NOW,
        command_id="no-pyramid",
    ) is None


def test_planner_reads_each_instrument_once_across_authorized_plans():
    plan = hammer_follow_through_plan()
    second = plan.model_copy(update={"name": "second hammer plan"})
    bars = hammer_bars()
    reads = 0

    def load(_instrument):
        nonlocal reads
        reads += 1
        return bars

    planner = CanonicalSignalPlanner(
        plans=lambda: (
            AuthorizedPlan(
                "first",
                plan,
                StrategyEvidenceStats(1.2, 0.45, 100),
            ),
            AuthorizedPlan(
                "second",
                second,
                StrategyEvidenceStats(1.1, 0.45, 100),
            ),
        ),
        instruments=lambda: ("NSE:TEST",),
        bars=load,
        quote=lambda instrument, now: ExecutableQuote(
            instrument,
            "snapshot:" + "f" * 64,
            10_000,
            now,
        ),
        average_turnover=lambda _instrument: 100_000_000.0,
    )

    assert planner.build(
        account_snapshot=account(),
        operational_health=health(),
        now=NOW,
        command_id="cached-bars",
    ) is not None
    assert reads == 1


def test_planner_ranks_every_signal_by_market_quality_not_ticker_order():
    plan = hammer_follow_through_plan()
    weak = _ranking_bars(
        start=100.0,
        sixty_third_close=101.0,
        twentieth_close=102.0,
        final_close=103.0,
        final_volume=900.0,
    )
    strong = _ranking_bars(
        start=100.0,
        sixty_third_close=112.0,
        twentieth_close=128.0,
        final_close=140.0,
        final_volume=2_000.0,
    )
    evaluated = []

    class EveryFrameSignals:
        def evaluate(self, request):
            evaluated.append(request.instrument_id)
            return SimpleNamespace(action=DecisionAction.ENTER_LONG)

    planner = CanonicalSignalPlanner(
        plans=lambda: (AuthorizedPlan(
            "lineage",
            plan,
            StrategyEvidenceStats(1.0, 0.5, 100),
        ),),
        instruments=lambda: ("NSE:ZZZBEST", "NSE:AAWEAK"),
        bars=lambda instrument: {
            "NSE:AAWEAK": weak,
            "NSE:ZZZBEST": strong,
        }[instrument],
        quote=lambda instrument, now: ExecutableQuote(
            instrument,
            "snapshot:" + "f" * 64,
            10_000,
            now,
        ),
        average_turnover=lambda instrument: {
            "NSE:AAWEAK": 10_000_000.0,
            "NSE:ZZZBEST": 100_000_000.0,
        }[instrument],
        engine=EveryFrameSignals(),
    )

    request = planner.build(
        account_snapshot=account(),
        operational_health=health(),
        now=NOW,
        command_id="rank-all-signals",
    )

    assert set(evaluated) == {"NSE:AAWEAK", "NSE:ZZZBEST"}
    assert request is not None
    assert request.quote.instrument_id == "NSE:ZZZBEST"


def test_planner_selection_is_invariant_to_universe_order():
    plan = hammer_follow_through_plan()
    frames = {
        "NSE:ALPHA": _ranking_bars(
            start=100, sixty_third_close=104, twentieth_close=108,
            final_close=110, final_volume=1_100,
        ),
        "NSE:OMEGA": _ranking_bars(
            start=100, sixty_third_close=112, twentieth_close=125,
            final_close=135, final_volume=1_800,
        ),
    }

    class EveryFrameSignals:
        def evaluate(self, _request):
            return SimpleNamespace(action=DecisionAction.ENTER_LONG)

    def selected(universe):
        planner = CanonicalSignalPlanner(
            plans=lambda: (AuthorizedPlan(
                "lineage", plan, StrategyEvidenceStats(1.0, 0.5, 100),
            ),),
            instruments=lambda: universe,
            bars=frames.__getitem__,
            quote=lambda instrument, now: ExecutableQuote(
                instrument, "snapshot:" + "f" * 64, 10_000, now,
            ),
            average_turnover=lambda instrument: {
                "NSE:ALPHA": 50_000_000.0,
                "NSE:OMEGA": 80_000_000.0,
            }[instrument],
            engine=EveryFrameSignals(),
        )
        request = planner.build(
            account_snapshot=account(),
            operational_health=health(),
            now=NOW,
            command_id="permutation-invariant",
        )
        assert request is not None
        return request.quote.instrument_id

    assert selected(("NSE:ALPHA", "NSE:OMEGA")) == "NSE:OMEGA"
    assert selected(("NSE:OMEGA", "NSE:ALPHA")) == "NSE:OMEGA"


def test_planner_audits_full_signal_count_and_selected_rank(tmp_path):
    plan = hammer_follow_through_plan()
    bars = _ranking_bars(
        start=100, sixty_third_close=110, twentieth_close=120,
        final_close=130, final_volume=1_500,
    )
    journal = OperationalJournal(tmp_path / "operations.sqlite3")

    class EveryFrameSignals:
        def evaluate(self, _request):
            return SimpleNamespace(action=DecisionAction.ENTER_LONG)

    planner = CanonicalSignalPlanner(
        plans=lambda: (AuthorizedPlan(
            "lineage", plan, StrategyEvidenceStats(1.0, 0.5, 100),
        ),),
        instruments=lambda: ("NSE:ONE", "NSE:TWO", "NSE:THREE"),
        bars=lambda _instrument: bars,
        quote=lambda instrument, now: ExecutableQuote(
            instrument, "snapshot:" + "f" * 64, 10_000, now,
        ),
        average_turnover=lambda _instrument: 50_000_000.0,
        journal=journal,
        engine=EveryFrameSignals(),
    )

    assert planner.build(
        account_snapshot=account(),
        operational_health=health(),
        now=NOW,
        command_id="audited-ranking",
    ) is not None

    event = next(
        event for event in journal.read_all()
        if event.event_type == "SignalRankingRecorded"
    )
    assert event.payload["signal_candidate_count"] == 3
    assert event.payload["selected_signal_rank"] == 1
    assert event.payload["policy"]["version"] == (
        "full-universe-market-quality-v1"
    )
    assert len(event.payload["candidates"]) == 3
    assert all(
        0.0 <= candidate["score"]["total"] <= 1.0
        for candidate in event.payload["candidates"]
    )


def test_planner_audits_quote_fallback_without_mislabeling_signal_count(tmp_path):
    plan = hammer_follow_through_plan()
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    frames = {
        "NSE:BEST": _ranking_bars(
            start=100, sixty_third_close=115, twentieth_close=125,
            final_close=140, final_volume=2_000,
        ),
        "NSE:NEXT": _ranking_bars(
            start=100, sixty_third_close=108, twentieth_close=115,
            final_close=125, final_volume=1_500,
        ),
    }

    class EveryFrameSignals:
        def evaluate(self, _request):
            return SimpleNamespace(action=DecisionAction.ENTER_LONG)

    planner = CanonicalSignalPlanner(
        plans=lambda: (AuthorizedPlan(
            "lineage", plan, StrategyEvidenceStats(1.0, 0.5, 100),
        ),),
        instruments=lambda: ("NSE:BEST", "NSE:NEXT"),
        bars=frames.__getitem__,
        quote=lambda instrument, now: (
            None if instrument == "NSE:BEST"
            else ExecutableQuote(
                instrument, "snapshot:" + "f" * 64, 10_000, now,
            )
        ),
        average_turnover=lambda instrument: {
            "NSE:BEST": 100_000_000.0,
            "NSE:NEXT": 80_000_000.0,
        }[instrument],
        journal=journal,
        engine=EveryFrameSignals(),
    )

    request = planner.build(
        account_snapshot=account(),
        operational_health=health(),
        now=NOW,
        command_id="quote-fallback",
    )

    assert request is not None
    assert request.quote.instrument_id == "NSE:NEXT"
    ranking = next(
        event for event in journal.read_all()
        if event.event_type == "SignalRankingRecorded"
    )
    assert ranking.payload["signal_candidate_count"] == 2
    assert ranking.payload["selected_signal_rank"] == 2
    assert ranking.payload["quote_attempts"] == 2


def test_planner_builds_ranked_executable_shortlist_from_one_full_scan():
    plan = hammer_follow_through_plan()
    frames = {
        "NSE:BEST": _oscillating_ranking_bars(
            phase=0.0, final_close=140, final_volume=2_000,
        ),
        "NSE:SECOND": _oscillating_ranking_bars(
            phase=1.7, final_close=132, final_volume=1_800,
        ),
        "NSE:THIRD": _oscillating_ranking_bars(
            phase=3.4, final_close=126, final_volume=1_600,
        ),
    }
    evaluations = []

    class EveryFrameSignals:
        def evaluate(self, request):
            evaluations.append(request.instrument_id)
            return SimpleNamespace(action=DecisionAction.ENTER_LONG)

    planner = CanonicalSignalPlanner(
        plans=lambda: (AuthorizedPlan(
            "lineage", plan, StrategyEvidenceStats(1.0, 0.5, 100),
        ),),
        instruments=lambda: tuple(frames),
        bars=frames.__getitem__,
        quote=lambda instrument, now: ExecutableQuote(
            instrument, "snapshot:" + "f" * 64, 10_000, now,
        ),
        average_turnover=lambda instrument: {
            "NSE:BEST": 100_000_000,
            "NSE:SECOND": 90_000_000,
            "NSE:THIRD": 80_000_000,
        }[instrument],
        engine=EveryFrameSignals(),
    )

    requests = planner.build_shortlist(
        account_snapshot=account(),
        operational_health=health(),
        now=NOW,
        command_id="ranked-shortlist",
        maximum_candidates=3,
    )

    assert set(evaluations) == set(frames)
    assert [request.quote.instrument_id for request in requests] == [
        "NSE:BEST",
        "NSE:SECOND",
        "NSE:THIRD",
    ]


def test_planner_detects_candidate_correlation_with_actual_holding():
    plan = hammer_follow_through_plan()
    leader = _oscillating_ranking_bars(
        phase=0.0, final_close=140.0, final_volume=2_000,
    )
    clone = leader.copy()
    clone.loc[:, ("open", "high", "low", "close")] *= 2

    class EveryFrameSignals:
        def evaluate(self, _request):
            return SimpleNamespace(action=DecisionAction.ENTER_LONG)

    planner = CanonicalSignalPlanner(
        plans=lambda: (AuthorizedPlan(
            "lineage", plan, StrategyEvidenceStats(1.0, 0.5, 100),
        ),),
        instruments=lambda: ("NSE:LEADER",),
        bars={
            "NSE:LEADER": leader,
            "NSE:CLONE": clone,
        }.__getitem__,
        quote=lambda instrument, now: ExecutableQuote(
            instrument, "snapshot:" + "f" * 64, 10_000, now,
        ),
        average_turnover=lambda _instrument: 100_000_000,
        engine=EveryFrameSignals(),
    )

    request = planner.build(
        account_snapshot=account(),
        operational_health=health(),
        now=NOW,
        command_id="diversified-shortlist",
    )
    assert request is not None
    held = replace(
        account(),
        positions=(AccountPosition(
            instrument_id="NSE:CLONE",
            quantity=1,
            notional_paise=20_000,
            risk_to_stop_paise=1_000,
        ),),
    )

    correlated = planner.correlated_holding(request, held)

    assert correlated is not None
    assert correlated[0] == "NSE:CLONE"
    assert correlated[1] == pytest.approx(1.0)


def test_planner_refreshes_shortlisted_request_with_new_exact_session_truth():
    plan = hammer_follow_through_plan()
    bars = hammer_bars()
    planner = CanonicalSignalPlanner(
        plans=lambda: (AuthorizedPlan(
            "lineage", plan, StrategyEvidenceStats(1.0, 0.5, 100),
        ),),
        instruments=lambda: ("NSE:TEST",),
        bars=lambda _instrument: bars,
        quote=lambda instrument, now: ExecutableQuote(
            instrument, "snapshot:" + "f" * 64, 10_000, now,
        ),
        average_turnover=lambda _instrument: 100_000_000,
    )
    original = planner.build(
        account_snapshot=account(),
        operational_health=health(),
        now=NOW,
        command_id="initial-truth",
    )
    assert original is not None
    refreshed_at = NOW + timedelta(seconds=1)
    refreshed_account = replace(
        account(),
        available_cash_paise=9_000_000,
        captured_at=refreshed_at,
    )

    refreshed = planner.refresh_request(
        original,
        account_snapshot=refreshed_account,
        operational_health=health(),
        command_id="second-candidate",
        now=refreshed_at,
    )

    assert refreshed is not None
    assert refreshed.account_snapshot is refreshed_account
    assert refreshed.now == refreshed_at
    assert refreshed.signal_observed_at == refreshed_at
    assert refreshed.quote.observed_at == refreshed_at
    assert refreshed.committee_context.portfolio_state.cash == 90_000
    assert refreshed.command_id.startswith("second-candidate:")


def _ranking_bars(
    *,
    start: float,
    sixty_third_close: float,
    twentieth_close: float,
    final_close: float,
    final_volume: float,
) -> pd.DataFrame:
    periods = 252
    closes = [start] * periods
    closes[-64] = sixty_third_close
    closes[-21] = twentieth_close
    closes[-1] = final_close
    volumes = [1_000.0] * periods
    volumes[-1] = final_volume
    index = pd.date_range("2024-01-01", periods=periods, freq="D")
    return pd.DataFrame({
        "open": closes,
        "high": [value * 1.01 for value in closes],
        "low": [value * 0.99 for value in closes],
        "close": closes,
        "volume": volumes,
    }, index=index)


def _oscillating_ranking_bars(
    *, phase: float, final_close: float, final_volume: float,
) -> pd.DataFrame:
    import math

    periods = 252
    closes = [
        100.0 + index * 0.08 + math.sin(index / 4 + phase) * 3
        for index in range(periods)
    ]
    closes[-1] = final_close
    volumes = [1_000.0] * periods
    volumes[-1] = final_volume
    index = pd.date_range("2024-01-01", periods=periods, freq="D")
    return pd.DataFrame({
        "open": closes,
        "high": [value * 1.01 for value in closes],
        "low": [value * 0.99 for value in closes],
        "close": closes,
        "volume": volumes,
    }, index=index)
