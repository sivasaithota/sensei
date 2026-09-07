"""Bounded split-unit evidence for saved trades; no execution or price repair."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import date
from fractions import Fraction
from pathlib import Path


PRICE_ENVELOPE_INR = 0.05


def validate_events(events):
    for event in events:
        date.fromisoformat(event["effective_date"])
        multiplier = event["new_shares_per_old_share"]
        if type(multiplier) is not int or multiplier <= 1:
            raise ValueError("split multiplier must be an integer greater than one")
        for key in ("exchange_symbol", "old_isin", "new_isin"):
            if not isinstance(event[key], str) or not event[key].strip():
                raise ValueError(f"missing split identity: {key}")
        if event["old_isin"] == event["new_isin"] or not event["sources"]:
            raise ValueError("split evidence requires distinct ISINs and primary sources")


def audit_trade(record, events, *, as_of):
    trade, reference = record["trade"], record["current_reference"]
    entry, exit = (date.fromisoformat(trade[key]) for key in ("entry_date", "exit_date"))
    capture_end = date.fromisoformat(as_of)
    if entry > exit or exit > capture_end:
        raise ValueError("trade dates fall outside the frozen capture")
    quantity = trade["quantity"]
    if type(quantity) is not int or quantity <= 0:
        raise ValueError("saved quantity must be a positive integer")
    candidates = [event for event in events
        if event["exchange_symbol"] == reference.get("exchange_symbol", reference["symbol"])]
    if not candidates:
        return {"status": "outside_evidence_ledger"}
    if len(candidates) != 1:
        return {"status": "ambiguous_split_evidence"}
    event = candidates[0]
    effective = date.fromisoformat(event["effective_date"])
    if effective > capture_end or entry >= effective:
        return {"status": "outside_pre_split_scope"}
    if exit >= effective:
        return {"status": "crosses_split_unsupported"}
    if reference["isin"] != event["new_isin"]:
        return {"status": "identity_mismatch"}
    multiplier = event["new_shares_per_old_share"]
    for endpoint in record["endpoints"].values():
        if endpoint["status"] != "matched":
            return {"status": "endpoint_unavailable"}
        identity = endpoint["raw_identity"]
        if identity["symbol"] != event["exchange_symbol"] or identity["isin"] != event["old_isin"]:
            return {"status": "identity_mismatch"}
        raw, kite = endpoint["raw"], endpoint["kite"]
        amounts = [float(frame[key]) for frame in (raw, kite)
            for key in ("open", "high", "low", "close", "volume")]
        if any(not math.isfinite(value) or value <= 0 for value in amounts):
            return {"status": "scaling_unavailable"}
        if (not math.isclose(kite["volume"] / raw["volume"], multiplier, rel_tol=1e-9)
                or any(abs(kite[key] - raw[key] / multiplier) > PRICE_ENVELOPE_INR + 1e-9
                    for key in ("open", "high", "low", "close"))):
            return {"status": "scaling_mismatch"}
    if set(record["endpoints"]) != {"entry_date", "exit_date"}:
        return {"status": "endpoint_unavailable"}
    equivalent = Fraction(quantity, multiplier)
    physical_floor = quantity // multiplier
    return {"status": "fractional_physical_equivalent" if equivalent.denominator != 1 else "integral_physical_equivalent",
        "split": event, "physical_quantity_numerator": equivalent.numerator,
        "physical_quantity_denominator": equivalent.denominator,
        "whole_physical_quantity_floor": physical_floor,
        "adjusted_quantity_floor": physical_floor * multiplier,
        "adjusted_units_removed_by_floor": quantity - physical_floor * multiplier}


def audit_screen(screen, events):
    validate_events(events)
    if screen.get("can_trade") is not False or screen.get("decision") != "DATA_BLOCKED":
        raise ValueError("requires a blocked research screen")
    return [{"source_run_id": record["source_run_id"], "trade_number": record["trade_number"],
        "trade": record["trade"], "snapshot_id": record["snapshot_id"],
        "audit": audit_trade(record, events,
            as_of=screen["snapshots"][record["snapshot_id"]]["identity"]["scope_end"])}
        for record in screen["trades"]]


def run_audit(screen_path, ledger_path, output):
    content = screen_path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != screen_path.parent.name or digest != screen_path.with_name("report.sha256").read_text().strip():
        raise ValueError("held-price screen checksum mismatch")
    screen = json.loads(content)
    for proof in screen["source_proofs"]:
        if hashlib.sha256(Path(proof["proof_path"]).read_bytes()).hexdigest() != proof["proof_sha256"]:
            raise ValueError("held-price source proof changed")
    ledger_content = ledger_path.read_bytes()
    ledger = json.loads(ledger_content)
    note_path = Path(ledger["research_note"])
    if not note_path.is_absolute():
        note_path = ledger_path.parent / note_path
    note_digest = hashlib.sha256(note_path.read_bytes()).hexdigest()
    if note_digest != ledger["research_note_sha256"]:
        raise ValueError("split research note changed")
    result = {"authority": "RESEARCH_ONLY", "decision": "DATA_BLOCKED", "can_trade": False,
        "source_screen_path": str(screen_path), "source_screen_sha256": digest,
        "source_proofs": screen["source_proofs"], "ledger": ledger,
        "ledger_sha256": hashlib.sha256(ledger_content).hexdigest(),
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "price_envelope_inr": PRICE_ENVELOPE_INR,
        "trades": audit_screen(screen, ledger["events"]),
        "limitations": ["Manually transcribed primary evidence, limited to the listed split transitions",
            "Endpoint agreement does not establish complete action history or executable tick prices",
            "Integral equivalent quantities do not certify trades; outside-ledger quantities remain unknown",
            "Floor quantities are diagnostic only: no portfolio, fees, cash, signals or P&L recomputed"]}
    encoded = (json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    result_digest = hashlib.sha256(encoded).hexdigest()
    path = output / result_digest / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != encoded:
        raise ValueError("existing split-unit audit changed")
    path.write_bytes(encoded)
    path.with_name("report.sha256").write_text(result_digest + "\n")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screen", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("data/reports/share-unit-audit"))
    args = parser.parse_args()
    print(run_audit(args.screen, args.ledger, args.output))


if __name__ == "__main__":
    main()
