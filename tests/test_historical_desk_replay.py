from datetime import date, datetime, timezone

import pandas as pd

from sensei.runtime.historical_replay import (
    HistoricalDeskReplay,
    PointInTimePriceView,
    ReplaySessionResult,
)


def test_point_in_time_view_never_exposes_future_bars(tmp_path):
    prices = tmp_path / "prices"
    prices.mkdir()
    pd.DataFrame(
        {"close": [100.0, 101.0, 999.0]},
        index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"]),
    ).to_parquet(prices / "INFY.parquet")

    view = PointInTimePriceView(prices, as_of=date(2026, 1, 2))

    frame = view.load("NSE:INFY")
    assert list(frame["close"]) == [100.0, 101.0]
    assert frame.index.max().date() == date(2026, 1, 2)


def test_replay_preserves_portfolio_across_sessions_and_restarts(tmp_path):
    prices = tmp_path / "prices"
    prices.mkdir()
    pd.DataFrame(
        {"close": [100.0, 101.0, 102.0]},
        index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"]),
    ).to_parquet(prices / "INFY.parquet")
    state = {"position": 0}
    seen = []

    def execute(session, view):
        seen.append((session, view.load("INFY").index.max().date()))
        state["position"] += 1
        return ReplaySessionResult(
            session=session,
            completed=True,
            role_names=("orchestrator",),
            committee_levels=("L1",),
            gateway_commands=("ENTRY",),
            open_positions=state["position"],
            closed_episodes=0,
            learned_episodes=0,
            blockers=(),
        )

    report = HistoricalDeskReplay(
        prices_path=prices,
        sessions=(date(2026, 1, 2), date(2026, 1, 5)),
        execute_session=execute,
        production_fingerprints=lambda: {"journal": "unchanged"},
    ).run()

    assert report.completed_sessions == 2
    assert [result.open_positions for result in report.sessions] == [1, 2]
    assert seen == [
        (date(2026, 1, 2), date(2026, 1, 2)),
        (date(2026, 1, 5), date(2026, 1, 5)),
    ]
    assert report.production_state_unchanged is True
    assert report.certified is False
    assert "TRADE_LIFECYCLE_INCOMPLETE" in report.blockers


def test_replay_fails_certification_for_missing_agents_or_committee(tmp_path):
    prices = tmp_path / "prices"
    prices.mkdir()
    pd.DataFrame(
        {"close": [100.0]},
        index=pd.to_datetime(["2026-01-02"]),
    ).to_parquet(prices / "INFY.parquet")

    report = HistoricalDeskReplay(
        prices_path=prices,
        sessions=(date(2026, 1, 2),),
        execute_session=lambda session, _view: ReplaySessionResult(
            session=session,
            completed=True,
            role_names=("orchestrator",),
            committee_levels=("L1",),
            gateway_commands=(),
            open_positions=0,
            closed_episodes=0,
            learned_episodes=0,
            blockers=(),
        ),
        production_fingerprints=lambda: {"journal": "unchanged"},
    ).run()

    assert report.certified is False
    assert (
        "COHERENT_NINE_AGENT_L1_L4_CYCLE_NOT_OBSERVED"
        in report.blockers
    )


def test_certification_requires_correlated_cycle_and_episode_chain(tmp_path):
    prices = tmp_path / "prices"
    prices.mkdir()
    pd.DataFrame(
        {"close": [100.0]},
        index=pd.to_datetime(["2026-01-02"]),
    ).to_parquet(prices / "INFY.parquet")

    report = HistoricalDeskReplay(
        prices_path=prices,
        sessions=(date(2026, 1, 2),),
        execute_session=lambda session, _view: ReplaySessionResult(
            session=session,
            completed=True,
            role_names=tuple(sorted({
                "orchestrator", "historian", "reporter", "crowd-reader",
                "analyst", "committee", "trader", "coach", "secretary",
            })),
            committee_levels=("L1", "L2", "L3", "L4"),
            gateway_commands=("ENTRY", "PROTECTION", "EXIT"),
            open_positions=0,
            closed_episodes=1,
            learned_episodes=1,
            blockers=(),
            coherent_agent_cycle=True,
            coherent_trade_lifecycle=True,
        ),
        production_fingerprints=lambda: {"journal": "unchanged"},
    ).run()

    assert report.certified is True
