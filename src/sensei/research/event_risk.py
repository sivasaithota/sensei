"""Announcement-aware research entry exclusions; never corporate-action accounting."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class UnresolvedDemerger:
    id: str
    symbol: str
    announced_on: date
    available_from: date
    ex_date: date
    sources: tuple[str, ...]


@dataclass(frozen=True)
class EventRiskPolicy:
    post_event_observations: int
    events: tuple[UnresolvedDemerger, ...]
    source_sha256: str

    def identity(self):
        return json.loads(json.dumps(asdict(self), default=str))


def load_event_risk(path: Path) -> EventRiskPolicy:
    content = path.read_bytes()
    raw = json.loads(content)
    if not isinstance(raw, dict) or set(raw) != {"version", "post_event_observations", "events"}:
        raise ValueError("event risk policy requires exactly the documented fields")
    if type(raw["version"]) is not int or raw["version"] != 1:
        raise ValueError("unsupported event risk policy version")
    observations = raw["post_event_observations"]
    if type(observations) is not int or observations < 252:
        raise ValueError("event risk policy requires at least 252 post-event observations")
    if not isinstance(raw["events"], list) or not raw["events"]:
        raise ValueError("event risk policy requires named events")
    events = []
    for row in raw["events"]:
        if not isinstance(row, dict) or set(row) != {"id", "symbol", "announced_on", "available_from", "ex_date", "sources"}:
            raise ValueError("invalid event fields")
        if any(not isinstance(row[k], str) or not row[k].strip() for k in ("id", "symbol")):
            raise ValueError("event id and symbol are required")
        announced, available, ex = (date.fromisoformat(row[k]) for k in ("announced_on", "available_from", "ex_date"))
        if available <= announced:
            raise ValueError("date-only announcements become available no earlier than the following day")
        sources = row["sources"]
        if (not isinstance(sources, list) or not sources or any(not isinstance(u, str)
                or urlparse(u).scheme != "https" or not urlparse(u).netloc for u in sources)):
            raise ValueError("event requires HTTPS primary-source references")
        events.append(UnresolvedDemerger(row["id"], row["symbol"], announced, available, ex, tuple(sources)))
    if len({e.id for e in events}) != len(events):
        raise ValueError("event IDs must be unique")
    return EventRiskPolicy(observations, tuple(events), hashlib.sha256(content).hexdigest())


def entry_masks(frames, policy: EventRiskPolicy):
    unknown = {e.symbol for e in policy.events} - set(frames)
    if unknown:
        raise ValueError(f"event risk policy contains unknown symbols: {sorted(unknown)}")
    masks = {}
    for symbol, frame in frames.items():
        index = frame.index
        if (not isinstance(index, pd.DatetimeIndex) or index.has_duplicates or not index.is_monotonic_increasing
                or index.tz is not None or index.hasnans or not index.equals(index.normalize())):
            raise ValueError("event risk requires an ordered unique daily price calendar")
        allowed = np.ones(len(index), dtype=bool)
        for event in policy.events:
            if event.symbol != symbol:
                continue
            # The bar on the prospective entry date is not yet observable.
            first = index.searchsorted(pd.Timestamp(event.ex_date), side="left")
            observations = np.maximum(0, np.arange(len(index)) - first)
            affected = (index >= pd.Timestamp(event.available_from)) & (observations < policy.post_event_observations)
            allowed &= ~affected
        masks[symbol] = pd.Series(allowed, index=index, dtype=bool)
    return masks


def held_event_exposure(trades, policy: EventRiskPolicy):
    exposed = []
    for trade in trades:
        entry, exit = date.fromisoformat(trade.entry_date[:10]), date.fromisoformat(trade.exit_date[:10])
        for event in policy.events:
            if trade.symbol == event.symbol and entry < event.ex_date <= exit:
                exposed.append({"event_id": event.id, "symbol": event.symbol,
                    "ex_date": str(event.ex_date), "entry_date": str(entry), "exit_date": str(exit),
                    "quantity": trade.quantity, "reason": "unmodeled demerger entitlements"})
    return exposed
