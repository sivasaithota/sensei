"""NSE bhavcopy raw ingestion — PRELIMINARY_RAW, quarantined staging source.

Status (owner reviews 2026-08-17): this is a RAW exchange EOD ingestion — a
QUARANTINED STAGING SOURCE, never an admissible catalog. It must NOT be wired
into `MarketDataCatalog`; the admissible path is the existing
`ManifestMarketDataCatalog` (src/sensei/research/catalog.py), which already does
hash verification, resource limits, membership, identity, adjustment policy and
trust pinning. The missing work is producing *valid inputs* for it (a real
manifest with stable identity, effective-dated membership, corporate actions,
adjustment policy, licensed lineage) — which needs authoritative vendor data.

A bhavcopy records securities that TRADED on a day. It does NOT establish index
membership, entry eligibility, adjusted prices, or instrument identity. Any
"survivorship-clean" framing is retracted. Bars here are raw/UNADJUSTED and
therefore inadmissible for governed examination.

What this module honestly is: a manual, personal-research downloader for NSE's
UDiFF "Common Bhavcopy Final" (cash-market, final), normalized to a stable
Parquet schema, with an internally hash-consistent per-session artifact chain. Access is through
`QuarantinedRawBhavcopy` (ADMISSIBLE=False), which verifies the provenance
chain (manifest schema + date + parser version + content hashes) on every read.

Collection posture: NSE's data policy says "downloadable" is not "free for an
automated database". This is MANUAL, personal-research only. No scheduler is
wired; unattended collection needs written usage rights first
(docs/research/indian-research-data-sources.md).

Storage: partitioned Parquet + retained raw ZIP + manifest under a CONFIGURABLE
base dir (SENSEI_BHAVCOPY_DIR) so the deploy destination can be swapped without
touching pull logic. Both trees are git-ignored.
"""

from __future__ import annotations

import enum
import hashlib
import io
import itertools
import json
import math
import os
import time
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pandas as pd

from sensei.research.local_artifacts import inspect_parquet, read_regular_file

STAMP = (
    "PRELIMINARY_RAW — raw/unadjusted exchange EOD; QUARANTINED staging source, "
    "NOT admissible for governed examination (no membership, no corporate-action "
    "adjustment, no authoritative identity); personal research only"
)
PARSER_VERSION = "bhavcopy-parser/4"

_DEFAULT_DIR = Path(__file__).resolve().parents[3] / "data" / "nse_bhavcopy"
_DEFAULT_RAW_DIR = Path(__file__).resolve().parents[3] / "data" / "nse_bhavcopy_raw"

_UDIFF_URL = (
    "https://nsearchives.nseindia.com/content/cm/"
    "BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip"
)
_NSE_HOME = "https://www.nseindia.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Resource bounds on untrusted external artifacts (mirrors catalog defenses).
_MAX_ZIP_BYTES = 50_000_000          # compressed download cap
_MAX_CSV_BYTES = 64_000_000          # decompressed CSV cap (zip-bomb guard)
_MAX_CSV_WORKING_BYTES = 512_000_000
_MAX_ZIP_MEMBERS = 8
_MAX_ROWS = 200_000
_MAX_COLS = 128
_MAX_MANIFEST_BYTES = 200_000
_MAX_PARQUET_BYTES = 64_000_000
_MAX_PARQUET_DECODED_BYTES = 256_000_000
_MAX_PARQUET_COLUMNS = 32
_MAX_PARQUET_WORKING_BYTES = 512_000_000

# Bounded retry for transient HTTP failures.
_RETRYABLE_HTTP = frozenset({403, 429, 500, 502, 503, 504})
_DEFAULT_ATTEMPTS = 3
_BACKOFF_BASE = 0.5

