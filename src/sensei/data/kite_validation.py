"""Offline Kite archive diagnostics and explicitly scoped development snapshots."""

from __future__ import annotations

import argparse
import inspect
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from sensei.data.kite_history import (
    STORE, KiteDataError, KiteRawStore, capture_lock, digest, encoded,
    history_frame, private_write, verify_plan,
)
from sensei.data.stock_repair import remove_confirmed_holiday_placeholders

SNAPSHOT_MANIFEST = "kite_snapshot_manifest.json"
AUTHORITY = {"authority": "QUARANTINED_KITE_DEVELOPMENT", "admissible": False, "can_trade": False}
CRISIS_WINDOWS = {
    "dotcom_2000_2002": ("2000-01-01", "2002-12-31"),
    "gfc_2007_2009": ("2007-01-01", "2009-12-31"),
    "covid_2020_2021": ("2020-01-01", "2021-12-31"),
}


def _strict_json_value(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, list):
        return [_strict_json_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _strict_json_value(v) for k, v in value.items()}
    return value


def diagnose_rejection(content: bytes, *, request: dict | None = None) -> dict:
    """Describe every anomaly; never choose, merge or modify a vendor bar."""
    try:
        payload = json.loads(content)
        rows = payload["data"]["candles"]
        if not isinstance(rows, list):
            raise TypeError
    except (ValueError, KeyError, TypeError):
        return {"unparseable_candle_payload": True}
    groups, invalid = defaultdict(list), []
    for number, row in enumerate(rows):
        defects = []
        if not isinstance(row, list) or len(row) not in (6, 7):
            invalid.append({"row_index": number, "row": _strict_json_value(row), "defects": ["invalid_width"]})
            continue
        try:
            stamp = pd.Timestamp(row[0])
            if pd.isna(stamp) or stamp.tzinfo is None:
                raise ValueError
            session = str(stamp.tz_convert("Asia/Kolkata").date())
            groups[session].append(row)
            if request and not request["start"] <= session <= request["end"]:
                defects.append("outside_requested_window")
        except (ValueError, TypeError, OverflowError):
            defects.append("invalid_timestamp")
        numeric = all(not isinstance(v, bool) and isinstance(v, (int, float)) for v in row[1:6])
        try:
            finite = numeric and all(math.isfinite(v) for v in row[1:6])
        except OverflowError:
            finite = False
        if not numeric:
            defects.append("invalid_numeric_type")
        elif not finite:
            defects.append("nonfinite_or_unrepresentable_numeric_value")
        else:
            o, h, l, c, v = row[1:6]
            if min(o, h, l, c) <= 0:
                defects.append("nonpositive_price")
            if l > min(o, c):
                defects.append("low_above_open_or_close")
            if h < max(o, c):
                defects.append("high_below_open_or_close")
            if v < 0 or not float(v).is_integer():
                defects.append("invalid_volume")
        if defects:
            invalid.append({"row_index": number, "row": _strict_json_value(row), "defects": defects})
    return {"raw_rows": len(rows), "invalid_rows": invalid,
            "row_encoding": "Nonfinite numbers shown as strings; exact original values remain in raw response bytes.",
            "duplicate_sessions": [{"date": session, "rows": _strict_json_value(values),
                "classification": "identical" if all(v == values[0] for v in values) else "conflicting"}
                for session, values in sorted(groups.items()) if len(values) > 1]}


