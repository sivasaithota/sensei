"""Verified, deterministic news-risk facts for entry admission.

Headlines are risk inputs, never autonomous trade signals.  Providers collect
facts; this module assigns bounded policy outcomes and expires old evidence.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import parsedate_to_datetime
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree

import httpx

from sensei.operations.journal import EventAppend, JournalConflict, OperationalJournal


class NewsRiskLevel(str, Enum):
    CLEAR = "CLEAR"
    CAUTION = "CAUTION"
    BLOCK = "BLOCK"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class NewsEvent:
    event_id: str
    title: str
    source: str
    source_url: str
    published_at: datetime
    affected_symbols: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.title.strip() or not self.source.strip():
            raise ValueError("news title and source are required")
        if not self.source_url.startswith("https://"):
            raise ValueError("news source URL must use HTTPS")
        _aware(self.published_at)
        if any(not symbol.startswith("NSE:") for symbol in self.affected_symbols):
            raise ValueError("affected symbols must use NSE identifiers")
        expected = event_identity(
            source=self.source,
            source_url=self.source_url,
            published_at=self.published_at,
            title=self.title,
            affected_symbols=self.affected_symbols,
        )
        if self.event_id != expected:
            raise ValueError("news event identity is invalid")

    def payload(self) -> dict[str, object]:
        return {
            **asdict(self),
            "published_at": self.published_at.isoformat(),
            "affected_symbols": list(self.affected_symbols),
        }


@dataclass(frozen=True)
class SignedNewsSnapshot:
    observed_at: datetime
    events: tuple[NewsEvent, ...]
    successful_sources: tuple[str, ...]
    failed_sources: tuple[str, ...]
    issuer_id: str
    signature: str
    schema_version: str = "1.0"

    @classmethod
    def issue(
        cls, *, observed_at: datetime, events: Iterable[NewsEvent],
        successful_sources: Iterable[str], failed_sources: Iterable[str],
        issuer_id: str, secret: bytes,
    ) -> "SignedNewsSnapshot":
        _aware(observed_at)
        event_tuple = tuple(sorted(events, key=lambda item: item.event_id))
        successful = tuple(sorted(set(successful_sources)))
        failed = tuple(sorted(set(failed_sources)))
        if not issuer_id.strip() or len(secret) < 32:
            raise ValueError("news issuer and 32-byte secret are required")
        unsigned = cls(
            observed_at, event_tuple, successful, failed,
            issuer_id.strip(), signature="",
        )
        return cls(
            observed_at, event_tuple, successful, failed, issuer_id.strip(),
            _sign(unsigned._unsigned_payload(), secret),
        )

    def _unsigned_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "observed_at": self.observed_at.isoformat(),
            "events": [event.payload() for event in self.events],
            "successful_sources": list(self.successful_sources),
            "failed_sources": list(self.failed_sources),
            "issuer_id": self.issuer_id,
        }

    def payload(self) -> dict[str, object]:
        return {**self._unsigned_payload(), "signature": self.signature}


@dataclass(frozen=True)
class NewsRiskDecision:
    level: NewsRiskLevel
    reason: str
    event_ids: tuple[str, ...] = ()
    snapshot_digest: str | None = None
    snapshot_observed_at: datetime | None = None

    @property
    def blocked(self) -> bool:
        return self.level in {NewsRiskLevel.BLOCK, NewsRiskLevel.UNKNOWN}


class NewsRiskPolicy:
    """Map verified headlines to a bounded admission decision."""

    _BLOCK_TERMS = (
        "market closure", "exchange closure", "trading suspension",
        "capital controls", "state of emergency", "accounting fraud",
        "insolvency", "bankruptcy", "cyberattack on exchange",
    )
    _CAUTION_TERMS = (
        "war", "military strike", "sanctions", "interest rate",
        "central bank", "inflation", "tariff", "earthquake",
        "terror attack", "oil supply", "currency intervention",
    )

    def __init__(
        self, *, maximum_snapshot_age: timedelta = timedelta(minutes=60),
        maximum_event_age: timedelta = timedelta(hours=24),
        minimum_available_feeds: int = 1,
    ) -> None:
        if maximum_snapshot_age <= timedelta(0) or maximum_event_age <= timedelta(0):
            raise ValueError("news freshness windows must be positive")
        if type(minimum_available_feeds) is not int or minimum_available_feeds < 1:
            raise ValueError("minimum_available_feeds must be positive")
        self._maximum_snapshot_age = maximum_snapshot_age
        self._maximum_event_age = maximum_event_age
        self._minimum_available_feeds = minimum_available_feeds

    def assess(
        self, snapshot: SignedNewsSnapshot | None, *, instrument_id: str,
        as_of: datetime,
    ) -> NewsRiskDecision:
        _aware(as_of)
        if snapshot is None:
            return NewsRiskDecision(NewsRiskLevel.UNKNOWN, "news snapshot unavailable")
        digest = snapshot_digest(snapshot)
        observed_at = snapshot.observed_at
        age = as_of - snapshot.observed_at
        if age < timedelta(0) or age > self._maximum_snapshot_age:
            return NewsRiskDecision(
                NewsRiskLevel.UNKNOWN, "news snapshot is stale", (),
                digest, observed_at,
            )
        if len(snapshot.successful_sources) < self._minimum_available_feeds:
            return NewsRiskDecision(
                NewsRiskLevel.UNKNOWN,
                "insufficient available news feeds",
                (), digest, observed_at,
            )
        active = tuple(
            event for event in snapshot.events
            if timedelta(0) <= as_of - event.published_at <= self._maximum_event_age
            and (not event.affected_symbols or instrument_id in event.affected_symbols)
        )
        blocked = tuple(
            event for event in active
            if any(term in event.title.lower() for term in self._BLOCK_TERMS)
        )
        if blocked:
            return NewsRiskDecision(
                NewsRiskLevel.BLOCK,
                _explain("critical news risk", blocked),
                tuple(event.event_id for event in blocked),
                digest, observed_at,
            )
        caution = tuple(
            event for event in active
            if any(term in event.title.lower() for term in self._CAUTION_TERMS)
        )
        if caution:
            return NewsRiskDecision(
                NewsRiskLevel.CAUTION,
                _explain("elevated news risk", caution),
                tuple(event.event_id for event in caution),
                digest, observed_at,
            )
        return NewsRiskDecision(
            NewsRiskLevel.CLEAR, "no active material news risk", (),
            digest, observed_at,
        )


class NewsRiskBook:
    """Persist and verify the latest signed news snapshot."""

    def __init__(
        self, path: Path, *, secret: bytes,
        expected_issuer_id: str = "market-news",
    ) -> None:
        if len(secret) < 32:
            raise ValueError("news verification secret must be at least 32 bytes")
        self._path = Path(path)
        self._secret = secret
        if not expected_issuer_id.strip():
            raise ValueError("expected news issuer is required")
        self._expected_issuer_id = expected_issuer_id.strip()

    def publish(self, snapshot: SignedNewsSnapshot) -> None:
        if snapshot.issuer_id != self._expected_issuer_id:
            raise ValueError("news snapshot issuer is not trusted")
        self.verify(snapshot, secret=self._secret)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(snapshot.payload(), sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, self._path)

    def latest(self) -> SignedNewsSnapshot | None:
        if not self._path.is_file():
            return None
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            snapshot = SignedNewsSnapshot(
                observed_at=datetime.fromisoformat(raw["observed_at"]),
                events=tuple(
                    NewsEvent(
                        event_id=item["event_id"], title=item["title"],
                        source=item["source"], source_url=item["source_url"],
                        published_at=datetime.fromisoformat(item["published_at"]),
                        affected_symbols=tuple(item.get("affected_symbols", ())),
                    )
                    for item in raw["events"]
                ),
                successful_sources=tuple(raw["successful_sources"]),
                failed_sources=tuple(raw["failed_sources"]),
                issuer_id=raw["issuer_id"], signature=raw["signature"],
                schema_version=raw["schema_version"],
            )
            if snapshot.issuer_id != self._expected_issuer_id:
                raise ValueError("news snapshot issuer is not trusted")
            self.verify(snapshot, secret=self._secret)
            return snapshot
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("news snapshot is corrupt or unverifiable") from exc

    @staticmethod
    def verify(snapshot: SignedNewsSnapshot, *, secret: bytes) -> None:
        expected = _sign(snapshot._unsigned_payload(), secret)
        if not hmac.compare_digest(snapshot.signature, expected):
            raise ValueError("news snapshot signature is invalid")


class NewsSecretStore:
    """Owner-only credential dedicated to the independent news producer."""

    @staticmethod
    def load_or_create(path: Path) -> bytes:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        secret = os.urandom(32)
        temporary = target.with_name(
            f".{target.name}.{os.getpid()}.{os.urandom(8).hex()}.tmp"
        )
        try:
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            with os.fdopen(descriptor, "w", encoding="ascii") as handle:
                handle.write(secret.hex())
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, target)
                return secret
            except FileExistsError:
                return NewsSecretStore.load(target)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def load(path: Path) -> bytes:
        target = Path(path)
        metadata = target.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise ValueError("news secret must be an owner-only regular file")
        try:
            secret = bytes.fromhex(target.read_text(encoding="ascii"))
        except ValueError as exc:
            raise ValueError("news secret is corrupt") from exc
        if len(secret) != 32:
            raise ValueError("news secret is corrupt")
        return secret


class RssNewsRefresher:
    """Fetch allowlisted HTTPS RSS/Atom feeds into one signed snapshot."""

    def __init__(
        self, *, book: NewsRiskBook, issuer_id: str, secret: bytes,
        fetch=None, journal: OperationalJournal | None = None,
    ) -> None:
        self._book = book
        self._issuer_id = issuer_id
        self._secret = secret
        self._fetch = fetch or self._fetch_https
        self._journal = journal

    def refresh(
        self, *, feeds: dict[str, str], known_instruments: Iterable[str],
        observed_at: datetime,
    ) -> SignedNewsSnapshot:
        _aware(observed_at)
        known = tuple(sorted(set(known_instruments)))
        events: dict[str, NewsEvent] = {}
        successful: list[str] = []
        failed: list[str] = []
        valid_feeds: dict[str, str] = {}
        for source, url in sorted(feeds.items()):
            if not source.strip() or not url.startswith("https://"):
                failed.append(source or "UNKNOWN")
                continue
            valid_feeds[source] = url
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(valid_feeds)))) as pool:
            futures = {
                pool.submit(self._fetch, url): source
                for source, url in valid_feeds.items()
            }
            for future in as_completed(futures):
                source = futures[future]
                try:
                    for event in _parse_feed(
                        future.result(), source=source, known_instruments=known,
                    ):
                        events[event.event_id] = event
                    successful.append(source)
                except (OSError, ValueError, ElementTree.ParseError, httpx.HTTPError):
                    failed.append(source)
        snapshot = SignedNewsSnapshot.issue(
            observed_at=observed_at,
            events=events.values(),
            successful_sources=successful,
            failed_sources=failed,
            issuer_id=self._issuer_id,
            secret=self._secret,
        )
        self._book.publish(snapshot)
        if self._journal is not None:
            payload = snapshot.payload()
            digest = hashlib.sha256(json.dumps(
                payload, sort_keys=True, separators=(",", ":")
            ).encode()).hexdigest()
            for attempt in range(2):
                try:
                    self._journal.append(EventAppend(
                        stream_id="news-risk",
                        event_type="NewsRiskSnapshotRefreshed",
                        payload={
                            "snapshot_digest": f"sha256:{digest}",
                            "observed_at": snapshot.observed_at.isoformat(),
                            "event_count": len(snapshot.events),
                            "successful_sources": list(snapshot.successful_sources),
                            "failed_sources": list(snapshot.failed_sources),
                        },
                        idempotency_key=(
                            f"news-risk-refresh:{digest}"
                        ),
                        expected_version=len(
                            self._journal.read_stream("news-risk")
                        ),
                        occurred_at=snapshot.observed_at,
                        correlation_id="news-risk-refresh",
                    ))
                    break
                except JournalConflict:
                    if attempt:
                        raise
        return snapshot

    @staticmethod
    def _fetch_https(url: str) -> bytes:
        response = httpx.get(
            url,
            timeout=15,
            follow_redirects=True,
            headers={"User-Agent": "SenseiNewsRisk/1.0"},
        )
        response.raise_for_status()
        return response.content


def event_identity(
    *, source: str, source_url: str, published_at: datetime,
    title: str, affected_symbols: tuple[str, ...],
) -> str:
    body = json.dumps({
        "source": source,
        "source_url": source_url,
        "published_at": published_at.isoformat(),
        "title": title,
        "affected_symbols": list(affected_symbols),
    }, sort_keys=True, separators=(",", ":")).encode()
    return "news:" + hashlib.sha256(body).hexdigest()


def snapshot_digest(snapshot: SignedNewsSnapshot) -> str:
    canonical = json.dumps(
        snapshot.payload(), sort_keys=True, separators=(",", ":")
    ).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def record_news_refresh_failure(
    journal: OperationalJournal, *, occurred_at: datetime, error: Exception,
) -> None:
    """Best-effort typed audit without ever suppressing trading safety work."""
    payload = {
        "reason_code": "NEWS_REFRESH_FAILED",
        "error_type": type(error).__name__,
    }
    key = hashlib.sha256(
        f"{occurred_at.isoformat()}:{type(error).__name__}".encode()
    ).hexdigest()
    try:
        for attempt in range(2):
            try:
                journal.append(EventAppend(
                    stream_id="news-risk",
                    event_type="NewsRiskRefreshFailed",
                    payload=payload,
                    idempotency_key=f"news-risk-failed:{key}",
                    expected_version=len(journal.read_stream("news-risk")),
                    occurred_at=occurred_at,
                    correlation_id="news-risk-refresh",
                ))
                return
            except JournalConflict:
                if attempt:
                    return
    except Exception:
        return


def _parse_feed(
    payload: bytes, *, source: str, known_instruments: tuple[str, ...],
) -> tuple[NewsEvent, ...]:
    root = ElementTree.fromstring(payload)
    results: list[NewsEvent] = []
    for item in root.iter():
        if _local_name(item.tag) not in {"item", "entry"}:
            continue
        fields = {
            _local_name(child.tag): (child.text or "").strip()
            for child in item
        }
        title = fields.get("title", "")
        link = fields.get("link", "")
        if not link:
            link_node = next(
                (child for child in item if _local_name(child.tag) == "link"),
                None,
            )
            if link_node is not None:
                link = link_node.attrib.get("href", "")
        published = fields.get("pubDate") or fields.get("published") or fields.get("updated")
        if not title or not link.startswith("https://") or not published:
            continue
        published_at = _parse_timestamp(published)
        mentioned = tuple(
            instrument for instrument in known_instruments
            if re.search(
                rf"\b{re.escape(instrument.split(':')[-1])}\b",
                title,
                flags=re.IGNORECASE,
            )
        )
        results.append(NewsEvent(
            event_id=event_identity(
                source=source, source_url=link, published_at=published_at,
                title=title, affected_symbols=mentioned,
            ),
            title=title,
            source=source,
            source_url=link,
            published_at=published_at,
            affected_symbols=mentioned,
        ))
    return tuple(results)


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _sign(payload: dict[str, object], secret: bytes) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(secret, canonical, hashlib.sha256).hexdigest()


def _explain(prefix: str, events: tuple[NewsEvent, ...]) -> str:
    first = events[0]
    return f"{prefix}: {first.title} [{first.source}; {first.source_url}]"


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")


__all__ = [
    "NewsEvent", "NewsRiskBook", "NewsRiskDecision", "NewsRiskLevel",
    "NewsSecretStore",
    "NewsRiskPolicy", "RssNewsRefresher", "SignedNewsSnapshot", "event_identity",
    "snapshot_digest",
    "record_news_refresh_failure",
]