_REQUIRED_COLS = frozenset({
    "TradDt", "FinInstrmTp", "TckrSymb", "SctySrs", "ISIN",
    "OpnPric", "HghPric", "LwPric", "ClsPric", "LastPric",
    "PrvsClsgPric", "TtlTradgVol", "TtlTrfVal",
})
_COLMAP = {
    "TckrSymb": "symbol", "SctySrs": "series", "ISIN": "isin",
    "OpnPric": "open", "HghPric": "high", "LwPric": "low", "ClsPric": "close",
    "LastPric": "last", "PrvsClsgPric": "prev_close",
    "TtlTradgVol": "volume", "TtlTrfVal": "turnover", "TtlNbOfTxsExctd": "trades",
}
_MANIFEST_REQUIRED = frozenset({
    "stamp", "parser_version", "source_uri", "retrieved_at", "trade_date",
    "sha256_zip", "sha256_csv", "sha256_parquet", "rows_total",
})

# Interim cash-EQUITY series allowlist. This is a NARROW QUARANTINE RULE, not an
# authoritative security master: FinInstrmTp=="STK" is NOT equity (also covers
# GS/GB/TB govt securities and debt). It cannot establish immutable identity,
# listing episodes, or symbol changes — that needs a licensed security master.
EQUITY_SERIES = frozenset({"EQ", "BE", "BZ"})

_tmp_counter = itertools.count()


class BhavcopySchemaError(ValueError):
    """Raised when a bhavcopy CSV violates the fail-closed schema contract."""


class ProvenanceError(RuntimeError):
    """Raised when a persisted snapshot fails provenance verification on load."""


class FetchStatus(str, enum.Enum):
    OK = "ok"
    NOT_PUBLISHED = "not_published"   # 404: unresolved absence at the source
    EMPTY = "empty"                   # zip present but no/blank CSV
    MALFORMED = "malformed"           # bad zip, oversize, or unparseable (fatal)
    RETRYABLE = "retryable"           # 403/429/5xx/timeout after bounded retries


_FATAL = frozenset({FetchStatus.NOT_PUBLISHED, FetchStatus.EMPTY,
                    FetchStatus.MALFORMED, FetchStatus.OK})


@dataclass
class FetchResult:
    status: FetchStatus
    csv_bytes: bytes | None = None
    raw_zip: bytes | None = None
    source_uri: str = ""
    http_status: int | None = None
    detail: str = ""

    @property
    def retryable(self) -> bool:
        return self.status is FetchStatus.RETRYABLE


@dataclass(frozen=True)
class BhavcopySessionReference:
    """Internal hash-chain reference for one quarantined raw session."""

    trade_date: date
    parser_version: str
    manifest_sha256: str
    zip_sha256: str
    csv_sha256: str
    parquet_sha256: str
    source_uri: str


_VERIFIED_SESSION_TOKEN = object()


class VerifiedBhavcopySession:
    """Opaque capability issued only after artifact verification and decode."""

    __slots__ = ("_frame", "_reference", "_token")

    def __init__(
        self,
        frame: pd.DataFrame,
        reference: BhavcopySessionReference,
        *,
        _token: object,
    ) -> None:
        if _token is not _VERIFIED_SESSION_TOKEN:
            raise TypeError("verified bhavcopy sessions are verifier-issued")
        self._frame = frame.copy(deep=True)
        self._reference = reference
        self._token = _token

    @property
    def frame(self) -> pd.DataFrame:
        return self._frame.copy(deep=True)

    @property
    def reference(self) -> BhavcopySessionReference:
        return self._reference

    def _is_verifier_issued(self) -> bool:
        return self._token is _VERIFIED_SESSION_TOKEN


def _issue_verified_session(
    frame: pd.DataFrame,
    reference: BhavcopySessionReference,
) -> VerifiedBhavcopySession:
    return VerifiedBhavcopySession(
        frame,
        reference,
        _token=_VERIFIED_SESSION_TOKEN,
    )


# --------------------------------------------------------------------------- #
# paths / config
# --------------------------------------------------------------------------- #

def base_dir() -> Path:
    env = os.environ.get("SENSEI_BHAVCOPY_DIR")
    return Path(env).expanduser() if env else _DEFAULT_DIR


def raw_dir() -> Path:
    env = os.environ.get("SENSEI_BHAVCOPY_RAW_DIR")
    if env:
        return Path(env).expanduser()
    override = os.environ.get("SENSEI_BHAVCOPY_DIR")
    return (Path(override).expanduser().parent / "nse_bhavcopy_raw") if override else _DEFAULT_RAW_DIR


