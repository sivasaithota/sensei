"""Local raw/Kite endpoint evidence; never a corporate-action adjustment ledger."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pandas as pd

from sensei.data.bhavcopy import QuarantinedRawBhavcopy
from sensei.research.stock_attribution import diagnose_report


def match_endpoint(raw, kite, reference):
    exchange_symbol = reference.get("exchange_symbol", reference["symbol"])
    candidates = raw.loc[(raw.instrument_class == "equity") &
        ((raw.symbol == exchange_symbol) | (raw["isin"] == reference["isin"]))]
    if len(candidates) != 1:
        return {"status": "missing_candidate" if candidates.empty else "ambiguous_candidates",
            "candidates": candidates[["symbol", "series", "isin", "ok"]].to_dict("records")}
    row = candidates.iloc[0]
    observation = {"status": "matched" if bool(row.ok) else "invalid_raw_row",
        "raw_identity": {key: str(row[key]) for key in ("symbol", "series", "isin")},
        "identity_status": "same_current_reference_isin" if row["isin"] == reference["isin"] else "different_isin_unverified",
        "series_matches_current_reference": bool(row.series == reference["series"])}
    if not bool(row.ok):
        return observation
    observation["raw"] = {key: float(row[key]) for key in ("open", "high", "low", "close", "volume")}
    observation["kite"] = {key: float(kite[key]) for key in ("open", "high", "low", "close", "volume")}
    observation["kite_over_raw_price"] = {key: float(kite[key] / row[key]) for key in ("open", "high", "low", "close")}
    observation["kite_over_raw_volume"] = float(kite["volume"] / row.volume) if row.volume > 0 else None
    return observation


def screen_reports(paths, output):
    output = Path(output)
    reports, snapshots, frames, proofs = [], {}, {}, []
    for path in paths:
        proof_path = diagnose_report(path, output / "source-verification")
        proof = json.loads(proof_path.read_text())
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != proof["source_report_sha256"]:
            raise ValueError("source changed after verification")
        report = json.loads(content)
        manifest_content = path.with_name("manifest.json").read_bytes()
        if hashlib.sha256(manifest_content).hexdigest() != proof["source_manifest_sha256"]:
            raise ValueError("source manifest changed after verification")
        manifest = json.loads(manifest_content)
        snapshot = manifest["identity"]["kite_manifest"]
        key = snapshot["snapshot_id"]
        snapshots[key] = snapshot
        reports.append((report, key))
        proofs.append({"source_run_id": report["run_id"], "proof_path": str(proof_path),
            "proof_sha256": hashlib.sha256(proof_path.read_bytes()).hexdigest()})
        for trade in report["campaign"]["trades"]:
            symbol = trade["symbol"]
            if (key, symbol) not in frames:
                filename = f"{symbol}.parquet"
                frame_content = (Path(report["settings"]["prices_path"]) / filename).read_bytes()
                if hashlib.sha256(frame_content).hexdigest() != snapshot["identity"]["outputs"][filename]:
                    raise ValueError("source prices changed after verification")
                frames[key, symbol] = pd.read_parquet(io.BytesIO(frame_content))
    requested = {(key, t["symbol"], t[field]) for report, key in reports
        for t in report["campaign"]["trades"] for field in ("entry_date", "exit_date")}
    raw_store = QuarantinedRawBhavcopy()
    available = set(raw_store.sessions())
    receipts, observations = {}, {}
    for day in sorted({value[2] for value in requested}):
        keys = sorted(k for k in requested if k[2] == day)
        if date.fromisoformat(day) not in available:
            for key in keys:
                observations[key] = {"status": "raw_session_not_captured"}
            continue
        verified = raw_store.verified_session(date.fromisoformat(day))
        raw = verified.frame
        receipts[day] = json.loads(json.dumps(asdict(verified.reference), default=str))
        for key, symbol, stamp in keys:
            reference = snapshots[key]["identity"]["selection"][symbol]
            observations[key, symbol, stamp] = match_endpoint(raw, frames[key, symbol].loc[stamp], reference)
    trades = []
    for report, key in reports:
        for number, trade in enumerate(report["campaign"]["trades"]):
            endpoints = {field: observations[key, trade["symbol"], trade[field]] for field in ("entry_date", "exit_date")}
            entry, exit = (endpoints[k].get("kite_over_raw_volume") for k in ("entry_date", "exit_date"))
            change = entry / exit if entry is not None and exit is not None and exit > 0 else None
            trades.append({"source_run_id": report["run_id"], "trade_number": number, "trade": trade,
                "snapshot_id": key, "current_reference": snapshots[key]["identity"]["selection"][trade["symbol"]],
                "endpoints": endpoints, "entry_over_exit_volume_ratio": change,
                "volume_scaling_change_over_1pct": abs(change - 1) > .01 if change is not None else None})
    result = {"authority": "RESEARCH_ONLY", "decision": "DATA_BLOCKED", "can_trade": False,
        "source_proofs": proofs, "snapshots": snapshots, "raw_receipts": receipts, "trades": trades,
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "limitations": ["Endpoint screen only; no complete event coverage or historical identity certification",
            "Volume ratio changes are screening observations, not confirmed splits or bonuses",
            "Price ratios do not establish cash-dividend conventions or repair factors",
            "No missing dates fetched, prices changed, cash credited or securities dropped"]}
    content = (json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    digest = hashlib.sha256(content).hexdigest()
    path = output / digest / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != content:
        raise ValueError("existing held-price screen was modified")
    path.write_bytes(content)
    path.with_name("report.sha256").write_text(digest + "\n")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, default=Path("data/reports/held-price-screen"))
    args = parser.parse_args()
    print(screen_reports(args.report, args.output))


if __name__ == "__main__":
    main()
