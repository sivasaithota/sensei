"""Observed vendor scaling beside primary action classifications, not unit maps."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


ACTION_CLASSES = {"split", "bonus", "split_and_bonus", "demerger", "unresolved"}


def summarize(screen, classifications):
    if screen.get("can_trade") is not False or screen.get("decision") != "DATA_BLOCKED":
        raise ValueError("requires a blocked held-price screen")
    symbols = {}
    for record in screen["trades"]:
        symbol = record["trade"]["symbol"]
        row = symbols.setdefault(symbol, {"trade_records": [], "endpoint_statuses": Counter(),
            "non_unit_endpoints": [], "unknown_volume_endpoint_count": 0})
        row["trade_records"].append({"source_run_id": record["source_run_id"],
            "trade_number": record["trade_number"]})
        if set(record["endpoints"]) != {"entry_date", "exit_date"}:
            raise ValueError("source trade must retain both endpoint records")
        for field, endpoint in record["endpoints"].items():
            row["endpoint_statuses"][endpoint["status"]] += 1
            ratio = endpoint.get("kite_over_raw_volume")
            if ratio is None:
                row["unknown_volume_endpoint_count"] += 1
            if endpoint["status"] == "matched" and ratio is not None and abs(ratio - 1) > .01:
                row["non_unit_endpoints"].append({"source_run_id": record["source_run_id"],
                    "trade_number": record["trade_number"], "endpoint": field,
                    "date": record["trade"][field], "volume_ratio": ratio,
                    "raw_identity": endpoint["raw_identity"],
                    "current_reference": record["current_reference"]})
    flagged = {symbol for symbol, row in symbols.items() if row["non_unit_endpoints"]}
    if set(classifications) != flagged:
        raise ValueError("classification registry must match exactly the flagged symbol set")
    class_symbols, class_endpoints = Counter(), Counter()
    for symbol, row in symbols.items():
        row["endpoint_statuses"] = dict(row["endpoint_statuses"])
        observations = row["non_unit_endpoints"]
        row["non_unit_endpoint_count"] = len(observations)
        row["classification"] = classifications.get(symbol)
        if observations:
            classification = row["classification"]
            kind = classification["kind"]
            if kind not in ACTION_CLASSES or not classification["note_ids"]:
                raise ValueError("invalid action classification or missing evidence notes")
            class_symbols[kind] += 1
            class_endpoints[kind] += len(observations)
            row["observed_volume_ratio_range"] = [min(o["volume_ratio"] for o in observations),
                max(o["volume_ratio"] for o in observations)]
            row["affected_endpoint_date_range"] = [min(o["date"] for o in observations),
                max(o["date"] for o in observations)]
    statuses = Counter()
    for row in symbols.values():
        statuses.update(row["endpoint_statuses"])
    return {"symbols": symbols, "trade_records": len(screen["trades"]),
        "endpoint_statuses": dict(statuses), "flagged_symbols": len(flagged),
        "unknown_volume_endpoint_count": sum(row["unknown_volume_endpoint_count"] for row in symbols.values()),
        "class_symbol_counts": dict(class_symbols), "class_endpoint_counts": dict(class_endpoints)}


def build_inventory(screen_path, registry_path, output):
    content = screen_path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != screen_path.parent.name or digest != screen_path.with_name("report.sha256").read_text().strip():
        raise ValueError("held-price screen checksum mismatch")
    screen = json.loads(content)
    for proof in screen["source_proofs"]:
        if hashlib.sha256(Path(proof["proof_path"]).read_bytes()).hexdigest() != proof["proof_sha256"]:
            raise ValueError("held-price source proof changed")
    registry_content = registry_path.read_bytes()
    registry = json.loads(registry_content)
    for note in registry["notes"].values():
        path = registry_path.parent / note["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != note["sha256"]:
            raise ValueError("classification research note changed")
    for classification in registry["symbols"].values():
        if set(classification["note_ids"]) - set(registry["notes"]):
            raise ValueError("classification refers to unknown research note")
    result = {"authority": "RESEARCH_ONLY", "decision": "DATA_BLOCKED", "can_trade": False,
        "source_screen_path": str(screen_path), "source_screen_sha256": digest,
        "source_proofs": screen["source_proofs"], "registry": registry,
        "registry_sha256": hashlib.sha256(registry_content).hexdigest(),
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "inventory": summarize(screen, registry["symbols"]),
        "limitations": ["Primary classification establishes documented actions, not cumulative vendor transformation",
            "Non-unit ratios are observations, not split factors or entitlement ratios",
            "Unflagged symbols are unclassified; a ratio of one is not a no-actions certificate",
            "No prices, trades, cash, quantities or execution authority changed"]}
    encoded = (json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    result_digest = hashlib.sha256(encoded).hexdigest()
    path = output / result_digest / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != encoded:
        raise ValueError("existing action inventory changed")
    path.write_bytes(encoded)
    path.with_name("report.sha256").write_text(result_digest + "\n")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screen", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("data/reports/corporate-action-inventory"))
    args = parser.parse_args()
    print(build_inventory(args.screen, args.registry, args.output))


if __name__ == "__main__":
    main()
