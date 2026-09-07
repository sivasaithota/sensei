"""Read-only, source-pinned diagnostics; append invariance is not data-vintage proof."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import version
import inspect
import json
from pathlib import Path

import pandas as pd

from sensei.research.raw_portfolio import pinned_json, sha
from sensei.research.stock_run import load_run_settings, scope_price_frames, _frame_digest, _signal_identity
from sensei.strategy.selection import SignalRankingPolicy, average_turnover


def checked_signal(frame, signal):
    result = signal(frame.copy()).fillna(False)
    if not isinstance(result, pd.Series) or not result.index.equals(frame.index) or not pd.api.types.is_bool_dtype(result.dtype):
        raise ValueError("signal must return aligned Boolean observations")
    return result.astype(bool)


def audit_prefixes(frame, signal, cutoffs, *, maximum_examples=20):
    """Compare every earlier output, including warmup, at each requested cutoff."""
    full = checked_signal(frame, signal)
    comparisons = cells = mismatches = with_future = 0
    examples = []
    for cutoff in cutoffs:
        if cutoff not in frame.index:
            continue
        prefix = frame.loc[:cutoff]
        observed = checked_signal(prefix, signal)
        expected = full.loc[prefix.index]
        different = observed != expected
        comparisons += 1
        cells += len(prefix)
        with_future += int(cutoff < frame.index[-1])
        mismatches += int(different.sum())
        for stamp in different[different].index[:max(0, maximum_examples - len(examples))]:
            examples.append({"cutoff": str(cutoff.date()), "signal_date": str(stamp.date()),
                "prefix": bool(observed.loc[stamp]), "full": bool(expected.loc[stamp])})
    return {"prefix_comparisons": comparisons, "comparisons_with_later_rows": with_future,
        "boolean_cells_compared": cells, "mismatched_cells": mismatches, "examples": examples}


def score(frame, policy, parameters):
    return asdict(policy.score(frame=frame, average_turnover_inr=average_turnover(frame),
        stop_pct=parameters["stop_pct"], target_pct=parameters["target_pct"], as_of=frame.index[-1].date()))


def audit_uniform_units(frame, signal, policy, parameters, multipliers):
    """Exact reciprocal scaling, without rounding; not a vendor factor reconstruction."""
    original_signal = checked_signal(frame, signal)
    original_score = score(frame, policy, parameters)
    results = []
    for multiplier in multipliers:
        if type(multiplier) is not int or multiplier <= 0:
            raise ValueError("unit multiplier must be a positive integer")
        transformed = frame.copy()
        for key in ("open", "high", "low", "close"):
            transformed[key] = transformed[key].astype(float) * multiplier
        transformed["volume"] = transformed["volume"].astype(float) / multiplier
        # A reported turnover column, if present, is currency turnover and stays unchanged.
        changed = checked_signal(transformed, signal) != original_signal
        new_score = score(transformed, policy, parameters)
        results.append({"multiplier": multiplier, "signal_changes": int(changed.sum()),
            "changed_dates": [str(d.date()) for d in changed[changed].index],
            "score_component_absolute_differences": {k: abs(new_score[k] - value) for k, value in original_score.items()}})
    return results


def negative_control():
    frame = pd.DataFrame({"close": [1., 2., 3., 9.]}, index=pd.bdate_range("2024-01-01", periods=4))
    causal = audit_prefixes(frame, lambda f: f.close > f.close.shift(1), frame.index)
    leaking = audit_prefixes(frame, lambda f: f.close > f.close.mean(), frame.index)
    if causal["mismatched_cells"] or not leaking["mismatched_cells"]:
        raise ValueError("prefix audit controls failed")
    return {"causal_mismatches": causal["mismatched_cells"], "deliberate_future_mean_mismatches": leaking["mismatched_cells"]}


def run_audit(plan_path, output):
    from sensei.backtest import playbook, strategies
    from sensei.strategy import selection
    from sensei.data.kite_validation import verify_priority_snapshot
    from sensei.research.exposure import record_development_frames

    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    source_path = (plan_path.parent / plan["source_report_path"]).resolve()
    source = pinned_json(source_path, plan["source_report_sha256"])
    source_manifest = pinned_json(source_path.with_name("manifest.json"), plan["source_manifest_sha256"])
    settings = load_run_settings(plan_path.parent / "stock-research-demerger-sensitivity.json")
    if source["comparisons"][0]["settings"] != settings.identity_payload():
        raise ValueError("source comparison settings changed")
    snapshot = verify_priority_snapshot(settings.prices_path)
    if sha(json.dumps(snapshot, sort_keys=True).encode()) != source_manifest["identity"]["snapshot_manifest_sha256"]:
        raise ValueError("source snapshot changed")
    original = {p.stem: pd.read_parquet(p) for p in sorted(settings.prices_path.glob("*.parquet"))}
    frames = scope_price_frames(original, start=settings.start, end=settings.end, warmup_sessions=settings.warmup_sessions)
    control_ref = source_manifest["identity"]["source_controls"]["sources"][0]
    root = Path(__file__).resolve().parents[3]
    control = pinned_json(root / control_ref["report_path"], control_ref["report_sha256"])
    control_manifest = pinned_json((root / control_ref["report_path"]).with_name("manifest.json"), control_ref["manifest_sha256"])
    frozen = control_manifest["identity"]
    policy = SignalRankingPolicy()
    spec = playbook.all_strategies()[settings.strategy_name]
    runtime = {name: version(name) for name in ("numpy", "pandas", "pydantic")}
    checks = {"input_frames": {s: _frame_digest(f) for s, f in sorted(frames.items())},
        "signal": _signal_identity(spec["fn"]), "effective_selection_policy": asdict(policy), "runtime": runtime}
    if any(value != frozen[key] for key, value in checks.items()) or control["settings"] != settings.identity_payload():
        raise ValueError("frozen signal, ranking, runtime or frames changed")
    cutoffs = pd.DatetimeIndex([p["session"] for p in source["comparisons"][0]["campaign"]["equity_curve"]])
    identity = {"plan": plan, "plan_sha256": sha(plan_bytes), "source_run_id": source["run_id"],
        "checked_inputs": checks, "cutoffs": [str(d.date()) for d in cutoffs],
        "implementation_sha256": sha(Path(__file__).read_bytes() + inspect.getsource(selection).encode() + inspect.getsource(strategies).encode()),
        "scope": "fixed-data append test and exact uniform-unit metamorphic diagnostic; no historical-vintage attestation"}
    run_id = sha(json.dumps(identity, sort_keys=True).encode())
    destination = output / run_id
    destination.mkdir(parents=True, exist_ok=True)
    manifest = destination / "manifest.json"
    if manifest.exists():
        if json.loads(manifest.read_text())["identity"] != identity:
            raise ValueError("audit identity mismatch")
    else:
        manifest.write_text(json.dumps({"run_id": run_id, "recorded_before_audit": datetime.now(timezone.utc).isoformat(), "identity": identity}, indent=2) + "\n")
    path = destination / "report.json"
    if path.exists():
        pinned_json(path, path.with_name("report.sha256").read_text().strip())
        return path
    controls = negative_control()
    record_development_frames(frames, campaign_id="signal-causality-v1")
    results = []
    for number, (symbol, frame) in enumerate(sorted(frames.items()), 1):
        result = {"symbol": symbol, "frame_rows": len(frame),
            "prefix": audit_prefixes(frame, spec["fn"], cutoffs, maximum_examples=plan["maximum_examples"]),
            "uniform_units": audit_uniform_units(frame, spec["fn"], policy, settings.strategy_parameters, plan["uniform_unit_multipliers"])}
        results.append(result)
        if number % 25 == 0:
            print(f"Audited {number}/{len(frames)} instruments", flush=True)
    totals = {key: sum(r["prefix"][key] for r in results) for key in
        ("prefix_comparisons", "comparisons_with_later_rows", "boolean_cells_compared", "mismatched_cells")}
    units = [u for r in results for u in r["uniform_units"]]
    payload = {"run_id": run_id, "controls": controls, "instruments": len(results), "prefix_totals": totals,
        "uniform_unit_signal_changes": sum(u["signal_changes"] for u in units),
        "uniform_unit_scores_outside_tolerance": sum(any(v > plan["score_absolute_tolerance"] for v in u["score_component_absolute_differences"].values()) for u in units),
        "maximum_score_component_difference": max(v for u in units for v in u["score_component_absolute_differences"].values()),
        "results": results, "decision": "DATA_BLOCKED", "authority": "RESEARCH_ONLY", "can_trade": False,
        "limitations": ["Fixed snapshot prefixes cannot establish historical adjustment vintages or announcement availability",
            "Current membership remains survivorship-biased", "Uniform reciprocal scaling excludes rounding and nonuniform/action-crossing revisions",
            "Ranking scores tested at final frame dates under uniform unit changes; correlation and portfolio paths not tested by this audit",
            "No strategy returns, new strategy selection or live-readiness claim"]}
    content = (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    path.write_bytes(content)
    path.with_name("report.sha256").write_text(sha(content) + "\n")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=Path("config/signal-causality-audit-v1.json"))
    parser.add_argument("--output", type=Path, default=Path("data/reports/signal-causality"))
    args = parser.parse_args()
    print(run_audit(args.plan, args.output))


if __name__ == "__main__":
    main()