def snapshot_path(day: date) -> Path:
    return base_dir() / f"{day:%Y}" / f"BhavCopy_{day:%Y%m%d}.parquet"


def manifest_path(day: date) -> Path:
    return base_dir() / f"{day:%Y}" / f"BhavCopy_{day:%Y%m%d}.manifest.json"


def raw_zip_path(day: date) -> Path:
    return raw_dir() / f"{day:%Y}" / f"BhavCopy_{day:%Y%m%d}.csv.zip"


def bhavcopy_url(day: date) -> str:
    return _UDIFF_URL.format(ymd=f"{day:%Y%m%d}")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- #
# parsing / classification / integrity
# --------------------------------------------------------------------------- #

def parse_bhavcopy(csv_bytes: bytes | str, *, expected_day: date | None = None) -> pd.DataFrame:
    """Normalize a UDiFF bhavcopy CSV. Pure and network-free. Fail-closed:
    raises BhavcopySchemaError on invalid UTF-8, missing required columns,
    row/column bounds, or a TradDt that disagrees with expected_day."""
    encoded = csv_bytes if isinstance(csv_bytes, bytes) else csv_bytes.encode("utf-8")
    if len(encoded) > _MAX_CSV_BYTES:
        raise BhavcopySchemaError("bhavcopy CSV exceeds safety limit")
    if len(encoded) * 8 > _MAX_CSV_WORKING_BYTES:
        raise BhavcopySchemaError("bhavcopy CSV exceeds working-memory limit")
    if encoded.count(b"\n") > _MAX_ROWS + 1:
        raise BhavcopySchemaError("bhavcopy row count exceeds safety limit")
    header = encoded.split(b"\n", 1)[0]
    if header.count(b",") + 1 > _MAX_COLS:
        raise BhavcopySchemaError("bhavcopy column count exceeds safety limit")
    try:
        text = encoded.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BhavcopySchemaError("bhavcopy is not valid UTF-8") from exc
    try:
        raw = pd.read_csv(io.StringIO(text))
    except (pd.errors.ParserError, ValueError) as exc:
        raise BhavcopySchemaError("bhavcopy CSV is unparseable") from exc
    raw.columns = [c.strip() for c in raw.columns]

    if len(raw.columns) > _MAX_COLS:
        raise BhavcopySchemaError("bhavcopy column count exceeds safety limit")
    if len(raw) > _MAX_ROWS:
        raise BhavcopySchemaError("bhavcopy row count exceeds safety limit")
    missing = _REQUIRED_COLS - set(raw.columns)
    if missing:
        raise BhavcopySchemaError(f"bhavcopy missing required columns: {sorted(missing)}")

    trad = pd.to_datetime(raw["TradDt"], errors="coerce", format="%Y-%m-%d")
    if trad.isna().any() or len(set(trad.dt.date.unique())) != 1:
        raise BhavcopySchemaError("bhavcopy contains invalid TradDt values")
    if expected_day is not None:
        got = set(trad.dropna().dt.date.unique())
        if got != {expected_day}:
            raise BhavcopySchemaError(
                f"bhavcopy TradDt {sorted(map(str, got))} != requested {expected_day}")

    present = {src: dst for src, dst in _COLMAP.items() if src in raw.columns}
    df = raw.rename(columns=present)[list(present.values())].copy()
    df["date"] = trad.values
    df = df.set_index("date")
    df.index.name = "date"

    required_numeric = (
        "open", "high", "low", "close", "prev_close", "volume",
        "turnover",
    )
    for col in required_numeric + ("last", "trades"):
        if col in df.columns:
            numeric = pd.to_numeric(df[col], errors="coerce")
            if col in required_numeric and (
                numeric.isna().any() or not numeric.map(math.isfinite).all()
            ):
                raise BhavcopySchemaError(
                    f"bhavcopy contains invalid numeric field: {col}"
                )
            df[col] = numeric
    for col in ("symbol", "series", "isin"):
        df[col] = df[col].fillna("").astype(str).str.strip()

    df["instrument_class"] = df["series"].isin(EQUITY_SERIES).map(
        {True: "equity", False: "non_equity"})
    if ((df["instrument_class"] == "equity") & df["symbol"].eq("")).any():
        raise BhavcopySchemaError("bhavcopy contains an empty equity symbol")

    pos = df[["open", "high", "low", "close"]].gt(0).all(axis=1)
    ordered = df["high"] >= df["low"]
    contained = (df["close"] >= df["low"]) & (df["close"] <= df["high"])
    nonnegative_activity = (df["volume"] >= 0) & (df["turnover"] >= 0)
    df["ok"] = (pos & ordered & contained & nonnegative_activity).fillna(False)
    df["issue"] = ""
    df.loc[~pos, "issue"] = "nonpositive_price"
    df.loc[pos & ~ordered, "issue"] = "high_lt_low"
    df.loc[pos & ordered & ~contained, "issue"] = "close_outside_range"
    df.loc[
        pos & ordered & contained & ~nonnegative_activity,
        "issue",
    ] = "negative_volume_or_turnover"

    return df.sort_values("symbol")


