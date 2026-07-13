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
    df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    df.index.name = "date"
    # Yahoo occasionally emits NaN rows or zero-price rows; either poisons
    # backtest stats (NaN expectancy) — drop them at the source.
    df = df.dropna()
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]
    df["turnover"] = df["close"] * df["volume"]
    PRICES_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(PRICES_DIR / f"{symbol}.parquet")
    return df


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
