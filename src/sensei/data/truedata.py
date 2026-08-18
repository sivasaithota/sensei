"""Quarantined TrueData trial ingestion for private research.

This module downloads owner-authorized vendor data into a private, content-
verified artifact store.  It is deliberately not a ``MarketDataCatalog`` and
cannot create admissible examination evidence: historical index membership,
stable identity, adjustment lineage, and final usage-rights certification are
still separate requirements.

Credentials are accepted only through ``TRUEDATA_USERNAME`` and
``TRUEDATA_PASSWORD`` (or an explicitly constructed in-memory config).  They
are never written to plans, manifests, URLs recorded on disk, or exceptions.
"""

from __future__ import annotations

import enum
import csv
import hashlib
import io
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

import httpx

STAMP = (
    "PRELIMINARY_VENDOR_TRIAL — private TrueData research artifacts; "
    "NOT admissible for governed examination"
)
SCHEMA_VERSION = 1
_DEFAULT_STORE = Path.home() / ".local" / "share" / "sensei" / "truedata"
_SECRET_KEYS = frozenset(
    {"password", "pass", "passw", "token", "access_token", "authorization", "user", "username"}
)
_ENDPOINT = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,127}\Z")
_MAX_MANIFEST_BYTES = 1_000_000
_DEFAULT_MAX_RESPONSE_BYTES = 256_000_000
_MAX_EOD_ROWS_PER_ARTIFACT = 1_000_000
_MAX_EOD_COLUMNS = 256


class TrueDataError(RuntimeError):
    """A credential-safe TrueData ingestion failure."""


class Service(str, enum.Enum):
    HISTORY = "history"
    CORPORATE = "corporate"
    MASTER = "master"


class Capability(str, enum.Enum):
    CORPORATE = "corporate"
    HISTORY = "history"
    MASTER = "master"


_SERVICE_BASES = {
    Service.HISTORY: "https://history.truedata.in",
    Service.CORPORATE: "https://corporate.truedata.in",
    Service.MASTER: "https://api.truedata.in",
}


@dataclass(frozen=True)
class TrueDataConfig:
    username: str = field(repr=False)
    password: str = field(repr=False)
    store: Path = _DEFAULT_STORE

    def __post_init__(self) -> None:
        if not self.username or not self.password:
            raise ValueError("TrueData credentials must not be empty")
        object.__setattr__(self, "store", Path(self.store).expanduser())

    @classmethod
    def from_environment(cls) -> "TrueDataConfig":
        username = os.environ.get("TRUEDATA_USERNAME", "")
        password = os.environ.get("TRUEDATA_PASSWORD", "")
        if not username or not password:
            raise TrueDataError(
                "set TRUEDATA_USERNAME and TRUEDATA_PASSWORD in the local environment"
            )
        return cls(
            username=username,
            password=password,
            store=Path(os.environ.get("SENSEI_TRUEDATA_DIR", _DEFAULT_STORE)),
        )


