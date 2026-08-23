"""Quarantined facts derived only from securities observed trading in bhavcopy.

This module deliberately models less than a point-in-time universe.  An
observation proves that one symbol/series/ISIN row traded in one verified raw
session.  Absence proves nothing about listing, delisting, suspension or index
membership.  Price discontinuities are review candidates, never inferred
corporate actions or adjustment factors.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from datetime import date
from typing import Protocol

import pandas as pd

from sensei.data.bhavcopy import (
    BhavcopySessionReference,
    QuarantinedRawBhavcopy,
    VerifiedBhavcopySession,
)


STAMP = (
    "PRELIMINARY_OBSERVED_TRADABILITY — observed trades only; no listing, "
    "delisting, membership, authoritative identity, or price adjustment claims"
)
_ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{10}\Z")
_REQUIRED_COLUMNS = frozenset(
    {
        "symbol",
        "series",
        "isin",
        "open",
        "close",
        "volume",
        "turnover",
        "instrument_class",
        "ok",
    }
)


class ObservedTradabilityError(RuntimeError):
    """The quarantined source cannot produce an unambiguous observation."""


class ObservedTradabilitySource(Protocol):
    ADMISSIBLE: bool

    def sessions(self) -> list[date]: ...

    def verified_session(self, day: date) -> VerifiedBhavcopySession: ...


@dataclass(frozen=True)
class TradabilityObservation:
    session_date: date
    observed_key: str
    symbol: str
    series: str
    isin: str | None
    identity_status: str
    observed_traded: bool = True
    listing_status: str = "unknown"
    delisting_status: str = "unknown"
    index_membership_status: str = "unknown"
    price_adjustment_status: str = "raw_unadjusted"


@dataclass(frozen=True)
class ObservedIdentityEpisode:
    episode_id: str
    observed_key: str
    symbol: str
    series: str
    isin: str | None
    first_observed: date
    last_observed: date
    observed_sessions: int
    authority: str = "observed_only"
    listing_status: str = "unknown"
    delisting_status: str = "unknown"


@dataclass(frozen=True)
class PriceDiscontinuityCandidate:
    observed_key: str
    symbol: str
    session_date: date
    previous_observed_date: date
    previous_close: float
    current_open: float
    return_pct: float
    missing_observed_sessions: int
    reason: str = "observed_interval_gap_exceeds_threshold"
    corporate_action_status: str = "unverified"
    quarantined: bool = True


@dataclass(frozen=True)
class ObservedTradabilityReport:
    observations: tuple[TradabilityObservation, ...]
    identity_episodes: tuple[ObservedIdentityEpisode, ...]
    anomalies: tuple[PriceDiscontinuityCandidate, ...]
    source_references: tuple[BhavcopySessionReference, ...]
    source_sessions: int
    excluded_rows: int
    stamp: str = STAMP

    ADMISSIBLE = False

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-ready research artifact without changing authority."""
        return {
            "stamp": self.stamp,
            "admissible": self.ADMISSIBLE,
            "source_sessions": self.source_sessions,
            "excluded_rows": self.excluded_rows,
            "source_references": [
                _json_record(item) for item in self.source_references
            ],
            "observations": [_json_record(item) for item in self.observations],
            "identity_episodes": [
                _json_record(item) for item in self.identity_episodes
            ],
            "anomalies": [_json_record(item) for item in self.anomalies],
        }