def equities_clean(df: pd.DataFrame) -> pd.DataFrame:
    """Equity-series rows passing integrity, in the OHLCV shape used elsewhere.
    This — never the raw frame — is what any price consumer should read."""
    keep = df[(df["instrument_class"] == "equity") & df["ok"]]
    cols = [c for c in ("symbol", "series", "isin", "open", "high", "low",
                        "close", "volume", "turnover") if c in keep.columns]
    return keep[cols]


# --------------------------------------------------------------------------- #
# fetch (typed, bounded, retrying)
# --------------------------------------------------------------------------- #

def fetch_bhavcopy(day: date, *, client: httpx.Client | None = None,
                   max_attempts: int = _DEFAULT_ATTEMPTS,
                   sleep=time.sleep) -> FetchResult:
    """Download + unzip one day's UDiFF bhavcopy into a typed FetchResult.
    Transient failures (403/429/5xx/timeout/transport) are retried with bounded
    exponential backoff, then returned as RETRYABLE (never raised) so a
    multi-day run is not aborted by one flaky session."""
    own = client is None
    http = client or httpx.Client(headers=_HEADERS, timeout=30, follow_redirects=True)
    uri = bhavcopy_url(day)
    try:
        last = FetchResult(FetchStatus.RETRYABLE, source_uri=uri, detail="no attempt")
        for attempt in range(max_attempts):
            try:
                try:
                    with http.stream("GET", _NSE_HOME, timeout=15):
                        pass
                except httpx.HTTPError:
                    pass
                with http.stream("GET", uri) as resp:
                    status_code = resp.status_code
                    if status_code == 200:
                        content = bytearray()
                        for chunk in resp.iter_bytes():
                            if len(content) + len(chunk) > _MAX_ZIP_BYTES:
                                return FetchResult(
                                    FetchStatus.MALFORMED,
                                    source_uri=uri,
                                    http_status=status_code,
                                    detail="zip exceeds size limit",
                                )
                            content.extend(chunk)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = FetchResult(FetchStatus.RETRYABLE, source_uri=uri,
                                   detail=f"{type(exc).__name__}")
            else:
                if status_code == 404:
                    return FetchResult(FetchStatus.NOT_PUBLISHED, source_uri=uri, http_status=404)
                if status_code in _RETRYABLE_HTTP:
                    last = FetchResult(FetchStatus.RETRYABLE, source_uri=uri,
                                       http_status=status_code,
                                       detail=f"http {status_code}")
                elif status_code != 200:
                    return FetchResult(FetchStatus.MALFORMED, source_uri=uri,
                                       http_status=status_code,
                                       detail=f"http {status_code}")
                else:
                    return _unpack_zip(bytes(content), uri, status_code)
            if attempt < max_attempts - 1:
                sleep(_BACKOFF_BASE * (2 ** attempt))
        return last
    finally:
        if own:
            http.close()


