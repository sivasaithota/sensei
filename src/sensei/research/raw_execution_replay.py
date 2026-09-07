"""Forced-entry raw-price replay of selected, action-reviewed holding intervals."""

from __future__ import annotations

import argparse
import hashlib
import io
import inspect
import json
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd

from sensei.backtest.portfolio_campaign import PortfolioCampaignConfig, run_portfolio_campaign
from sensei.data.bhavcopy import QuarantinedRawBhavcopy
from sensei.research.quantity_sizing_reproduction import _pinned_json


def in_interval_actions(records, *, symbol, start, end):
    if not isinstance(records, list) or not records:
        raise ValueError("empty or malformed action response cannot establish scoped absence")
    conflicts = []
    for action in records:
        if action["symbol"] != symbol or action["series"] != "EQ":
            raise ValueError("action response contains another security or series")
        ex_date = pd.Timestamp(datetime.strptime(action["exDate"], "%d-%b-%Y"))
        if ex_date.year != 2024:
            raise ValueError("action response lies outside its requested scope")
        if start <= ex_date <= end:
            conflicts.append(action)
    return conflicts


def assemble_raw_frame(sessions, calendar, *, symbol, isin):
    rows, issues = [], []
    for stamp in calendar:
        day = stamp.date()
        raw = sessions.get(day)
        if raw is None:
            issues.append({"date": str(day), "reason": "raw_session_not_captured"})
            continue
        candidates = raw[(raw.symbol == symbol) & (raw.series == "EQ") & (raw.instrument_class == "equity")]
        if len(candidates) != 1:
            issues.append({"date": str(day), "reason": "missing_or_ambiguous_raw_identity"})
            continue
        row = candidates.iloc[0]
        if row["isin"] != isin or not bool(row.ok):
            issues.append({"date": str(day), "reason": "wrong_isin_or_invalid_raw_row"})
            continue
        rows.append({"date": stamp, **{key: float(row[key]) for key in ("open", "high", "low", "close", "volume")}})
    if issues:
        return None, issues
    return pd.DataFrame(rows).set_index("date"), []


