from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from sensei.loop.openexec import live_market_snapshot
from sensei.runtime.production import ProductionPaperSession
from sensei.runtime.production_replay import ReplayProductionPaperSession, ReplayCurrentSessionBarUnavailable

NOW = datetime(2026, 9, 7, 4, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("market_time", [None, "unknown", float("nan"), -1])
def test_quote_without_valid_provider_time_is_unavailable(monkeypatch, market_time):
    import yfinance
    monkeypatch.setattr(yfinance, "Ticker", lambda _: SimpleNamespace(get_info=lambda: {
        "regularMarketPrice": 100, "regularMarketVolume": 1000,
        "regularMarketTime": market_time,
    }))
    assert live_market_snapshot("TEST") is None


@pytest.mark.parametrize("age", [0, 31, -1])
def test_paper_quote_uses_source_time_not_fetch_time(monkeypatch, age):
    from sensei.loop import openexec
    monkeypatch.setattr(openexec, "live_price", lambda _: 100.0)
    observed = NOW - timedelta(seconds=age)
    monkeypatch.setattr(openexec, "live_market_snapshot", lambda _: {
        "last_price": 100.0, "session_volume": 1000.0, "observed_at": observed,
    })
    session = ProductionPaperSession(journal_path="unused", scheduler_config=None)
    quote = session._quote("NSE:TEST", NOW)
    if age != 0:
        assert quote is None
    else:
        assert quote.observed_at == observed
        assert session._execution_observation("NSE:TEST", NOW).observed_at == observed


def test_replay_separates_decision_close_from_execution_open(tmp_path):
    dates = pd.bdate_range("2020-01-01", periods=3)
    bars = pd.DataFrame({
        "open": [100, 120, 900], "high": [101, 800, 1000],
        "low": [99, 1, 800], "close": [100, 700, 999],
        "volume": [100_000, 90_000_000, 1],
    }, index=dates)
    bars.to_parquet(tmp_path / "TEST.parquet")
    session = ReplayProductionPaperSession(
        source_as_of=dates[0].date(), target_as_of=date(2026, 9, 4),
        execution_source_session=dates[1].date(),
        journal_path=tmp_path / "unused", scheduler_config=None, prices_path=tmp_path,
    )
    assert session._bars("NSE:TEST").close.iloc[-1] == 100
    observation = session._execution_observation("NSE:TEST", NOW)
    assert observation.reference_price_paise == 12000
    assert observation.traded_volume <= 100_000
    assert observation.volume_is_estimated
    assert observation.evidence_source == "DAILY_OPEN_PROXY_LAGGED_VOLUME"
    assert session._quote("NSE:TEST", NOW).worst_entry_price_paise >= 12000


def test_replay_rejects_missing_execution_bar_instead_of_using_prior_close(tmp_path):
    bars = pd.DataFrame({"open": [100], "close": [100], "volume": [100_000]},
                        index=pd.to_datetime(["2020-01-01"]))
    bars.to_parquet(tmp_path / "TEST.parquet")
    session = ReplayProductionPaperSession(
        source_as_of=date(2020, 1, 1), target_as_of=date(2026, 9, 4),
        execution_source_session=date(2020, 1, 2),
        journal_path=tmp_path / "unused", scheduler_config=None, prices_path=tmp_path,
    )
    with pytest.raises(ReplayCurrentSessionBarUnavailable):
        session._execution_observation("NSE:TEST", NOW)
    assert session._quote("NSE:TEST", NOW) is None


def test_after_market_paper_settlement_retains_session_close_time(tmp_path):
    from zoneinfo import ZoneInfo

    eod = datetime(2026, 9, 7, 18, 31, tzinfo=ZoneInfo("Asia/Kolkata"))
    bars = pd.DataFrame({"open": [100], "high": [115], "low": [95], "close": [110], "volume": [100_000]},
                        index=pd.to_datetime(["2026-09-07"]))
    bars.to_parquet(tmp_path / "TEST.parquet")
    session = ProductionPaperSession(journal_path=tmp_path / "unused", scheduler_config=None, prices_path=tmp_path)
    observation = session._daily_paper_exit_observation("NSE:TEST", eod)
    assert observation.observed_at.hour == 15
    assert observation.observed_at.minute == 30
    assert observation.observed_at < eod
    assert observation.reference_price_paise == 11000
    assert observation.evidence_source == "COMPLETED_DAILY_BAR_PAPER_SETTLEMENT"
    with pytest.raises(Exception, match="completed current-session bar"):
        session._daily_paper_exit_observation("NSE:TEST", eod + timedelta(days=1))
    with pytest.raises(Exception, match="completed current-session bar"):
        session._daily_paper_exit_observation("NSE:TEST", eod.replace(hour=9))


def test_ranking_many_symbols_does_not_discard_the_selected_quote(monkeypatch):
    from sensei.loop import openexec

    calls = []
    def snapshot(symbol):
        calls.append(symbol)
        return {"last_price": 100., "session_volume": 1000., "observed_at": NOW}
    monkeypatch.setattr(openexec, "live_market_snapshot", snapshot)
    session = ProductionPaperSession(journal_path="unused", scheduler_config=None)
    first = session._execution_observation("NSE:FIRST", NOW)
    session._execution_observation("NSE:SECOND", NOW)
    assert session._execution_observation("NSE:FIRST", NOW) is first
    assert calls == ["FIRST", "SECOND"]