def _unpack_zip(raw_zip: bytes, uri: str, http_status: int) -> FetchResult:
    """Bounded unzip: cap compressed size, member count, and decompressed size
    (zip-bomb guard) BEFORE extracting."""
    if len(raw_zip) > _MAX_ZIP_BYTES:
        return FetchResult(FetchStatus.MALFORMED, raw_zip=raw_zip, source_uri=uri,
                           http_status=http_status, detail="zip exceeds size limit")
    try:
        with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
            infos = zf.infolist()
            if len(infos) > _MAX_ZIP_MEMBERS:
                return FetchResult(FetchStatus.MALFORMED, raw_zip=raw_zip, source_uri=uri,
                                   http_status=http_status, detail="too many zip members")
            if sum(i.file_size for i in infos) > _MAX_CSV_BYTES:
                return FetchResult(FetchStatus.MALFORMED, raw_zip=raw_zip, source_uri=uri,
                                   http_status=http_status, detail="decompressed size over limit")
            name = next((i.filename for i in infos if i.filename.lower().endswith(".csv")), None)
            if name is None:
                return FetchResult(FetchStatus.EMPTY, raw_zip=raw_zip, source_uri=uri,
                                   http_status=http_status)
            csv_bytes = zf.read(name)
    except zipfile.BadZipFile:
        return FetchResult(FetchStatus.MALFORMED, raw_zip=raw_zip, source_uri=uri,
                           http_status=http_status, detail="bad zip")
    if len(csv_bytes) > _MAX_CSV_BYTES or not csv_bytes.strip():
        status = FetchStatus.MALFORMED if len(csv_bytes) > _MAX_CSV_BYTES else FetchStatus.EMPTY
        return FetchResult(status, raw_zip=raw_zip, source_uri=uri, http_status=http_status)
    return FetchResult(FetchStatus.OK, csv_bytes=csv_bytes, raw_zip=raw_zip,
                       source_uri=uri, http_status=http_status)


# --------------------------------------------------------------------------- #
# transactional persistence + provenance verification
# --------------------------------------------------------------------------- #

def _commit(day: date, df: pd.DataFrame, res: FetchResult) -> None:
    """Write parquet + raw ZIP + manifest as one transactional set: all to
    unique temp siblings, then os.replace with the MANIFEST LAST as the commit
    marker. An interruption leaves no manifest, so the day reads as unverified
    and is re-fetched — never a half-committed provenance chain."""
    pq, rz, man = snapshot_path(day), raw_zip_path(day), manifest_path(day)
    pq.parent.mkdir(parents=True, exist_ok=True)
    rz.parent.mkdir(parents=True, exist_ok=True)
    tag = f".{os.getpid()}.{next(_tmp_counter)}.tmp"
    pq_tmp = pq.with_name(pq.name + tag)
    rz_tmp = rz.with_name(rz.name + tag)
    man_tmp = man.with_name(man.name + tag)
    temps = [pq_tmp, rz_tmp, man_tmp]
    try:
        df.to_parquet(pq_tmp)
        parquet_bytes = pq_tmp.read_bytes()
        rz_tmp.write_bytes(res.raw_zip)
        manifest = {
            "stamp": STAMP,
            "parser_version": PARSER_VERSION,
            "source_uri": res.source_uri,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "trade_date": day.isoformat(),
            "http_status": res.http_status,
            "sha256_zip": _sha256(res.raw_zip),
            "sha256_csv": _sha256(res.csv_bytes),
            "sha256_parquet": _sha256(parquet_bytes),
            "rows_total": int(len(df)),
            "rows_equity": int((df["instrument_class"] == "equity").sum()),
            "rows_equity_clean": int(((df["instrument_class"] == "equity") & df["ok"]).sum()),
            "rows_quarantined": int((~df["ok"]).sum()),
            "series_present": sorted({str(s) for s in df["series"].unique()}),
        }
        man_tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True))
        os.replace(pq_tmp, pq)
        os.replace(rz_tmp, rz)
        os.replace(man_tmp, man)   # commit marker, last
    except BaseException:
        for t in temps:
            try:
                t.unlink()
            except OSError:
                pass
        raise


