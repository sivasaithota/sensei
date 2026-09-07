"""Pinned raw-price accounting comparison of already frozen development controls."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
import re
from importlib.metadata import version
from urllib.parse import parse_qs, urlparse

import pandas as pd

from sensei.backtest.raw_accounting import RawAccounting, RawAction
from sensei.backtest.portfolio_campaign import run_portfolio_campaign
from sensei.data.bhavcopy import QuarantinedRawBhavcopy
from sensei.data.kite_validation import verify_priority_snapshot
from sensei.research.stock_run import load_run_settings, scope_price_frames, _frame_digest, _signal_identity


ROOT = Path(__file__).resolve().parents[3]
ACTION_MANIFEST = ROOT / "data/reports/portfolio-action-evidence/manifest.json"
SOURCE_CONTROLS = ROOT / "config/raw-portfolio-source-controls-v1.json"


def sha(content):
    return hashlib.sha256(content).hexdigest()


def pinned_json(path, digest):
    content = Path(path).read_bytes()
    if sha(content) != digest:
        raise ValueError(f"source changed: {path}")
    return json.loads(content)


def load_actions(path):
    """Use the partition union, retaining the known whole-year discrepancy."""
    manifest_bytes = path.read_bytes()
    manifest = json.loads(manifest_bytes)
    rows = []
    ranges = []
    for partition in manifest["partition_validation"]:
        for capture in partition["captures"]:
            url = urlparse(capture["request_url"])
            expected = {"index": ["equities"], "from_date": [capture["requested_from_date"]],
                "to_date": [capture["requested_to_date"]]}
            if capture["http_status"] != 200 or url.hostname != "www.nseindia.com" or (
                    url.path != "/api/corporates-corporateActions" or parse_qs(url.query) != expected):
                raise ValueError("unexpected corporate action request scope")
            records = pinned_json(ROOT / capture["body_path"], capture["body_sha256"])
            if not records or len(records) != capture["record_count"]:
                raise ValueError("action response count mismatch")
            start = pd.to_datetime(capture["requested_from_date"], format="%d-%m-%Y")
            end = pd.to_datetime(capture["requested_to_date"], format="%d-%m-%Y")
            ranges.append((start, end))
            for row in records:
                stamp = pd.to_datetime(row["exDate"], format="%d-%b-%Y")
                if not start <= stamp <= end:
                    raise ValueError("corporate action outside requested dates")
                rows.append({**row, "date": stamp, "source_id": sha(json.dumps(row, sort_keys=True).encode())})
    ranges.sort()
    if ranges[0][0] != pd.Timestamp("2024-01-01") or ranges[-1][1] != pd.Timestamp("2026-09-04") or any(
            b[0] != a[1] + pd.Timedelta(days=1) for a, b in zip(ranges, ranges[1:])):
        raise ValueError("action captures must partition the entire accounting period")
    if len({r["source_id"] for r in rows}) != len(rows):
        raise ValueError("duplicate corporate action source rows")
    return rows, {"path": str(path), "sha256": sha(manifest_bytes), "manifest": manifest}


def action_treatment(row):
    subject = row["subject"].strip()
    if row["series"] != "EQ":
        return "unsupported", 0.0
    if subject in {"Annual General Meeting", "Extra Ordinary General Meeting"}:
        return "no_accounting", 0.0
    if row["symbol"] == "ZYDUSLIFE" and row["date"] == pd.Timestamp("2024-02-23") and subject == "Buy Back":
        return "no_accounting", 0.0  # voluntary tender; source pinned in policy note
    cleaned = re.sub(r"Annual General Meeting\s*/\s*", "", subject, flags=re.I)
    amounts = re.findall(r"(?:(?:Interim|Final|Special)\s+)?Dividend\s*-\s*R(?:s|e)\.?\s*([\d.]+)\s*Per\s+Sh(?:are)?", cleaned, flags=re.I)
    remainder = re.sub(r"(?:(?:Interim|Final|Special)\s+)?Dividend\s*-\s*R(?:s|e)\.?\s*[\d.]+\s*Per\s+Sh(?:are)?", "", cleaned, flags=re.I)
    if amounts and not remainder.strip(" /&,+"):
        return "dividend", sum(float(a) for a in amounts)
    return "unsupported", 0.0


def tick_reference(session, calendar):
    if session < pd.Timestamp("2024-06-10"):
        return None
    if pd.Timestamp("2025-04-15") <= session < pd.Timestamp("2025-05-01"):
        return pd.Timestamp("2025-03-28")
    before = calendar[calendar < session.replace(day=1)]
    return before[-1] if len(before) else pd.NaT


def tick_from_reference(session, close):
    if session < pd.Timestamp("2024-06-10"):
        return 5
    if not pd.notna(close) or close <= 0:
        return pd.NA
    if close < 250:
        return 1
    if session < pd.Timestamp("2025-04-15") or close <= 1000:
        return 5
    if close <= 5000:
        return 10
    if close <= 10000:
        return 50
    if close <= 20000:
        return 100
    return 500


def expected_isin(reference, splits, stamp):
    expected = reference["isin"]
    for event in sorted(splits, key=lambda x: x["effective_date"], reverse=True):
        if event["exchange_symbol"] == reference["exchange_symbol"] and stamp < pd.Timestamp(event["effective_date"]):
            if expected != event["new_isin"]:
                raise ValueError("split identity chain does not reach current security")
            expected = event["old_isin"]
    return expected


def identity_matches(row, reference, splits, stamp):
    return row["isin"] == expected_isin(reference, splits, stamp) and row["series"] in {"EQ", "BE"} and bool(row["ok"])


def merge_candidate_rows(symbol_matches, isin_matches):
    """Union two lookups by source row number, never by security identity.

    Two conflicting rows for the same security remain two ambiguous candidates.
    Only the identical source row found through both lookups is deduplicated.
    """
    return dict(symbol_matches + isin_matches)


def build_inputs(selection, calendar, *, start, end):
    splits, documents = [], {}
    for filename in ("stock-split-evidence-v1.json", "stock-split-evidence-additional-v1.json",
                     "stock-split-identity-pgel-v1.json", "stock-split-identity-remaining-v1.json"):
        path = ROOT / "config" / filename
        content = path.read_bytes()
        ledger = json.loads(content)
        note = (path.parent / ledger["research_note"]).resolve()
        if sha(note.read_bytes()) != ledger["research_note_sha256"]:
            raise ValueError("split evidence note changed")
        documents[str(path)] = sha(content)
        documents[str(note)] = sha(note.read_bytes())
        splits.extend(ledger["events"])
    # These ledgers determine dated ISIN only. No split or bonus ratio is used
    # for holdings; an unsupported held entitlement still blocks the whole run.
    for name in ("raw-portfolio-accounting-policy-2026-09-07.md", "nse-equity-tick-rules-2026-09-07.md"):
        path = ROOT / "docs/research" / name
        documents[str(path)] = sha(path.read_bytes())
    actions, action_evidence = load_actions(ACTION_MANIFEST)
    expected = calendar[(calendar >= start) & (calendar <= end)]
    store = QuarantinedRawBhavcopy()
    available = set(store.sessions())
    missing = [str(d.date()) for d in expected if d.date() not in available]
    if missing:
        raise ValueError(f"raw sessions missing: {missing}")
    receipts, collected, coverage = {}, defaultdict(list), Counter()
    for number, stamp in enumerate(expected):
        verified = store.verified_session(stamp.date())
        receipts[str(stamp.date())] = json.loads(json.dumps(asdict(verified.reference), default=str))
        raw = verified.frame
        rows = raw[raw.instrument_class == "equity"].to_dict("records")
        by_symbol, by_isin = defaultdict(list), defaultdict(list)
        for row_number, row in enumerate(rows):
            by_symbol[row["symbol"]].append((row_number, row))
            by_isin[row["isin"]].append((row_number, row))
        for symbol, reference in selection.items():
            candidates = merge_candidate_rows(by_symbol[reference["exchange_symbol"]],
                by_isin[expected_isin(reference, splits, stamp)])
            if len(candidates) != 1:
                coverage["missing_or_ambiguous_symbol_sessions"] += 1
                continue
            row = next(iter(candidates.values()))
            ok = identity_matches(row, reference, splits, stamp)
            coverage["verified_identity_rows" if ok else "unverified_identity_rows"] += 1
            collected[symbol].append({"date": stamp, "identity_verified": ok,
                **{k: row[k] for k in ("open", "high", "low", "close", "volume", "symbol", "series", "isin")}})
        if number % 100 == 0:
            print(f"Verified raw sessions {number + 1}/{len(expected)}", flush=True)
    frames = {symbol: pd.DataFrame(collected[symbol], columns=["date", "identity_verified", "open", "high", "low", "close", "volume", "symbol", "series", "isin"]).set_index("date") for symbol in selection}
    ticks = {}
    for symbol, frame in frames.items():
        values = []
        for stamp in frame.index:
            reference = tick_reference(stamp, calendar)
            close = None
            if reference in frame.index and bool(frame.loc[reference, "identity_verified"]):
                close = frame.loc[reference, "close"]
            values.append(tick_from_reference(stamp, close))
        ticks[symbol] = pd.Series(values, index=frame.index, dtype="Int64")
    mapped_actions = []
    for symbol, reference in selection.items():
        for row in actions:
            if not start <= row["date"] <= end or not (
                    row["symbol"] == reference["exchange_symbol"] or row["isin"] == reference["isin"]):
                continue
            kind, amount = action_treatment(row)
            mapped_actions.append(RawAction(symbol, row["date"], kind, amount, row["source_id"], row["subject"]))
    evidence = {"raw_receipts": receipts, "documents": documents, "actions": action_evidence,
        "coverage": dict(coverage), "universe_count": len(selection), "raw_sessions": len(expected),
        "identity_policy": "dated source-pinned split identity ledgers; otherwise same current ISIN; canonical symbol or evidenced dated ISIN, unique EQ/BE row; no inferred share entitlement",
        "limitations": ["Current constituent universe; survivorship bias remains", "Action API captures have no completeness certificate; partition union retains omitted COASTCORP row",
            "Tick rules reconstructed from circulars and previous-month raw close, not an archived daily security master",
            "Adjusted signals are held fixed for comparison, not certified point-in-time", "Mandatory held actions outside bounded policy stop the entire run"]}
    digest = sha(json.dumps(evidence, sort_keys=True).encode())
    return RawAccounting(frames, ticks, tuple(mapped_actions), digest, start, end), evidence


def holding_coverage(trades, inputs):
    results = []
    calendar = pd.DatetimeIndex(sorted({d for f in inputs.frames.values() for d in f.index}))
    for number, trade in enumerate(trades):
        start, end = pd.Timestamp(trade["entry_date"]), pd.Timestamp(trade["exit_date"])
        sessions = calendar[(calendar >= start) & (calendar <= end)]
        issues = []
        for stamp in sessions:
            try:
                inputs.bar(trade["symbol"], stamp)
                inputs.tick(trade["symbol"], stamp)
            except ValueError as exc:
                issues.append(str(exc))
        events = [asdict(a) for a in inputs.actions if a.symbol == trade["symbol"] and start < a.ex_date <= end]
        results.append({"trade_number": number, "symbol": trade["symbol"], "entry_date": str(start.date()),
            "exit_date": str(end.date()), "sessions": len(sessions), "issues": issues, "events": events})
    return results


def require_frozen_inputs(source_identity, current):
    for key, value in current.items():
        if value != source_identity[key]:
            raise ValueError(f"frozen source input changed: {key}")


def run_comparison(config_paths, output):
    from sensei.backtest import portfolio_campaign, raw_accounting, daily_execution, costs, playbook
    from sensei.execution import nse
    from sensei.strategy import selection as ranking
    from sensei.research import event_risk, stock_evaluation
    from sensei.research.exposure import record_development_frames

    settings = [load_run_settings(p) for p in config_paths]
    first = settings[0]
    control_bytes = SOURCE_CONTROLS.read_bytes()
    controls, source_identities = {}, {}
    for item in json.loads(control_bytes)["sources"]:
        path = ROOT / item["report_path"]
        source = pinned_json(path, item["report_sha256"])
        source_manifest = pinned_json(path.with_name("manifest.json"), item["manifest_sha256"])
        if source["run_id"] != source_manifest["run_id"]:
            raise ValueError("source report identity mismatch")
        controls[item["name"]] = source
        source_identities[item["name"]] = source_manifest["identity"]
    if any(s.name not in controls or s.identity_payload() != controls[s.name]["settings"] for s in settings):
        raise ValueError("raw comparison must preserve the frozen source settings")
    if any((s.prices_path, s.start, s.end, s.benchmark_path) != (
            first.prices_path, first.start, first.end, first.benchmark_path) for s in settings):
        raise ValueError("comparison controls must share snapshot, dates and benchmark")
    snapshot = verify_priority_snapshot(first.prices_path)
    original = {p.stem: pd.read_parquet(p) for p in sorted(first.prices_path.glob("*.parquet"))}
    benchmark_bytes = first.benchmark_path.read_bytes()
    benchmark_manifest = json.loads(first.benchmark_path.with_suffix(".manifest.json").read_text())
    if sha(benchmark_bytes) != benchmark_manifest["parquet_sha256"]:
        raise ValueError("benchmark capture changed")
    benchmark_frame = pd.read_parquet(first.benchmark_path)
    benchmark = benchmark_frame.close
    prepared = {}
    for setting in settings:
        frames = scope_price_frames(original, start=setting.start, end=setting.end, warmup_sessions=setting.warmup_sessions)
        policy = event_risk.load_event_risk(setting.event_risk_path) if setting.event_risk_path else None
        spec = {**playbook.all_strategies()[setting.strategy_name], **setting.strategy_parameters}
        require_frozen_inputs(source_identities[setting.name], {
            "kite_manifest": snapshot, "benchmark_sha256": sha(benchmark_bytes),
            "benchmark_manifest": benchmark_manifest,
            "event_risk_policy": policy.identity() if policy else None,
            "input_frames": {symbol: _frame_digest(frame) for symbol, frame in sorted(frames.items())},
            "signal": _signal_identity(spec["fn"]),
            "effective_selection_policy": asdict(portfolio_campaign.SELECTION_POLICY),
            "effective_charge_schedule": asdict(costs.IndianDeliveryChargeSchedule()),
            "runtime": {name: version(name) for name in ("numpy", "pandas", "pydantic")},
        })
        prepared[setting.name] = frames, policy, spec
    expected = benchmark.index[(benchmark.index.date >= first.start) & (benchmark.index.date <= first.end)]
    observed = pd.DatetimeIndex(sorted({d for f in original.values() for d in f.index if first.start <= d.date() <= first.end}))
    if not expected.equals(observed) or not all(s.portfolio.liquidate_at_end for s in settings):
        raise ValueError("raw comparison requires the complete benchmark calendar and final liquidation")
    inputs, evidence = build_inputs(snapshot["identity"]["selection"], benchmark.index,
        start=pd.Timestamp(first.start), end=pd.Timestamp(first.end))
    identity = {"settings": [s.identity_payload() for s in settings], "snapshot_id": snapshot["snapshot_id"],
        "runtime": {name: version(name) for name in ("numpy", "pandas", "pydantic")},
        "source_controls_sha256": sha(control_bytes), "source_controls": json.loads(control_bytes),
        "snapshot_manifest_sha256": sha(json.dumps(snapshot, sort_keys=True).encode()),
        "raw_evidence": evidence, "benchmark_manifest": benchmark_manifest,
        "event_policies": [event_risk.load_event_risk(s.event_risk_path).identity() if s.event_risk_path else None for s in settings],
        "implementation_sha256": sha("".join(inspect.getsource(m) for m in (
            portfolio_campaign, raw_accounting, daily_execution, costs, playbook, nse, ranking, event_risk, stock_evaluation)).encode() + Path(__file__).read_bytes())}
    run_id = sha(json.dumps(identity, sort_keys=True).encode())
    root = output / run_id
    root.mkdir(parents=True, exist_ok=True)
    manifest = root / "manifest.json"
    if manifest.exists():
        if json.loads(manifest.read_text())["identity"] != identity:
            raise ValueError("comparison identity mismatch")
    else:
        manifest.write_text(json.dumps({"run_id": run_id, "recorded_before_evaluation": datetime.now(timezone.utc).isoformat(), "identity": identity}, indent=2) + "\n")
    if (root / "report.json").exists():
        pinned_json(root / "report.json", (root / "report.sha256").read_text().strip())
        return root / "report.json"
    results = []
    for setting in settings:
        frames, policy, spec = prepared[setting.name]
        if setting.market_entry_gate is not None:
            raise ValueError("freeze the two original controls without new market filters")
        record_development_frames(frames, campaign_id=setting.name + "-raw-accounting")
        record_development_frames({"NIFTY500_TRI": benchmark_frame}, campaign_id=setting.name + "-raw-accounting")
        masks = event_risk.entry_masks(frames, policy) if policy else None
        audit = stock_evaluation.audit_stock_data(frames)
        result = {"name": setting.name, "decision": "DATA_BLOCKED", "can_trade": False,
            "authority": "RESEARCH_ONLY", "simulation_blockers": [], "settings": setting.identity_payload(),
            "source_run_id": controls[setting.name]["run_id"],
            "source_holding_coverage": holding_coverage(controls[setting.name]["campaign"]["trades"], inputs)}
        try:
            campaign = run_portfolio_campaign(frames=frames, strategies={setting.strategy_name: spec},
                config=setting.portfolio, evaluation_start=pd.Timestamp(setting.start),
                evaluation_end=pd.Timestamp(setting.end), entry_eligibility=masks, raw_accounting=inputs)
        except ValueError as exc:
            result["simulation_blockers"].append(str(exc))
        else:
            result.update(stock_evaluation.evaluate_stock_portfolio(campaign=campaign, protocol=setting.evaluation,
                data_audit=audit, benchmark=benchmark, benchmark_name=setting.benchmark_name))
            result["holding_coverage"] = holding_coverage([asdict(t) for t in campaign.trades], inputs)
        results.append(result)
        print(setting.name, result.get("campaign", {}).get("final_equity"), result["simulation_blockers"], flush=True)
    payload = {"run_id": run_id, "decision": "DATA_BLOCKED", "can_trade": False, "authority": "RESEARCH_ONLY",
        "coverage": evidence["coverage"], "raw_sessions": evidence["raw_sessions"],
        "limitations": evidence["limitations"], "comparisons": results}
    content = (json.dumps(payload, sort_keys=True, indent=2, default=str, allow_nan=False) + "\n").encode()
    (root / "report.json").write_bytes(content)
    (root / "report.sha256").write_text(sha(content) + "\n")
    return root / "report.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, default=Path("data/reports/raw-portfolio"))
    args = parser.parse_args()
    print(run_comparison(args.config, args.output))


if __name__ == "__main__":
    main()
