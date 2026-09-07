"""Source-pinned, two-stock split mechanics diagnostic; no portfolio execution."""

import argparse
from dataclasses import asdict, replace
from fractions import Fraction
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd

from sensei.data.bhavcopy import QuarantinedRawBhavcopy
from sensei.research.action_history import ShareAction, signal_history
from sensei.research.raw_portfolio import load_actions


ROOT = Path(__file__).resolve().parents[3]
FIELDS = ["open", "high", "low", "close", "volume"]


def sha(content):
    return hashlib.sha256(content).hexdigest()


def pinned(spec):
    data = (ROOT / spec["path"]).read_bytes()
    if sha(data) != spec["sha256"]:
        raise ValueError(f"changed input: {spec['path']}")
    return data


def identity_row(frame, symbol, isin):
    candidates = frame[(frame["symbol"] == symbol) | (frame["isin"] == isin)]
    if len(candidates) != 1:
        raise ValueError("missing or ambiguous raw instrument")
    row = candidates.iloc[0]
    if (row["isin"] != isin or row["series"] != "EQ"
            or row["instrument_class"] != "equity" or not bool(row["ok"])):
        raise ValueError("raw identity/quality mismatch")
    return row


def audit_transform(frame, action, *, rtol, atol, transform=signal_history):
    """Check every decision against a scalar rational oracle and truncated input."""
    if not (0 <= rtol <= 1e-12 and 0 <= atol <= 1e-10):
        raise ValueError("diagnostic tolerances cannot be widened")
    original = frame.copy(deep=True)
    comparisons, cells = 0, 0
    ratio = Fraction(action.new_shares, action.old_shares)
    for cutoff in frame.index:
        actual = transform(frame, [action], cutoff)
        prefix = transform(frame.loc[:cutoff], [action], cutoff)
        pd.testing.assert_frame_equal(actual, prefix)
        if not actual.index.equals(frame.loc[:cutoff].index) or list(actual.columns) != list(frame.columns):
            raise ValueError("transform changed history shape")
        for stamp in actual.index:
            applies = stamp < action.ex_session <= cutoff
            expected = []
            for name in FIELDS:
                value = Fraction(str(original.loc[stamp, name]))
                if applies:
                    value = value * ratio if name == "volume" else value / ratio
                expected.append(float(value))
            if not np.allclose(actual.loc[stamp, FIELDS].to_numpy(dtype=float), expected, rtol=rtol, atol=atol):
                raise ValueError("dated history disagrees with rational oracle")
            cells += len(FIELDS)
        pd.testing.assert_frame_equal(frame, original)
        comparisons += 1
    try:
        transform(frame, [replace(action, known_session=action.ex_session + pd.Timedelta(days=1))], action.ex_session)
    except ValueError as exc:
        if "not known" not in str(exc):
            raise
    else:
        raise ValueError("later knowledge negative control did not block")
    pd.testing.assert_frame_equal(frame, original)
    return {"decision_cutoffs": comparisons, "oracle_cells": cells,
        "append_invariance": True, "later_knowledge_blocked": True, "raw_input_unchanged": True}