def _verified_snapshot_bytes(
    day: date,
) -> tuple[bytes, dict[str, object], BhavcopySessionReference]:
    """Read and verify one immutable artifact set before any Parquet decode.

    Returning the already-verified bytes prevents a path replacement between
    verification and decode.  The retained raw ZIP is mandatory: without it,
    the normalized Parquet cannot be reproduced or independently audited.
    """
    pq, man, rz = snapshot_path(day), manifest_path(day), raw_zip_path(day)
    if not (pq.exists() and man.exists() and rz.exists()):
        raise ProvenanceError(f"snapshot for {day} is missing an artifact")
    try:
        manifest_bytes = read_regular_file(man, max_bytes=_MAX_MANIFEST_BYTES)
        manifest = json.loads(manifest_bytes)
    except Exception as exc:
        raise ProvenanceError(f"snapshot for {day} has an invalid manifest") from exc
    if not isinstance(manifest, dict) or (_MANIFEST_REQUIRED - manifest.keys()):
        raise ProvenanceError(f"snapshot for {day} has an incomplete manifest")
    if manifest.get("trade_date") != day.isoformat():
        raise ProvenanceError(f"snapshot for {day} has a mismatched trade date")
    if manifest.get("parser_version") != PARSER_VERSION:
        raise ProvenanceError(f"snapshot for {day} has a stale parser version")
    if manifest.get("stamp") != STAMP:
        raise ProvenanceError(f"snapshot for {day} has a mismatched quarantine stamp")
    if manifest.get("source_uri") != bhavcopy_url(day):
        raise ProvenanceError(f"snapshot for {day} has a mismatched source URI")
    try:
        retrieved_at = datetime.fromisoformat(str(manifest["retrieved_at"]))
    except (TypeError, ValueError) as exc:
        raise ProvenanceError(
            f"snapshot for {day} has an invalid retrieval timestamp"
        ) from exc
    if retrieved_at.tzinfo is None:
        raise ProvenanceError(
            f"snapshot for {day} has a timezone-free retrieval timestamp"
        )
    expected_rows = manifest.get("rows_total")
    if (
        isinstance(expected_rows, bool)
        or not isinstance(expected_rows, int)
        or expected_rows < 1
        or expected_rows > _MAX_ROWS
    ):
        raise ProvenanceError(f"snapshot for {day} has an invalid row count")

    try:
        parquet_bytes = read_regular_file(pq, max_bytes=_MAX_PARQUET_BYTES)
        raw_zip = read_regular_file(rz, max_bytes=_MAX_ZIP_BYTES)
        if _sha256(parquet_bytes) != manifest["sha256_parquet"]:
            raise ProvenanceError(f"snapshot for {day} has a parquet hash mismatch")
        if _sha256(raw_zip) != manifest["sha256_zip"]:
            raise ProvenanceError(f"snapshot for {day} has a ZIP hash mismatch")
        unpacked = _unpack_zip(raw_zip, str(manifest["source_uri"]), 200)
        if (
            unpacked.status is not FetchStatus.OK
            or unpacked.csv_bytes is None
            or _sha256(unpacked.csv_bytes) != manifest["sha256_csv"]
        ):
            raise ProvenanceError(f"snapshot for {day} has a CSV hash mismatch")
        usage = inspect_parquet(
            parquet_bytes,
            label=f"bhavcopy {day}",
            expected_rows=expected_rows,
        )
        if usage.column_count > _MAX_PARQUET_COLUMNS:
            raise ProvenanceError(f"snapshot for {day} has too many columns")
        if usage.decoded_bytes > _MAX_PARQUET_DECODED_BYTES:
            raise ProvenanceError(f"snapshot for {day} exceeds the decode budget")
        estimated_peak = (
            len(parquet_bytes)
            + usage.decoded_bytes * 6
            + usage.row_count * usage.column_count * 16
        )
        if estimated_peak > _MAX_PARQUET_WORKING_BYTES:
            raise ProvenanceError(
                f"snapshot for {day} exceeds the working-memory budget"
            )
    except ProvenanceError:
        raise
    except Exception as exc:
        raise ProvenanceError(f"snapshot for {day} failed provenance verification") from exc
    reference = BhavcopySessionReference(
        trade_date=day,
        parser_version=PARSER_VERSION,
        manifest_sha256=_sha256(manifest_bytes),
        zip_sha256=str(manifest["sha256_zip"]),
        csv_sha256=str(manifest["sha256_csv"]),
        parquet_sha256=str(manifest["sha256_parquet"]),
        source_uri=str(manifest["source_uri"]),
    )
    return parquet_bytes, manifest, reference


