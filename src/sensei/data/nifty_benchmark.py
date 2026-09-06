"""Capture the official Nifty 500 gross total-return series for research.

Request format is taken from NSE Indices' historical-data page JavaScript.
Raw responses and request metadata are retained; no missing dates are filled.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

SOURCE_PAGE = "https://www.niftyindices.com/reports/historical-data"
SOURCE_SCRIPT = "https://liveindexsa.niftyindices.com/assets/js/IISLComponet.js"
ENDPOINT = "https://www.niftyindices.com/BackPage/getTotalReturnIndexString"


def parse_nifty500_tri(raw: bytes, *, start: date, end: date) -> pd.DataFrame:
    records = json.loads(raw)
    if not isinstance(records, list) or not records:
        raise ValueError("benchmark response must contain rows")
    if any(str(row.get("Index Name", "")).strip().upper() != "NIFTY 500" for row in records):
        raise ValueError("benchmark index identity mismatch")
    frame = pd.DataFrame(records)
    dates = pd.to_datetime(frame["Date"], format="%d %b %Y", errors="raise")
    levels = pd.to_numeric(frame["TotalReturnsIndex"], errors="raise").to_numpy(dtype=float)
    if dates.duplicated().any() or not np.isfinite(levels).all() or (levels <= 0).any():
        raise ValueError("invalid benchmark dates or levels")
    if any(day < start or day > end for day in dates.dt.date):
        raise ValueError("benchmark rows outside requested interval")
    result = pd.DataFrame({"close": levels}, index=pd.DatetimeIndex(dates, name="date"))
    return result.sort_index()


def capture_nifty500_tri(*, start: date, end: date, destination: Path) -> dict:
    if start > end or end > datetime.now(timezone.utc).date():
        raise ValueError("invalid benchmark request interval")
    if destination.exists() or destination.with_suffix(".manifest.json").exists():
        raise FileExistsError("benchmark output already exists; select a new capture path")
    root = destination.parent / "raw"
    root.mkdir(parents=True, exist_ok=True)
    pieces, requests = [], []
    with httpx.Client(timeout=30, headers={"User-Agent": "Mozilla/5.0", "Referer": SOURCE_PAGE}) as client:
        cursor = start
        while cursor <= end:
            last = min(end, cursor + timedelta(days=364))
            query = {"name": "NIFTY 500", "indexName": "NIFTY 500",
                     "startDate": cursor.strftime("%d-%b-%Y"), "endDate": last.strftime("%d-%b-%Y")}
            response = client.post(ENDPOINT, json={"cinfo": json.dumps(query)})
            response.raise_for_status()
            parsed = parse_nifty500_tri(response.content, start=cursor, end=last)
            digest = hashlib.sha256(response.content).hexdigest()
            raw_path = root / f"nifty500-tri-{digest}.json"
            raw_path.write_bytes(response.content)
            requests.append({"query": query, "sha256": digest, "raw_file": raw_path.name,
                             "rows": len(parsed), "retrieved_at": datetime.now(timezone.utc).isoformat()})
            pieces.append(parsed)
            cursor = last + timedelta(days=1)
    frame = pd.concat(pieces).sort_index()
    if frame.index.has_duplicates:
        raise ValueError("duplicate benchmark sessions across responses")
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(destination)
    manifest = {"version": "nifty500-gross-tri-capture-v1", "name": "Nifty 500 gross total return",
                "source_page": SOURCE_PAGE, "source_script": SOURCE_SCRIPT, "endpoint": ENDPOINT,
                "requests": requests, "rows": len(frame), "first": str(frame.index[0].date()),
                "last": str(frame.index[-1].date()), "requested_start": start.isoformat(),
                "requested_end": end.isoformat(), "parquet_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                "authority": "RESEARCH_BENCHMARK_ONLY", "missing_dates_filled": False}
    destination.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = capture_nifty500_tri(start=args.start, end=args.end, destination=args.output)
    print(json.dumps({key: manifest[key] for key in ("rows", "first", "last", "authority")}))


if __name__ == "__main__":
    main()
