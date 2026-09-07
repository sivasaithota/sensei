"""Isolated sizing checks for the split audit; never portfolio performance."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path

import pandas as pd

from sensei.backtest.portfolio_campaign import PortfolioCampaignConfig, run_portfolio_campaign


def _pinned_json(path, expected):
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected:
        raise ValueError(f"sizing reproduction input changed: {path.name}")
    return json.loads(content)


def reproduce(audit_path, reports_root, output):
    digest = audit_path.with_name("report.sha256").read_text().strip()
    if digest != audit_path.parent.name:
        raise ValueError("split audit identity mismatch")
    audit = _pinned_json(audit_path, digest)
    if audit.get("can_trade") is not False or audit.get("decision") != "DATA_BLOCKED":
        raise ValueError("requires a blocked split audit")
    screen = _pinned_json(Path(audit["source_screen_path"]), audit["source_screen_sha256"])
    reports = {}
    for item in screen["source_proofs"]:
        proof = _pinned_json(Path(item["proof_path"]), item["proof_sha256"])
        reports[item["source_run_id"]] = _pinned_json(
            reports_root / item["source_run_id"] / "report.json", proof["source_report_sha256"])
    cases, frames = [], {}
    for record in audit["trades"]:
        if record["audit"]["status"] not in {"fractional_physical_equivalent", "integral_physical_equivalent"}:
            continue
        source = reports[record["source_run_id"]]
        trade = record["trade"]
        if source["campaign"]["trades"][record["trade_number"]] != trade:
            raise ValueError("audited trade differs from frozen source")
        symbol = trade["symbol"]
        frame_key = record["snapshot_id"], symbol
        if frame_key not in frames:
            filename = f"{symbol}.parquet"
            content = (Path(source["settings"]["prices_path"]) / filename).read_bytes()
            expected = screen["snapshots"][record["snapshot_id"]]["identity"]["outputs"][filename]
            if hashlib.sha256(content).hexdigest() != expected:
                raise ValueError("sizing reproduction prices changed")
            frames[frame_key] = pd.read_parquet(io.BytesIO(content))
        entry = pd.Timestamp(trade["entry_date"])
        frame = frames[frame_key].loc[:entry]
        if len(frame) < 2 or frame.index[-1] != entry:
            raise ValueError("sizing reproduction lacks entry or predecessor")
        signals = pd.Series(False, index=frame.index)
        signals.iloc[-2] = True
        parameters = source["settings"]["strategy_parameters"]
        config = PortfolioCampaignConfig(**source["campaign"]["config"])
        if not config.liquidate_at_end:
            raise ValueError("sizing reproduction requires final liquidation")
        common = dict(frames={symbol: frame}, strategies={"isolated_entry": parameters}, config=config,
            prepared_signals={("isolated_entry", symbol): signals}, evaluation_start=entry, evaluation_end=entry)
        control = run_portfolio_campaign(**common)
        steps = pd.Series([record["audit"]["split"]["new_shares_per_old_share"]],
            index=pd.DatetimeIndex([entry]), dtype="Int64")
        corrected = run_portfolio_campaign(**common, entry_quantity_steps={symbol: steps},
            quantity_evidence_sha256=digest)
        if len(control.trades) != 1 or control.trades[0].quantity != trade["quantity"]:
            raise ValueError("isolated control does not reproduce saved sizing")
        expected_floor = record["audit"]["adjusted_quantity_floor"]
        corrected_quantity = corrected.trades[0].quantity if corrected.trades else 0
        if corrected_quantity != expected_floor:
            raise ValueError("corrected sizing differs from evidenced floor")
        if control.trades[0].entry_price != trade["entry_price"]:
            raise ValueError("isolated control does not reproduce saved entry price")
        cases.append({"source_run_id": record["source_run_id"], "trade_number": record["trade_number"],
            "symbol": symbol, "entry_date": trade["entry_date"], "entry_price": trade["entry_price"],
            "saved_quantity": trade["quantity"], "corrected_adjusted_quantity": corrected_quantity,
            "physical_quantity": corrected_quantity // int(steps.iloc[0]),
            "control_experiment_id": control.experiment_id, "corrected_experiment_id": corrected.experiment_id,
            "quantity_evidence_sha256": digest, "config": source["campaign"]["config"]})
    result = {"authority": "RESEARCH_ONLY", "decision": "DATA_BLOCKED", "can_trade": False,
        "unit_audit_sha256": digest, "unit_audit_path": str(audit_path), "cases": cases,
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "limitations": ["Forced isolated entries with full initial capital available, not the original portfolio cash path",
            "Same-day liquidation is a sizing harness only; no return or fill-outcome comparison is reported",
            "Two-stock split evidence is insufficient to enable this mode for the complete stock universe"]}
    encoded = (json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    result_digest = hashlib.sha256(encoded).hexdigest()
    path = output / result_digest / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != encoded:
        raise ValueError("existing sizing reproduction changed")
    path.write_bytes(encoded)
    path.with_name("report.sha256").write_text(result_digest + "\n")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit-audit", type=Path, required=True)
    parser.add_argument("--reports-root", type=Path, default=Path("data/reports/stock-development"))
    parser.add_argument("--output", type=Path, default=Path("data/reports/quantity-sizing-reproduction"))
    args = parser.parse_args()
    print(reproduce(args.unit_audit, args.reports_root, args.output))


if __name__ == "__main__":
    main()
