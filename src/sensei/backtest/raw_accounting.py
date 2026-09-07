"""Physical-share execution inputs for a deliberately bounded research model.

Signals may use a separate adjusted series. Cash dividends accrue as non-spendable
gross entitlements. Unsupported mandatory actions stop the simulation.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import hashlib
import inspect
import json
import math
import re

import pandas as pd


def tick_round(price, tick_paise, *, buy=False):
    tick = Decimal(int(tick_paise)) / 100
    return float((Decimal(str(price)) / tick).to_integral_value(
        rounding=ROUND_CEILING if buy else ROUND_FLOOR) * tick)


@dataclass(frozen=True)
class RawAction:
    symbol: str
    ex_date: pd.Timestamp
    kind: str
    amount: float
    source_id: str
    subject: str


@dataclass(frozen=True)
class RawAccounting:
    frames: dict[str, pd.DataFrame]
    ticks: dict[str, pd.Series]
    actions: tuple[RawAction, ...]
    evidence_sha256: str
    start: pd.Timestamp
    end: pd.Timestamp

    def validate(self, symbols, sessions):
        if set(self.frames) != set(symbols) or set(self.ticks) != set(symbols):
            raise ValueError("raw execution must retain the complete signal universe")
        if re.fullmatch(r"[0-9a-f]{64}", self.evidence_sha256) is None:
            raise ValueError("raw execution requires an evidence SHA-256")
        if not sessions or sessions[0] < self.start or sessions[-1] > self.end:
            raise ValueError("raw accounting scope does not cover evaluation")
        for symbol, frame in self.frames.items():
            if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.has_duplicates:
                raise ValueError("raw execution dates must be unique")
            if not self.ticks[symbol].index.equals(frame.index):
                raise ValueError("raw tick calendar must equal raw price calendar")
        ids = set()
        for action in self.actions:
            if action.symbol not in symbols or not self.start <= action.ex_date <= self.end:
                raise ValueError("action outside accounting scope")
            if action.source_id in ids:
                raise ValueError("duplicate corporate action")
            ids.add(action.source_id)
            if action.kind not in {"dividend", "no_accounting", "unsupported"}:
                raise ValueError("unknown action treatment")
            if not math.isfinite(action.amount) or action.amount < 0 or (
                    action.kind != "dividend" and action.amount != 0):
                raise ValueError("invalid corporate action amount")

    def bar(self, symbol, session):
        frame = self.frames[symbol]
        if session not in frame.index:
            raise ValueError(f"missing raw execution bar: {symbol}:{session.date()}")
        row = frame.loc[session]
        if not bool(row["identity_verified"]):
            raise ValueError(f"unverified raw identity: {symbol}:{session.date()}")
        values = [float(row[k]) for k in ("open", "high", "low", "close", "volume")]
        o, h, l, c, v = values
        if not all(math.isfinite(x) for x in values) or not 0 < l <= min(o, c) <= max(o, c) <= h or v < 0:
            raise ValueError(f"invalid raw execution prices: {symbol}:{session.date()}")
        return row

    def tick(self, symbol, session):
        value = self.ticks[symbol].get(session)
        if pd.isna(value) or value is None or float(value) != int(value) or value <= 0:
            raise ValueError(f"unverified execution tick: {symbol}:{session.date()}")
        return int(value)

    def identity(self):
        def digest(value):
            return hashlib.sha256(pd.util.hash_pandas_object(value, index=True).values.tobytes()).hexdigest()
        return hashlib.sha256(json.dumps({
            "evidence": self.evidence_sha256, "start": str(self.start), "end": str(self.end),
            "frames": {k: digest(v) for k, v in sorted(self.frames.items())},
            "ticks": {k: digest(v) for k, v in sorted(self.ticks.items())},
            "actions": [vars(a) for a in self.actions],
            "implementation": inspect.getsource(inspect.getmodule(self)),
        }, sort_keys=True, default=str).encode()).hexdigest()
