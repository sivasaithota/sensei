"""Quarantined AccelPix historical-data capture for private research.

The provider token is read only from the environment and is never stored in a
plan, manifest, source URI, exception, or artifact. Captured data remains
preliminary vendor-trial material and cannot enter strategy governance.
"""

from __future__ import annotations

import enum
import hashlib
import json
import math
import os
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib.parse import quote

import httpx
import pandas as pd

ACCELPIX_STAMP = (
    "PRELIMINARY_ACCELPIX_VENDOR_DATA — private personal research; "
    "NOT admissible for governed examination"
)
BASE_URL = "https://apidata.accelpix.in"
DEFAULT_STORE = Path.home() / ".local" / "share" / "sensei" / "accelpix"
MAX_RESPONSE_BYTES = 64_000_000
MAX_SYMBOLS = 20_000


class AccelPixError(RuntimeError):
    """Credential-safe AccelPix ingestion failure."""


class AccelPixRequestError(AccelPixError):
    """Safe request failure carrying only operational classification."""

    def __init__(self, message: str, *, classification: str, status_code: int | None):
        super().__init__(message)
        self.classification = classification
        self.status_code = status_code


class RequestKind(str, enum.Enum):
    MASTER = "master"
    EOD = "eod"


@dataclass(frozen=True)
class AccelPixConfig:
    api_token: str = field(repr=False)
    store: Path = DEFAULT_STORE
    request_interval_seconds: float = 1.0

    def __post_init__(self) -> None:
        if not self.api_token:
            raise ValueError("AccelPix API token must not be empty")
        if self.request_interval_seconds < 0:
            raise ValueError("request interval must not be negative")
        object.__setattr__(self, "store", Path(self.store).expanduser())

    @classmethod
    def from_environment(cls) -> "AccelPixConfig":
        token = os.environ.get("ACCELPIX_API_TOKEN", "")
        if not token:
            raise AccelPixError("set ACCELPIX_API_TOKEN in the local environment")
        try:
            interval = float(os.environ.get("ACCELPIX_REQUEST_INTERVAL_SECONDS", "1.0"))
        except ValueError:
            raise AccelPixError(
                "ACCELPIX_REQUEST_INTERVAL_SECONDS must be numeric"
            ) from None
        return cls(
            api_token=token,
            store=Path(os.environ.get("SENSEI_ACCELPIX_DIR", DEFAULT_STORE)),
            request_interval_seconds=interval,
        )


@dataclass(frozen=True)
class AccelPixRequest:
    kind: RequestKind
    ticker: str = ""
    start: date | None = None
    end: date | None = None

    def __post_init__(self) -> None:
        if self.kind is RequestKind.EOD:
            if not self.ticker or self.start is None or self.end is None:
                raise ValueError("EOD request requires ticker, start, and end")
            if self.start > self.end:
                raise ValueError("EOD start must not be after end")
            if len(self.ticker) > 128 or any(char in self.ticker for char in "\r\n"):
                raise ValueError("invalid AccelPix ticker")
        elif self.ticker or self.start is not None or self.end is not None:
            raise ValueError("master request accepts no ticker or dates")

    @classmethod
    def master(cls) -> "AccelPixRequest":
        return cls(RequestKind.MASTER)

    @classmethod
    def eod(cls, ticker: str, start: date, end: date) -> "AccelPixRequest":
        return cls(RequestKind.EOD, ticker.strip().upper(), start, end)

    def canonical(self) -> dict[str, str | None]:
        return {
            "kind": self.kind.value,
            "ticker": self.ticker or None,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
        }

    @property
    def request_id(self) -> str:
        payload = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    @property
    def safe_source_uri(self) -> str:
        if self.kind is RequestKind.MASTER:
            return f"{BASE_URL}/api/hsd/Masters/3?fmt=json"
        assert self.start is not None and self.end is not None
        ticker = quote(self.ticker, safe="")
        return (
            f"{BASE_URL}/api/fda/rest/{ticker}/"
            f"{self.start:%Y%m%d}/{self.end:%Y%m%d}"
        )