def build_observed_tradability(
    source: ObservedTradabilitySource,
    *,
    start: date | None = None,
    end: date | None = None,
    discontinuity_threshold_pct: float = 30.0,
) -> ObservedTradabilityReport:
    """Build observed-only facts from a provenance-verifying quarantined source.

    The threshold detects large open-versus-prior-observed-close gaps for
    review.  It does not identify an action or create an adjustment factor.
    """
    if getattr(source, "ADMISSIBLE", None) is not False:
        raise ObservedTradabilityError(
            "observed tradability requires an explicitly quarantined source"
        )
    if not isinstance(source, QuarantinedRawBhavcopy):
        raise ObservedTradabilityError(
            "observed tradability requires the hash-verifying bhavcopy source"
        )
    if (
        isinstance(discontinuity_threshold_pct, bool)
        or not math.isfinite(discontinuity_threshold_pct)
        or discontinuity_threshold_pct <= 0
    ):
        raise ValueError("discontinuity threshold must be positive and finite")
    if start is not None and end is not None and start > end:
        raise ValueError("start must be on or before end")

    sessions = tuple(
        day
        for day in sorted(set(source.sessions()))
        if (start is None or day >= start) and (end is None or day <= end)
    )
    session_position = {day: position for position, day in enumerate(sessions)}
    observations: list[TradabilityObservation] = []
    episode_rows: list[dict[str, object]] = []
    active_alias: dict[str, tuple[tuple[str, str], int]] = {}
    previous: dict[str, tuple[date, float, str]] = {}
    anomalies: list[PriceDiscontinuityCandidate] = []
    source_references: list[BhavcopySessionReference] = []
    excluded_rows = 0

    for day in sessions:
        session = source.verified_session(day)
        if (
            not isinstance(session, VerifiedBhavcopySession)
            or not session._is_verifier_issued()
        ):
            raise ObservedTradabilityError(
                f"session {day} lacks a verified bhavcopy capability"
            )
        reference = session.reference
        hashes = (
            reference.manifest_sha256,
            reference.zip_sha256,
            reference.csv_sha256,
            reference.parquet_sha256,
        )
        if (
            reference.trade_date != day
            or not reference.parser_version
            or any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in hashes)
        ):
            raise ObservedTradabilityError(
                f"session {day} has an invalid source reference"
            )
        source_references.append(reference)
        frame = session.frame
        missing = _REQUIRED_COLUMNS - set(frame.columns)
        if missing:
            raise ObservedTradabilityError(
                f"session {day} is missing observed-tradability columns: "
                + ", ".join(sorted(missing))
            )
        if not isinstance(frame.index, pd.DatetimeIndex):
            raise ObservedTradabilityError(f"session {day} has no datetime index")
        if any(timestamp.date() != day for timestamp in frame.index):
            raise ObservedTradabilityError(
                f"session {day} contains rows from another date"
            )

        eligible = frame[
            (frame["instrument_class"] == "equity")
            & frame["ok"].eq(True)
            & (pd.to_numeric(frame["volume"], errors="coerce") > 0)
            & (pd.to_numeric(frame["turnover"], errors="coerce") > 0)
        ]
        excluded_rows += len(frame) - len(eligible)
        seen: set[str] = set()
        for _, row in eligible.iterrows():
            symbol = str(row["symbol"]).strip().upper()
            series = str(row["series"]).strip().upper()
            raw_isin = str(row["isin"]).strip().upper()
            isin = raw_isin if _ISIN.fullmatch(raw_isin) else None
            if not symbol or not series:
                raise ObservedTradabilityError(
                    f"session {day} contains an empty symbol or series"
                )
            observed_key = (
                f"isin:{isin}" if isin is not None else f"unresolved:{symbol}:{series}"
            )
            if observed_key in seen:
                raise ObservedTradabilityError(
                    f"duplicate observed identity {observed_key} in session {day}"
                )
            seen.add(observed_key)

            open_price = _finite_positive(row["open"], day, symbol, "open")
            close = _finite_positive(row["close"], day, symbol, "close")
            observations.append(
                TradabilityObservation(
                    session_date=day,
                    observed_key=observed_key,
                    symbol=symbol,
                    series=series,
                    isin=isin,
                    identity_status=("isin_observed" if isin else "unresolved"),
                )
            )
            alias = (symbol, series)
            active = active_alias.get(observed_key)
            if active is None or active[0] != alias:
                episode_rows.append(
                    {
                        "observed_key": observed_key,
                        "symbol": symbol,
                        "series": series,
                        "isin": isin,
                        "first_observed": day,
                        "last_observed": day,
                        "observed_sessions": 1,
                    }
                )
                active_alias[observed_key] = (alias, len(episode_rows) - 1)
            else:
                episode = episode_rows[active[1]]
                episode["last_observed"] = day
                episode["observed_sessions"] = (
                    int(episode["observed_sessions"]) + 1
                )

            prior = previous.get(observed_key)
            if prior is not None:
                prior_day, prior_close, _ = prior
                change_pct = (open_price / prior_close - 1.0) * 100.0
                if abs(change_pct) >= discontinuity_threshold_pct:
                    anomalies.append(
                        PriceDiscontinuityCandidate(
                            observed_key=observed_key,
                            symbol=symbol,
                            session_date=day,
                            previous_observed_date=prior_day,
                            previous_close=prior_close,
                            current_open=open_price,
                            return_pct=change_pct,
                            missing_observed_sessions=max(
                                0,
                                session_position[day]
                                - session_position[prior_day]
                                - 1,
                            ),
                        )
                    )
            previous[observed_key] = (day, close, symbol)

    episodes = tuple(
        ObservedIdentityEpisode(
            episode_id=(
                f"observed-alias:{row['observed_key']}:{row['symbol']}:"
                f"{row['series']}:{row['first_observed'].isoformat()}"
            ),
            observed_key=str(row["observed_key"]),
            symbol=str(row["symbol"]),
            series=str(row["series"]),
            isin=str(row["isin"]) if row["isin"] is not None else None,
            first_observed=row["first_observed"],
            last_observed=row["last_observed"],
            observed_sessions=int(row["observed_sessions"]),
        )
        for row in episode_rows
    )
    return ObservedTradabilityReport(
        observations=tuple(observations),
        identity_episodes=episodes,
        anomalies=tuple(anomalies),
        source_references=tuple(source_references),
        source_sessions=len(sessions),
        excluded_rows=excluded_rows,
    )


def _finite_positive(value: object, day: date, symbol: str, field: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ObservedTradabilityError(
            f"session {day} has invalid {field} for {symbol}"
        ) from exc
    if not math.isfinite(numeric) or numeric <= 0:
        raise ObservedTradabilityError(
            f"session {day} has invalid {field} for {symbol}"
        )
    return numeric


def _json_record(value: object) -> dict[str, object]:
    record = asdict(value)
    for key, item in tuple(record.items()):
        if isinstance(item, date):
            record[key] = item.isoformat()
    return record
