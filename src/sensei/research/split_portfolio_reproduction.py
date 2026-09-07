"""HEG subdivision inventory reproduction, with explicit availability controls."""

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

from sensei.backtest.portfolio_campaign import PortfolioCampaignConfig, run_portfolio_campaign
from sensei.backtest.raw_accounting import RawAccounting, RawAction
from sensei.data.bhavcopy import QuarantinedRawBhavcopy
from sensei.research.raw_portfolio import load_actions, tick_from_reference
from sensei.research.split_reproduction import FIELDS, ROOT, identity_row, pinned, sha


def load_inputs(plan):
    prior = json.loads(pinned(plan["prior_reproduction"]))
    for spec in [plan["contract"], *plan["implementations"]]:
        pinned(spec)
    case = next(c for c in prior["cases"] if c["symbol"] == "HEG")
    parent = json.loads(pinned(prior["plan"]["parent_manifest"]))["identity"]["raw_evidence"]
    lineage = json.loads(pinned(prior["plan"]["lineage"]))["events"]
    event = next(e for e in lineage if e["exchange_symbol"] == "HEG")
    captures = json.loads(pinned(prior["plan"]["capture_manifest"]))["captures"]
    pinned(prior["plan"]["publication_note"])
    support = prior["plan"]["cases"][0]["support_urls"]
    selected = [c for c in captures if c["url"] in support]
    if len(selected) != 2:
        raise ValueError("missing HEG primary evidence")
    for capture in selected:
        pdf = pinned(capture)
        if (capture["http_status"] != 200 or not pdf.startswith(b"%PDF-") or len(pdf) != capture["bytes"]
                or any(urlparse(capture[k]).scheme != "https" or urlparse(capture[k]).hostname != "nsearchives.nseindia.com"
                    for k in ("url", "final_url"))):
            raise ValueError("invalid HEG primary evidence")
    admission = next(c for c in selected if c["url"].endswith("/CML64528.pdf"))
    ex = pd.Timestamp("2024-10-18")
    if (pd.Timestamp(event["effective_date"]) != ex or event["new_shares_per_old_share"] != 5
            or pd.Timestamp(case["action"]["known_session"]) != ex
            or max(c["publication_date"] for c in selected) != "2024-10-17"):
        raise ValueError("HEG split/knowledge declaration changed")
    pinned(prior["plan"]["action_manifest"])
    actions, _ = load_actions(ROOT / prior["plan"]["action_manifest"]["path"])
    observed = [a for a in actions if a["symbol"] == "HEG" and pd.Timestamp("2024-10-14") <= a["date"] <= pd.Timestamp("2024-10-25")]
    if len(observed) != 1 or observed[0] != {**case["observed_action"], "date": ex}:
        raise ValueError("HEG observed action changed")
    store, receipts, rows = QuarantinedRawBhavcopy(), {}, []
    stamps = [pd.Timestamp("2024-09-30"), *[pd.Timestamp(r["session"]) for r in case["raw_rows"]]]
    if len(stamps) != 11:
        raise ValueError("HEG reproduction calendar changed")
    for stamp in stamps:
        verified = store.verified_session(stamp.date())
        receipt = json.loads(json.dumps(asdict(verified.reference), default=str))
        if receipt != parent["raw_receipts"][str(stamp.date())]:
            raise ValueError("HEG raw receipt differs from frozen input")
        receipts[str(stamp.date())] = receipt
        isin = event["old_isin"] if stamp < ex else event["new_isin"]
        row = identity_row(verified.frame, "HEG", isin)
        if stamp == stamps[0]:
            reference_close = float(row["close"])
        else:
            rows.append({"session": stamp, **{k: float(row[k]) for k in FIELDS}, "identity_verified": True})
    frame = pd.DataFrame(rows).set_index("session")
    ticks = pd.Series([tick_from_reference(s, reference_close) for s in frame.index], index=frame.index, dtype="Int64")
    if not ticks.eq(5).all():
        raise ValueError("HEG October tick changed")
    return frame, ticks, receipts, observed[0], admission, reference_close