@dataclass(frozen=True)
class FetchedPayload:
    content: bytes = field(repr=False)
    content_type: str
    retrieved_at: datetime
    source_uri: str
    status_code: int


class AccelPixClient:
    """Bounded REST client for the provider's documented master and EOD APIs."""

    def __init__(
        self,
        config: AccelPixConfig,
        *,
        http: httpx.Client | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        maximum_attempts: int = 3,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
    ) -> None:
        if maximum_attempts <= 0 or max_response_bytes <= 0:
            raise ValueError("client safety limits must be positive")
        self.config = config
        self.http = http or httpx.Client(timeout=60, follow_redirects=False)
        self.sleeper = sleeper
        self.maximum_attempts = maximum_attempts
        self.max_response_bytes = max_response_bytes
        self._last_request_at: float | None = None

    def fetch(self, request: AccelPixRequest) -> FetchedPayload:
        last_status: int | None = None
        for attempt in range(1, self.maximum_attempts + 1):
            self._pace()
            try:
                response = self.http.get(
                    request.safe_source_uri,
                    params={
                        "api_token": self.config.api_token,
                        **({"fmt": "json"} if request.kind is RequestKind.MASTER else {}),
                    },
                    headers={"Accept": "application/json"},
                )
            except httpx.HTTPError:
                if attempt == self.maximum_attempts:
                    raise AccelPixRequestError(
                        "AccelPix request failed after bounded retries",
                        classification="network_error",
                        status_code=None,
                    ) from None
                self.sleeper(float(2 ** (attempt - 1)) + random.uniform(0.0, 0.25))
                continue
            if response.status_code == 200:
                content = response.content
                if len(content) > self.max_response_bytes:
                    raise AccelPixError("AccelPix response exceeds the safety limit")
                try:
                    decoded = json.loads(content)
                except (UnicodeError, json.JSONDecodeError):
                    raise AccelPixError(
                        "AccelPix response is not a valid JSON data array"
                    ) from None
                if not isinstance(decoded, list):
                    raise AccelPixError(
                        "AccelPix response is not a valid JSON data array"
                    )
                return FetchedPayload(
                    content=content,
                    content_type=response.headers.get("content-type", ""),
                    retrieved_at=datetime.now(timezone.utc),
                    source_uri=request.safe_source_uri,
                    status_code=200,
                )
            last_status = response.status_code
            if response.status_code not in {429, 500, 502, 503, 504}:
                classification = (
                    "authorization_error"
                    if response.status_code in {401, 403}
                    else "not_found"
                    if response.status_code == 404
                    else "request_error"
                )
                raise AccelPixRequestError(
                    f"AccelPix request rejected (HTTP {response.status_code})",
                    classification=classification,
                    status_code=response.status_code,
                )
            if attempt < self.maximum_attempts:
                retry_after = _retry_after_seconds(response.headers.get("Retry-After"))
                delay = (
                    retry_after
                    if retry_after is not None
                    else float(2 ** (attempt - 1)) + random.uniform(0.0, 0.25)
                )
                self.sleeper(delay)
        raise AccelPixRequestError(
            "AccelPix request failed after bounded retries",
            classification="throttled" if last_status == 429 else "remote_error",
            status_code=last_status,
        )

    def _pace(self) -> None:
        now = time.monotonic()
        if self._last_request_at is not None:
            remaining = self.config.request_interval_seconds - (
                now - self._last_request_at
            )
            if remaining > 0:
                self.sleeper(remaining)
        self._last_request_at = time.monotonic()


@dataclass(frozen=True)
class StoredArtifact:
    payload_path: Path
    manifest_path: Path


@dataclass(frozen=True)
class AuditResult:
    expected: int
    verified: int
    missing: int
    failures: int = 0


