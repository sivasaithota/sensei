"""Locally held trust material and verified runtime observations.

Secrets are operational state, never repository configuration.  Surveillance
is an observation signed by one of those independently configured producers;
an issuer label inside the observation cannot establish trust by itself.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import json
import os
import stat
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from io import StringIO
from urllib.parse import urlencode

import httpx

from sensei.errors import ActionableSchedulerError


class RuntimeTrustError(ActionableSchedulerError):
    """Runtime authority material or a signed observation is not trustworthy."""

    reason_code = "RUNTIME_TRUST_INPUT_UNAVAILABLE"


@dataclass(frozen=True)
class SurveillanceFetchFailure:
    source_session: date
    report_type: str
    attempt: int
    category: str


@dataclass(frozen=True)
class SurveillanceSourceEvidence:
    source_session: date
    report_type: str
    content_sha256: str


@dataclass(frozen=True)
class SurveillanceRefreshResult:
    stages: dict[str, int]
    source: SurveillanceSourceEvidence
    failed_attempts: tuple[SurveillanceFetchFailure, ...]


class SurveillanceSourceUnavailable(RuntimeTrustError):
    """No recent official regulatory-indicator source could be retrieved."""

    reason_code = "SURVEILLANCE_SOURCE_UNAVAILABLE"

    def __init__(
        self,
        message: str,
        *,
        attempts: tuple[SurveillanceFetchFailure, ...] = (),
    ) -> None:
        super().__init__(message)
        self.attempts = attempts


class RuntimeSecretStore:
    """Create and load a complete, owner-readable-only HMAC trust store."""

    REQUIRED_ISSUERS = (
        "historian",
        "paper-admission",
        "desk-supervisor",
        "risk-officer",
        "devils-advocate",
        "compliance",
        "orchestrator",
        "market-data",
        "paper-gateway",
        "reconciliation",
        "operations-monitor",
        "paper-account",
        "market-surveillance",
    )

    @classmethod
    def bootstrap(cls, path: Path) -> dict[str, bytes]:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise RuntimeTrustError(f"runtime secret store already exists: {target}")
        material = {issuer: os.urandom(32) for issuer in cls.REQUIRED_ISSUERS}
        payload = {
            "schema_version": "1.0",
            "secrets": {
                issuer: base64.b64encode(secret).decode("ascii")
                for issuer, secret in material.items()
            },
        }
        try:
            descriptor = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError as exc:
            raise RuntimeTrustError(
                f"runtime secret store already exists: {target}"
            ) from exc
        with os.fdopen(descriptor, mode="w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        return material

    @classmethod
    def load(cls, path: Path) -> dict[str, bytes]:
        target = Path(path)
        try:
            metadata = target.lstat()
        except FileNotFoundError as exc:
            raise RuntimeTrustError(f"runtime secret store is missing: {target}") from exc
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
        ):
            raise RuntimeTrustError(
                "runtime secret store must be a regular owner file"
            )
        mode = stat.S_IMODE(metadata.st_mode)
        if mode != 0o600:
            raise RuntimeTrustError("runtime secret store must have mode 0600")
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
            encoded = raw["secrets"]
            if raw["schema_version"] != "1.0" or not isinstance(encoded, dict):
                raise ValueError
            if set(encoded) != set(cls.REQUIRED_ISSUERS):
                raise ValueError
            material = {
                issuer: base64.b64decode(encoded[issuer], validate=True)
                for issuer in cls.REQUIRED_ISSUERS
            }
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeTrustError("runtime secret store is invalid or incomplete") from exc
        if any(len(secret) < 32 for secret in material.values()):
            raise RuntimeTrustError("runtime secret material is too short")
        return material


class VerifiedSurveillanceSource:
    """Resolve exchange surveillance stage from a fresh signed daily snapshot."""

    def __init__(
        self,
        path: Path,
        *,
        issuer_id: str,
        secret: bytes,
        maximum_age: timedelta,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        if maximum_age <= timedelta(0):
            raise ValueError("maximum_age must be positive")
        self._path = Path(path)
        self._issuer_id = issuer_id
        self._secret = secret
        self._maximum_age = maximum_age
        self._clock = clock

    @staticmethod
    def publish(
        path: Path,
        *,
        stages: Mapping[str, int],
        session: date,
        observed_at: datetime,
        issuer_id: str,
        secret: bytes,
        source_session: date | None = None,
        source_report_type: str | None = None,
        source_content_sha256: str | None = None,
    ) -> None:
        _aware(observed_at)
        normalized = _stages(stages)
        fact = {
            "schema_version": "1.0",
            "issuer_id": issuer_id,
            "session": session.isoformat(),
            "observed_at": observed_at.isoformat(),
            "stages": normalized,
        }
        if source_session is not None:
            fact["source_session"] = source_session.isoformat()
        if source_report_type is not None:
            fact["source_report_type"] = source_report_type
        if source_content_sha256 is not None:
            fact["source_content_sha256"] = source_content_sha256
        payload = {**fact, "signature": _sign(fact, secret)}
        _atomic_private_json(Path(path), payload)

    def __call__(self, symbol: str, session: date) -> int | None:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            signature = payload.pop("signature")
            observed_at = datetime.fromisoformat(payload["observed_at"])
            snapshot_session = date.fromisoformat(payload["session"])
            source_session = date.fromisoformat(
                payload.get("source_session", payload["session"])
            )
            stages = _stages(payload["stages"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if payload.get("schema_version") != "1.0" or payload.get("issuer_id") != self._issuer_id:
            raise RuntimeTrustError("surveillance producer identity is invalid")
        if not hmac.compare_digest(signature, _sign(payload, self._secret)):
            raise RuntimeTrustError("surveillance signature verification failed")
        now = self._clock()
        _aware(now)
        if observed_at > now or now - observed_at > self._maximum_age:
            return None
        if snapshot_session != session:
            return None
        if source_session > snapshot_session:
            raise RuntimeTrustError("surveillance source session is in the future")
        if snapshot_session - source_session > timedelta(days=7):
            return None
        return stages.get(symbol)


class NseSurveillanceRefresher:
    """Fetch NSE's official daily regulatory-indicator file and attest parsing."""

    REPORTS_URL = "https://www.nseindia.com/api/reports"
    REPORT_TYPES = (
        ("REG1_IND", "Surveillance Indicator New"),
        ("REG_IND", "Surveillance Indicator"),
    )
    REQUIRED_COLUMNS = (
        "scripcode",
        "symbol",
        "nse exclusive",
        "status",
        "series",
        "gsm",
        "long_term_additional_surveillance_measure (long term asm)",
        "unsolicited_sms",
        "insolvency_resolution_process(irp)",
        "short_term_additional_surveillance_measure (short term asm)",
    )

    def __init__(
        self,
        *,
        destination: Path,
        issuer_id: str,
        secret: bytes,
        fetch=None,
        maximum_attempts: int = 3,
        retry_backoff_seconds: float = 1.0,
        sleep=time.sleep,
    ) -> None:
        if maximum_attempts < 1:
            raise ValueError("maximum_attempts must be positive")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must not be negative")
        self._destination = Path(destination)
        self._issuer_id = issuer_id
        self._secret = secret
        self._fetch = fetch or self._fetch_official
        self._maximum_attempts = maximum_attempts
        self._retry_backoff_seconds = retry_backoff_seconds
        self._sleep = sleep
    def refresh(self, *, session: date, observed_at: datetime) -> dict[str, int]:
        return self.refresh_result(session=session, observed_at=observed_at).stages

    def refresh_result(
        self,
        *,
        session: date,
        observed_at: datetime,
    ) -> SurveillanceRefreshResult:
        _aware(observed_at)
        stages = None
        source_session = session
        selected_content = None
        selected_report_type = None
        failures: list[SurveillanceFetchFailure] = []
        prior_day = session - timedelta(days=1)
        for candidate in _recent_trading_sessions(prior_day, limit=7):
            for report_type, report_name in self.REPORT_TYPES:
                url = self.report_url(report_name=report_name, source_session=candidate)
                parsed = None
                content = None
                for attempt in range(self._maximum_attempts):
                    try:
                        content = self._fetch(url)
                        parsed = self.parse(content)
                        break
                    except RuntimeTrustError as exc:
                        failures.append(
                            SurveillanceFetchFailure(
                                source_session=candidate,
                                report_type=report_type,
                                attempt=attempt + 1,
                                category=_surveillance_failure_category(exc),
                            )
                        )
                        if (
                            attempt + 1 < self._maximum_attempts
                            and self._retry_backoff_seconds
                        ):
                            self._sleep(self._retry_backoff_seconds * (2**attempt))
                if parsed:
                    stages = parsed
                    source_session = candidate
                    selected_content = content
                    selected_report_type = report_type
                    break
            if stages is not None:
                break
        if stages is None:
            raise SurveillanceSourceUnavailable(
                "no recent official NSE surveillance file is available",
                attempts=tuple(failures),
            )
        assert selected_content is not None and selected_report_type is not None
        content_sha256 = hashlib.sha256(selected_content).hexdigest()
        VerifiedSurveillanceSource.publish(
            self._destination,
            stages=stages,
            session=session,
            observed_at=observed_at,
            issuer_id=self._issuer_id,
            secret=self._secret,
            source_session=source_session,
            source_report_type=selected_report_type,
            source_content_sha256=content_sha256,
        )
        return SurveillanceRefreshResult(
            stages=stages,
            source=SurveillanceSourceEvidence(
                source_session=source_session,
                report_type=selected_report_type,
                content_sha256=content_sha256,
            ),
            failed_attempts=tuple(failures),
        )

    @classmethod
    def report_url(cls, *, report_name: str, source_session: date) -> str:
        archives = json.dumps(
            [
                {
                    "name": report_name,
                    "type": "daily-reports",
                    "category": "capital-market",
                    "section": "equities",
                }
            ],
            separators=(",", ":"),
        )
        query = urlencode(
            {
                "archives": archives,
                "date": source_session.strftime("%d-%b-%Y"),
                "type": "Equities",
                "mode": "single",
            }
        )
        return f"{cls.REPORTS_URL}?{query}"

    @staticmethod
    def parse(content: bytes) -> dict[str, int]:
        try:
            text = content.decode("utf-8-sig")
        except (AttributeError, UnicodeDecodeError) as exc:
            raise RuntimeTrustError("NSE regulatory indicator encoding is invalid") from exc
        try:
            rows = csv.reader(StringIO(text))
            header = next(rows)
            normalized_header = tuple(value.strip().lower() for value in header[:10])
            if normalized_header != NseSurveillanceRefresher.REQUIRED_COLUMNS:
                raise ValueError
            result: dict[str, int] = {}
            for row in rows:
                if not row:
                    continue
                if len(row) < 10 or row[3].strip() != "A":
                    continue
                symbol = row[1].strip()
                raw_stages = (int(row[5]), int(row[6]), int(row[9]))
                active = [stage for stage in raw_stages if stage != 100]
                stage = max(active, default=0)
                if not symbol or stage < 0:
                    raise ValueError
                result[symbol] = max(result.get(symbol, 0), stage)
        except (csv.Error, IndexError, StopIteration, ValueError) as exc:
            raise RuntimeTrustError("NSE regulatory indicator schema is invalid") from exc
        return dict(sorted(result.items()))

    @staticmethod
    def _fetch_official(url: str) -> bytes:
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/138 Safari/537.36"
                ),
                "Accept": "text/csv,*/*",
                "Referer": "https://www.nseindia.com/all-reports",
            }
            with httpx.Client(
                headers=headers,
                follow_redirects=True,
                timeout=30,
            ) as client:
                landing = client.get("https://www.nseindia.com/all-reports")
                landing.raise_for_status()
                response = client.get(url)
                response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            disposition = response.headers.get("content-disposition", "").upper()
            if "csv" not in content_type or "REG" not in disposition:
                raise RuntimeTrustError(
                    "official NSE surveillance response is not a regulatory CSV"
                )
        except httpx.HTTPError as exc:
            raise RuntimeTrustError("official NSE surveillance download failed") from exc
        return response.content


