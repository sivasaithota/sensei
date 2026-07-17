"""Historical data store (PRD §8, free-sources-first per owner decision).

Universe: Nifty 100 from NSE's official constituents CSV.
Prices:   daily OHLCV via Yahoo Finance (.NS symbols) into a local
          parquet store. Vendor-swappable: everything downstream reads
          only from the parquet files, never from the fetcher.

Known caveat (accepted for P0): Yahoo data is survivorship-biased and
occasionally gappy. Upgrade to a paid vendor before P2 (micro-live).
"""

from __future__ import annotations

import time
from datetime import timedelta
from pathlib import Path

import httpx
import pandas as pd
import yfinance as yf

# Universe: Nifty 500 (owner decision 2026-07-10). The ₹5 Cr/day liquidity
# rail keeps the illiquid tail untradeable regardless of index membership.
UNIVERSE_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
UA = {"User-Agent": "Mozilla/5.0"}

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
PRICES_DIR = DATA_DIR / "prices"
UNIVERSE_FILE = DATA_DIR / "universe.csv"


def fetch_universe() -> pd.DataFrame:
    """Nifty 100 constituents: symbol, company, industry, ISIN."""
    resp = httpx.get(UNIVERSE_URL, headers=UA, timeout=30)
    resp.raise_for_status()
    from io import StringIO

    df = pd.read_csv(StringIO(resp.text))
    df = df.rename(columns={"Symbol": "symbol", "Company Name": "company",
                            "Industry": "industry", "ISIN Code": "isin"})
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(UNIVERSE_FILE, index=False)
    return df


def load_universe() -> pd.DataFrame:
    if not UNIVERSE_FILE.exists():
        return fetch_universe()
    return pd.read_csv(UNIVERSE_FILE)


def download_symbol(symbol: str, start: str = "1996-01-01") -> pd.DataFrame | None:
    """Daily OHLCV for one NSE symbol; writes data/prices/<symbol>.parquet."""
    df = yf.download(f"{symbol}.NS", start=start, auto_adjust=True,
                     progress=False, multi_level_index=False)
    if df is None or df.empty:
        return None
    df = _clean_prices(df)
    PRICES_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(PRICES_DIR / f"{symbol}.parquet")
    return df


def download_symbols(symbols: list[str] | tuple[str, ...]) -> dict[str, pd.DataFrame | None]:
    """Incrementally refresh a symbol batch with one Yahoo request."""

    selected = tuple(dict.fromkeys(str(symbol).strip() for symbol in symbols))
    if not selected or any(not symbol for symbol in selected):
        return {}
    existing = {}
    starts = []
    for symbol in selected:
        path = PRICES_DIR / f"{symbol}.parquet"
        if not path.is_file():
            starts.append(pd.Timestamp("1996-01-01"))
            continue
        frame = load_prices(symbol)
        existing[symbol] = frame
        starts.append(pd.Timestamp(frame.index[-1]) - timedelta(days=7))
    start = min(starts).date().isoformat()
    tickers = [f"{symbol}.NS" for symbol in selected]
    downloaded = yf.download(
        tickers,
        start=start,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    result = {}
    for symbol, ticker in zip(selected, tickers, strict=True):
        try:
            candidate = (
                downloaded[ticker]
                if isinstance(downloaded.columns, pd.MultiIndex)
                else downloaded
            )
            candidate = _clean_prices(candidate)
            if candidate.empty:
                result[symbol] = None
                continue
            combined = pd.concat((existing.get(symbol), candidate)).drop_duplicates(
                keep="last"
            ) if symbol in existing else candidate
            combined = combined[~combined.index.duplicated(keep="last")].sort_index()
            PRICES_DIR.mkdir(parents=True, exist_ok=True)
            combined.to_parquet(PRICES_DIR / f"{symbol}.parquet")
            result[symbol] = combined
        except (KeyError, TypeError, ValueError):
            result[symbol] = None
    return result


def _clean_prices(frame: pd.DataFrame) -> pd.DataFrame:
    cleaned = frame.rename(columns=str.lower)[
        ["open", "high", "low", "close", "volume"]
    ].copy()
    cleaned.index.name = "date"
    cleaned = cleaned.dropna()
    cleaned = cleaned[(cleaned[["open", "high", "low", "close"]] > 0).all(axis=1)]
    cleaned["turnover"] = cleaned["close"] * cleaned["volume"]
    return cleaned


def download_universe(start: str = "1996-01-01", sleep: float = 0.5) -> dict[str, int]:
    """Download all universe symbols. Returns {symbol: row_count} (0 = failed)."""
    result: dict[str, int] = {}
    for symbol in load_universe()["symbol"]:
        try:
            df = download_symbol(symbol, start=start)
            result[symbol] = 0 if df is None else len(df)
        except Exception:
            result[symbol] = 0
        time.sleep(sleep)
    return result


def load_prices(symbol: str) -> pd.DataFrame:
    df = pd.read_parquet(PRICES_DIR / f"{symbol}.parquet")
    # defensive: older parquet files may predate the download-time cleaning
    df = df.dropna(subset=["open", "high", "low", "close"])
    return df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]


def available_symbols() -> list[str]:
    if not PRICES_DIR.exists():
        return []
    return sorted(p.stem for p in PRICES_DIR.glob("*.parquet"))


def avg_daily_turnover(symbol: str, days: int = 60) -> float:
    """Mean daily traded value (₹) over the trailing window — liquidity rail input."""
    df = load_prices(symbol)
    return float(df["turnover"].tail(days).mean())