def run(plan_path, output):
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    if plan["authority"] != "RESEARCH_ONLY" or plan["can_trade"] is not False:
        raise ValueError("research plan cannot authorize trading")
    if len(plan["cases"]) != 2 or {c["symbol"] for c in plan["cases"]} != {"HEG", "MAZDOCK"}:
        raise ValueError("this diagnostic requires both preregistered cases")
    parent = json.loads(pinned(plan["parent_manifest"]))["identity"]["raw_evidence"]
    pinned(plan["contract"])
    pinned(plan["transform"])
    pinned(plan["publication_note"])
    captures = json.loads(pinned(plan["capture_manifest"]))["captures"]
    by_url = {c["url"]: c for c in captures}
    if len(by_url) != len(captures) or set(by_url) != {u for c in plan["cases"] for u in c["support_urls"]}:
        raise ValueError("case evidence must account for every captured source")
    allowed = {"nsearchives.nseindia.com", "www.msei.in", "www.mazagondock.in"}
    for capture in captures:
        if capture["http_status"] != 200 or any(urlparse(capture[k]).scheme != "https"
                or urlparse(capture[k]).hostname not in allowed for k in ("url", "final_url")):
            raise ValueError("unexpected primary source")
        pdf = pinned({"path": capture["path"], "sha256": capture["sha256"]})
        if not pdf.startswith(b"%PDF-") or len(pdf) != capture["bytes"]:
            raise ValueError("invalid PDF capture")
    lineage = json.loads(pinned(plan["lineage"]))["events"]
    pinned(plan["action_manifest"])
    actions, _ = load_actions(ROOT / plan["action_manifest"]["path"])
    calendar = pd.DatetimeIndex(sorted(parent["raw_receipts"]))
    store = QuarantinedRawBhavcopy()
    results = []
    receipts = {}
    for case in plan["cases"]:
        start, end, ex, published, known = (pd.Timestamp(case[k]) for k in
            ("start", "end", "ex_session", "all_support_published_by", "known_session"))
        latest = max(pd.Timestamp(by_url[u]["publication_date"]) for u in case["support_urls"])
        if (not start < ex < end or any(s not in calendar for s in (start, end, ex))
                or latest != published or calendar[calendar > published][0] != known or known > ex):
            raise ValueError("invalid case session/knowledge scope")
        evidence = [e for e in lineage if e["exchange_symbol"] == case["symbol"]
            and pd.Timestamp(e["effective_date"]) == ex]
        if len(evidence) != 1 or Fraction(case["new_shares"], case["old_shares"]) != Fraction(str(evidence[0]["new_shares_per_old_share"])):
            raise ValueError("case ratio does not match pinned lineage")
        event = evidence[0]
        if not set(case["support_urls"]).issubset(event["sources"]):
            raise ValueError("case publications do not support the lineage")
        observed = [a for a in actions if a["symbol"] == case["symbol"] and start <= a["date"] <= end]
        if (len(observed) != 1 or observed[0]["source_id"] != case["action_source_id"]
                or observed[0]["date"] != ex or observed[0]["isin"] != event["old_isin"]
                or not observed[0]["subject"].startswith("Face Value Split")):
            raise ValueError("window does not contain exactly the expected observed action")
        rows, metadata = [], []
        for stamp in calendar[(calendar >= start) & (calendar <= end)]:
            verified = store.verified_session(stamp.date())
            receipt = json.loads(json.dumps(asdict(verified.reference), default=str))
            if receipt != parent["raw_receipts"][str(stamp.date())]:
                raise ValueError("raw receipt differs from frozen portfolio input")
            receipts[str(stamp.date())] = receipt
            isin = event["old_isin"] if stamp < ex else event["new_isin"]
            row = identity_row(verified.frame, case["symbol"], isin)
            rows.append({"session": stamp, **{k: float(row[k]) for k in FIELDS}})
            metadata.append({"session": str(stamp.date()), "isin": isin, "prev_close": float(row.prev_close)})
        raw = pd.DataFrame(rows).set_index("session")
        action = ShareAction(case["action_source_id"], ex, known, "split", case["new_shares"], case["old_shares"])
        checks = audit_transform(raw, action, rtol=plan["acceptance"]["rtol"], atol=plan["acceptance"]["atol"])
        before = raw.index[raw.index < ex][-1]
        adjusted = signal_history(raw, [action], ex)
        old_close, normal_close, ex_close = float(raw.loc[before, "close"]), float(adjusted.loc[before, "close"]), float(raw.loc[ex, "close"])
        results.append({"symbol": case["symbol"], "checks": checks, "raw_rows": rows,
            "identity_rows": metadata, "action": asdict(action), "prior_session": before,
            "raw_prior_close": old_close, "normalized_prior_close": normal_close,
            "ex_close": ex_close, "ex_close_return_pct": (ex_close / normal_close - 1) * 100,
            "ex_file_previous_close": next(m["prev_close"] for m in metadata if m["session"] == str(ex.date())),
            "observed_action": observed[0]})
    result = {"plan_sha256": sha(plan_bytes), "implementation_sha256": sha(Path(__file__).read_bytes()),
        "plan": plan, "raw_receipts": receipts, "cases": results,
        "authority": "RESEARCH_ONLY", "can_trade": False, "decision": "DATA_BLOCKED",
        "scope_result": "TWO_REAL_SPLIT_MECHANICS_CHECKS_PASS",
        "limitations": ["Dated PDFs captured now do not prove historical upload timestamps or raw-data vintages",
            "Partitioned API responses establish observed action coverage, not guaranteed exchange completeness",
            "No bonus case, signal warmup, ranking/correlation, physical entitlements or membership certification",
            "No strategy or portfolio performance evaluation"]}
    data = (json.dumps(result, indent=2, sort_keys=True, default=str) + "\n").encode()
    path = output / sha(data) / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != data:
        raise ValueError("existing report changed")
    path.write_bytes(data)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=ROOT / "config/dated-split-reproduction-v1.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/reports/dated-split-reproduction")
    args = parser.parse_args()
    print(run(args.plan, args.output))


if __name__ == "__main__":
    main()
