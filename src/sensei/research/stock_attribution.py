"""Descriptive attribution of frozen stock runs; never strategy selection."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from sensei.data.kite_validation import verify_priority_snapshot
from sensei.research.stock_run import _frame_digest, scope_price_frames


def pre_entry_atr(frame, entry, calendar):
    """Simple ATR14 on exactly 15 benchmark sessions strictly before entry."""
    expected = calendar[calendar < pd.Timestamp(entry)][-15:]
    if len(expected) != 15:
        return None
    prior = frame.reindex(expected)[["high", "low", "close"]]
    if not np.isfinite(prior.to_numpy(dtype=float)).all():
        return None
    ranges = pd.concat((prior.high - prior.low,
        (prior.high - prior.close.shift()).abs(),
        (prior.low - prior.close.shift()).abs()), axis=1).max(axis=1).iloc[1:]
    value = float(ranges.mean())
    return value if value > 0 else None


def volatility_bin(ratio):
    if ratio is None:
        return "unknown"
    if ratio < 1:
        return "below_1_atr"
    return "1_to_below_2_atr" if ratio < 2 else "at_least_2_atr"


def attribute_trades(campaign, frames, calendar, *, stop_pct):
    if campaign["open_positions"]:
        raise ValueError("attribution requires all holdings to be closed")
    if not np.isfinite(stop_pct) or not 0 < stop_pct < 100:
        raise ValueError("invalid initial stop percentage")
    if calendar.has_duplicates or not calendar.is_monotonic_increasing:
        raise ValueError("benchmark calendar must be ordered and unique")
    rows = []
    for trade in campaign["trades"]:
        values = [trade[k] for k in ("gross_pnl", "costs", "net_pnl", "entry_price")]
        if not np.isfinite(values).all():
            raise ValueError("nonfinite trade amounts")
        if abs(trade["gross_pnl"] - trade["costs"] - trade["net_pnl"]) > .015001:
            raise ValueError("trade P&L does not reconcile")
        atr = pre_entry_atr(frames[trade["symbol"]], trade["entry_date"], calendar)
        ratio = trade["entry_price"] * stop_pct / 100 / atr if atr is not None else None
        rows.append({**trade, "exit_year": str(pd.Timestamp(trade["exit_date"]).year),
            "pre_entry_atr14": atr, "stop_atr_ratio": ratio, "stop_atr_bin": volatility_bin(ratio)})
    residual = float(campaign["net_pnl"] - sum(t["net_pnl"] for t in rows))
    tolerance = .005 * len(rows) + .01
    if not np.isfinite(residual) or abs(residual) > tolerance:
        raise ValueError("campaign P&L does not reconcile to rounded trades")
    groups = {}
    for dimension in ("exit_year", "symbol", "exit_reason", "stop_atr_bin"):
        groups[dimension] = {}
        for key in sorted({row[dimension] for row in rows}):
            members = [row for row in rows if row[dimension] == key]
            groups[dimension][key] = {"trades": len(members),
                **{field: round(sum(t[field] for t in members), 2) for field in ("gross_pnl", "costs", "net_pnl")},
                "losing_trades": sum(t["net_pnl"] < 0 for t in members),
                "absolute_net_losses": round(-sum(min(0, t["net_pnl"]) for t in members), 2)}
    return {"groups": groups, "trades": rows, "pnl_rounding_residual": round(residual, 8),
        "pnl_rounding_tolerance": tolerance, "unknown_volatility_trades": sum(t["pre_entry_atr14"] is None for t in rows)}


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def diagnose_report(report_path: Path, output: Path) -> Path:
    report_hash = _sha(report_path)
    if report_path.with_name("report.sha256").read_text().strip() != report_hash:
        raise ValueError("source report checksum mismatch")
    report = json.loads(report_path.read_text())
    manifest_path = report_path.with_name("manifest.json")
    manifest = json.loads(manifest_path.read_text())
    identity = manifest["identity"]
    run_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    if run_id != report_path.parent.name or run_id != manifest["run_id"] or run_id != report["run_id"]:
        raise ValueError("source manifest run identity mismatch")
    settings = report["settings"]
    if settings != identity["settings"]:
        raise ValueError("source settings mismatch")
    if report.get("can_trade") is not False or "campaign" not in report or report.get("simulation_blockers"):
        raise ValueError("requires a completed research-only simulation")
    if settings.get("snapshot_type") != "kite_development":
        raise ValueError("diagnostic requires the verified Kite development snapshot")
    prices = Path(settings["prices_path"])
    if verify_priority_snapshot(prices) != identity["kite_manifest"]:
        raise ValueError("source snapshot mismatch")
    frames = scope_price_frames({p.stem: pd.read_parquet(p) for p in sorted(prices.glob("*.parquet"))},
        start=date.fromisoformat(settings["start"]), end=date.fromisoformat(settings["end"]),
        warmup_sessions=settings["warmup_sessions"])
    if {symbol: _frame_digest(frame) for symbol, frame in frames.items()} != identity["input_frames"]:
        raise ValueError("source frame digests mismatch")
    benchmark = Path(settings["benchmark_path"])
    if _sha(benchmark) != identity["benchmark_sha256"]:
        raise ValueError("source benchmark checksum mismatch")
    calendar = pd.read_parquet(benchmark).index
    result = {"authority": "RESEARCH_ONLY", "decision": "DATA_BLOCKED", "can_trade": False,
        "phase": "DESCRIPTIVE_REUSED_DEVELOPMENT", "source_run_id": run_id,
        "source_report_sha256": report_hash, "source_manifest_sha256": _sha(manifest_path),
        "implementation_sha256": _sha(Path(__file__)),
        "definitions": {"atr": "simple mean true range of 14 complete benchmark sessions strictly before entry",
            "year": "exit-year realized trade P&L, not annual portfolio return",
            "limitations": "Adjusted-chart volatility; historical membership and shareholder accounting remain unresolved. No causal benefit of a wider stop is established."},
        "attribution": attribute_trades(report["campaign"], frames, calendar,
            stop_pct=settings["strategy_parameters"]["stop_pct"])}
    content = (json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    digest = hashlib.sha256(content).hexdigest()
    path = output / digest / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != content:
        raise ValueError("existing attribution artifact was modified")
    path.write_bytes(content)
    path.with_name("report.sha256").write_text(digest + "\n")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("data/reports/stock-attribution"))
    args = parser.parse_args()
    print(diagnose_report(args.report, args.output))


if __name__ == "__main__":
    main()