def audit_capture(plan: dict, store: KiteRawStore, *, progress=print) -> dict:
    implementation_hash = digest(inspect.getsource(sys.modules[__name__]).encode())
    verify_plan(plan, store)
    counts = Counter({"accepted_windows": 0, "rejected_windows": 0, "missing_windows": 0,
                      "empty_windows": 0, "accepted_rows": 0, "raw_bytes": 0})
    inputs, rejected, coverage = {}, [], {}
    crisis = {name: {"rows": 0, "symbols": set(), "bookends": defaultdict(set)} for name in CRISIS_WINDOWS}
    for number, request in enumerate(plan["identity"]["requests"], 1):
        request_id = digest(encoded(request))
        bad = store.verified_rejection(request)
        if bad is not None:
            metadata = json.loads(store.rejection_paths(request)[1].read_text())
            counts["rejected_windows"] += 1
            counts["raw_bytes"] += len(bad)
            inputs[request_id] = {"classification": "rejected", "sha256": digest(bad)}
            rejected.append({"request": request, "reason": metadata["reason"],
                             "sha256": digest(bad), **diagnose_rejection(bad, request=request)})
        else:
            raw = store.verified(request)
            if raw is None:
                counts["missing_windows"] += 1
                inputs[request_id] = {"classification": "missing"}
                continue
            rows = json.loads(raw)["data"]["candles"]
            counts["accepted_windows"] += 1
            counts["empty_windows"] += not rows
            counts["accepted_rows"] += len(rows)
            counts["raw_bytes"] += len(raw)
            inputs[request_id] = {"classification": "accepted", "sha256": digest(raw)}
            # Validation has already established exchange-local session dates.
            days = sorted(str(pd.Timestamp(r[0]).tz_convert("Asia/Kolkata").date()) for r in rows)
            if days:
                value = coverage.setdefault(request["symbol"], {"rows": 0, "first": days[0], "last": days[-1]})
                value["rows"] += len(days)
                value["first"], value["last"] = min(value["first"], days[0]), max(value["last"], days[-1])
                for name, (start, end) in CRISIS_WINDOWS.items():
                    selected = [d for d in days if start <= d <= end]
                    if selected:
                        c = crisis[name]
                        c["rows"] += len(selected)
                        c["symbols"].add(request["symbol"])
                        if any(d[:7] == start[:7] for d in selected):
                            c["bookends"][request["symbol"]].add("first_month")
                        if any(d[:7] == end[:7] for d in selected):
                            c["bookends"][request["symbol"]].add("last_month")
        if number % 500 == 0 or number == len(plan["identity"]["requests"]):
            progress(json.dumps({"audited": number, "total": len(plan["identity"]["requests"])}), flush=True)
    return {"plan_id": plan["plan_id"], "implementation_sha256": implementation_hash,
            "counts": dict(counts), "inputs": inputs,
            "rejected": rejected, "accepted_coverage": coverage,
            "crisis_coverage": {name: {"window": CRISIS_WINDOWS[name], "rows": values["rows"],
                "instruments_with_some_bars": len(values["symbols"]),
                "instruments_in_first_and_last_month": sum(len(v) == 2 for v in values["bookends"].values())}
                for name, values in crisis.items()},
            "scope_note": "Current instrument identities; some bars and bookend presence do not prove complete historical coverage.",
            "all_requests_retained": counts["missing_windows"] == 0,
            "all_responses_structurally_valid": counts["missing_windows"] == counts["rejected_windows"] == 0,
            **AUTHORITY}


def _priority_selection(plan, universe: Path):
    frame = pd.read_csv(universe, dtype=str)
    if "symbol" not in frame or frame.symbol.isna().any() or frame.symbol.duplicated().any():
        raise KiteDataError("Priority universe requires unique nonempty symbols")
    names = set(frame.symbol)
    if not names or any(not s.strip() for s in names):
        raise KiteDataError("Priority universe is empty")
    scope = plan["identity"].get("scope")
    mappings = scope["mappings"] if scope else [
        {"symbol": r["symbol"], "exchange_symbol": r["symbol"], "instrument_token": r["instrument_token"]}
        for r in plan["identity"]["requests"]]
    selected = {r["symbol"]: r for r in mappings if r["exchange_symbol"] in names}
    if not selected:
        raise KiteDataError("No priority symbols match the captured master")
    if any(not re.fullmatch(r"[A-Za-z0-9&_.-]+", s) or s in (".", "..") for s in selected):
        raise KiteDataError("Instrument symbol cannot be used as a snapshot filename")
    return selected, sorted(names - {r["exchange_symbol"] for r in selected.values()})


def _selected_requests(plan, selected, start: str, end: str):
    if not plan["identity"]["start"] <= start <= end <= plan["identity"]["end"]:
        raise KiteDataError("Snapshot window must lie within the frozen capture plan")
    return [r for r in plan["identity"]["requests"] if r["symbol"] in selected
            and r["start"] <= end and r["end"] >= start]