@dataclass(frozen=True)
class TrueDataRequest:
    service: Service
    endpoint: str
    params: Mapping[str, str | int | float | bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if _ENDPOINT.fullmatch(self.endpoint) is None:
            raise ValueError("invalid TrueData endpoint")
        normalized: dict[str, str | int | float | bool] = {}
        for key, value in self.params.items():
            if key.lower() in _SECRET_KEYS:
                raise ValueError("credentials must not appear in request params")
            if not isinstance(value, (str, int, float, bool)):
                raise TypeError("TrueData request params must be scalar")
            normalized[str(key)] = value
        object.__setattr__(self, "params", normalized)

    @property
    def request_id(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            {
                "service": self.service.value,
                "endpoint": self.endpoint,
                "params": dict(self.params),
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

    @property
    def safe_source_uri(self) -> str:
        return f"{_SERVICE_BASES[self.service]}/{self.endpoint}"


@dataclass(frozen=True)
class FetchedPayload:
    content: bytes
    content_type: str
    retrieved_at: datetime
    source_uri: str
    status_code: int


@dataclass(frozen=True)
class EntitlementProbeResult:
    capability: Capability
    accessible: bool
    response_class: str


class _Clock(Protocol):
    def __call__(self) -> float: ...


class _RateGate:
    def __init__(
        self,
        interval: float,
        *,
        clock: _Clock,
        sleeper: Callable[[float], None],
    ) -> None:
        self.interval = interval
        self.clock = clock
        self.sleeper = sleeper
        self._last: float | None = None

    def wait(self) -> None:
        now = self.clock()
        if self._last is not None:
            remaining = self.interval - (now - self._last)
            if remaining > 0:
                self.sleeper(remaining)
                now = self.clock()
        self._last = now


class TrueDataClient:
    """Bounded, retrying client for documented TrueData REST services."""

    def __init__(
        self,
        config: TrueDataConfig,
        *,
        http: httpx.Client | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: _Clock = time.monotonic,
        max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES,
        maximum_attempts: int = 3,
    ) -> None:
        if max_response_bytes <= 0 or maximum_attempts <= 0:
            raise ValueError("client safety limits must be positive")
        self.config = config
        self.http = http or httpx.Client(timeout=60, follow_redirects=False)
        self.sleeper = sleeper
        self.max_response_bytes = max_response_bytes
        self.maximum_attempts = maximum_attempts
        self._token: str | None = None
        self._gates = {
            Service.CORPORATE: _RateGate(1.0, clock=clock, sleeper=sleeper),
            Service.HISTORY: _RateGate(0.1, clock=clock, sleeper=sleeper),
            Service.MASTER: _RateGate(1.0, clock=clock, sleeper=sleeper),
        }

    def authenticate(self, *, force: bool = False) -> None:
        if self._token is not None and not force:
            return
        try:
            request = self.http.build_request(
                "POST",
                "https://auth.truedata.in/token",
                data={
                    "username": self.config.username,
                    "password": self.config.password,
                    "grant_type": "password",
                },
            )
            response = self.http.send(request, stream=True)
            try:
                response.raise_for_status()
                data = json.loads(_bounded_response_bytes(response, 1_000_000))
            finally:
                response.close()
        except (httpx.HTTPError, ValueError):
            # The originating request contains form credentials.
            raise TrueDataError("TrueData authentication failed") from None
        token = data.get("access_token") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token:
            raise TrueDataError("TrueData authentication returned no access token")
        self._token = token

    def fetch(self, request: TrueDataRequest) -> FetchedPayload:
        params = dict(request.params)
        headers: dict[str, str] = {"Accept": "text/csv, application/json"}
        if request.service is Service.MASTER:
            params.update(
                {"user": self.config.username, "password": self.config.password}
            )
        else:
            self.authenticate()
            headers["Authorization"] = f"Bearer {self._token}"

        for attempt in range(self.maximum_attempts):
            self._gates[request.service].wait()
            try:
                request_message = self.http.build_request(
                    "GET", request.safe_source_uri, params=params, headers=headers
                )
                response = self.http.send(request_message, stream=True)
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt + 1 < self.maximum_attempts:
                    self.sleeper(min(2**attempt, 8))
                    continue
                break

            if response.status_code in {401, 403} and request.service is not Service.MASTER:
                if attempt == 0:
                    response.close()
                    self.authenticate(force=True)
                    headers["Authorization"] = f"Bearer {self._token}"
                    continue
            if response.status_code == 429 or 500 <= response.status_code < 600:
                if attempt + 1 < self.maximum_attempts:
                    retry_after = response.headers.get("Retry-After", "")
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        delay = float(2**attempt)
                    response.close()
                    self.sleeper(max(0.0, min(delay, 30.0)))
                    continue
                response.close()
                break
            if response.status_code >= 400:
                response.close()
                raise TrueDataError(
                    f"TrueData request rejected (HTTP {response.status_code})"
                )
            try:
                content = _bounded_response_bytes(response, self.max_response_bytes)
                return FetchedPayload(
                    content=content,
                    content_type=response.headers.get(
                        "Content-Type", "application/octet-stream"
                    ).split(";", 1)[0],
                    retrieved_at=datetime.now(timezone.utc),
                    source_uri=request.safe_source_uri,
                    status_code=response.status_code,
                )
            finally:
                response.close()
        # Master requests use vendor-required query credentials.  Never retain the
        # originating httpx exception as context because it may embed that URL.
        raise TrueDataError("TrueData request failed after bounded retries") from None


def _bounded_response_bytes(response: httpx.Response, maximum: int) -> bytes:
    declared = response.headers.get("Content-Length")
    if declared is not None:
        try:
            declared_bytes = int(declared)
        except ValueError:
            raise TrueDataError("TrueData returned an invalid response length") from None
        if declared_bytes < 0 or declared_bytes > maximum:
            raise TrueDataError("TrueData response exceeds the safety limit")
    content = bytearray()
    for chunk in response.iter_bytes():
        if len(content) + len(chunk) > maximum:
            raise TrueDataError("TrueData response exceeds the safety limit")
        content.extend(chunk)
    return bytes(content)


@dataclass(frozen=True)
class StoredArtifact:
    request_id: str
    payload_path: Path
    manifest_path: Path


@dataclass(frozen=True)
class AuditResult:
    total: int
    verified: int
    missing: int
    data: int
    no_data: int
    error: int
    eod_requests: int
    eod_with_data: int
    eod_rows: int
    eod_earliest: str | None
    eod_latest: str | None
    eod_duplicate_dates: int
    eod_invalid: int
    eod_range_gaps: int


class PrivateArtifactStore:
    """Atomic, content-verified owner-only storage for trial responses."""

    def __init__(
        self, root: Path, *, max_artifact_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES
    ) -> None:
        if max_artifact_bytes <= 0:
            raise ValueError("artifact safety limit must be positive")
        self.root = Path(root).expanduser().resolve()
        self.max_artifact_bytes = max_artifact_bytes
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)

    def _directory(self, request: TrueDataRequest) -> Path:
        return self.root / "raw" / request.service.value / request.endpoint / request.request_id

    def verified(self, request: TrueDataRequest) -> StoredArtifact | None:
        directory = self._directory(request)
        manifest_path = directory / "manifest.json"
        try:
            if manifest_path.stat().st_size > _MAX_MANIFEST_BYTES:
                return None
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                return None
            if manifest.get("schema_version") != SCHEMA_VERSION:
                return None
            if manifest.get("stamp") != STAMP:
                return None
            if manifest.get("request_id") != request.request_id:
                return None
            if manifest.get("request") != json.loads(request.canonical_bytes()):
                return None
            name = manifest.get("payload_file")
            if not isinstance(name, str) or Path(name).name != name:
                return None
            expected_bytes = manifest.get("bytes")
            if (
                not isinstance(expected_bytes, int)
                or expected_bytes < 0
                or expected_bytes > self.max_artifact_bytes
            ):
                return None
            payload_path = directory / name
            if payload_path.stat().st_size != expected_bytes:
                return None
            digest = hashlib.sha256()
            observed = 0
            with payload_path.open("rb") as handle:
                while chunk := handle.read(1_048_576):
                    observed += len(chunk)
                    if observed > self.max_artifact_bytes:
                        return None
                    digest.update(chunk)
            if observed != expected_bytes or digest.hexdigest() != manifest.get("sha256"):
                return None
            return StoredArtifact(request.request_id, payload_path, manifest_path)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            return None

    def save(
        self,
        request: TrueDataRequest,
        payload: FetchedPayload,
        *,
        replace_checkpoint: bool = False,
    ) -> StoredArtifact:
        if len(payload.content) > self.max_artifact_bytes:
            raise TrueDataError("TrueData artifact exceeds the safety limit")
        existing = self.verified(request)
        if existing is not None and not replace_checkpoint:
            return existing
        directory = self._directory(request)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(directory, 0o700)
        suffix = _suffix_for(payload.content_type, payload.content)
        digest = hashlib.sha256(payload.content).hexdigest()
        payload_name = f"payload-{digest}{suffix}"
        payload_path = directory / payload_name
        manifest_path = directory / "manifest.json"
        revision_dir = directory / "revisions"
        revision_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(revision_dir, 0o700)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "stamp": STAMP,
            "request_id": request.request_id,
            "request": json.loads(request.canonical_bytes()),
            "source_uri": payload.source_uri,
            "retrieved_at": payload.retrieved_at.isoformat(),
            "status_code": payload.status_code,
            "content_type": payload.content_type,
            "payload_file": payload_name,
            "bytes": len(payload.content),
            "sha256": digest,
            "response_class": _response_class(payload.content, payload.content_type),
        }
        encoded_manifest = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
        if not payload_path.exists():
            _atomic_bytes(payload_path, payload.content)
        revision_name = (
            payload.retrieved_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            + f"-{digest}.json"
        )
        revision_path = revision_dir / revision_name
        if not revision_path.exists():
            _atomic_bytes(revision_path, encoded_manifest)
        _atomic_bytes(manifest_path, encoded_manifest)
        return StoredArtifact(request.request_id, payload_path, manifest_path)

    def audit(self, plan: "TrialPlan") -> AuditResult:
        verified = data = no_data = error = 0
        eod_requests = eod_with_data = eod_rows = eod_duplicate_dates = 0
        eod_earliest: date | None = None
        eod_latest: date | None = None
        eod_invalid = eod_range_gaps = 0
        for request in plan.requests:
            if request.endpoint == "getbars":
                eod_requests += 1
            artifact = self.verified(request)
            if artifact is None:
                continue
            verified += 1
            manifest = json.loads(artifact.manifest_path.read_text(encoding="utf-8"))
            classification = manifest.get("response_class", "error")
            if classification == "data":
                data += 1
                if request.endpoint == "getbars":
                    rows, earliest, latest, duplicates, valid = _eod_csv_profile(
                        artifact.payload_path, self.max_artifact_bytes
                    )
                    if not valid:
                        data -= 1
                        error += 1
                        eod_invalid += 1
                    else:
                        eod_with_data += 1
                        eod_rows += rows
                        eod_duplicate_dates += duplicates
                        assert earliest is not None and latest is not None
                        eod_earliest = (
                            earliest if eod_earliest is None else min(eod_earliest, earliest)
                        )
                        eod_latest = latest if eod_latest is None else max(eod_latest, latest)
                        if _outside_requested_eod_range(request, earliest, latest):
                            eod_range_gaps += 1
            elif classification == "no_data":
                no_data += 1
            else:
                error += 1
        return AuditResult(
            len(plan.requests),
            verified,
            len(plan.requests) - verified,
            data,
            no_data,
            error,
            eod_requests,
            eod_with_data,
            eod_rows,
            eod_earliest.isoformat() if eod_earliest else None,
            eod_latest.isoformat() if eod_latest else None,
            eod_duplicate_dates,
            eod_invalid,
            eod_range_gaps,
        )


def _eod_csv_profile(
    path: Path, maximum_bytes: int
) -> tuple[int, date | None, date | None, int, bool]:
    """Return bounded row/date diagnostics for an EOD CSV artifact."""

    if path.stat().st_size > maximum_bytes:
        return 0, None, None, 0, False
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or len(reader.fieldnames) > _MAX_EOD_COLUMNS:
                return 0, None, None, 0, False
            date_key = next(
                (
                    key
                    for key in reader.fieldnames
                    if key.strip().lower() in {"date", "timestamp", "datetime", "time"}
                ),
                None,
            )
            rows = 0
            earliest: date | None = None
            latest: date | None = None
            seen: set[date] = set()
            duplicates = 0
            for row in reader:
                rows += 1
                if rows > _MAX_EOD_ROWS_PER_ARTIFACT:
                    return 0, None, None, 0, False
                if date_key is None:
                    continue
                raw = row.get(date_key, "").strip()[:10]
                try:
                    value = date.fromisoformat(raw)
                except ValueError:
                    continue
                if value in seen:
                    duplicates += 1
                seen.add(value)
                earliest = value if earliest is None else min(earliest, value)
                latest = value if latest is None else max(latest, value)
            return rows, earliest, latest, duplicates, bool(rows and earliest and latest)
    except (OSError, UnicodeError, csv.Error):
        return 0, None, None, 0, False


def _outside_requested_eod_range(
    request: TrueDataRequest, earliest: date, latest: date
) -> bool:
    try:
        requested_start = datetime.strptime(str(request.params["from"])[:6], "%y%m%d").date()
        requested_end = datetime.strptime(str(request.params["to"])[:6], "%y%m%d").date()
    except (KeyError, TypeError, ValueError):
        return True
    while requested_start.weekday() >= 5:
        requested_start += timedelta(days=1)
    while requested_end.weekday() >= 5:
        requested_end -= timedelta(days=1)
    return earliest > requested_start or latest < requested_end


def _atomic_bytes(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _suffix_for(content_type: str, content: bytes) -> str:
    lowered = content_type.lower()
    if "json" in lowered or content.lstrip().startswith((b"{", b"[")):
        return ".json"
    if "csv" in lowered or b"," in content[:1024]:
        return ".csv"
    if "pdf" in lowered or content.startswith(b"%PDF"):
        return ".pdf"
    return ".bin"


def _response_class(content: bytes, content_type: str = "") -> str:
    if not content.strip():
        return "error"
    sample = content[:16_384].lower()
    if b"no data exists" in sample:
        return "no_data"
    if any(
        marker in sample
        for marker in (
            b"authorization has been denied",
            b"quota exceeded",
            b"segment not subscribed",
            b'"status":"error"',
            b'"status": "error"',
        )
    ):
        return "error"
    stripped = content.lstrip()
    lowered_type = content_type.lower()
    if "html" in lowered_type or stripped.startswith((b"<html", b"<!doctype html")):
        return "error"
    if "json" in lowered_type or stripped.startswith((b"{", b"[")):
        try:
            decoded = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return "error"
        if isinstance(decoded, dict):
            status = str(decoded.get("status", "")).lower()
            if status in {"error", "failed", "failure"} or decoded.get("success") is False:
                return "error"
        return "data"
    if "csv" in lowered_type:
        try:
            text = content.decode("utf-8-sig")
            rows = csv.reader(io.StringIO(text))
            header = next(rows)
        except (UnicodeDecodeError, csv.Error, StopIteration):
            return "error"
        return "data" if len(header) >= 2 else "error"
    if "pdf" in lowered_type or content.startswith(b"%PDF"):
        return "data"
    return "error"


_SYMBOL_KEYS = frozenset(
    {
        "symbol",
        "symbol_nse",
        "nse_symbol",
        "tradingsymbol",
        "ticker",
        "sym",
        "old_symbol",
        "new_symbol",
        "oldsymbol",
        "newsymbol",
        "fromsymbol",
        "tosymbol",
    }
)


def extract_symbols(content: bytes, *, content_type: str = "") -> tuple[str, ...]:
    """Extract NSE-style symbols from a vendor master without assuming one shape."""

    if len(content) > _DEFAULT_MAX_RESPONSE_BYTES:
        raise TrueDataError("symbol master exceeds the safety limit")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TrueDataError("symbol master is not valid UTF-8") from exc
    symbols: set[str] = set()
    if "json" in content_type.lower() or text.lstrip().startswith(("{", "[")):
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise TrueDataError("symbol master is malformed JSON") from exc

        def visit(item: Any) -> None:
            if isinstance(item, dict):
                for key, child in item.items():
                    if key.lower() in _SYMBOL_KEYS and isinstance(child, str):
                        _add_symbol(symbols, child)
                    else:
                        visit(child)
            elif isinstance(item, list):
                for child in item:
                    visit(child)

        visit(value)
    else:
        try:
            reader = csv.DictReader(io.StringIO(text))
            if reader.fieldnames is None:
                raise TrueDataError("symbol master CSV has no header")
            keys = [
                name
                for name in reader.fieldnames
                if name.strip().lower() in _SYMBOL_KEYS
            ]
            if not keys:
                raise TrueDataError("symbol master CSV has no symbol column")
            for row in reader:
                for key in keys:
                    _add_symbol(symbols, row.get(key, ""))
        except csv.Error as exc:
            raise TrueDataError("symbol master is malformed CSV") from exc
    if not symbols:
        raise TrueDataError("symbol master contains no recognized symbols")
    if len(symbols) > 20_000:
        raise TrueDataError("symbol master exceeds the instrument safety limit")
    return tuple(sorted(symbols))


def _add_symbol(symbols: set[str], value: str) -> None:
    symbol = value.strip().upper()
    if symbol and len(symbol) <= 64 and re.fullmatch(r"[A-Z0-9&._-]+", symbol):
        symbols.add(symbol)


def extract_record_ids(content: bytes, *, content_type: str = "") -> tuple[str, ...]:
    """Extract list-record IDs used to request immutable detail records."""

    if len(content) > _DEFAULT_MAX_RESPONSE_BYTES:
        raise TrueDataError("record list exceeds the safety limit")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TrueDataError("record list is not valid UTF-8") from exc
    identifiers: set[str] = set()
    if "json" in content_type.lower() or text.lstrip().startswith(("{", "[")):
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise TrueDataError("record list is malformed JSON") from exc

        def visit(item: Any) -> None:
            if isinstance(item, dict):
                for key, child in item.items():
                    if key.lower() == "id" and isinstance(child, (str, int)):
                        identifiers.add(str(child))
                    else:
                        visit(child)
            elif isinstance(item, list):
                for child in item:
                    visit(child)

        visit(value)
    else:
        try:
            reader = csv.DictReader(io.StringIO(text))
            if reader.fieldnames is None:
                raise TrueDataError("record list CSV has no header")
            key = next(
                (name for name in reader.fieldnames if name.strip().lower() == "id"),
                None,
            )
            if key is None:
                raise TrueDataError("record list CSV has no id column")
            for row in reader:
                value = row.get(key, "").strip()
                if value:
                    identifiers.add(value)
        except csv.Error as exc:
            raise TrueDataError("record list is malformed CSV") from exc
    if len(identifiers) > 1_000_000:
        raise TrueDataError("record list exceeds the ID safety limit")
    return tuple(sorted(identifiers))


@dataclass(frozen=True)
class TrialPlan:
    plan_id: str
    requests: tuple[TrueDataRequest, ...]

    @classmethod
    def for_trial(
        cls,
        *,
        as_of: date,
        eod_start: date,
        corporate_start: date,
        segments: tuple[str, ...] = ("eq", "in"),
        symbols: tuple[str, ...] = (),
        capabilities: tuple[Capability | str, ...] = tuple(Capability),
    ) -> "TrialPlan":
        if eod_start > as_of or corporate_start > as_of:
            raise ValueError("trial plan start dates must not exceed as-of")
        if (as_of - eod_start).days > 730:
            raise ValueError("trial EOD window must not exceed 730 days")
        if (as_of - corporate_start).days > 92:
            raise ValueError("trial corporate window must not exceed 92 days")
        if not segments or any(segment not in {"eq", "in"} for segment in segments):
            raise ValueError("trial segments must be eq and/or in")
        try:
            enabled = {Capability(capability) for capability in capabilities}
        except ValueError as exc:
            raise ValueError("unknown TrueData trial capability") from exc
        if not enabled:
            raise ValueError("at least one TrueData trial capability is required")
        requests: list[TrueDataRequest] = []
        if Capability.MASTER in enabled:
            for segment in segments:
                requests.append(
                    TrueDataRequest(
                        Service.MASTER,
                        "getAllSymbols",
                        {
                            "segment": segment,
                            "csv": True,
                            "csvHeader": True,
                            "allexpiry": True,
                        },
                    )
                )
        if Capability.HISTORY in enabled:
            requests.append(
                TrueDataRequest(
                    Service.HISTORY,
                    "getsymbolchangehistory",
                    {"response": "csv", "SYMBOL": ""},
                )
            )
            requests.append(
                TrueDataRequest(
                    Service.HISTORY,
                    "getcorpactionrange",
                    {
                        "exdatefrom": corporate_start.isoformat(),
                        "exdateto": as_of.isoformat(),
                        "response": "csv",
                    },
                )
            )
            day = eod_start
            while day <= as_of:
                if day.weekday() < 5:
                    for segment in segments:
                        requests.append(
                            TrueDataRequest(
                                Service.HISTORY,
                                "getbhavcopy",
                                {
                                    "segment": segment.upper(),
                                    "date": day.isoformat(),
                                    "response": "csv",
                                },
                            )
                        )
                day += timedelta(days=1)
        normalized_symbols = sorted(set(symbols))
        for symbol in normalized_symbols if Capability.HISTORY in enabled else ():
            requests.append(
                TrueDataRequest(
                    Service.HISTORY,
                    "getbars",
                    {
                        "symbol": symbol,
                        "from": f"{eod_start:%y%m%d}T00:00:00",
                        "to": f"{as_of:%y%m%d}T23:59:59",
                        "response": "csv",
                        "interval": "eod",
                    },
                )
            )
        if Capability.CORPORATE in enabled:
            cursor = corporate_start
            while cursor <= as_of:
                requests.extend(
                    (
                        TrueDataRequest(
                            Service.CORPORATE,
                            "annoucements",
                            {
                                "from": f"{cursor:%y%m%d}",
                                "to": f"{cursor:%y%m%d}",
                                "response": "csv",
                            },
                        ),
                        TrueDataRequest(
                            Service.CORPORATE,
                            "getResultList",
                            {"date": cursor.isoformat(), "response": "json"},
                        ),
                        TrueDataRequest(
                            Service.CORPORATE,
                            "getSHPListByDate",
                            {"date": cursor.isoformat(), "response": "json"},
                        ),
                    )
                )
                cursor += timedelta(days=1)
        unique = {request.request_id: request for request in requests}
        ordered = tuple(unique[key] for key in sorted(unique))
        identity = hashlib.sha256(
            b"\n".join(request.canonical_bytes() for request in ordered)
        ).hexdigest()[:20]
        return cls(f"truedata-trial-{identity}", ordered)

    def write(self, path: Path) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "stamp": STAMP,
            "plan_id": self.plan_id,
            "requests": [json.loads(request.canonical_bytes()) for request in self.requests],
        }
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _atomic_bytes(path, json.dumps(payload, indent=2, sort_keys=True).encode())

    @classmethod
    def read(cls, path: Path) -> "TrialPlan":
        path = Path(path)
        if path.stat().st_size > 64_000_000:
            raise TrueDataError("trial plan exceeds the safety limit")
        raw = path.read_bytes()
        try:
            data = json.loads(raw)
            if data.get("schema_version") != SCHEMA_VERSION or data.get("stamp") != STAMP:
                raise ValueError
            requests = tuple(
                TrueDataRequest(
                    service=Service(item["service"]),
                    endpoint=item["endpoint"],
                    params=item.get("params", {}),
                )
                for item in data["requests"]
            )
            plan = cls(data["plan_id"], requests)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise TrueDataError("invalid TrueData trial plan") from exc
        return plan


@dataclass(frozen=True)
class DownloadResult:
    total: int
    stored: int
    skipped: int
    failed: int
    failures: Mapping[str, str]


def expand_plan_from_masters(
    bootstrap: TrialPlan,
    *,
    store: PrivateArtifactStore,
    as_of: date,
    eod_start: date,
    corporate_start: date,
    segments: tuple[str, ...],
    capabilities: tuple[Capability | str, ...] = tuple(Capability),
) -> TrialPlan:
    """Build the full symbol plan only from verified downloaded master artifacts."""

    symbols_by_segment: dict[str, set[str]] = {}
    found_segments: set[str] = set()
    for request in bootstrap.requests:
        if request.service not in {Service.MASTER, Service.HISTORY}:
            continue
        artifact = store.verified(request)
        if artifact is None:
            continue
        manifest = json.loads(artifact.manifest_path.read_text(encoding="utf-8"))
        if manifest.get("response_class") != "data":
            continue
        if request.endpoint == "getsymbolchangehistory":
            symbols_by_segment.setdefault("eq", set()).update(
                extract_symbols(
                    artifact.payload_path.read_bytes(),
                    content_type=str(manifest.get("content_type", "")),
                )
            )
            continue
        if request.endpoint != "getAllSymbols":
            continue
        segment = request.params.get("segment")
        if isinstance(segment, str):
            symbols_by_segment.setdefault(segment, set()).update(
                extract_symbols(
                    artifact.payload_path.read_bytes(),
                    content_type=str(manifest.get("content_type", "")),
                )
            )
            found_segments.add(segment)
    missing = set(segments) - found_segments
    if missing:
        raise TrueDataError(
            "verified symbol masters are missing for: " + ", ".join(sorted(missing))
        )
    return TrialPlan.for_trial(
        as_of=as_of,
        eod_start=eod_start,
        corporate_start=corporate_start,
        segments=segments,
        symbols=tuple(sorted(set().union(*symbols_by_segment.values()))),
        capabilities=capabilities,
    )


_DETAIL_ENDPOINTS = {
    "getResultList": (
        "getAllResultItemsById",
        "getResultALById",
        "getPnLById",
        "getBalSheetById2",
        "getCashFlowSummaryById",
        "getCashFlowDetailById",
    ),
    "getSHPListByDate": (
        "getAllShpById",
        "getShpSummaryById",
        "getShpDetailById",
    ),
    "annoucements": ("getannouncementbyid", "announcementfile2"),
}


def probe_entitlements(
    client: TrueDataClient,
    *,
    as_of: date,
    capabilities: tuple[Capability | str, ...] = tuple(Capability),
) -> tuple[EntitlementProbeResult, ...]:
    """Issue one bounded, non-persistent probe for each independently gated service."""

    probes = {
        Capability.CORPORATE: TrueDataRequest(
            Service.CORPORATE,
            "getResultList",
            {"date": as_of.isoformat(), "response": "json"},
        ),
        Capability.HISTORY: TrueDataRequest(
            Service.HISTORY,
            "getbhavcopystatus",
            {"segment": "EQ", "date": as_of.isoformat(), "response": "csv"},
        ),
        Capability.MASTER: TrueDataRequest(
            Service.MASTER,
            "getAllSymbols",
            {
                "segment": "eq",
                "csv": True,
                "csvHeader": True,
                "search": "RELIANCE",
            },
        ),
    }
    enabled = {Capability(capability) for capability in capabilities}
    results: list[EntitlementProbeResult] = []
    for capability, request in probes.items():
        if capability not in enabled:
            continue
        try:
            payload = client.fetch(request)
            classification = _response_class(payload.content, payload.content_type)
            accessible = classification == "no_data" or (
                classification == "data"
                and _probe_payload_matches(capability, payload)
            )
            results.append(
                EntitlementProbeResult(
                    capability,
                    accessible,
                    classification if accessible else "error",
                )
            )
        except TrueDataError:
            results.append(EntitlementProbeResult(capability, False, "error"))
    return tuple(results)


def _probe_payload_matches(capability: Capability, payload: FetchedPayload) -> bool:
    try:
        if capability is Capability.CORPORATE:
            decoded = json.loads(payload.content)
            return isinstance(decoded, dict) and (
                str(decoded.get("status", "")).lower() == "success"
                or isinstance(decoded.get("Records"), list)
            )
        if capability is Capability.MASTER:
            return bool(extract_symbols(payload.content, content_type=payload.content_type))
        text = payload.content.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(text))
        header = {value.strip().lower() for value in next(reader)}
        return bool(header & {"date", "status", "segment"})
    except (TrueDataError, UnicodeError, json.JSONDecodeError, csv.Error, StopIteration):
        return False


