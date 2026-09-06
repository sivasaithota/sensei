"""Durable research exposure across campaign and dataset identifiers."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from sensei.operations import EventAppend, JournalConflict, OperationalJournal


class ResearchDataAlreadyExposed(ValueError):
    pass


# Conservatively classify the history already used by this repository as
# development. Changing vendor, rules or thresholds cannot restore a holdout.
KNOWN_STOCK_EXPOSURE = (date(2018, 1, 1), date(2026, 9, 6))
EXPOSURE_STREAM = "research-exposure:NSE_CASH_EQUITY"


def record_development_frames(frames, *, campaign_id: str,
                              journal: OperationalJournal | None = None,
                              now: datetime | None = None):
    """Record history, including warmup, before an owner-facing research run.

    Pure simulation functions remain side-effect free. CLI and governed lab
    composition own this ledger, shared with their confirmation registry.
    """
    dates = [stamp.date() for frame in frames.values() for stamp in frame.index]
    if not dates:
        return
    if journal is None:
        journal = OperationalJournal(Path(__file__).resolve().parents[3] / "data/operations.sqlite3")
    digest = hashlib.sha256()
    for symbol, frame in sorted(frames.items()):
        digest.update(symbol.encode())
        digest.update(pd.util.hash_pandas_object(frame, index=True).values.tobytes())
    ResearchExposureLedger(journal).record(
        start=min(dates), end=max(dates), campaign_id=campaign_id,
        snapshot_id=f"sha256:{digest.hexdigest()}", purpose="discovery",
        now=now or datetime.now(timezone.utc),
    )


class ResearchExposureLedger:
    def __init__(self, journal: OperationalJournal):
        self.journal = journal

    def claim_policy(self, policy_id: str, campaign_id: str, now: datetime):
        """Burn opaque-policy access before invoking a potentially failing resolver."""
        digest = hashlib.sha256(policy_id.encode()).hexdigest()
        stream = f"research-holdout-policy:{digest}"
        events = self.journal.read_stream(stream)
        if events:
            if events[0].payload["campaign_id"] != campaign_id:
                raise ResearchDataAlreadyExposed("holdout policy belongs to an earlier campaign")
            return
        self.journal.append(EventAppend(
            stream_id=stream, event_type="ResearchHoldoutPolicyClaimed",
            payload={"policy_id": policy_id, "campaign_id": campaign_id},
            idempotency_key=f"research-policy:{digest}:{campaign_id}",
            expected_version=0, occurred_at=now,
        ))

    def record(self, *, start: date, end: date, campaign_id: str,
               snapshot_id: str, purpose: str, now: datetime):
        if not isinstance(start, date) or not isinstance(end, date) or start > end:
            raise ValueError("research exposure requires a valid date interval")
        if end > now.date():
            raise ValueError("research interval cannot extend into the future")
        if purpose not in {"discovery", "confirmation"}:
            raise ValueError("invalid research exposure purpose")
        payload = {"start": start.isoformat(), "end": end.isoformat(),
                   "campaign_id": campaign_id, "snapshot_id": snapshot_id, "purpose": purpose}
        # Include the command timestamp: concurrent identical payloads may have
        # different occurred_at values. Payload deduplication below still makes
        # exposure idempotent; a stream conflict triggers a fresh overlap check.
        key = hashlib.sha256((str(sorted(payload.items())) + now.isoformat()).encode()).hexdigest()
        for attempt in range(8):
            events = self.journal.read_stream(EXPOSURE_STREAM)
            if purpose == "confirmation":
                known_start, known_end = KNOWN_STOCK_EXPOSURE
                if start <= known_end and known_start <= end:
                    raise ResearchDataAlreadyExposed("requested dates are known stock development history")
                for event in events:
                    previous = event.payload
                    overlaps = start <= date.fromisoformat(previous["end"]) and date.fromisoformat(previous["start"]) <= end
                    same_fixed_cohort = previous["purpose"] == "confirmation" and previous["campaign_id"] == campaign_id
                    if overlaps and not same_fixed_cohort:
                        raise ResearchDataAlreadyExposed("dates were exposed by a previous experiment")
            if any(event.payload == payload for event in events):
                return
            try:
                self.journal.append(EventAppend(
                    stream_id=EXPOSURE_STREAM, event_type="ResearchWindowExposed",
                    payload=payload, idempotency_key=f"research-exposure:{key}",
                    expected_version=len(events), occurred_at=now,
                ))
                return
            except JournalConflict:
                if attempt == 7:
                    raise