def build_priority_snapshot(plan_path: Path, store: KiteRawStore, universe: Path, *,
                            start: date, end: date, output: Path) -> Path:
    plan_raw = plan_path.read_bytes()
    plan = json.loads(plan_raw)
    verify_plan(plan, store)
    selected, unmapped = _priority_selection(plan, universe)
    requests = _selected_requests(plan, selected, str(start), str(end))
    frames, sources, removed = defaultdict(list), [], {}
    for request in requests:
        if store.verified_rejection(request) is not None:
            raise KiteDataError(f'Selected window has a rejected response: {request["symbol"]}')
        raw = store.verified(request)
        if raw is None:
            raise KiteDataError(f'Selected window is missing: {request["symbol"]}')
        frame = history_frame(raw, request)
        frames[request["symbol"]].append(frame.loc[str(start):str(end)])
        sources.append({"request": request, "sha256": digest(raw)})
    outputs = {}
    for symbol in sorted(selected):
        frame = pd.concat(frames[symbol]).sort_index()
        if frame.index.has_duplicates:
            raise KiteDataError("Selected history windows overlap")
        frame, exclusions = remove_confirmed_holiday_placeholders(frame)
        outputs[symbol + ".parquet"] = frame.to_parquet()
        if exclusions:
            removed[symbol] = exclusions
    identity = {"recipe": "kite-current-priority-development-v1", "plan_id": plan["plan_id"],
                "plan_path": str(plan_path.resolve()), "plan_sha256": digest(plan_raw), "store": str(store.root),
                "universe_path": str(universe.resolve()), "universe_sha256": digest(universe.read_bytes()),
                "scope_start": str(start), "scope_end": str(end), "selection": selected,
                "unmapped_symbols": unmapped, "sources": sources, "removed_holidays": removed,
                "outputs": {name: digest(raw) for name, raw in outputs.items()},
                "implementation_sha256": digest(inspect.getsource(sys.modules[__name__]).encode()
                    + inspect.getsource(remove_confirmed_holiday_placeholders).encode()),
                "pandas_version": pd.__version__,
                "limitations": ["current matched cohort, not historical membership", "unmapped original symbols retained as exclusions",
                    "corporate-action and executable-price treatment unverified", "outside-window rejected responses remain unresolved",
                    "reused history; not an untouched holdout"], **AUTHORITY}
    snapshot_id = digest(encoded(identity))
    destination = output.resolve() / snapshot_id
    if destination.exists():
        verify_priority_snapshot(destination)
        return destination
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    with TemporaryDirectory(prefix=".kite-snapshot-", dir=output) as directory:
        staging = Path(directory)
        for filename, raw in outputs.items():
            private_write(staging / filename, raw)
        private_write(staging / SNAPSHOT_MANIFEST, encoded({"snapshot_id": snapshot_id, "identity": identity}))
        staging.rename(destination)
    return destination


def verify_priority_snapshot(path: Path) -> dict:
    manifest = json.loads((path / SNAPSHOT_MANIFEST).read_text())
    identity = manifest["identity"]
    if manifest["snapshot_id"] != digest(encoded(identity)) or path.name != manifest["snapshot_id"]:
        raise KiteDataError("Kite snapshot identity mismatch")
    if any(identity.get(k) != v for k, v in AUTHORITY.items()):
        raise KiteDataError("Kite snapshot cannot grant data or trading authority")
    plan_path, universe = Path(identity["plan_path"]), Path(identity["universe_path"])
    if digest(plan_path.read_bytes()) != identity["plan_sha256"] or digest(universe.read_bytes()) != identity["universe_sha256"]:
        raise KiteDataError("Kite snapshot source identity changed")
    plan, store = json.loads(plan_path.read_bytes()), KiteRawStore(Path(identity["store"]))
    verify_plan(plan, store)
    selected, unmapped = _priority_selection(plan, universe)
    if selected != identity["selection"] or unmapped != identity["unmapped_symbols"] or plan["plan_id"] != identity["plan_id"]:
        raise KiteDataError("Kite snapshot selection changed")
    expected_requests = _selected_requests(plan, selected, identity["scope_start"], identity["scope_end"])
    if [s["request"] for s in identity["sources"]] != expected_requests:
        raise KiteDataError("Kite snapshot source request set changed")
    for source in identity["sources"]:
        if store.verified_rejection(source["request"]) is not None:
            raise KiteDataError("Kite snapshot source is rejected")
        raw = store.verified(source["request"])
        if raw is None or digest(raw) != source["sha256"]:
            raise KiteDataError("Kite snapshot raw source content changed")
    outputs = identity["outputs"]
    if set(outputs) != {s + ".parquet" for s in selected} or set(outputs) != {p.name for p in path.glob("*.parquet")}:
        raise KiteDataError("Kite snapshot instrument set changed")
    for filename, expected in outputs.items():
        if digest((path / filename).read_bytes()) != expected:
            raise KiteDataError("Kite snapshot output content mismatch")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("audit", "snapshot"))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--universe", type=Path, default=Path("data/universe.csv"))
    parser.add_argument("--start", type=date.fromisoformat, default=date(2022,1,1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026,9,4))
    args = parser.parse_args()
    store = KiteRawStore(args.store)
    with capture_lock(store.root):
        if args.command == "audit":
            report = audit_capture(json.loads(args.plan.read_bytes()), store)
            private_write(args.output, encoded(report))
            print(json.dumps({"report": str(args.output), "counts": report["counts"], **AUTHORITY}))
        else:
            path = build_priority_snapshot(args.plan, store, args.universe, start=args.start, end=args.end, output=args.output)
            print(json.dumps({"snapshot": str(path), **AUTHORITY}))


if __name__ == "__main__":
    main()
