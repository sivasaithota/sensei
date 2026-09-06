"""Audited, non-destructive calendar repair for the stock research corpus.

Only confirmed holiday placeholders are removed. Missing-session adjustment
factors are assessed, never inferred into price rows by this module.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import io
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from sensei.data.bhavcopy import QuarantinedRawBhavcopy, equities_clean

HOLIDAYS = {
    "2026-01-15": "https://nsearchives.nseindia.com/content/circulars/CMTR72260.pdf",
    "2026-05-01": "https://nsearchives.nseindia.com/content/circulars/CMTR71775.pdf",
    "2026-05-28": "https://nsearchives.nseindia.com/content/circulars/CMTR71775.pdf",
    "2026-06-26": "https://nsearchives.nseindia.com/content/circulars/CMTR71775.pdf",
}
MISSING_SESSIONS = ("2024-01-20", "2024-03-02", "2024-05-18", "2026-02-01")
MANIFEST_NAME = "snapshot_manifest.json"
EVIDENCE_KEYS = ("outputs", "source_directory", "removed_rows", "removed_row_count",
                 "instrument_count", "inserted_rows", "authority", "admissible", "unresolved")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def remove_confirmed_holiday_placeholders(frame: pd.DataFrame):
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.has_duplicates:
        raise ValueError("price dates must be unique")
    if frame.index.tz is not None or not frame.index.equals(frame.index.normalize()):
        raise ValueError("daily research dates must be naive midnight dates")
    dates = pd.to_datetime(list(HOLIDAYS))
    rows = frame.loc[frame.index.isin(dates)]
    removed = []
    for stamp, row in rows.iterrows():
        prices = row[["open", "high", "low", "close"]].to_numpy(dtype=float)
        if (not np.isfinite(prices).all() or (prices <= 0).any()
                or not np.all(prices == prices[0]) or row["volume"] != 0
                or ("turnover" in row and row["turnover"] != 0)):
            raise ValueError(f"holiday row is not an empty flat placeholder: {stamp.date()}")
        removed.append({"date": str(stamp.date()), "row": {str(k): float(v) for k, v in row.items()},
                        "official_source": HOLIDAYS[str(stamp.date())]})
    return frame.loc[~frame.index.isin(dates)].copy(), removed


def verify_repair_snapshot(path: Path) -> dict:
    manifest = json.loads((path / MANIFEST_NAME).read_text())
    identity = manifest["identity"]
    expected_id = _sha(json.dumps(identity, sort_keys=True).encode())
    if manifest["snapshot_id"] != expected_id or path.name != expected_id:
        raise ValueError("repair snapshot identity mismatch")
    if any(manifest[key] != identity[key] for key in EVIDENCE_KEYS):
        raise ValueError("repair snapshot evidence mismatch")
    if (manifest["inserted_rows"] != 0 or manifest["admissible"] is not False
            or manifest["authority"] != "QUARANTINED_RESEARCH_REPAIR"
            or manifest["removed_row_count"] != sum(len(rows) for rows in manifest["removed_rows"].values())
            or manifest["instrument_count"] != len(manifest["outputs"])):
        raise ValueError("invalid repair snapshot claims")
    outputs = manifest["outputs"]
    if set(outputs) != {p.name for p in path.glob("*.parquet")} or set(outputs) != set(identity["inputs"]):
        raise ValueError("repair snapshot instrument set changed")
    for filename, expected in outputs.items():
        if Path(filename).name != filename or _sha((path / filename).read_bytes()) != expected:
            raise ValueError(f"repair snapshot content mismatch: {filename}")
    return manifest


def build_calendar_clean_snapshot(*, prices_path: Path, output_directory: Path) -> Path:
    source = prices_path.resolve()
    destination_root = output_directory.resolve()
    if destination_root == source or source in destination_root.parents:
        raise ValueError("repair output must be outside the source price directory")
    paths = sorted(source.glob("*.parquet"))
    if not paths:
        raise ValueError("source price directory is empty")
    frames, input_hashes, exclusions = {}, {}, {}
    # Validate all proposed exclusions before writing any repaired files.
    for path in paths:
        raw = path.read_bytes()
        cleaned, removed = remove_confirmed_holiday_placeholders(pd.read_parquet(io.BytesIO(raw)))
        frames[path.name] = cleaned
        input_hashes[path.name] = _sha(raw)
        if removed:
            exclusions[path.name] = removed
    encoded = {filename: frame.to_parquet() for filename, frame in frames.items()}
    evidence = {"outputs": {filename: _sha(raw) for filename, raw in encoded.items()},
                "source_directory": str(source), "removed_rows": exclusions,
                "removed_row_count": sum(len(rows) for rows in exclusions.values()),
                "instrument_count": len(encoded), "inserted_rows": 0,
                "authority": "QUARANTINED_RESEARCH_REPAIR", "admissible": False,
                "unresolved": ["missing-session adjustment factors", "historical membership", "corporate-action ledger"]}
    identity = {"recipe": "verified-holiday-placeholder-removal-v2", "inputs": input_hashes,
                "confirmed_holidays": HOLIDAYS,
                "implementation_sha256": _sha(inspect.getsource(remove_confirmed_holiday_placeholders).encode()),
                "pandas_version": pd.__version__, **evidence}
    snapshot_id = _sha(json.dumps(identity, sort_keys=True).encode())
    destination = destination_root / snapshot_id
    if destination.exists():
        verify_repair_snapshot(destination)
        return destination
    manifest = {"snapshot_id": snapshot_id, "identity": identity, **evidence}
    destination_root.mkdir(parents=True, exist_ok=True)
    # Publish only a fully written snapshot; failed writes leave no final directory.
    with TemporaryDirectory(prefix=".repair-", dir=destination_root) as temporary:
        staging = Path(temporary)
        for filename, raw in encoded.items():
            (staging / filename).write_bytes(raw)
        (staging / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        staging.rename(destination)
    verify_repair_snapshot(destination)
    return destination


def _unique_raw_row(frame: pd.DataFrame, *, symbol: str, isin: str):
    rows = frame.loc[frame["isin"] == isin] if isin else frame.loc[frame["symbol"] == symbol]
    if len(rows) != 1:
        return None
    return rows.iloc[0]


def _observed_factors(adjusted: pd.Series, raw: pd.Series):
    raw_prices = raw[["open", "high", "low", "close"]].to_numpy(dtype=float)
    prices = adjusted[["open", "high", "low", "close"]].to_numpy(dtype=float)
    if not np.isfinite(raw_prices).all() or (raw_prices <= 0).any():
        return None
    ratios = prices / raw_prices
    if not np.isfinite(ratios).all() or (ratios <= 0).any() or raw["volume"] <= 0:
        return None
    return {"price_ratios": ratios.tolist(), "volume_ratio": float(adjusted["volume"] / raw["volume"])}


def audit_missing_adjustments(*, prices_path: Path, universe_path: Path,
                              benchmark_path: Path, output_path: Path,
                              raw_store=None) -> dict:
    store = raw_store or QuarantinedRawBhavcopy()
    benchmark = pd.read_parquet(benchmark_path)
    calendar = benchmark.index.sort_values()
    if not isinstance(calendar, pd.DatetimeIndex) or calendar.has_duplicates:
        raise ValueError("benchmark calendar must have unique daily dates")
    universe = pd.read_csv(universe_path).fillna("")
    identities = dict(zip(universe["symbol"], universe["isin"], strict=True))
    frames = {p.stem: pd.read_parquet(p).sort_index() for p in sorted(prices_path.glob("*.parquet"))}
    references, raw_frames, rows = {}, {}, []
    for target_text in MISSING_SESSIONS:
        target = pd.Timestamp(target_text)
        if target not in calendar or not len(calendar[calendar < target]) or not len(calendar[calendar > target]):
            raise ValueError("benchmark does not contain the target and both adjacent sessions")
        before, after = calendar[calendar < target][-1], calendar[calendar > target][0]
        for day in (before, target, after):
            if day not in raw_frames:
                verified = store.verified_session(day.date())
                raw_frames[day] = equities_clean(verified.frame)
                references[str(day.date())] = json.loads(json.dumps(asdict(verified.reference), default=str))
        for symbol, frame in frames.items():
            item = {"symbol": symbol, "session": target_text,
                    "before": str(before.date()), "after": str(after.date()),
                    "exact_date_factor_verified": False, "can_insert": False}
            if frame.empty or target < frame.index.min() or target > frame.index.max():
                item["status"] = "OUTSIDE_OBSERVED_HISTORY"
            elif target in frame.index:
                item["status"] = "ALREADY_PRESENT"
            else:
                isin = str(identities.get(symbol, ""))
                raw_rows = [_unique_raw_row(raw_frames[d], symbol=symbol, isin=isin) for d in (before, target, after)]
                if not isin or any(row is None for row in raw_rows):
                    item["status"] = "IDENTITY_OR_RAW_BAR_UNRESOLVED"
                elif before not in frame.index or after not in frame.index:
                    item["status"] = "ADJACENT_ADJUSTED_BAR_MISSING"
                else:
                    left = _observed_factors(frame.loc[before], raw_rows[0])
                    right = _observed_factors(frame.loc[after], raw_rows[2])
                    item.update({"isin": isin, "raw_target_symbol": str(raw_rows[1]["symbol"]),
                                 "before_factors": left, "after_factors": right})
                    if left is None or right is None:
                        item["status"] = "FACTOR_COMPARISON_UNAVAILABLE"
                    else:
                        price_ratios = left["price_ratios"] + right["price_ratios"]
                        price_spread = max(price_ratios) / min(price_ratios) - 1
                        volumes = [left["volume_ratio"], right["volume_ratio"]]
                        volume_spread = max(volumes) / min(volumes) - 1 if min(volumes) > 0 else None
                        item.update({"relative_price_factor_spread": price_spread,
                                     "relative_volume_factor_spread": volume_spread})
                        stable = price_spread <= 1e-5 and volume_spread is not None and volume_spread <= 1e-5
                        item["status"] = "NEIGHBOURS_AGREE_EXACT_FACTOR_UNVERIFIED" if stable else "NEIGHBOURS_DISAGREE"
            rows.append(item)
    payload = {"version": "missing-session-adjustment-audit-v1", "counts": dict(Counter(row["status"] for row in rows)),
               "rows": rows, "raw_references": references, "relative_comparison_tolerance": 1e-5,
               "inputs": {p.name: _sha(p.read_bytes()) for p in sorted(prices_path.glob("*.parquet"))},
               "universe_sha256": _sha(universe_path.read_bytes()), "benchmark_sha256": _sha(benchmark_path.read_bytes()),
               "authority": "ADJUSTMENT_DIAGNOSTIC_ONLY", "admissible": False,
               "exact_date_factors_verified": 0, "inserted_rows": 0,
               "note": "Current ISIN matching and neighbour agreement are diagnostics, not a historical identity or action certificate."}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prices", type=Path, default=Path("data/prices"))
    parser.add_argument("--output-directory", type=Path, default=Path("data/research/stock-repairs"))
    parser.add_argument("--universe", type=Path, default=Path("data/universe.csv"))
    parser.add_argument("--benchmark", type=Path, default=Path("data/research/benchmarks/nifty500-tri-20260906.parquet"))
    args = parser.parse_args()
    snapshot = build_calendar_clean_snapshot(prices_path=args.prices, output_directory=args.output_directory)
    audit = audit_missing_adjustments(prices_path=snapshot, universe_path=args.universe,
        benchmark_path=args.benchmark, output_path=snapshot / "adjustment_audit.json")
    print(json.dumps({"snapshot": str(snapshot), "removed_rows": verify_repair_snapshot(snapshot)["removed_row_count"],
                      "adjustment_counts": audit["counts"], "inserted_rows": 0, "admissible": False}))


if __name__ == "__main__":
    main()
