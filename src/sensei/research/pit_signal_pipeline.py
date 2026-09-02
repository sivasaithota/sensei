"""Combine quarantined bhavcopy prices with quarantined TrueData filing events.

    TrueData fundamentals/events ─┐
                                  ├─ point-in-time strategy signals
    NSE bhavcopy prices/universe ─┘
                    │
                    └─ portfolio backtest

Both inputs are PRELIMINARY and quarantined, so their combination is too: this
produces research evidence, never admissible examination evidence.

Direction of use matters. The filing study over 11,724 events found post-filing
entries underperform an equal-weight benchmark at every horizon (-0.5% at 1
session decaying to -2.4% at 40) and in every conditional cut. So filings enter
this pipeline as an ENTRY BLACKOUT, not as a long signal — the evidence does not
support buying them.

Point-in-time discipline:
  - a filing is known only from its published ``file_time``, never its period end;
  - blackouts apply to the entry session, so a signal may enter once clear;
  - prices are back-adjusted from NSE's own ``prev_close`` restatements, and any
    window still containing an unexplained jump is dropped rather than traded.
"""

from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from sensei.data.bhavcopy import QuarantinedRawBhavcopy, available_days

STAMP = (
    "PRELIMINARY_COMBINED — quarantined bhavcopy prices + quarantined TrueData "
    "filing events; short-window, index membership NOT established; "
    "must not feed governed examination"
)

_FACTOR_TOL = 0.005
_MIN_FACTOR, _MAX_FACTOR = 0.02, 50.0
_TRUEDATA_ROOT = "~/.local/share/sensei/truedata/raw/corporate"


@dataclass
class PriceUniverse:
    frames: dict[str, pd.DataFrame]
    sessions: list[pd.Timestamp]
    actions: pd.DataFrame
    excluded: list[str] = field(default_factory=list)


def build_price_universe(*, min_sessions: int = 250,
                         min_turnover_inr: float = 5e7) -> PriceUniverse:
    """Back-adjusted per-symbol bars plus the corporate actions detected.

    NSE's ``prev_close`` is the prior close restated in the current session's
    terms; disagreement with the close we archived exposes an action and its
    ratio is the adjustment factor. Earlier bars are scaled by the cumulative
    product of later factors.
    """
    src = QuarantinedRawBhavcopy()
    parts = []
    for day in available_days():
        raw = src.raw_session(day)
        keep = raw[(raw["instrument_class"] == "equity") & raw["ok"]].copy()
        keep["date"] = pd.Timestamp(day)
        parts.append(keep[["date", "symbol", "open", "high", "low", "close",
                           "volume", "turnover", "prev_close"]])
    panel = pd.concat(parts, ignore_index=True).dropna(subset=["symbol", "close"])

    frames, events, excluded = {}, [], []
    for symbol, g in panel.groupby("symbol", sort=True):
        g = g.sort_values("date")
        prior = g["close"].shift(1)
        ratio = g["prev_close"] / prior
        rel = (g["prev_close"] - prior).abs() / g["prev_close"].replace(0, np.nan)
        is_event = rel.gt(_FACTOR_TOL) & ratio.notna()
        if (is_event & ~ratio.between(_MIN_FACTOR, _MAX_FACTOR)).any():
            excluded.append(symbol)
            continue
        frame = g.set_index("date")[
            ["open", "high", "low", "close", "volume", "turnover"]
        ].astype(float)
        if is_event.any():
            factors = pd.Series(1.0, index=frame.index)
            factors.loc[g.loc[is_event, "date"].to_numpy()] = ratio[is_event].to_numpy()
            cum = factors[::-1].cumprod()[::-1].shift(-1).fillna(1.0)
            for col in ("open", "high", "low", "close"):
                frame[col] = frame[col] * cum
            frame["turnover"] = frame["close"] * frame["volume"]
            for d, f in zip(g.loc[is_event, "date"], ratio[is_event]):
                events.append({"symbol": symbol, "date": d, "factor": float(f)})
        if len(frame) < min_sessions:
            continue
        if float(frame["turnover"].median()) < min_turnover_inr:
            continue
        frames[symbol] = frame

    sessions = sorted({d for f in frames.values() for d in f.index})
    return PriceUniverse(frames, sessions,
                         pd.DataFrame(events, columns=["symbol", "date", "factor"]),
                         excluded)


def load_filing_events(root: str = _TRUEDATA_ROOT) -> pd.DataFrame:
    """Result filings keyed on their published ``file_time`` (point-in-time)."""
    base = os.path.expanduser(root)
    rows = []
    for manifest in glob.iglob(base + "/getAllResultsByCompany/**/manifest.json",
                               recursive=True):
        meta = json.load(open(manifest))
        if meta.get("response_class") != "data":
            continue
        payload = os.path.join(os.path.dirname(manifest), meta["payload_file"])
        for rec in json.load(open(payload)).get("Records", []):
            filed = (rec.get("file_time") or "")[:10]
            symbol = (rec.get("Symbol") or "").strip()
            if filed and symbol:
                rows.append({"symbol": symbol, "filed": pd.Timestamp(filed)})
    return pd.DataFrame(rows).drop_duplicates()


def blackout_mask(frames: dict[str, pd.DataFrame], filings: pd.DataFrame, *,
                  before: int = 2, after: int = 3) -> dict[str, pd.Series]:
    """Per-symbol boolean: True where an entry is blocked by filing proximity.

    ``before`` uses only the fact that a filing later appeared on that date,
    which a live desk cannot know; it is therefore included only to measure the
    ceiling of avoidance. ``after`` is strictly point-in-time.
    """
    by_symbol = {s: g["filed"].tolist() for s, g in filings.groupby("symbol")}
    masks = {}
    for symbol, frame in frames.items():
        mask = pd.Series(False, index=frame.index)
        for filed in by_symbol.get(symbol, ()):
            lo = frame.index.searchsorted(filed) - before
            hi = frame.index.searchsorted(filed, side="right") + after
            mask.iloc[max(0, lo):max(0, hi)] = True
        masks[symbol] = mask
    return masks


def filtered_signal(signal_fn, mask: pd.Series):
    """Wrap a strategy so blacked-out sessions cannot originate an entry."""
    def wrapped(df: pd.DataFrame) -> pd.Series:
        raw = signal_fn(df).fillna(False).astype(bool)
        return raw & ~mask.reindex(df.index).fillna(False).astype(bool)
    return wrapped