def expand_detail_plan(plan: TrialPlan, *, store: PrivateArtifactStore) -> TrialPlan:
    """Expand verified corporate indexes into their immutable detail requests."""

    requests = list(plan.requests)
    for request in plan.requests:
        endpoints = _DETAIL_ENDPOINTS.get(request.endpoint)
        if endpoints is None:
            continue
        artifact = store.verified(request)
        if artifact is None:
            continue
        manifest = json.loads(artifact.manifest_path.read_text(encoding="utf-8"))
        if _response_class(
            artifact.payload_path.read_bytes(),
            str(manifest.get("content_type", "")),
        ) != "data":
            continue
        identifiers = extract_record_ids(
            artifact.payload_path.read_bytes(),
            content_type=str(manifest.get("content_type", "")),
        )
        for identifier in identifiers:
            for endpoint in endpoints:
                requests.append(
                    TrueDataRequest(
                        Service.CORPORATE,
                        endpoint,
                        _detail_params(endpoint, identifier),
                    )
                )
    unique = {request.request_id: request for request in requests}
    ordered = tuple(unique[key] for key in sorted(unique))
    identity = hashlib.sha256(
        b"\n".join(request.canonical_bytes() for request in ordered)
    ).hexdigest()[:20]
    return TrialPlan(f"truedata-detail-{identity}", ordered)