def _stages(values: Mapping[str, int]) -> dict[str, int]:
    if not isinstance(values, Mapping):
        raise ValueError("surveillance stages must be a mapping")
    normalized: dict[str, int] = {}
    for symbol, stage in values.items():
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("surveillance symbol is invalid")
        if isinstance(stage, bool) or not isinstance(stage, int) or stage < 0:
            raise ValueError("surveillance stage is invalid")
        normalized[symbol.strip()] = stage
    return dict(sorted(normalized.items()))


def _surveillance_failure_category(exc: RuntimeTrustError) -> str:
    cause = exc.__cause__
    if isinstance(cause, httpx.HTTPStatusError):
        return f"http_{cause.response.status_code}"
    if isinstance(cause, httpx.RequestError):
        return "network_error"
    message = str(exc).lower()
    if "schema" in message or "encoding" in message:
        return "schema_invalid"
    if "not a regulatory csv" in message:
        return "unexpected_content"
    return "source_unavailable"


def _sign(fact: Mapping[str, object], secret: bytes) -> str:
    message = json.dumps(fact, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _atomic_private_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")


__all__ = [
    "NseSurveillanceRefresher",
    "RuntimeSecretStore",
    "RuntimeTrustError",
    "SurveillanceSourceUnavailable",
    "VerifiedSurveillanceSource",
]


def _recent_trading_sessions(session: date, *, limit: int) -> tuple[date, ...]:
    result = []
    candidate = session
    while len(result) < limit:
        if candidate.weekday() < 5:
            result.append(candidate)
        candidate -= timedelta(days=1)
    return tuple(result)