class AccelPixStore:
    """Owner-only raw store with per-response hashes and safe provenance."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)

    def paths(self, request: AccelPixRequest) -> StoredArtifact:
        directory = self.root / "raw" / request.kind.value / request.request_id[:2]
        return StoredArtifact(
            directory / f"{request.request_id}.json",
            directory / f"{request.request_id}.manifest.json",
        )

    def failure_path(self, request: AccelPixRequest) -> Path:
        directory = self.root / "failures" / request.kind.value / request.request_id[:2]
        return directory / f"{request.request_id}.manifest.json"

    def record_failure(self, request: AccelPixRequest, error: AccelPixRequestError) -> None:
        _atomic_private_write(
            self.failure_path(request),
            (
                json.dumps(
                    {
                        "schema_version": 1,
                        "stamp": ACCELPIX_STAMP,
                        "admissible": False,
                        "request": request.canonical(),
                        "request_id": request.request_id,
                        "source_uri": request.safe_source_uri,
                        "recorded_at": datetime.now(timezone.utc).isoformat(),
                        "classification": error.classification,
                        "status_code": error.status_code,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode(),
        )

    def put(
        self,
        request: AccelPixRequest,
        *,
        content: bytes,
        content_type: str,
        retrieved_at: datetime,
        status_code: int = 200,
    ) -> StoredArtifact:
        paths = self.paths(request)
        paths.payload_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        rows = _json_array_rows(content)
        digest = hashlib.sha256(content).hexdigest()
        manifest = {
            "schema_version": 1,
            "stamp": ACCELPIX_STAMP,
            "admissible": False,
            "request": request.canonical(),
            "request_id": request.request_id,
            "source_uri": request.safe_source_uri,
            "retrieved_at": retrieved_at.astimezone(timezone.utc).isoformat(),
            "content_type": content_type,
            "status_code": status_code,
            "classification": "data" if rows else "no_data",
            "rows": rows,
            "bytes": len(content),
            "sha256": digest,
        }
        _atomic_private_write(paths.payload_path, content)
        _atomic_private_write(
            paths.manifest_path,
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
        )
        return paths

    def verified(self, request: AccelPixRequest) -> StoredArtifact | None:
        paths = self.paths(request)
        if not paths.payload_path.is_file() or not paths.manifest_path.is_file():
            return None
        try:
            manifest = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise AccelPixError("AccelPix artifact manifest is unreadable") from None
        content = paths.payload_path.read_bytes()
        if manifest.get("request_id") != request.request_id:
            raise AccelPixError("AccelPix artifact request identity mismatch")
        if manifest.get("bytes") != len(content):
            raise AccelPixError("AccelPix artifact byte count mismatch")
        if hashlib.sha256(content).hexdigest() != manifest.get("sha256"):
            raise AccelPixError("AccelPix artifact hash mismatch")
        return paths

    def terminal_failure(self, request: AccelPixRequest) -> Mapping[str, object] | None:
        path = self.failure_path(request)
        if not path.is_file():
            return None
        try:
            failure = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise AccelPixError("AccelPix failure checkpoint is unreadable") from None
        if failure.get("request_id") != request.request_id:
            raise AccelPixError("AccelPix failure checkpoint identity mismatch")
        if failure.get("classification") in {
            "authorization_error",
            "request_error",
            "not_found",
        }:
            return failure
        return None

    def audit(self, plan: "AccelPixPlan") -> AuditResult:
        verified = sum(self.verified(request) is not None for request in plan.requests)
        failures = sum(
            self.failure_path(request).is_file() and self.verified(request) is None
            for request in plan.requests
        )
        return AuditResult(
            len(plan.requests), verified, len(plan.requests) - verified, failures
        )


@dataclass(frozen=True)
class AccelPixPlan:
    plan_id: str
    requests: tuple[AccelPixRequest, ...]

    def __post_init__(self) -> None:
        if not self.plan_id or len(self.requests) > MAX_SYMBOLS + 1:
            raise ValueError("invalid AccelPix plan")
        if len({request.request_id for request in self.requests}) != len(self.requests):
            raise ValueError("AccelPix plan contains duplicate requests")

    @classmethod
    def for_eod(
        cls, *, symbols: Sequence[str], start: date, end: date
    ) -> "AccelPixPlan":
        normalized = tuple(sorted({symbol.strip().upper() for symbol in symbols if symbol.strip()}))
        if not normalized or len(normalized) > MAX_SYMBOLS:
            raise ValueError("symbol count is outside the safety limit")
        requests = tuple(AccelPixRequest.eod(symbol, start, end) for symbol in normalized)
        identity = hashlib.sha256(
            json.dumps(
                [request.canonical() for request in requests],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()[:16]
        return cls(f"accelpix-eod-{identity}", requests)

    def write(self, path: Path) -> None:
        payload = {
            "schema_version": 1,
            "stamp": ACCELPIX_STAMP,
            "admissible": False,
            "plan_id": self.plan_id,
            "requests": [request.canonical() for request in self.requests],
        }
        _atomic_private_write(
            path, (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
        )

    @classmethod
    def read(cls, path: Path) -> "AccelPixPlan":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            requests = tuple(
                AccelPixRequest(
                    RequestKind(item["kind"]),
                    item.get("ticker") or "",
                    date.fromisoformat(item["start"]) if item.get("start") else None,
                    date.fromisoformat(item["end"]) if item.get("end") else None,
                )
                for item in payload["requests"]
            )
            return cls(payload["plan_id"], requests)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise AccelPixError("invalid AccelPix plan") from None


def download_plan(
    plan: AccelPixPlan,
    *,
    client: AccelPixClient,
    store: AccelPixStore,
    retry_terminal: bool = False,
) -> AuditResult:
    for request in plan.requests:
        if store.verified(request) is not None:
            continue
        if not retry_terminal and store.terminal_failure(request) is not None:
            raise AccelPixError(
                "plan contains a terminal failure checkpoint; review it before explicit retry"
            )
        try:
            payload = client.fetch(request)
        except AccelPixRequestError as exc:
            store.record_failure(request, exc)
            raise
        store.put(
            request,
            content=payload.content,
            content_type=payload.content_type,
            retrieved_at=payload.retrieved_at,
        )
    return store.audit(plan)


def symbols_from_master(store: AccelPixStore) -> tuple[str, ...]:
    """Return NSE cash-equity tickers from the hash-verified vendor master."""

    artifact = store.verified(AccelPixRequest.master())
    if artifact is None:
        raise AccelPixError("verified AccelPix master is required")
    payload = _load_json_array(artifact.payload_path.read_bytes())
    symbols: set[str] = set()
    for row in payload:
        if not isinstance(row, Mapping):
            raise AccelPixError("AccelPix master row must be an object")
        if str(row.get("xid", "")) == "1" and str(row.get("inst", "")).upper() == "EQUITY":
            ticker = str(row.get("tkr", "")).strip().upper()
            if ticker:
                symbols.add(ticker)
    if not symbols:
        raise AccelPixError("AccelPix master contains no NSE cash equities")
    return tuple(sorted(symbols))


def normalize_eod_plan(
    plan: AccelPixPlan, *, store: AccelPixStore, output: Path
) -> dict[str, int]:
    audit = store.audit(plan)
    if audit.missing:
        raise AccelPixError("cannot normalize an incomplete AccelPix plan")
    rows: list[dict[str, object]] = []
    for request in plan.requests:
        if request.kind is not RequestKind.EOD:
            continue
        artifact = store.verified(request)
        assert artifact is not None
        rows.extend(validate_eod_payload(request, artifact.payload_path.read_bytes()))
    frame = pd.DataFrame(
        rows,
        columns=(
            "symbol",
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "open_interest",
        ),
    )
    if not frame.empty:
        frame = frame.sort_values(["symbol", "date"]).reset_index(drop=True)
        if frame.duplicated(["symbol", "date"]).any():
            raise AccelPixError("AccelPix EOD data contains duplicate symbol dates")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    frame.to_parquet(temporary, index=False)
    temporary.chmod(0o600)
    temporary.replace(output)
    output.chmod(0o600)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    manifest_path = output.with_suffix(".manifest.json")
    coverage: dict[str, dict[str, object]] = {}
    if not frame.empty:
        all_sessions = set(frame["date"])
        for symbol, group in frame.groupby("symbol", sort=True):
            symbol_sessions = set(group["date"])
            jumps = group["close"].pct_change().abs().gt(0.40)
            coverage[str(symbol)] = {
                "rows": len(group),
                "first_date": group["date"].min().date().isoformat(),
                "last_date": group["date"].max().date().isoformat(),
                "missing_observed_sessions": len(all_sessions - symbol_sessions),
                "suspicious_close_jumps": int(jumps.sum()),
            }
    _atomic_private_write(
        manifest_path,
        (
            json.dumps(
                {
                    "schema_version": 1,
                    "stamp": ACCELPIX_STAMP,
                    "admissible": False,
                    "plan_id": plan.plan_id,
                    "symbols": int(frame["symbol"].nunique()) if not frame.empty else 0,
                    "rows": len(frame),
                    "first_date": (
                        frame["date"].min().date().isoformat() if not frame.empty else None
                    ),
                    "last_date": (
                        frame["date"].max().date().isoformat() if not frame.empty else None
                    ),
                    "coverage": coverage,
                    "sha256": digest,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode(),
    )
    return {
        "symbols": int(frame["symbol"].nunique()) if not frame.empty else 0,
        "rows": len(frame),
    }


def validate_eod_payload(
    request: AccelPixRequest, content: bytes
) -> tuple[dict[str, object], ...]:
    """Validate one EOD response without storing or promoting it."""

    if request.kind is not RequestKind.EOD:
        raise ValueError("EOD validation requires an EOD request")
    normalized = tuple(_normalize_eod_row(item, request=request) for item in _load_json_array(content))
    identities = {(row["symbol"], row["date"]) for row in normalized}
    if len(identities) != len(normalized):
        raise AccelPixError("AccelPix EOD data contains duplicate symbol dates")
    return normalized


def _normalize_eod_row(
    item: object, *, request: AccelPixRequest
) -> dict[str, object]:
    if not isinstance(item, Mapping):
        raise AccelPixError("AccelPix EOD row must be an object")
    try:
        symbol = str(item["tkr"]).strip().upper()
        session = pd.Timestamp(item["td"]).tz_localize(None).normalize()
        open_price = float(item["op"])
        high = float(item["hp"])
        low = float(item["lp"])
        close = float(item["cp"])
        raw_volume = float(item["vol"])
        raw_open_interest = float(item.get("oi", 0))
    except (KeyError, TypeError, ValueError, OverflowError):
        raise AccelPixError("AccelPix EOD row has invalid fields") from None
    values = (open_price, high, low, close)
    if symbol != request.ticker or not all(
        math.isfinite(value) and value > 0 for value in values
    ):
        raise AccelPixError("AccelPix EOD row has invalid identity or prices")
    assert request.start is not None and request.end is not None
    if not request.start <= session.date() <= request.end:
        raise AccelPixError("AccelPix EOD row is outside its request window")
    if "eod" in item and item["eod"] is not True:
        raise AccelPixError("AccelPix row is not marked as EOD")
    if high < max(open_price, low, close) or low > min(open_price, high, close):
        raise AccelPixError("AccelPix EOD row has invalid OHLC")
    if (
        not math.isfinite(raw_volume)
        or not math.isfinite(raw_open_interest)
        or not raw_volume.is_integer()
        or not raw_open_interest.is_integer()
        or raw_volume < 0
        or raw_open_interest < 0
    ):
        raise AccelPixError("AccelPix EOD row has invalid volume")
    volume = int(raw_volume)
    open_interest = int(raw_open_interest)
    return {
        "symbol": symbol,
        "date": session,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "open_interest": open_interest,
    }


def _atomic_private_write(path: Path, content: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(content)
    temporary.chmod(0o600)
    temporary.replace(path)
    path.chmod(0o600)


def _load_json_array(content: bytes) -> list[object]:
    try:
        payload = json.loads(content)
    except (UnicodeError, json.JSONDecodeError):
        raise AccelPixError("AccelPix response is not a valid JSON data array") from None
    if not isinstance(payload, list):
        raise AccelPixError("AccelPix response is not a valid JSON data array")
    return payload


def _json_array_rows(content: bytes) -> int:
    return len(_load_json_array(content))


def _retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return max(0.0, min(seconds, 300.0))