def _detail_params(endpoint: str, identifier: str) -> dict[str, str | bool]:
    params: dict[str, str | bool] = {"id": identifier}
    if endpoint != "announcementfile2":
        params["response"] = "json"
    if endpoint in {"getPnLById", "getCashFlowDetailById"}:
        params["cumulative"] = True
    return params


def download_plan(
    plan: TrialPlan,
    *,
    client: TrueDataClient,
    store: PrivateArtifactStore,
    stop_on_error: bool = False,
) -> DownloadResult:
    stored = skipped = failed = 0
    failures: dict[str, str] = {}
    for request in plan.requests:
        existing = store.verified(request)
        replace_checkpoint = False
        if existing is not None:
            manifest = json.loads(existing.manifest_path.read_text(encoding="utf-8"))
            if manifest.get("response_class") != "error":
                skipped += 1
                continue
            replace_checkpoint = True
        try:
            payload = client.fetch(request)
            classification = _response_class(payload.content, payload.content_type)
            store.save(request, payload, replace_checkpoint=replace_checkpoint)
            if classification == "error":
                failed += 1
                failures[request.request_id] = "vendor response was not usable data"
                if stop_on_error:
                    break
            else:
                stored += 1
        except TrueDataError as exc:
            failed += 1
            failures[request.request_id] = str(exc)
            if stop_on_error:
                break
    return DownloadResult(len(plan.requests), stored, skipped, failed, failures)
