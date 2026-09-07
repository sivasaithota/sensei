"""Pinned BSE bonus holding scenarios through the public research portfolio."""

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

from sensei.backtest.portfolio_campaign import PortfolioCampaignConfig, run_portfolio_campaign
from sensei.backtest.raw_accounting import RawAccounting, RawAction
from sensei.data.bhavcopy import QuarantinedRawBhavcopy
from sensei.research.bonus_indicator_replay import classify_actions
from sensei.research.raw_portfolio import load_actions, tick_from_reference
from sensei.research.split_reproduction import FIELDS, ROOT, identity_row, pinned, sha


def load_inputs(plan):
    parent = json.loads(pinned(plan["parent_manifest"]))["identity"]["raw_evidence"]
    pinned(plan["action_manifest"])
    for spec in [plan["contract"], plan["availability_note"], plan["tick_note"], *plan["implementations"]]:
        pinned(spec)
    manifest = json.loads(pinned(plan["bonus_manifest"]))
    captures = {c["url"]: c for c in manifest["captures"]}
    if len(captures) != len(manifest["captures"]):
        raise ValueError("duplicate bonus evidence")
    for capture in captures.values():
        if capture["http_status"] != 200 or any(
                urlparse(capture[k]).scheme != "https" or urlparse(capture[k]).hostname != "nsearchives.nseindia.com"
                for k in ("url", "final_url")):
            raise ValueError("unexpected bonus primary source")
        pdf = pinned(capture)
        if not pdf.startswith(b"%PDF-") or len(pdf) != capture["bytes"]:
            raise ValueError("invalid bonus primary PDF")
    declaration = plan["action"]
    known = pd.Timestamp(declaration["known_session"])
    if any(pd.Timestamp(captures[url]["publication_date"]) >= known for url in declaration["support_urls"]):
        raise ValueError("bonus evidence not published before assumed knowledge")
    availability = captures[plan["availability_source_url"]]
    if (availability["sha256"] != plan["availability_source_sha256"]
            or pd.Timestamp(availability["publication_date"]) >= known):
        raise ValueError("availability scenario source mismatch")
    calendar = pd.DatetimeIndex(sorted(parent["raw_receipts"]))
    start, end = pd.Timestamp(plan["history_start"]), pd.Timestamp(plan["end"])
    sessions = calendar[(calendar >= start) & (calendar <= end)]
    if len(sessions) != 9 or sessions[0] != start or sessions[-1] != end:
        raise ValueError("BSE scenario calendar changed")
    all_actions, _ = load_actions(ROOT / plan["action_manifest"]["path"])
    observed = [a for a in all_actions if a["symbol"] == "BSE" and start <= a["date"] <= end]
    classified = classify_actions(observed, [declaration])
    if len(classified["BSE"]) != 1:
        raise ValueError("unexpected BSE action coverage")
    store, receipts, rows = QuarantinedRawBhavcopy(), {}, []
    reference = pd.Timestamp(plan["tick_reference_session"])
    for stamp in [reference, *sessions]:
        verified = store.verified_session(stamp.date())
        receipt = json.loads(json.dumps(asdict(verified.reference), default=str))
        if receipt != parent["raw_receipts"][str(stamp.date())]:
            raise ValueError("raw input differs from frozen receipt")
        receipts[str(stamp.date())] = receipt
        row = identity_row(verified.frame, "BSE", declaration["old_isin"])
        if stamp == reference:
            reference_close = float(row["close"])
        else:
            rows.append({"session": stamp, **{k: float(row[k]) for k in FIELDS}, "identity_verified": True})
    ticks = pd.Series([tick_from_reference(s, reference_close) for s in sessions], index=sessions, dtype="Int64")
    if not ticks.eq(50).all():
        raise ValueError("BSE May tick differs from the documented monthly reference")
    return pd.DataFrame(rows).set_index("session"), ticks, receipts, observed, reference_close