def run_replay(plan_path, reports_root, output):
    plan_content = plan_path.read_bytes()
    plan_hash = hashlib.sha256(plan_content).hexdigest()
    plan = json.loads(plan_content)
    for note in plan["notes"].values():
        if hashlib.sha256((plan_path.parent / note["path"]).read_bytes()).hexdigest() != note["sha256"]:
            raise ValueError("raw replay source note changed")
    audit_path = plan_path.parent / plan["unit_audit_path"]
    audit = _pinned_json(audit_path, plan["unit_audit_sha256"])
    if audit.get("can_trade") is not False or audit.get("decision") != "DATA_BLOCKED":
        raise ValueError("raw replay requires a blocked source audit")
    screen = _pinned_json(Path(audit["source_screen_path"]), audit["source_screen_sha256"])
    action_manifest_path = plan_path.parent / plan["action_manifest_path"]
    action_manifest = _pinned_json(action_manifest_path, plan["action_manifest_sha256"])
    if action_manifest["scope"] != {"from_date": "2024-01-01", "to_date": "2024-12-31",
            "purpose_filter": None, "symbols": ["HEG", "MAZDOCK"]}:
        raise ValueError("action capture scope differs from selected replay")
    action_records = {}
    for capture in action_manifest["responses"]:
        parsed = urlparse(capture["request_url"])
        expected_query = {"index": ["equities"], "symbol": [capture["symbol"]],
            "from_date": ["01-01-2024"], "to_date": ["31-12-2024"]}
        if (capture["http_status"] != 200 or parsed.hostname != "www.nseindia.com"
                or parsed.path != "/api/corporates-corporateActions" or parse_qs(parsed.query) != expected_query
                or capture["symbol"] in action_records):
            raise ValueError("invalid action capture request")
        records = _pinned_json(Path(capture["body_path"]), capture["body_sha256"])
        if len(records) != capture["record_count"]:
            raise ValueError("action capture count mismatch")
        action_records[capture["symbol"]] = records
    if set(action_records) != {"HEG", "MAZDOCK"}:
        raise ValueError("action captures must cover both selected securities")
    sources, calendars = {}, {}
    for item in screen["source_proofs"]:
        proof = _pinned_json(Path(item["proof_path"]), item["proof_sha256"])
        root = reports_root / item["source_run_id"]
        report = _pinned_json(root / "report.json", proof["source_report_sha256"])
        manifest = _pinned_json(root / "manifest.json", proof["source_manifest_sha256"])
        benchmark = Path(report["settings"]["benchmark_path"]).read_bytes()
        if hashlib.sha256(benchmark).hexdigest() != manifest["identity"]["benchmark_sha256"]:
            raise ValueError("raw replay benchmark changed")
        sources[item["source_run_id"]] = report
        calendars[item["source_run_id"]] = pd.read_parquet(io.BytesIO(benchmark)).index
    store = QuarantinedRawBhavcopy()
    available = set(store.sessions())
    raw_sessions, receipts = {}, {}

    def load_days(days):
        for day in days:
            if day in available and day not in raw_sessions:
                verified = store.verified_session(day)
                raw_sessions[day] = verified.frame
                receipts[str(day)] = json.loads(json.dumps(asdict(verified.reference), default=str))

    cases = []
    for record in audit["trades"]:
        if record["audit"]["status"] not in {"fractional_physical_equivalent", "integral_physical_equivalent"}:
            continue
        trade = record["trade"]
        key = "|".join(trade[field] for field in ("symbol", "entry_date", "exit_date"))
        case = {"source_run_id": record["source_run_id"], "trade_number": record["trade_number"],
            "source_trade": trade, "status": "BLOCKED", "strict_validation": "BLOCKED", "issues": []}
        cases.append(case)
        evidence = plan["cases"].get(key)
        if evidence is None or evidence["action_coverage"] != "no_action_in_reviewed_interval":
            case["issues"].append({"reason": "action_coverage_unresolved"})
            continue
        source = sources[record["source_run_id"]]
        if source["campaign"]["trades"][record["trade_number"]] != trade:
            raise ValueError("raw replay trade changed")
        entry, end = pd.Timestamp(trade["entry_date"]), pd.Timestamp(trade["exit_date"])
        if not pd.Timestamp("2024-01-01") <= entry <= end <= pd.Timestamp("2024-12-31"):
            case["issues"].append({"reason": "trade_outside_action_capture_scope"})
            continue
        split = record["audit"]["split"]
        conflicts = in_interval_actions(action_records[split["exchange_symbol"]],
            symbol=split["exchange_symbol"], start=entry, end=end)
        if conflicts:
            case["issues"].append({"reason": "in_interval_action_requires_modeling", "actions": conflicts})
            continue
        calendar = calendars[record["source_run_id"]]
        previous = calendar[calendar < entry]
        if not len(previous) or entry not in calendar or end not in calendar:
            case["issues"].append({"reason": "source_calendar_missing_boundary"})
            continue
        expected = calendar[(calendar >= previous[-1]) & (calendar <= end)]
        load_days(stamp.date() for stamp in expected)
        raw_frame, issues = assemble_raw_frame(raw_sessions, expected,
            symbol=split["exchange_symbol"], isin=split["old_isin"])
        case["issues"].extend(issues)
        if issues:
            continue
        reference_day = evidence["tick_reference_date"]
        if reference_day is not None:
            reference_stamp = pd.Timestamp(reference_day)
            load_days([reference_stamp.date()])
            reference_frame, issues = assemble_raw_frame(raw_sessions, pd.DatetimeIndex([reference_stamp]),
                symbol=split["exchange_symbol"], isin=split["old_isin"])
            if issues or reference_stamp >= entry or reference_frame.iloc[0]["close"] < 250:
                case["issues"].append({"reason": "tick_reference_unavailable_or_inapplicable"})
                continue
            case["tick_reference_close"] = float(reference_frame.iloc[0]["close"])
        # This plan covers only the documented 2024 five-paise cases, not a generic tick engine.
        if evidence["tick_paise"] != 5 or not end < pd.Timestamp("2025-04-15"):
            case["issues"].append({"reason": "tick_regime_outside_replay_scope"})
            continue
        if entry >= pd.Timestamp("2024-06-10") and reference_day is None:
            case["issues"].append({"reason": "monthly_tick_reference_missing"})
            continue
        if entry >= pd.Timestamp("2024-06-10"):
            prior_month = calendar[calendar < entry.replace(day=1)]
            if not len(prior_month) or str(prior_month[-1].date()) != reference_day:
                case["issues"].append({"reason": "tick_reference_is_not_prior_month_end"})
                continue
            if entry.month != end.month:
                case["issues"].append({"reason": "constant_tick_replay_crosses_monthly_review"})
                continue
        signals = pd.Series(False, index=raw_frame.index)
        signals.iloc[0] = True
        config = replace(PortfolioCampaignConfig(**source["campaign"]["config"]),
            execution_tick_paise=5, liquidate_at_end=True)
        steps = pd.Series([1], index=pd.DatetimeIndex([entry]), dtype="Int64")
        case_evidence = {"plan_sha256": plan_hash, "case": key,
            "receipts": {str(stamp.date()): receipts[str(stamp.date())] for stamp in expected}}
        if reference_day is not None:
            case_evidence["tick_reference_receipt"] = receipts[reference_day]
        evidence_hash = hashlib.sha256(json.dumps(case_evidence, sort_keys=True).encode()).hexdigest()
        campaign = run_portfolio_campaign(frames={trade["symbol"]: raw_frame},
            strategies={"frozen_entry": source["settings"]["strategy_parameters"]}, config=config,
            prepared_signals={("frozen_entry", trade["symbol"]): signals}, evaluation_start=entry, evaluation_end=end,
            entry_quantity_steps={trade["symbol"]: steps}, quantity_evidence_sha256=evidence_hash)
        case.update(status="REPLAYED", strict_validation="SCOPED_CHECKS_PASSED",
            evidence=case_evidence, evidence_sha256=evidence_hash,
            campaign=campaign.to_dict(), horizon_censored=any(t.exit_reason == "final_session" for t in campaign.trades))
    result = {"authority": "RESEARCH_ONLY", "decision": "DATA_BLOCKED", "can_trade": False,
        "plan": plan, "plan_sha256": plan_hash, "raw_receipts": receipts, "cases": cases,
        "action_manifest": action_manifest,
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_verifier_implementation_sha256": hashlib.sha256(inspect.getsource(_pinned_json).encode()).hexdigest(),
        "limitations": ["Frozen selected entries and full initial cash per case; not a complete strategy or portfolio rerun",
            "Saved exit date bounds the replay; forced end closures are horizon-censored",
            "Tick assignments follow scoped rules and raw references, not archived security-master certification",
            "Primary action coverage is bounded; source universe remains survivorship-biased and reused development history"]}
    encoded = (json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    digest = hashlib.sha256(encoded).hexdigest()
    path = output / digest / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != encoded:
        raise ValueError("existing raw replay changed")
    path.write_bytes(encoded)
    path.with_name("report.sha256").write_text(digest + "\n")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--reports-root", type=Path, default=Path("data/reports/stock-development"))
    parser.add_argument("--output", type=Path, default=Path("data/reports/raw-execution-replay"))
    args = parser.parse_args()
    print(run_replay(args.plan, args.reports_root, args.output))


if __name__ == "__main__":
    main()