def verify_snapshot(day: date) -> bool:
    """A capture is present only if its internal artifact chain checks out:
    manifest is bounded-readable, valid JSON with the required schema, matching
    trade_date and parser_version, and the recorded parquet/zip hashes match the
    files on disk. A bare or truncated artifact does NOT count."""
    try:
        _verified_snapshot_bytes(day)
    except Exception:
        return False
    return True


def rebuild_from_raw(day: date) -> FetchStatus:
    """Rebuild normalized Parquet from the retained, hash-pinned raw ZIP.

    This performs no network access.  It is the only safe parser-upgrade path:
    the previous manifest must authenticate both the ZIP and its CSV before the
    current parser may replace the derived Parquet and commit a new manifest.
    """
    man, rz = manifest_path(day), raw_zip_path(day)
    try:
        manifest = json.loads(
            read_regular_file(man, max_bytes=_MAX_MANIFEST_BYTES)
        )
        if not isinstance(manifest, dict) or (_MANIFEST_REQUIRED - manifest.keys()):
            return FetchStatus.MALFORMED
        if manifest.get("trade_date") != day.isoformat():
            return FetchStatus.MALFORMED
        raw_zip = read_regular_file(rz, max_bytes=_MAX_ZIP_BYTES)
        if _sha256(raw_zip) != manifest["sha256_zip"]:
            return FetchStatus.MALFORMED
        unpacked = _unpack_zip(
            raw_zip,
            str(manifest["source_uri"]),
            int(manifest.get("http_status") or 200),
        )
        if (
            unpacked.status is not FetchStatus.OK
            or unpacked.csv_bytes is None
            or _sha256(unpacked.csv_bytes) != manifest["sha256_csv"]
        ):
            return FetchStatus.MALFORMED
        frame = parse_bhavcopy(unpacked.csv_bytes, expected_day=day)
        if frame.empty:
            return FetchStatus.EMPTY
        _commit(day, frame, unpacked)
    except Exception:
        return FetchStatus.MALFORMED
    return FetchStatus.OK


def rebuild_all_from_raw() -> dict[str, str]:
    """Offline parser migration for every locally archived session."""
    return {day.isoformat(): rebuild_from_raw(day).value for day in available_days()}


# --------------------------------------------------------------------------- #
# snapshot orchestration
# --------------------------------------------------------------------------- #

def snapshot_day(day: date, *, client: httpx.Client | None = None,
                 overwrite: bool = False) -> FetchStatus:
    """Fetch + normalize + transactionally persist one session with an
    internally hash-consistent artifact chain. Idempotent: skips a consistent capture unless
    overwrite=True. Never raises on a single bad day — parse failures become
    MALFORMED. A NOT_PUBLISHED response remains an unresolved collection gap;
    it is never promoted into an authoritative non-trading-day fact."""
    if verify_snapshot(day) and not overwrite:
        return FetchStatus.OK
    res = fetch_bhavcopy(day, client=client)
    if res.status is not FetchStatus.OK:
        return res.status
    try:
        df = parse_bhavcopy(res.csv_bytes, expected_day=day)
    except BhavcopySchemaError:
        return FetchStatus.MALFORMED
    if df.empty:
        return FetchStatus.EMPTY
    _commit(day, df, res)
    return FetchStatus.OK


def _attempt(day: date, client: httpx.Client, overwrite: bool) -> str:
    """One day's attempt, fully guarded so nothing aborts a batch."""
    if verify_snapshot(day) and not overwrite:
        return "skipped_verified"
    try:
        return snapshot_day(day, client=client, overwrite=overwrite).value
    except Exception as exc:   # defensive: batch must survive any single-day fault
        return f"error:{type(exc).__name__}"


