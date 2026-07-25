"""Events guard — "The Reporter" v0 (PRD §4.3, no-trade windows).

Earnings dates from Yahoo's calendar for NSE symbols. Conservative
posture per PRD §12: a symbol inside its no-trade window is blocked in
code (scanner AND fill time), not left to agent judgment. Unknown
dates also block new exposure; absence of event data is not evidence
that an entry is safe.

Results are cached per-day in data/earnings_cache.json — Yahoo calls
are slow and the calendar doesn't move intraday.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

CACHE_FILE = Path(__file__).resolve().parents[3] / "data" / "earnings_cache.json"
NO_TRADE_DAYS_BEFORE = 2   # block entries this close to results
NO_TRADE_DAYS_AFTER = 1    # and right after (gap risk, thesis reset)


def _load_cache(cache_file: Path | None = None) -> dict:
    cache_file = cache_file or CACHE_FILE
    if cache_file.exists():
        cache = json.loads(cache_file.read_text())
        if cache.get("as_of") == date.today().isoformat():
            return cache
    return {"as_of": date.today().isoformat(), "symbols": {}}


def _save_cache(cache: dict, cache_file: Path | None = None) -> None:
    cache_file = cache_file or CACHE_FILE
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(cache, indent=2))


def next_earnings_date(
    symbol: str, *, cache_file: Path | None = None
) -> date | None:
    """Next known earnings date for an NSE symbol; None if unknown."""
    cache = _load_cache(cache_file)
    if symbol in cache["symbols"]:
        v = cache["symbols"][symbol]
        return date.fromisoformat(v) if v else None

    result: date | None = None
    try:
        import yfinance as yf
        t = yf.Ticker(f"{symbol}.NS")
        today = date.today()
        candidates: list[date] = []
        try:
            cal = t.calendar or {}
            for d in cal.get("Earnings Date") or []:
                if isinstance(d, datetime):
                    d = d.date()
                if d >= today:
                    candidates.append(d)
        except Exception:
            pass
        if not candidates:
            try:
                ed = t.earnings_dates
                if ed is not None:
                    for ts in ed.index:
                        d = ts.date()
                        if d >= today:
                            candidates.append(d)
            except Exception:
                pass
        result = min(candidates) if candidates else None
    except Exception:
        result = None

    cache["symbols"][symbol] = result.isoformat() if result else None
    _save_cache(cache, cache_file)
    return result


def in_no_trade_window(
    symbol: str,
    on: date | None = None,
    *,
    cache_file: Path | None = None,
) -> tuple[bool, str]:
    """(blocked, reason). Blocked when `on` falls inside
    [earnings - NO_TRADE_DAYS_BEFORE, earnings + NO_TRADE_DAYS_AFTER]."""
    on = on or date.today()
    ed = (
        next_earnings_date(symbol)
        if cache_file is None
        else next_earnings_date(symbol, cache_file=cache_file)
    )
    if ed is None:
        return True, "earnings date unknown — entry blocked"
    lo = ed - timedelta(days=NO_TRADE_DAYS_BEFORE)
    hi = ed + timedelta(days=NO_TRADE_DAYS_AFTER)
    if lo <= on <= hi:
        return True, f"no-trade window: earnings {ed.isoformat()}"
    return False, f"next earnings {ed.isoformat()} ({(ed - on).days}d away)"
