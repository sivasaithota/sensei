"""Resumable, read-only Kite daily-history capture into a private raw store."""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import io
import json
import math
import os
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

from sensei.data.kite_auth import read_secret

BASE = "https://api.kite.trade"
STORE = Path.home() / ".local/share/sensei/kite"
IST = ZoneInfo("Asia/Kolkata")
MISSING_DATES = ("2024-01-20", "2024-03-02", "2024-05-18", "2026-02-01")
AUTHORITY = {"authority": "QUARANTINED_KITE_CAPTURE", "admissible": False, "can_trade": False}


class KiteDataError(RuntimeError):
    pass


class KiteRequestError(KiteDataError):
    def __init__(self, classification: str, status: int | None = None):
        self.classification, self.status = classification, status
        super().__init__(f"Kite request stopped: {classification}; HTTP {status}")


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def encoded(value) -> bytes:
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()


def private_write(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temporary, "xb") as stream:
            os.chmod(temporary, 0o600)
            stream.write(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def capture_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    with open(root / ".capture.lock", "a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise KiteDataError("Another Kite capture is running in this store") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class KiteHistoryClient:
    """Only master/history GETs; a single paced stream, bounded retries and bytes."""

    def __init__(self, api_key: str, access_token: str, *, http=None, sleeper=time.sleep,
                 clock=time.monotonic, interval=0.55):
        if not api_key or not access_token or not math.isfinite(interval) or interval < 0.5:
            raise KiteDataError("Kite credentials and at least 0.5 seconds between requests are required")
        self._headers = {"X-Kite-Version": "3", "Authorization": f"token {api_key}:{access_token}"}
        self.http = http or httpx.Client(timeout=60, follow_redirects=False)
        self.sleeper, self.clock, self.interval = sleeper, clock, interval
        self.last = None

    def fetch(self, request: dict) -> bytes:
        if request["kind"] == "master":
            path, params = "/instruments/NSE", None
        elif request["kind"] == "history":
            validate_request(request)
            path = f'/instruments/historical/{request["instrument_token"]}/day'
            params = {"from": request["start"] + " 00:00:00", "to": request["end"] + " 23:59:59",
                      "continuous": 0, "oi": 0}
        else:
            raise KiteDataError("Unsupported read-only request")
        for attempt in range(3):
            if self.last is not None:
                self.sleeper(max(0, self.interval - (self.clock() - self.last)))
            self.last = self.clock()
            try:
                with self.http.stream("GET", BASE + path, params=params, headers=self._headers) as response:
                    status = response.status_code
                    if status in (401, 403):
                        raise KiteRequestError("authentication_or_entitlement", status)
                    if status == 429:
                        raise KiteRequestError("rate_limited_wait_before_resuming", status)
                    if status >= 500:
                        if attempt < 2:
                            self.sleeper(2 ** attempt)
                            continue
                        raise KiteRequestError("server_error", status)
                    if status != 200:
                        raise KiteRequestError("request_rejected", status)
                    chunks, size = [], 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > 32_000_000:
                            raise KiteDataError("Kite response exceeds 32 MB limit")
                        chunks.append(chunk)
                    return b"".join(chunks)
            except httpx.HTTPError:
                if attempt == 2:
                    raise KiteRequestError("network_error") from None
                self.sleeper(2 ** attempt)
        raise KiteRequestError("retry_limit")


def validate_request(request: dict):
    expected = {"kind", "symbol", "instrument_token", "start", "end", "master_sha256"}
    if set(request) != expected or request["kind"] != "history":
        raise KiteDataError("Invalid history request fields")
    if type(request["instrument_token"]) is not int or request["instrument_token"] <= 0:
        raise KiteDataError("Invalid instrument token")
    start, end = date.fromisoformat(request["start"]), date.fromisoformat(request["end"])
    if start > end or (end - start).days >= 2000:
        raise KiteDataError("History window must contain at most 2000 calendar dates")
    if not isinstance(request["symbol"], str) or not request["symbol"] or len(request["master_sha256"]) != 64:
        raise KiteDataError("History request lacks master identity")


def master_equities(content: bytes) -> list[dict]:
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
        if not {"instrument_token", "tradingsymbol", "exchange", "segment", "instrument_type"}.issubset(reader.fieldnames or []):
            raise KiteDataError("Kite master is not a valid instrument CSV")
        selected = []
        for row in reader:
            if row["exchange"] == "NSE" and row["segment"] == "NSE" and row["instrument_type"] == "EQ":
                token = int(row["instrument_token"])
                if token <= 0 or not row["tradingsymbol"]:
                    raise KiteDataError("Invalid cash instrument identity")
                selected.append({"symbol": row["tradingsymbol"], "instrument_token": token})
        if (not selected or len({r["symbol"] for r in selected}) != len(selected)
                or len({r["instrument_token"] for r in selected}) != len(selected)):
            raise KiteDataError("Kite NSE cash master is empty or contains duplicate identities")
        return sorted(selected, key=lambda row: row["symbol"])
    except (UnicodeError, ValueError, KeyError, TypeError):
        raise KiteDataError("Invalid Kite instrument CSV") from None


def history_frame(content: bytes, request: dict) -> pd.DataFrame:
    validate_request(request)
    try:
        payload = json.loads(content)
        if payload["status"] != "success" or not isinstance(payload["data"]["candles"], list):
            raise KiteDataError("Kite response is not successful candle data")
        rows, stamps = [], []
        for row in payload["data"]["candles"]:
            if not isinstance(row, list) or len(row) not in (6, 7):
                raise KiteDataError("Invalid candle width")
            stamp = pd.Timestamp(row[0])
            if pd.isna(stamp) or stamp.tzinfo is None:
                raise KiteDataError("Kite candle needs an explicit exchange timestamp")
            stamp = stamp.tz_convert(IST).normalize().tz_localize(None)
            if not request["start"] <= str(stamp.date()) <= request["end"]:
                raise KiteDataError("Kite candle lies outside its requested window")
            if any(isinstance(v, bool) or not isinstance(v, (float, int)) for v in row[1:6]):
                raise KiteDataError("Kite candle has invalid numeric fields")
            o, h, l, c, v = map(float, row[1:6])
            if (not all(math.isfinite(x) for x in (o, h, l, c, v)) or min(o, h, l, c) <= 0
                    or l > min(o, c) or h < max(o, c) or v < 0 or not v.is_integer()):
                raise KiteDataError("Kite candle has invalid OHLCV")
            rows.append((o, h, l, c, int(v)))
            stamps.append(stamp)
        index = pd.DatetimeIndex(stamps, name="date")
        if index.has_duplicates:
            raise KiteDataError("Kite response contains duplicate session dates")
        return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=index).sort_index()
    except (ValueError, KeyError, TypeError, OverflowError):
        raise KiteDataError("Invalid Kite historical response") from None


class KiteRawStore:
    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()

    def paths(self, request):
        identifier = digest(encoded(request))
        directory = self.root / "raw" / identifier[:2] / identifier
        return directory / "response.bin", directory / "manifest.json"

    def verified(self, request) -> bytes | None:
        raw_path, meta_path = self.paths(request)
        if not raw_path.exists() and not meta_path.exists():
            return None
        if not raw_path.exists() or not meta_path.exists():
            raise KiteDataError("Incomplete raw artifact; preserve it and inspect before resuming")
        content, metadata = raw_path.read_bytes(), json.loads(meta_path.read_text())
        if (metadata.get("request") != request or metadata.get("sha256") != digest(content)
                or metadata.get("bytes") != len(content)):
            raise KiteDataError("Kite stored artifact integrity mismatch")
        if request["kind"] == "master":
            master_equities(content)
        else:
            frame = history_frame(content, request)
            if metadata.get("rows") != len(frame):
                raise KiteDataError("Kite stored row count mismatch")
        return content

    def capture(self, request, client) -> bytes:
        existing = self.verified(request)
        if existing is not None:
            return existing
        content = client.fetch(request)
        rows = len(master_equities(content)) if request["kind"] == "master" else len(history_frame(content, request))
        metadata = {"request": request, "sha256": digest(content), "bytes": len(content),
                    "rows": rows, "classification": "data" if rows else "no_data",
                    "retrieved_at": datetime.now(IST).isoformat(), **AUTHORITY}
        raw_path, meta_path = self.paths(request)
        raw_path.parent.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with TemporaryDirectory(prefix=".capture-", dir=raw_path.parent.parent) as temporary:
            staging = Path(temporary)
            private_write(staging / raw_path.name, content)
            private_write(staging / meta_path.name, encoded(metadata))
            staging.rename(raw_path.parent)
        return content


def date_windows(start: date, end: date) -> list[tuple[date, date]]:
    if start > end:
        raise KiteDataError("Start date follows end date")
    windows = []
    while start <= end:
        stop = min(start + timedelta(days=1999), end)
        windows.append((start, stop))
        start = stop + timedelta(days=1)
    return list(reversed(windows))


def equity_scope(master: bytes, reference_paths: list[Path]) -> dict:
    """Match current official equity/SME lists; retain every unmatched identity."""
    candidates = {row["symbol"]: row for row in master_equities(master)}
    selected, references, unmatched, mappings = {}, [], [], []
    for path in reference_paths:
        content = path.read_bytes()
        receipt = json.loads(path.with_suffix(".manifest.json").read_text())
        if receipt.get("sha256") != digest(content):
            raise KiteDataError("NSE classification file does not match its capture receipt")
        frame = pd.read_csv(io.BytesIO(content), dtype=str).fillna("")
        frame.columns = [c.strip().replace(" ", "_") for c in frame.columns]
        if not {"SYMBOL", "SERIES", "ISIN_NUMBER"}.issubset(frame.columns):
            raise KiteDataError("NSE classification file lacks security identity")
        references.append({"path": str(path.resolve()), "sha256": digest(content), "receipt": receipt})
        for _, row in frame.iterrows():
            symbol, series = row["SYMBOL"].strip(), row["SERIES"].strip()
            aliases = {symbol, f"{symbol}-{series}"} | {f"{symbol}-{s}" for s in ("EQ", "BE", "BZ", "SM", "ST")}
            matches = [candidates[s] for s in sorted(aliases) if s in candidates]
            if not matches:
                unmatched.append({"symbol": symbol, "series": series, "isin": row["ISIN_NUMBER"]})
            for match in matches:
                selected[match["symbol"]] = match
                mappings.append({**match, "exchange_symbol": symbol, "series": series, "isin": row["ISIN_NUMBER"]})
    if not selected:
        raise KiteDataError("No official equity/SME symbols match the Kite master")
    return {"policy": "current official equity and SME symbol/series match; historical identity unverified",
            "references": references, "selected": sorted(selected.values(), key=lambda row: row["symbol"]),
            "mappings": sorted(mappings, key=lambda row: (row["symbol"], row["isin"])),
            "unmatched_exchange_symbols": sorted(unmatched, key=lambda row: row["symbol"]),
            "excluded_master_symbols": sorted(set(candidates) - set(selected))}


def build_plan(master: bytes, *, master_request: dict, start: date, end: date,
               priority_symbols=(), scope=None) -> dict:
    equities = list(scope["selected"]) if scope else master_equities(master)
    priority = set(priority_symbols)
    priority_aliases = priority | ({r["symbol"] for r in scope["mappings"]
                                   if r["exchange_symbol"] in priority} if scope else set())
    equities.sort(key=lambda row: (row["symbol"] not in priority_aliases, row["symbol"]))
    # Capture the current research window first, then older history. No stock
    # is excluded using future completeness, and no missing dates are filled.
    boundary = date(2022, 1, 1)
    windows = (date_windows(max(start, boundary), end) if end >= boundary else [])
    if start < boundary:
        windows += date_windows(start, min(end, boundary - timedelta(days=1)))
    requests = [{"kind": "history", **equity, "start": str(a), "end": str(b),
                 "master_sha256": digest(master)} for a, b in windows for equity in equities]
    identity = {"version": 1, "master_request": master_request, "master_sha256": digest(master),
                "start": str(start), "end": str(end), "requests": requests,
                "scope": scope,
                "universe": "current NSE cash-segment EQ records; stock/ETF classification unverified",
                "missing_priority_symbols": sorted(priority - ({r["exchange_symbol"] for r in scope["mappings"]}
                    if scope else {r["symbol"] for r in equities}))}
    return {"plan_id": digest(encoded(identity)), "identity": identity, **AUTHORITY}


def verify_plan(plan: dict, store: KiteRawStore):
    identity = plan["identity"]
    if plan["plan_id"] != digest(encoded(identity)):
        raise KiteDataError("Kite plan identity mismatch")
    master = store.verified(identity["master_request"])
    if master is None or digest(master) != identity["master_sha256"]:
        raise KiteDataError("Kite plan master is missing or changed")
    valid = {(r["symbol"], r["instrument_token"]) for r in master_equities(master)}
    if identity.get("scope") is not None:
        scope = identity["scope"]
        actual = equity_scope(master, [Path(r["path"]) for r in scope["references"]])
        if scope != actual:
            raise KiteDataError("Kite equity classification evidence changed")
        valid = {(r["symbol"], r["instrument_token"]) for r in scope["selected"]}
    requests = identity["requests"]
    if not requests or len({digest(encoded(r)) for r in requests}) != len(requests):
        raise KiteDataError("Kite plan has missing or duplicate requests")
    for request in requests:
        validate_request(request)
        if ((request["symbol"], request["instrument_token"]) not in valid
                or request["master_sha256"] != identity["master_sha256"]):
            raise KiteDataError("Kite plan instrument does not match captured master")
    by_instrument = {}
    for request in requests:
        by_instrument.setdefault((request["symbol"], request["instrument_token"]), []).append(request)
    if set(by_instrument) != valid:
        raise KiteDataError("Kite plan does not cover the complete declared instrument set")
    for windows in by_instrument.values():
        expected_start = date.fromisoformat(identity["start"])
        for window in sorted(windows, key=lambda item: item["start"]):
            if date.fromisoformat(window["start"]) != expected_start:
                raise KiteDataError("Kite plan date coverage contains a gap or overlap")
            expected_start = date.fromisoformat(window["end"]) + timedelta(days=1)
        if expected_start != date.fromisoformat(identity["end"]) + timedelta(days=1):
            raise KiteDataError("Kite plan does not cover the complete declared date range")


def download(plan, store, client, *, progress=print):
    verify_plan(plan, store)
    identity = plan["identity"]
    result = probe(store.verified(identity["master_request"]), identity["master_request"], store, client)
    if not result["coverage_passed"]:
        raise KiteDataError("Required-session probe failed; bulk download and resume are blocked")
    requests = plan["identity"]["requests"]
    fetched = skipped = empty = 0
    for i, request in enumerate(requests, 1):
        content = store.verified(request)
        if content is None:
            try:
                content = store.capture(request, client)
            except KiteRequestError as exc:
                private_write(store.root / "reports" / f'{plan["plan_id"]}-stopped.json', encoded({
                    "request": request, "completed": i - 1, "classification": exc.classification,
                    "http_status": exc.status, **AUTHORITY}))
                raise
            fetched += 1
        else:
            skipped += 1
        if history_frame(content, request).empty:
            empty += 1
        if i % 25 == 0 or i == len(requests):
            progress(json.dumps({"completed": i, "total": len(requests), "new_requests": fetched,
                "cached": skipped, "empty_responses": empty}), flush=True)
    return {"requests": len(requests), "new_requests": fetched, "cached": skipped, "empty_responses": empty}


def probe(master, master_request, store, client):
    mapping = {r["symbol"]: r for r in master_equities(master)}
    cases = [("TCS", "2024-01-19", "2024-01-23", "2024-01-20"),
             ("TCS", "2024-03-01", "2024-03-04", "2024-03-02"),
             ("TCS", "2024-05-17", "2024-05-21", "2024-05-18"),
             ("TCS", "2026-01-30", "2026-02-02", "2026-02-01"),
             ("BSE", "2025-05-22", "2025-05-26", "2025-05-23")]
    cases += [(s, "2026-01-30", "2026-02-02", "2026-02-01") for s in ("BALKRISIND", "BPCL", "IDEA", "LTFOODS")]
    rows = []
    for symbol, start, end, required in cases:
        if symbol not in mapping:
            rows.append({"symbol": symbol, "required": required, "status": "MISSING_FROM_MASTER"})
            continue
        request = {"kind": "history", **mapping[symbol], "start": start, "end": end,
                   "master_sha256": digest(master)}
        content = store.capture(request, client)
        frame = history_frame(content, request)
        present = pd.Timestamp(required) in frame.index
        rows.append({"request": request, "raw_sha256": digest(content), "required": required,
                     "observed_dates": [str(d.date()) for d in frame.index],
                     "status": "REQUIRED_SESSION_PRESENT" if present else "REQUIRED_SESSION_MISSING"})
    report = {"master_request": master_request, "master_sha256": digest(master), "checks": rows,
              "coverage_passed": all(r["status"] == "REQUIRED_SESSION_PRESENT" for r in rows),
              "adjustment_factors_verified": False, **AUTHORITY}
    private_write(store.root / "reports" / f'probe-{digest(encoded(report))}.json', encoded(report))
    return report


def normalize(plan, store):
    verify_plan(plan, store)
    grouped = {}
    for request in plan["identity"]["requests"]:
        grouped.setdefault(request["symbol"], []).append(request)
    output = store.root / "normalized" / plan["plan_id"]
    counts, artifacts = [], {}
    for symbol, requests in grouped.items():
        frames, inputs = [], {}
        for request in requests:
            content = store.verified(request)
            if content is None:
                raise KiteDataError("Complete the capture before normalization")
            frames.append(history_frame(content, request))
            inputs[digest(encoded(request))] = digest(content)
        frame = pd.concat(frames).sort_index()
        if frame.index.has_duplicates:
            raise KiteDataError("Overlapping history windows cannot be normalized")
        filename = f'{requests[0]["instrument_token"]}.parquet'
        raw = frame.to_parquet()
        existing = output / filename
        if existing.exists() and existing.read_bytes() != raw:
            raise KiteDataError("Normalized snapshot changed; preserve existing artifact")
        if not existing.exists():
            private_write(existing, raw)
        artifacts[filename] = {"symbol": symbol, "sha256": digest(raw), "inputs": inputs}
        observed = set(str(d.date()) for d in frame.index)
        counts.append({"symbol": symbol, "rows": len(frame), "first": min(observed) if observed else None,
                       "last": max(observed) if observed else None,
                       "missing_special_sessions_within_observed_history": [d for d in MISSING_DATES
                           if observed and min(observed) <= d <= max(observed) and d not in observed]})
    report = {"plan_id": plan["plan_id"], "artifacts": artifacts, "coverage": counts,
              "total_rows": sum(row["rows"] for row in counts), "instruments": len(counts),
              "adjustment_convention": "vendor adjusted; action methodology not certified",
              "historical_membership_verified": False, **AUTHORITY}
    private_write(output / "manifest.json", encoded(report))
    return output, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("capture", "download", "normalize", "audit"))
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--start", type=date.fromisoformat, default=date(1996, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 9, 4))
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--priority-universe", type=Path, default=Path("data/universe.csv"))
    parser.add_argument("--equity-reference", type=Path, default=STORE / "reference/20260906-EQUITY_L.csv")
    parser.add_argument("--sme-reference", type=Path, default=STORE / "reference/20260906-SME_EQUITY_L.csv")
    args = parser.parse_args()
    store = KiteRawStore(args.store)
    try:
        if args.command != "capture" and args.plan is None:
            raise KiteDataError("--plan is required for this command")
        if args.command == "capture" and args.plan is not None:
            raise KiteDataError("Use download --plan to resume the exact original master and requests")
        with capture_lock(store.root):
            if args.command in ("capture", "download"):
                key, token = read_secret("api-key"), read_secret("access-token")
                if not key or not token:
                    raise KiteDataError("Run kite_auth configure and login first")
                client = KiteHistoryClient(key, token)
            if args.command == "capture":
                if args.end >= datetime.now(IST).date() or args.start > args.end:
                    raise KiteDataError("Choose a valid range ending before today's incomplete session")
                master_request = {"kind": "master", "as_of": str(datetime.now(IST).date())}
                master = store.capture(master_request, client)
                priority = pd.read_csv(args.priority_universe)["symbol"].tolist()
                plan = build_plan(master, master_request=master_request, start=args.start, end=args.end,
                                  priority_symbols=priority,
                                  scope=equity_scope(master, [args.equity_reference, args.sme_reference]))
                plan_path = store.root / "plans" / f'{plan["plan_id"]}.json'
                private_write(plan_path, encoded(plan))
                print(json.dumps({"plan": str(plan_path), "requests": len(plan["identity"]["requests"]),
                                  "missing_local_symbols": plan["identity"]["missing_priority_symbols"]}), flush=True)
                result = probe(master, master_request, store, client)
                print(json.dumps({"probe_coverage_passed": result["coverage_passed"], **AUTHORITY}), flush=True)
                if not result["coverage_passed"]:
                    raise KiteDataError("Required-session probe failed; inspect its report before bulk capture")
            else:
                plan = json.loads(args.plan.read_text())
            if args.command in ("capture", "download"):
                print(json.dumps(download(plan, store, client)), flush=True)
            if args.command in ("capture", "normalize"):
                path, report = normalize(plan, store)
                print(json.dumps({"normalized": str(path), "rows": report["total_rows"],
                                  "instruments": report["instruments"], **AUTHORITY}), flush=True)
            if args.command == "audit":
                verify_plan(plan, store)
                requests = plan["identity"]["requests"]
                verified = sum(store.verified(r) is not None for r in requests)
                print(json.dumps({"expected": len(requests), "verified": verified,
                                  "missing": len(requests) - verified, **AUTHORITY}))
                if verified != len(requests):
                    raise SystemExit(2)
    except KiteDataError as exc:
        print(str(exc), flush=True)
        raise SystemExit(2) from None
    except (OSError, ValueError, KeyError, TypeError):
        print("Capture stopped on an invalid local artifact or configuration. Original data preserved.", flush=True)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