def snapshot_range(start: date, end: date, *,
                   overwrite: bool = False) -> dict[str, str]:
    """Manually attempt every date in [start, end].

    A 404 remains an unresolved collection outcome; this module has no
    authority to convert absence into an exchange-calendar fact.
    """
    if end < start:
        raise ValueError("end must not precede start")
    result: dict[str, str] = {}
    with httpx.Client(headers=_HEADERS, timeout=30, follow_redirects=True) as http:
        d = start
        while d <= end:
            # Never assume a date cannot trade: NSE held live sessions on
            # 2024-01-20, 2024-03-02, 2024-05-18 and 2025-02-01 (Saturdays) and
            # on 2026-02-01 (Sunday, budget). Skipping weekends silently broke
            # the prev_close continuity chain and produced thousands of phantom
            # corporate actions. A 404 remains unresolved rather than being
            # remembered as an authoritative holiday.
            result[d.isoformat()] = _attempt(d, http, overwrite)
            d += timedelta(days=1)
    return result


def missing_sessions(start: date, end: date) -> list[date]:
    """Dates in [start, end] lacking an internally consistent snapshot."""
    out, d = [], start
    while d <= end:
        if not verify_snapshot(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def catch_up(*, through: date | None = None, max_lookback_days: int = 30,
             overwrite: bool = False) -> dict[str, str]:
    """Manually attempt every unresolved date in the bounded recent window."""
    if max_lookback_days < 0:
        raise ValueError("max_lookback_days must be non-negative")
    through = through or date.today()
    gaps = missing_sessions(through - timedelta(days=max_lookback_days), through)
    if not gaps:
        return {}
    result: dict[str, str] = {}
    with httpx.Client(headers=_HEADERS, timeout=30, follow_redirects=True) as http:
        for d in gaps:
            result[d.isoformat()] = _attempt(d, http, overwrite)
    return result


# --------------------------------------------------------------------------- #
# quarantined read interface  (NOT a MarketDataCatalog)
# --------------------------------------------------------------------------- #

def _load_verified(day: date) -> pd.DataFrame:
    return _verified_session(day).frame.copy()


def _verified_session(day: date) -> VerifiedBhavcopySession:
    parquet_bytes, manifest, reference = _verified_snapshot_bytes(day)
    try:
        frame = pd.read_parquet(io.BytesIO(parquet_bytes))
    except Exception as exc:
        raise ProvenanceError(f"snapshot for {day} cannot be decoded") from exc
    expected_columns = {
        "symbol", "series", "isin", "open", "high", "low", "close",
        "last", "prev_close", "volume", "turnover", "instrument_class",
        "ok", "issue",
    }
    if expected_columns - set(frame.columns):
        raise ProvenanceError(f"snapshot for {day} has an invalid decoded schema")
    if len(frame) != manifest["rows_total"]:
        raise ProvenanceError(f"snapshot for {day} changed during decode")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ProvenanceError(f"snapshot for {day} has no datetime index")
    if frame.empty or any(timestamp.date() != day for timestamp in frame.index):
        raise ProvenanceError(f"snapshot for {day} contains another trade date")
    return _issue_verified_session(frame, reference)


def available_days() -> list[date]:
    root = base_dir()
    if not root.exists():
        return []
    days = []
    for p in root.glob("*/BhavCopy_*.parquet"):
        stamp = p.stem.replace("BhavCopy_", "")
        try:
            days.append(date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8])))
        except ValueError:
            continue
    return sorted(days)


class QuarantinedRawBhavcopy:
    """Explicitly NON-ADMISSIBLE staging access to the raw bhavcopy corpus.

    This is deliberately NOT a `MarketDataCatalog`: bars are raw/unadjusted and
    lack membership/identity, so they must never reach governed examination.
    Every read verifies the internal artifact chain first. Use only for exploratory
    research; feeding these frames to lifecycle governance is a bug.
    """

    ADMISSIBLE = False

    def sessions(self) -> list[date]:
        return available_days()

    def raw_session(self, day: date) -> pd.DataFrame:
        """Internally hash-consistent raw frame (all classes + flags)."""
        return _load_verified(day)

    def verified_session(self, day: date) -> VerifiedBhavcopySession:
        """Decoded frame and the exact internal artifact hashes checked."""
        return _verified_session(day)

    def equities(self, day: date) -> pd.DataFrame:
        """Hash-consistent, integrity-passing equity rows (raw/unadjusted)."""
        return equities_clean(_load_verified(day))