def run(plan_path, output):
    content = plan_path.read_bytes()
    plan = json.loads(content)
    if plan["authority"] != "RESEARCH_ONLY" or plan["can_trade"] is not False or plan["cases"] != ["documented_market_admission", "unknown_availability"]:
        raise ValueError("unsupported HEG reproduction authority or cases")
    frame, ticks, receipts, observed, admission, reference_close = load_inputs(plan)
    ex = pd.Timestamp("2024-10-18")
    action = RawAction("HEG", ex, "split", 0., observed["source_id"], observed["subject"],
        new_shares=5, old_shares=1, known_from=ex, available_from=ex, availability_known_from=ex,
        availability_source_sha256=admission["sha256"], availability_basis="documented_market_admission")
    reports = {}
    for name in plan["cases"]:
        event = action if name == "documented_market_admission" else replace(action, available_from=None,
            availability_known_from=None, availability_source_sha256=None, availability_basis=None)
        report = run_portfolio_campaign(frames={"HEG": frame.drop(columns="identity_verified")},
            strategies={"forced_holding": {"stop_pct": 5, "target_pct": 100, "max_hold_days": 2}},
            prepared_signals={("forced_holding", "HEG"): pd.Series(frame.index == pd.Timestamp("2024-10-16"), index=frame.index)},
            config=PortfolioCampaignConfig(capital=300_000, cost_model="current_delivery_schedule", liquidate_at_end=True),
            evaluation_start=pd.Timestamp("2024-10-17"),
            raw_accounting=RawAccounting({"HEG": frame}, {"HEG": ticks}, (event,), sha(content), pd.Timestamp("2024-10-17"), pd.Timestamp("2024-10-25")))
        legs = [(t.quantity, t.entry_date, t.exit_date, t.exit_price, t.exit_reason) for t in report.trades]
        expected = [(120, "2024-10-17", "2024-10-18", 496.35, "time")] if name == "documented_market_admission" else []
        pending = 0 if expected else 120
        if (legs != expected or report.open_positions != bool(pending)
                or abs(report.equity_curve[-1].share_receivables - pending * float(frame.iloc[-1]["close"])) > 1e-8
                or report.raw_accounting["liquidation_complete"] != (pending == 0)):
            raise ValueError("HEG subdivision inventory or exit did not match declared case")
        if any(abs(p.equity - p.cash - p.invested - p.share_receivables - p.dividend_receivables) > 1e-8 for p in report.equity_curve):
            raise ValueError("HEG equity components do not reconcile")
        if abs(sum(report.strategy_pnl.values()) - report.net_pnl) > 1e-8:
            raise ValueError("HEG P&L does not reconcile")
        reports[name] = report.to_dict()
        reports[name]["raw_accounting"]["signal_basis"] = "Forced prepared entry and raw diagnostic frames; no strategy signal validation"
    result = {"authority": "RESEARCH_ONLY", "can_trade": False, "decision": "SPLIT_ACCOUNTING_CASES_PASS",
        "plan": plan, "plan_sha256": sha(content), "implementation_sha256": sha(Path(__file__).read_bytes()),
        "raw_receipts": receipts, "observed_action": observed, "cases": reports,
        "tick_reference_close": reference_close, "tick_paise": 5,
        "limitations": ["NSE new-ISIN admission is not actual account credit; date-level knowledge convention",
            "Forced holding, not a strategy performance test; unknown availability control deliberately retains inventory",
            "Current fee schedule counterfactual; no historical settlement or fee certification",
            "One sourced subdivision, not complete corporate actions or universe eligibility"]}
    payload = (json.dumps(result, sort_keys=True, indent=2, default=str) + "\n").encode()
    path = output / sha(payload) / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != payload:
        raise ValueError("existing report changed")
    path.write_bytes(payload)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=ROOT / "config/split-portfolio-reproduction-v1.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/reports/split-portfolio-reproduction")
    args = parser.parse_args()
    print(run(args.plan, args.output))


if __name__ == "__main__":
    main()
