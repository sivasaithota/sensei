from __future__ import annotations

import pandas as pd

from sensei.data import store


def _bars(session: str, close: float) -> pd.DataFrame:
    index = pd.DatetimeIndex([session], name="Date")
    return pd.DataFrame(
        {
            "Open": [close],
            "High": [close + 1],
            "Low": [close - 1],
            "Close": [close],
            "Volume": [1_000],
        },
        index=index,
    )


def test_download_symbols_fetches_one_batch_and_merges_existing_history(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(store, "PRICES_DIR", tmp_path)
    _bars("2026-07-15", 100).rename(columns=str.lower).assign(
        turnover=100_000
    ).to_parquet(tmp_path / "INFY.parquet")
    downloaded = pd.concat(
        {
            "INFY.NS": _bars("2026-07-16", 101),
            "TCS.NS": _bars("2026-07-16", 202),
        },
        axis=1,
    )
    calls = []
    monkeypatch.setattr(
        store.yf,
        "download",
        lambda tickers, **kwargs: calls.append((tickers, kwargs)) or downloaded,
    )

    result = store.download_symbols(("INFY", "TCS"))

    assert len(calls) == 1
    assert calls[0][0] == ["INFY.NS", "TCS.NS"]
    # Concurrency is bounded, not unbounded: launchd gives its children only
    # 256 descriptors and an unbounded threaded fetch exhausted them, which then
    # stopped sqlite opening the operations journal mid-desk-cycle.
    assert calls[0][1]["threads"] == store._DOWNLOAD_THREADS
    assert isinstance(store._DOWNLOAD_THREADS, int)
    assert 1 <= store._DOWNLOAD_THREADS <= 8
    assert list(result["INFY"].index.date) == [
        pd.Timestamp("2026-07-15").date(),
        pd.Timestamp("2026-07-16").date(),
    ]
    assert result["TCS"]["close"].iloc[-1] == 202


def test_download_symbols_reports_only_missing_member_as_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PRICES_DIR", tmp_path)
    downloaded = pd.concat({"INFY.NS": _bars("2026-07-16", 101)}, axis=1)
    monkeypatch.setattr(store.yf, "download", lambda *args, **kwargs: downloaded)

    result = store.download_symbols(("INFY", "MISSING"))

    assert result["INFY"] is not None
    assert result["MISSING"] is None


def test_download_symbols_chunks_large_universes(tmp_path, monkeypatch):
    """A full-universe refresh must not open one connection per symbol at once."""
    monkeypatch.setattr(store, "PRICES_DIR", tmp_path)
    symbols = tuple(f"SYM{i}" for i in range(store._DOWNLOAD_CHUNK * 2 + 5))
    calls = []

    def fake(tickers, **kwargs):
        calls.append(tickers)
        return pd.concat({t: _bars("2026-07-16", 10) for t in tickers}, axis=1)

    monkeypatch.setattr(store.yf, "download", fake)
    store.download_symbols(symbols)

    assert len(calls) == 3                       # 50 + 50 + 5
    assert all(len(c) <= store._DOWNLOAD_CHUNK for c in calls)
    assert sum(len(c) for c in calls) == len(symbols)