def run(plan_path, output):
    content = plan_path.read_bytes()
    plan = json.loads(content)
    # This is a fixed reproduction, not a configurable search over favorable cases.
    expected = {"authority": "RESEARCH_ONLY", "can_trade": False,
        "history_start": "2025-05-20", "entry_session": "2025-05-22", "end": "2025-05-30",
        "tick_reference_session": "2025-04-30", "assumed_available_from": "2025-05-27",
        "cases": ["planned_availability_scenario", "unknown_availability"]}
    if any(plan[k] != v for k, v in expected.items()):
        raise ValueError("unsupported BSE reproduction scope")
    frame, ticks, receipts, observed, reference_close = load_inputs(plan)
    a = plan["action"]
    action = RawAction("BSE", pd.Timestamp(a["ex_session"]), "bonus", 0., a["source_id"], a["subject"],
        new_shares=a["new_shares"], old_shares=a["old_shares"], known_from=pd.Timestamp(a["known_session"]),
        available_from=pd.Timestamp(plan["assumed_available_from"]),
        availability_known_from=pd.Timestamp(a["known_session"]),
        availability_source_sha256=plan["availability_source_sha256"], availability_basis="scenario")
    config = PortfolioCampaignConfig(capital=300_000, max_position_pct=20, max_risk_per_trade_pct=2,
        cost_model="current_delivery_schedule", liquidate_at_end=True)
    prepared = pd.Series(frame.index == pd.Timestamp("2025-05-21"), index=frame.index)
    reports = {}
    for case in plan["cases"]:
        event = action if case == "planned_availability_scenario" else replace(action, available_from=None,
            availability_known_from=None, availability_source_sha256=None, availability_basis=None)
        report = run_portfolio_campaign(frames={"BSE": frame.drop(columns="identity_verified")},
            strategies={"forced_holding": {"stop_pct": 10, "target_pct": 100, "max_hold_days": 2}},
            prepared_signals={("forced_holding", "BSE"): prepared}, config=config,
            evaluation_start=pd.Timestamp(plan["entry_session"]),
            raw_accounting=RawAccounting({"BSE": frame}, {"BSE": ticks}, (event,), sha(content),
                pd.Timestamp(plan["entry_session"]), pd.Timestamp(plan["end"])))
        actual_legs = [(t.quantity, t.exit_date, t.exit_reason, t.exit_price) for t in report.trades]
        expected_legs = [(8, "2025-05-23", "time", 2448.)]
        if case == "planned_availability_scenario":
            expected_legs.append((16, "2025-05-27", "deferred_time", 2450.))
        if actual_legs != expected_legs or any(t.entry_date != "2025-05-22" or t.entry_price != 2435. for t in report.trades):
            raise ValueError("BSE sale legs differ from declared accounting scenario")
        pending = 0 if len(expected_legs) == 2 else 16
        last = report.equity_curve[-1]
        if (report.open_positions != bool(pending)
                or abs(last.share_receivables - pending * float(frame.iloc[-1]["close"])) > 1e-8
                or report.raw_accounting["liquidation_complete"] != (pending == 0)):
            raise ValueError("BSE final pending state does not reconcile")
        if any(abs(p.equity - p.cash - p.invested - p.dividend_receivables - p.share_receivables) > 1e-8
                for p in report.equity_curve) or abs(sum(report.strategy_pnl.values()) - report.net_pnl) > 1e-8:
            raise ValueError("BSE equity or strategy P&L does not reconcile")
        reports[case] = report.to_dict()
        reports[case]["raw_accounting"]["signal_basis"] = (
            "Forced prepared entry with raw diagnostic frames; no adjusted strategy history or signal validation")
    result = {"authority": "RESEARCH_ONLY", "can_trade": False, "decision": "ACCOUNTING_SCENARIOS_PASS",
        "plan": plan, "plan_sha256": sha(content), "implementation_sha256": sha(Path(__file__).read_bytes()),
        "raw_receipts": receipts, "observed_actions": observed, "raw_prices": frame.to_dict(orient="index"),
        "tick_reference_close": reference_close, "tick_paise": 50, "cases": reports,
        "limitations": ["Forced holding, not a strategy signal or performance evaluation",
            "May 27 availability is a planned-date scenario; actual broker credit is unverified",
            "Current delivery charges applied uniformly; no historical fee certification",
            "Whole BSE bonus only; no general mandatory-action or historical-universe certification"]}
    result["raw_prices"] = {str(k.date()): v for k, v in result["raw_prices"].items()}
    payload = (json.dumps(result, sort_keys=True, indent=2, default=str) + "\n").encode()
    path = output / sha(payload) / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != payload:
        raise ValueError("existing reproduction changed")
    path.write_bytes(payload)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=ROOT / "config/bonus-portfolio-reproduction-v1.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/reports/bonus-portfolio-reproduction")
    args = parser.parse_args()
    print(run(args.plan, args.output))


if __name__ == "__main__":
    main()
