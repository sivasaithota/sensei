"""Verified, deterministic news-risk facts for entry admission.

Headlines are risk inputs, never autonomous trade signals.  Providers collect
facts; this module assigns bounded policy outcomes and expires old evidence.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import stat
import re
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import parsedate_to_datetime
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import urlencode, urljoin
from zoneinfo import ZoneInfo
from xml.etree import ElementTree

import httpx
from lxml import html
from pypdf import PdfReader

from sensei.operations.journal import EventAppend, JournalConflict, OperationalJournal


class NewsRiskLevel(str, Enum):
    CLEAR = "CLEAR"
    CAUTION = "CAUTION"
    BLOCK = "BLOCK"
    UNKNOWN = "UNKNOWN"


class NewsEventCategory(str, Enum):
    GENERAL = "GENERAL"
    GEOPOLITICAL = "GEOPOLITICAL"
    MONETARY_POLICY = "MONETARY_POLICY"
    NATURAL_DISASTER = "NATURAL_DISASTER"
    FINANCIAL_RESULTS = "FINANCIAL_RESULTS"
    SALES_UPDATE = "SALES_UPDATE"
    GUIDANCE = "GUIDANCE"
    CORPORATE_ACTION = "CORPORATE_ACTION"
    PROMOTER_PLEDGE = "PROMOTER_PLEDGE"
    AUDITOR_EVENT = "AUDITOR_EVENT"
    INSOLVENCY = "INSOLVENCY"
    ENFORCEMENT = "ENFORCEMENT"
    TRADING_SUSPENSION = "TRADING_SUSPENSION"


@dataclass(frozen=True)
class FinancialMetric:
    name: str
    value: float
    unit: str
    growth_pct: float | None = None

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.unit.strip():
            raise ValueError("financial metric name and unit are required")
        if not math.isfinite(self.value) or (
            self.growth_pct is not None and not math.isfinite(self.growth_pct)
        ):
            raise ValueError("financial metric values must be finite")


@dataclass(frozen=True)
class NewsEvent:
    event_id: str
    content_digest: str
    source_event_id: str
    title: str
    source: str
    source_url: str
    published_at: datetime
    affected_symbols: tuple[str, ...] = ()
    category: NewsEventCategory = NewsEventCategory.GENERAL
    financial_metrics: tuple[FinancialMetric, ...] = ()
    regions: tuple[str, ...] = ()
    industry: str | None = None
    attachment_url: str | None = None
    attachment_digest: str | None = None
    extractor_version: str | None = None
    expires_at: datetime | None = None
    reporting_period: str | None = None

    def __post_init__(self) -> None:
        if not self.title.strip() or not self.source.strip():
            raise ValueError("news title and source are required")
        if not self.source_url.startswith("https://"):
            raise ValueError("news source URL must use HTTPS")
        _aware(self.published_at)
        if any(not symbol.startswith("NSE:") for symbol in self.affected_symbols):
            raise ValueError("affected symbols must use NSE identifiers")
        if not isinstance(self.category, NewsEventCategory):
            raise TypeError("news category must be a NewsEventCategory")
        if self.attachment_url is not None and not self.attachment_url.startswith(
            "https://"
        ):
            raise ValueError("news attachment URL must use HTTPS")
        if self.expires_at is not None:
            _aware(self.expires_at)
            if self.expires_at < self.published_at:
                raise ValueError("news expiry cannot precede publication")
        expected = event_identity(
            source=self.source,
            source_url=self.source_url,
            published_at=self.published_at,
            title=self.title,
            affected_symbols=self.affected_symbols,
            category=self.category,
            financial_metrics=self.financial_metrics,
            regions=self.regions,
            industry=self.industry,
            attachment_url=self.attachment_url,
            attachment_digest=self.attachment_digest,
            extractor_version=self.extractor_version,
            expires_at=self.expires_at,
            reporting_period=self.reporting_period,
            source_event_id=self.source_event_id,
        )
        if self.event_id != expected:
            raise ValueError("news event identity is invalid")
        if self.content_digest != news_event_content_digest(self):
            raise ValueError("news event content digest is invalid")

    def payload(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "content_digest": self.content_digest,
            "source_event_id": self.source_event_id,
            "title": self.title,
            "source": self.source,
            "source_url": self.source_url,
            "published_at": self.published_at.isoformat(),
            "affected_symbols": list(self.affected_symbols),
            "category": self.category.value,
            "financial_metrics": [
                {
                    "name": item.name, "value": item.value,
                    "unit": item.unit, "growth_pct": item.growth_pct,
                }
                for item in self.financial_metrics
            ],
            "regions": list(self.regions),
            "industry": self.industry,
            "attachment_url": self.attachment_url,
            "attachment_digest": self.attachment_digest,
            "extractor_version": self.extractor_version,
            "expires_at": (
                self.expires_at.isoformat() if self.expires_at is not None else None
            ),
            "reporting_period": self.reporting_period,
        }

    def with_category(self, category: NewsEventCategory) -> "NewsEvent":
        return build_news_event(
            title=self.title, source=self.source, source_url=self.source_url,
            published_at=self.published_at,
            affected_symbols=self.affected_symbols, category=category,
            financial_metrics=self.financial_metrics, regions=self.regions,
            industry=self.industry, attachment_url=self.attachment_url,
            attachment_digest=self.attachment_digest,
            extractor_version=self.extractor_version,
            expires_at=self.expires_at,
            reporting_period=self.reporting_period,
            source_event_id=self.source_event_id,
        )


@dataclass(frozen=True)
class SignedNewsSnapshot:
    observed_at: datetime
    events: tuple[NewsEvent, ...]
    successful_sources: tuple[str, ...]
    failed_sources: tuple[str, ...]
    issuer_id: str
    signature: str
    schema_version: str = "2.0"

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
    _BLOCK_CATEGORIES = frozenset({
        NewsEventCategory.AUDITOR_EVENT,
        NewsEventCategory.INSOLVENCY,
        NewsEventCategory.TRADING_SUSPENSION,
    })
    _CAUTION_CATEGORIES = frozenset({
        NewsEventCategory.GEOPOLITICAL,
        NewsEventCategory.MONETARY_POLICY,
        NewsEventCategory.FINANCIAL_RESULTS,
        NewsEventCategory.SALES_UPDATE,
        NewsEventCategory.GUIDANCE,
        NewsEventCategory.CORPORATE_ACTION,
        NewsEventCategory.PROMOTER_PLEDGE,
        NewsEventCategory.ENFORCEMENT,
    })

    def __init__(
        self, *, maximum_snapshot_age: timedelta = timedelta(minutes=60),
        maximum_event_age: timedelta = timedelta(hours=24),
        minimum_available_feeds: int = 1,
        required_sources: frozenset[str] = frozenset(),
    ) -> None:
        if maximum_snapshot_age <= timedelta(0) or maximum_event_age <= timedelta(0):
            raise ValueError("news freshness windows must be positive")
        if type(minimum_available_feeds) is not int or minimum_available_feeds < 1:
            raise ValueError("minimum_available_feeds must be positive")
        self._maximum_snapshot_age = maximum_snapshot_age
        self._maximum_event_age = maximum_event_age
        self._minimum_available_feeds = minimum_available_feeds
        self._required_sources = frozenset(required_sources)

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
        missing_required = self._required_sources - set(snapshot.successful_sources)
        if missing_required:
            return NewsRiskDecision(
                NewsRiskLevel.UNKNOWN,
                "required news sources unavailable: "
                + ", ".join(sorted(missing_required)),
                (), digest, observed_at,
            )
        active = tuple(
            event for event in snapshot.events
            if timedelta(0) <= as_of - event.published_at <= self._maximum_event_age
            and (not event.affected_symbols or instrument_id in event.affected_symbols)
            and (event.expires_at is None or as_of <= event.expires_at)
        )
        blocked = tuple(
            event for event in active
            if event.category in self._BLOCK_CATEGORIES
            or any(term in event.title.lower() for term in self._BLOCK_TERMS)
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
            if event.category in self._CAUTION_CATEGORIES
            or (
                event.category is NewsEventCategory.NATURAL_DISASTER
                and (
                    bool(event.affected_symbols)
                    or any(term in event.title.lower() for term in (
                        "red alert", "cyclone", "earthquake", "severe",
                    ))
                )
            )
            or any(term in event.title.lower() for term in self._CAUTION_TERMS)
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
        temporary = self._path.with_name(
            f".{self._path.name}.{os.getpid()}.{os.urandom(8).hex()}.tmp"
        )
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
                        content_digest=item["content_digest"],
                        source_event_id=item["source_event_id"],
                        source=item["source"], source_url=item["source_url"],
                        published_at=datetime.fromisoformat(item["published_at"]),
                        affected_symbols=tuple(item.get("affected_symbols", ())),
                        category=NewsEventCategory(
                            item.get("category", NewsEventCategory.GENERAL.value)
                        ),
                        financial_metrics=tuple(
                            FinancialMetric(
                                name=metric["name"], value=float(metric["value"]),
                                unit=metric["unit"],
                                growth_pct=(
                                    float(metric["growth_pct"])
                                    if metric.get("growth_pct") is not None else None
                                ),
                            )
                            for metric in item.get("financial_metrics", ())
                        ),
                        regions=tuple(item.get("regions", ())),
                        industry=item.get("industry"),
                        attachment_url=item.get("attachment_url"),
                        attachment_digest=item.get("attachment_digest"),
                        extractor_version=item.get("extractor_version"),
                        expires_at=(
                            datetime.fromisoformat(item["expires_at"])
                            if item.get("expires_at") else None
                        ),
                        reporting_period=item.get("reporting_period"),
                    )
                    for item in raw["events"]
                ),
                successful_sources=tuple(raw["successful_sources"]),
                failed_sources=tuple(raw["failed_sources"]),
                issuer_id=raw["issuer_id"], signature=raw["signature"],
                schema_version=raw["schema_version"],
            )
            if snapshot.schema_version != "2.0":
                raise ValueError("news snapshot schema is unsupported")
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


class NseCorporateEventSource:
    """Official NSE corporate-announcement facts for known instruments."""

    endpoint = "https://www.nseindia.com/api/corporate-announcements"

    def __init__(
        self, *, fetch_json=None,
        metric_cache: "CorporateMetricCache | None" = None,
        attachment_text=None,
        maximum_attachment_reads: int = 10,
    ) -> None:
        self._fetch_json = fetch_json or self._fetch
        self._metric_cache = metric_cache
        self._attachment_text = attachment_text or _pdf_text
        self._maximum_attachment_reads = maximum_attachment_reads

    def fetch(
        self, *, observed_at: datetime, known_instruments: Iterable[str],
    ) -> tuple[NewsEvent, ...]:
        local_day = observed_at.astimezone(ZoneInfo("Asia/Kolkata")).date()
        query = urlencode({
            "index": "equities",
            "from_date": (local_day - timedelta(days=1)).strftime("%d-%m-%Y"),
            "to_date": local_day.strftime("%d-%m-%Y"),
        })
        payload = self._fetch_json(f"{self.endpoint}?{query}")
        if not isinstance(payload, list):
            raise ValueError("NSE corporate response is invalid")
        known = frozenset(known_instruments)
        events: list[NewsEvent] = []
        attachment_reads = 0
        for item in payload:
            if not isinstance(item, Mapping):
                continue
            symbol = f"NSE:{str(item.get('symbol', '')).strip().upper()}"
            if symbol not in known:
                continue
            title = " - ".join(filter(None, (
                str(item.get("desc", "")).strip(),
                str(item.get("attchmntText", "")).strip(),
            )))
            attachment = str(item.get("attchmntFile", "")).strip() or None
            if not title or attachment is None or not attachment.startswith("https://"):
                continue
            published_at = datetime.strptime(
                str(item["an_dt"]), "%d-%b-%Y %H:%M:%S"
            ).replace(tzinfo=ZoneInfo("Asia/Kolkata")).astimezone(timezone.utc)
            category = _corporate_category(title)
            metrics = (
                _extract_financial_metrics(title)
                if category is NewsEventCategory.FINANCIAL_RESULTS else ()
            )
            attachment_digest = None
            extractor_version = None
            if (
                category is NewsEventCategory.FINANCIAL_RESULTS
                and not metrics
                and self._metric_cache is not None
                and attachment_reads < self._maximum_attachment_reads
            ):
                try:
                    metrics, fetched, attachment_digest = self._metric_cache.resolve(
                        attachment,
                        text_loader=self._attachment_text,
                    )
                    extractor_version = CorporateMetricCache.EXTRACTOR_VERSION
                    attachment_reads += int(fetched)
                except Exception:
                    attachment_reads += 1
                    metrics = ()
            events.append(build_news_event(
                title=title,
                source="NSE_CORPORATE",
                source_url=attachment,
                published_at=published_at,
                affected_symbols=(symbol,),
                category=category,
                financial_metrics=metrics,
                reporting_period=_extract_reporting_period(title),
                industry=(str(item.get("smIndustry")).strip()
                          if item.get("smIndustry") else None),
                attachment_url=attachment,
                attachment_digest=attachment_digest,
                extractor_version=extractor_version,
                source_event_id=str(item.get("seq_id") or attachment),
            ))
        return tuple(events)

    @staticmethod
    def _fetch(url: str) -> object:
        response = httpx.get(
            url, timeout=20, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        )
        response.raise_for_status()
        return response.json()


class CorporateMetricCache:
    """Durable extraction cache keyed by the downloaded filing bytes."""

    EXTRACTOR_VERSION = "financial-metrics-v1"

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def resolve(
        self, url: str, *, text_loader,
    ) -> tuple[tuple[FinancialMetric, ...], bool, str]:
        attachment_digest, text = text_loader(url)
        cache = self._load()
        key = f"{self.EXTRACTOR_VERSION}:{attachment_digest}"
        if key in cache:
            return (
                tuple(_metric_from_payload(item) for item in cache[key]["metrics"]),
                False,
                attachment_digest,
            )
        metrics = _extract_financial_metrics(text)
        cache[key] = {
            "url": url,
            "attachment_digest": attachment_digest,
            "extractor_version": self.EXTRACTOR_VERSION,
            "metrics": [_metric_payload(item) for item in metrics],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(
            f".{self._path.name}.{os.getpid()}.{os.urandom(8).hex()}.tmp"
        )
        temporary.write_text(
            json.dumps(
                {"schema_version": "3.0", "attachments": cache},
                sort_keys=True, separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        os.replace(temporary, self._path)
        return metrics, True, attachment_digest

    def _load(self) -> dict[str, dict[str, object]]:
        if not self._path.is_file():
            return {}
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != "3.0"
            or not isinstance(payload.get("attachments"), dict)
        ):
            return {}
        return payload["attachments"]


class NdmaDisasterEventSource:
    """Official NDMA Sachet alerts scoped through configured company regions."""

    endpoint = "https://sachet.ndma.gov.in/cap_public_website/FetchAllAlertDetails"

    def __init__(self, *, fetch_json=None) -> None:
        self._fetch_json = fetch_json or self._fetch

    def fetch(
        self, *, observed_at: datetime,
        company_regions: Mapping[str, tuple[str, ...]],
    ) -> tuple[NewsEvent, ...]:
        payload = self._fetch_json(self.endpoint)
        if not isinstance(payload, list):
            raise ValueError("NDMA alert response is invalid")
        events: list[NewsEvent] = []
        for item in payload:
            if not isinstance(item, Mapping):
                continue
            area = str(item.get("area_description", "")).strip()
            message = str(item.get("warning_message", "")).strip()
            disaster = str(item.get("disaster_type", "Disaster alert")).strip()
            if not area or not message:
                continue
            starts_at = _parse_ndma_timestamp(
                str(item.get("effective_start_time", ""))
            )
            ends_at = _parse_ndma_timestamp(
                str(item.get("effective_end_time", ""))
            )
            regions = tuple(sorted({
                region
                for configured in company_regions.values()
                for region in configured
                if region.lower() in area.lower()
            }))
            symbols = tuple(sorted(
                symbol for symbol, configured in company_regions.items()
                if any(region.lower() in area.lower() for region in configured)
            ))
            severity = str(item.get("severity", "")).upper()
            title = f"{severity} {disaster}: {message} ({area})"
            events.append(build_news_event(
                title=title,
                source="NDMA_SACHET",
                source_url=self.endpoint,
                published_at=starts_at,
                affected_symbols=symbols,
                category=NewsEventCategory.NATURAL_DISASTER,
                regions=regions,
                expires_at=ends_at,
                source_event_id=str(item.get("identifier") or title),
            ))
        return tuple(events)

    @staticmethod
    def _fetch(url: str) -> object:
        response = httpx.get(url, timeout=20, follow_redirects=True)
        response.raise_for_status()
        return response.json()


class SebiEnforcementEventSource:
    """Official SEBI enforcement orders scoped to the trading universe."""

    endpoint = (
        "https://www.sebi.gov.in/sebiweb/home/HomeAction.do"
        "?doListing=yes&sid=2&ssid=9&smid=6"
    )

    def __init__(self, *, fetch_html=None) -> None:
        self._fetch_html = fetch_html or self._fetch

    def fetch(
        self, *, observed_at: datetime, known_instruments: Iterable[str],
    ) -> tuple[NewsEvent, ...]:
        document = html.fromstring(self._fetch_html(self.endpoint))
        page_title = " ".join(document.xpath("//title/text()"))
        order_links = document.xpath("//a[contains(@href, '/enforcement/orders/')]")
        if "SEBI" not in page_title or "Orders" not in page_title or not order_links:
            raise ValueError("SEBI orders listing schema is invalid")
        known = tuple(sorted(set(known_instruments)))
        events: list[NewsEvent] = []
        for row in document.xpath("//tr[td]"):
            cells = row.xpath("./td")
            anchors = row.xpath(".//a[@href]")
            if len(cells) < 2 or not anchors:
                continue
            date_text = " ".join(cells[0].itertext()).strip()
            title = " ".join(anchors[0].itertext()).strip()
            try:
                published_at = datetime.strptime(date_text, "%b %d, %Y").replace(
                    tzinfo=ZoneInfo("Asia/Kolkata")
                ).astimezone(timezone.utc)
            except ValueError:
                continue
            if not title or not timedelta(0) <= observed_at - published_at <= timedelta(days=2):
                continue
            symbols = tuple(
                instrument for instrument in known
                if re.search(
                    rf"(?<![A-Z0-9]){re.escape(instrument.split(':', 1)[1])}(?![A-Z0-9])",
                    title,
                    re.IGNORECASE,
                )
            )
            source_url = urljoin("https://www.sebi.gov.in", anchors[0].get("href"))
            if "/enforcement/orders/" not in source_url:
                continue
            events.append(build_news_event(
                title=title,
                source="SEBI_ORDERS",
                source_url=source_url,
                published_at=published_at,
                affected_symbols=symbols,
                category=NewsEventCategory.ENFORCEMENT,
                source_event_id=source_url,
            ))
        return tuple(events)

    @staticmethod
    def _fetch(url: str) -> bytes:
        response = httpx.get(
            url, timeout=20, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        return response.content


def india_structured_news_sources(
    *, observed_at: datetime, known_instruments: tuple[str, ...],
    company_regions: Mapping[str, tuple[str, ...]],
    corporate_metric_cache_path: Path,
) -> dict[str, object]:
    """Build lazy authoritative India-market source calls for one refresh."""
    nse = NseCorporateEventSource(
        # Scheduled admission refreshes publish filing metadata immediately.
        # Attachment enrichment belongs to an offline research process and
        # must never delay the single-instance 09:20 scheduler wakeup.
        metric_cache=CorporateMetricCache(corporate_metric_cache_path),
        maximum_attachment_reads=0,
    )
    ndma = NdmaDisasterEventSource()
    sebi = SebiEnforcementEventSource()
    return {
        "NSE_CORPORATE": lambda: nse.fetch(
            observed_at=observed_at,
            known_instruments=known_instruments,
        ),
        "NDMA_SACHET": lambda: ndma.fetch(
            observed_at=observed_at,
            company_regions=company_regions,
        ),
        "SEBI_ORDERS": lambda: sebi.fetch(
            observed_at=observed_at,
            known_instruments=known_instruments,
        ),
    }


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
        structured_sources: Mapping[str, object] | None = None,
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
        structured = dict(structured_sources or {})
        with ThreadPoolExecutor(max_workers=min(4, max(1, len(structured)))) as pool:
            futures = {
                pool.submit(fetch_events): source
                for source, fetch_events in structured.items()
                if callable(fetch_events)
            }
            failed.extend(
                source for source, fetch_events in structured.items()
                if not callable(fetch_events)
            )
            for future in as_completed(futures):
                source = futures[future]
                try:
                    for event in future.result():
                        if not isinstance(event, NewsEvent):
                            raise TypeError("structured source returned an invalid event")
                        events[event.event_id] = event
                    successful.append(source)
                except (OSError, TypeError, ValueError, httpx.HTTPError):
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
    category: NewsEventCategory = NewsEventCategory.GENERAL,
    financial_metrics: tuple[FinancialMetric, ...] = (),
    regions: tuple[str, ...] = (), industry: str | None = None,
    attachment_url: str | None = None,
    attachment_digest: str | None = None,
    extractor_version: str | None = None,
    expires_at: datetime | None = None,
    reporting_period: str | None = None,
    source_event_id: str | None = None,
) -> str:
    upstream = source_event_id or f"{source_url}\n{published_at.isoformat()}"
    body = json.dumps({
        "source": source,
        "source_event_id": upstream,
    }, sort_keys=True, separators=(",", ":")).encode()
    return "news:" + hashlib.sha256(body).hexdigest()


def build_news_event(
    *, title: str, source: str, source_url: str, published_at: datetime,
    affected_symbols: tuple[str, ...] = (),
    category: NewsEventCategory = NewsEventCategory.GENERAL,
    financial_metrics: tuple[FinancialMetric, ...] = (),
    regions: tuple[str, ...] = (), industry: str | None = None,
    attachment_url: str | None = None,
    attachment_digest: str | None = None,
    extractor_version: str | None = None,
    expires_at: datetime | None = None,
    reporting_period: str | None = None,
    source_event_id: str | None = None,
) -> NewsEvent:
    upstream = source_event_id or f"{source_url}\n{published_at.isoformat()}"
    identity = event_identity(
        source=source, source_url=source_url, published_at=published_at,
        title=title, affected_symbols=affected_symbols, category=category,
        financial_metrics=financial_metrics, regions=regions,
        industry=industry, attachment_url=attachment_url,
        attachment_digest=attachment_digest, extractor_version=extractor_version,
        expires_at=expires_at,
        reporting_period=reporting_period,
        source_event_id=upstream,
    )
    content_payload = _news_event_content_payload(
        title=title, source=source, source_url=source_url,
        published_at=published_at, affected_symbols=affected_symbols,
        category=category, financial_metrics=financial_metrics,
        regions=regions, industry=industry, attachment_url=attachment_url,
        attachment_digest=attachment_digest, extractor_version=extractor_version,
        expires_at=expires_at, reporting_period=reporting_period,
    )
    digest = "sha256:" + hashlib.sha256(json.dumps(
        content_payload, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    return NewsEvent(
        event_id=identity, content_digest=digest, source_event_id=upstream,
        title=title, source=source,
        source_url=source_url, published_at=published_at,
        affected_symbols=affected_symbols, category=category,
        financial_metrics=financial_metrics, regions=regions,
        industry=industry, attachment_url=attachment_url,
        attachment_digest=attachment_digest, extractor_version=extractor_version,
        expires_at=expires_at,
        reporting_period=reporting_period,
    )


def news_event_content_digest(event: NewsEvent) -> str:
    payload = _news_event_content_payload(
        title=event.title, source=event.source, source_url=event.source_url,
        published_at=event.published_at,
        affected_symbols=event.affected_symbols, category=event.category,
        financial_metrics=event.financial_metrics, regions=event.regions,
        industry=event.industry, attachment_url=event.attachment_url,
        attachment_digest=event.attachment_digest,
        extractor_version=event.extractor_version,
        expires_at=event.expires_at, reporting_period=event.reporting_period,
    )
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _news_event_content_payload(
    *, title: str, source: str, source_url: str, published_at: datetime,
    affected_symbols: tuple[str, ...], category: NewsEventCategory,
    financial_metrics: tuple[FinancialMetric, ...], regions: tuple[str, ...],
    industry: str | None, attachment_url: str | None,
    attachment_digest: str | None, extractor_version: str | None,
    expires_at: datetime | None, reporting_period: str | None,
) -> dict[str, object]:
    return {
        "title": title, "source": source, "source_url": source_url,
        "published_at": published_at.isoformat(),
        "affected_symbols": list(affected_symbols), "category": category.value,
        "financial_metrics": [_metric_payload(item) for item in financial_metrics],
        "regions": list(regions), "industry": industry,
        "attachment_url": attachment_url,
        "attachment_digest": attachment_digest,
        "extractor_version": extractor_version,
        "expires_at": expires_at.isoformat() if expires_at is not None else None,
        "reporting_period": reporting_period,
    }


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
        results.append(build_news_event(
            title=title,
            source=source,
            source_url=link,
            published_at=published_at,
            affected_symbols=mentioned,
            category=_headline_category(title),
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


def _parse_ndma_timestamp(value: str) -> datetime:
    try:
        return datetime.strptime(
            value, "%a %b %d %H:%M:%S IST %Y"
        ).replace(tzinfo=ZoneInfo("Asia/Kolkata")).astimezone(timezone.utc)
    except ValueError as exc:
        raise ValueError("NDMA alert timestamp is invalid") from exc


def _corporate_category(text: str) -> NewsEventCategory:
    lowered = text.lower()
    rules = (
        (NewsEventCategory.TRADING_SUSPENSION, ("trading suspension", "suspension of trading")),
        (NewsEventCategory.INSOLVENCY, ("insolvency", "bankruptcy", "liquidation")),
        (NewsEventCategory.AUDITOR_EVENT, ("auditor resignation", "resignation of auditor", "qualified opinion")),
        (NewsEventCategory.PROMOTER_PLEDGE, ("promoter pledge", "encumbrance of shares")),
        (NewsEventCategory.FINANCIAL_RESULTS, ("financial results", "quarterly results", "annual results")),
        (NewsEventCategory.SALES_UPDATE, ("sales update", "production and sales", "business update")),
        (NewsEventCategory.GUIDANCE, ("guidance", "outlook")),
        (NewsEventCategory.ENFORCEMENT, ("sebi order", "penalty", "show cause notice")),
        (NewsEventCategory.CORPORATE_ACTION, ("dividend", "buyback", "stock split", "bonus issue", "merger")),
    )
    for category, terms in rules:
        if any(term in lowered for term in terms):
            return category
    return NewsEventCategory.GENERAL


def _headline_category(text: str) -> NewsEventCategory:
    lowered = text.lower()
    if any(term in lowered for term in (
        "war", "military strike", "sanctions", "tariff", "capital controls",
    )):
        return NewsEventCategory.GEOPOLITICAL
    if any(term in lowered for term in (
        "inflation", "interest rate", "central bank", "monetary policy",
        "currency intervention",
    )):
        return NewsEventCategory.MONETARY_POLICY
    if any(term in lowered for term in (
        "earthquake", "cyclone", "flood", "landslide", "tsunami",
    )):
        return NewsEventCategory.NATURAL_DISASTER
    return NewsEventCategory.GENERAL


def _pdf_text(url: str) -> tuple[str, str]:
    response = httpx.get(
        url, timeout=20, follow_redirects=True,
        headers={"User-Agent": "SenseiCorporateFacts/1.0"},
    )
    response.raise_for_status()
    if len(response.content) > 10_000_000:
        raise ValueError("corporate filing attachment exceeds safety limit")
    attachment_digest = "sha256:" + hashlib.sha256(response.content).hexdigest()
    reader = PdfReader(BytesIO(response.content), strict=False)
    text = "\n".join(
        (page.extract_text() or "")
        for page in reader.pages[:20]
    )[:200_000]
    return attachment_digest, text


def _extract_reporting_period(text: str) -> str | None:
    quarter = re.search(r"\bQ[1-4]\s*(?:FY\s*)?\d{2,4}\b", text, re.IGNORECASE)
    if quarter:
        return quarter.group(0).upper().replace(" ", "")
    ended = re.search(
        r"\b(?:quarter|year|period)\s+ended\s+"
        r"([A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}[./-]\d{1,2}[./-]\d{4})",
        text,
        re.IGNORECASE,
    )
    return ended.group(0).strip() if ended else None


def _metric_payload(metric: FinancialMetric) -> dict[str, object]:
    return {
        "name": metric.name, "value": metric.value,
        "unit": metric.unit, "growth_pct": metric.growth_pct,
    }


def _metric_from_payload(payload: Mapping[str, object]) -> FinancialMetric:
    return FinancialMetric(
        name=str(payload["name"]),
        value=float(payload["value"]),
        unit=str(payload["unit"]),
        growth_pct=(
            float(payload["growth_pct"])
            if payload.get("growth_pct") is not None else None
        ),
    )


def _extract_financial_metrics(text: str) -> tuple[FinancialMetric, ...]:
    names = {
        "revenue": "revenue", "sales": "sales", "net profit": "net_profit",
        "pat": "net_profit", "ebitda": "ebitda", "eps": "eps",
    }
    pattern = re.compile(
        r"\b(revenue|sales|net profit|pat|ebitda|eps)\b[^₹\d]{0,30}"
        r"(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)\s*"
        r"(crore|cr|million|billion)?"
        r"(?:[^.;]{0,35}?\b(up|down|increased?|decreased?|grew|fell)\b"
        r"\s*(?:by\s*)?([\d.]+)\s*%)?",
        flags=re.IGNORECASE,
    )
    metrics: list[FinancialMetric] = []
    seen: set[tuple[object, ...]] = set()
    for match in pattern.finditer(text):
        raw_name, raw_value, raw_unit, direction, growth = match.groups()
        normalized_name = names[raw_name.lower()]
        if raw_unit is None and normalized_name != "eps":
            continue
        unit = {
            "crore": "INR_CRORE", "cr": "INR_CRORE",
            "million": "INR_MILLION", "billion": "INR_BILLION",
        }.get((raw_unit or "").lower(), "NUMBER")
        growth_pct = float(growth) if growth is not None else None
        if growth_pct is not None and direction.lower() in {
            "down", "decrease", "decreased", "fell"
        }:
            growth_pct = -growth_pct
        metric = FinancialMetric(
            normalized_name,
            float(raw_value.replace(",", "")),
            unit,
            growth_pct,
        )
        identity = (metric.name, metric.value, metric.unit, metric.growth_pct)
        if identity not in seen:
            metrics.append(metric)
            seen.add(identity)
    return tuple(metrics)


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
    "CorporateMetricCache", "FinancialMetric", "NdmaDisasterEventSource", "NewsEvent",
    "NewsEventCategory", "NewsRiskBook", "NewsRiskDecision", "NewsRiskLevel",
    "NewsSecretStore", "NseCorporateEventSource", "SebiEnforcementEventSource",
    "NewsRiskPolicy", "RssNewsRefresher", "SignedNewsSnapshot", "event_identity",
    "build_news_event", "snapshot_digest",
    "india_structured_news_sources",
    "record_news_refresh_failure",
]
