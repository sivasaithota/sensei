from datetime import datetime, timedelta, timezone

from sensei.automation.governed_entry import AuthorizedPlan, CanonicalSignalPlanner
from sensei.operations.health import HealthState, OperationalHealth
from sensei.orchestration import ExecutableQuote, StrategyEvidenceStats
from sensei.portfolio_risk import AccountSnapshot
from sensei.operations import OperationalJournal
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
