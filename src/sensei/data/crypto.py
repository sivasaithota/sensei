"""Crypto data store — daily OHLCV for the crypto swing experiment.

USD pairs from Yahoo (signal validation doesn't care about the quote
currency; INR execution comes later if edges exist). Stored separately
from equities in data/crypto/ — crypto rules must earn adoption on
crypto evidence, never inherit NSE statistics.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import yfinance as yf

CRYPTO_DIR = Path(__file__).resolve().parents[3] / "data" / "crypto"

# Top coins by market cap with multi-year daily history on Yahoo.
# Stables and exchange tokens excluded.
UNIVERSE = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX",
            "DOT", "LINK", "LTC", "UNI", "ATOM", "XLM", "NEAR"]


def download_crypto(symbols: list[str] | None = None,
                    start: str = "2014-01-01") -> dict[str, int]:
    result: dict[str, int] = {}
    CRYPTO_DIR.mkdir(parents=True, exist_ok=True)
    for sym in symbols or UNIVERSE:
        try:
            df = yf.download(f"{sym}-USD", start=start, auto_adjust=True,
                             progress=False, multi_level_index=False)
            if df is None or df.empty:
                result[sym] = 0
                continue
            df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
            df.index.name = "date"
            df["turnover"] = df["close"] * df["volume"]
            df.to_parquet(CRYPTO_DIR / f"{sym}.parquet")
            result[sym] = len(df)
        except Exception:
            result[sym] = 0
        time.sleep(0.3)
    return result


def load_crypto(symbol: str) -> pd.DataFrame:
    return pd.read_parquet(CRYPTO_DIR / f"{symbol}.parquet")


def available_crypto() -> list[str]:
    if not CRYPTO_DIR.exists():
        return []
    return sorted(p.stem for p in CRYPTO_DIR.glob("*.parquet"))
