"""Consecutive historical master coverage, dated schemas and identity diagnostics."""

import argparse
from collections import Counter
from datetime import date
import gzip
import io
import json
from pathlib import Path
import time
import zlib

from sensei.research import security_master_batch as batch
from sensei.research.security_master_sample import read_master, reconcile
from sensei.research.split_reproduction import ROOT, pinned, sha


CAS_START = "2026-08-03"
IDENTITY = ("TckrSymb", "SctySrs", "ISIN", "FinInstrmId")


def expected_header(original, session):
    header = list(original)
    if session >= CAS_START:
        header[23], header[58] = "ElgbltyClsgAuctnSsn", "XchgExclsv"
    return header


def window_sessions(windows, calendar):
    result = []
    for window in windows:
        start, end = window["start"], window["end"]
        if (date.fromisoformat(start).isoformat() != start or date.fromisoformat(end).isoformat() != end
                or start > end or start not in calendar or end not in calendar):
            raise ValueError("window endpoints must be frozen exchange sessions")
        result.append([s for s in sorted(calendar) if start <= s <= end])
    if not result or len(set(s for block in result for s in block)) != sum(map(len, result)):
        raise ValueError("empty or overlapping windows")
    return result


def load_plan(path):
    content = path.read_bytes()
    plan = json.loads(content)
    if plan["authority"] != "RESEARCH_ONLY" or plan["can_trade"] is not False:
        raise ValueError("unsupported authority")
    for spec in [plan["contract"], *plan["implementations"], *plan["schema_evidence"], *plan["reuse_evidence"]]:
        pinned(spec)
    sample = json.loads(pinned(plan["sample_plan"]))
    parent = json.loads(pinned(sample["parent_manifest"]))["identity"]["raw_evidence"]["raw_receipts"]
    blocks = window_sessions(plan["windows"], parent)
    planned = [s for block in blocks for s in block] + plan["probe_sessions"]
    if (not 1 <= len(planned) <= 40 or len(set(planned)) != len(planned)
            or sorted(planned) != plan["sessions"] or not set(planned) <= set(parent)):
        raise ValueError("planned sessions differ from complete windows")
    seen_events = set()
    for event in plan["identity_events"]:
        source = pinned(event["source"])
        if (sha(source) != event["source_sha256"] or event["announced_on"] > event["effective_from"]
                or not event["old_symbol"] or not event["new_symbol"] or event["old_symbol"] == event["new_symbol"]):
            raise ValueError("invalid dated identity evidence")
        for key in ("announced_on", "effective_from"):
            if date.fromisoformat(event[key]).isoformat() != event[key]:
                raise ValueError("invalid identity date")
        pair = frozenset((event["old_symbol"], event["new_symbol"]))
        if pair in seen_events:
            raise ValueError("ambiguous identity events")
        seen_events.add(pair)
    return plan, sample, parent, blocks, sha(content)


def capture(plan_path, cache, pause=time.sleep):
    plan, _, _, _, _ = load_plan(plan_path)
    requests = 0
    for start in range(0, len(plan["sessions"]), 6):
        part = {key: plan[key] for key in ("authority", "can_trade", "contract", "implementations", "schema_evidence", "sample_plan")}
        part.update(sessions=plan["sessions"][start:start + 6], seeds={})
        content = batch.payload(part)
        path = cache / "plans" / f"{sha(content)}.json"
        batch.immutable(path, content)
        if start:
            pause(1)
        result = batch.capture(path, cache, pause=pause)
        requests += result["network_requests"]
    return {"network_requests": requests, "sessions": len(plan["sessions"]), "kite_requests": 0}


def identity_diagnostics(master, observations, events, session):
    by_token = {r["FinInstrmId"]: r for r in master}
    result = []
    for observation in observations:
        counterpart = by_token.get(observation["FinInstrmId"])
        if counterpart is None or all(observation[k] == counterpart[k] for k in IDENTITY):
            continue
        item = {"raw": {k: observation[k] for k in IDENTITY}, "master": {k: counterpart[k] for k in IDENTITY},
            "status": "unexplained_identity_difference"}
        if all(observation[k] == counterpart[k] for k in ("ISIN", "SctySrs")):
            for event in events:
                if (event["announced_on"] > session or {observation["TckrSymb"], counterpart["TckrSymb"]}
                        != {event["old_symbol"], event["new_symbol"]}):
                    continue
                before = session < event["effective_from"]
                expected = event["old_symbol"] if before else event["new_symbol"]
                status = "master_ahead_of_effective_symbol" if before else "master_stale_after_effective_symbol"
                item.update(status=status if observation["TckrSymb"] == expected else "raw_symbol_outside_notice_interval",
                    source_sha256=event["source_sha256"], announced_on=event["announced_on"], effective_from=event["effective_from"])
        result.append(item)
    return result


def normalize_rows(rows, observations, events, session):
    normalized = [batch.normalize(row, session) for row in rows]
    batch.annotate_reconciliation(normalized, observations)
    diagnostics = identity_diagnostics(rows, observations, events, session)
    by_token = {r["raw"]["FinInstrmId"]: r for r in normalized}
    for diagnostic in diagnostics:
        row = by_token[diagnostic["master"]["FinInstrmId"]]
        row.setdefault("identity_diagnostics", []).append(diagnostic)
        row["screen_status"] = "unresolved_metadata"
        row["screen_reasons"].append(diagnostic["status"])
        row["admission_blockers"].append("dated_identity_difference")
    for row in normalized:
        row["schema_version"] = "mii-cas-20260803" if session >= CAS_START else "mii-120-original"
        if session >= CAS_START:
            value = row["raw"]["ElgbltyClsgAuctnSsn"]
            row["decoded"]["ElgbltyClsgAuctnSsn"] = {"0": "ineligible", "1": "eligible"}.get(value)
            if value not in {"0", "1"}:
                row["unknown_code_fields"].append("ElgbltyClsgAuctnSsn")
                row["screen_reasons"].append("unknown_code:ElgbltyClsgAuctnSsn")
                row["screen_status"] = "unresolved_metadata"
    return normalized, diagnostics


def compressed_rows(rows):
    stream = io.BytesIO()
    with gzip.GzipFile(fileobj=stream, mode="wb", mtime=0) as archive:
        for row in rows:
            archive.write((json.dumps(row, sort_keys=True) + "\n").encode())
    return stream.getvalue()


def coverage_summary(sessions, results):
    index = {r["session"]: r for r in results}
    valid = [s for s in sessions if index.get(s, {}).get("status") == "validated"]
    best, current = [], []
    for session in sessions:
        current = current + [session] if session in valid else []
        if len(current) > len(best):
            best = current
    exact = len(valid) == len(sessions) and all(index[s]["reconciliation"]["missing_count"] == 0
        and index[s]["reconciliation"]["token_mismatch_count"] == 0 for s in valid)
    return {"start": sessions[0], "end": sessions[-1], "requested_sessions": len(sessions),
        "validated_sessions": len(valid), "gap_sessions": [s for s in sessions if s not in valid],
        "longest_validated_run": {"start": best[0] if best else None, "end": best[-1] if best else None, "sessions": len(best)},
        "exact_reconciliation_complete": exact}


def audit_session(session, sample, parent, events, cache, output):
    if not (cache / session / "capture.json").exists():
        return {"session": session, "status": "capture_missing"}
    receipt, content = batch.read_capture(cache / session, session)
    try:
        batch.validate_url(receipt["final_url"], session)
        filename = date.fromisoformat(session).strftime("NSE_CM_security_%d%m%Y.csv.gz")
        if (receipt.get("error") or receipt["status"] != 200
                or receipt["content_disposition"] != f'attachment; filename="{filename}"'):
            raise ValueError("unsuccessful or wrong attachment response")
        body, rows = read_master(content, expected_header(sample["header"], session))
    except (ValueError, zlib.error) as exc:
        return {"session": session, "status": "capture_invalid", "reason": str(exc), "capture": receipt}
    observations = batch.raw_observations(session, parent[session])
    comparison = reconcile(rows, observations)
    normalized, diagnostics = normalize_rows(rows, observations, events, session)
    artifact = compressed_rows(normalized)
    path = output / "rows" / f"{sha(artifact)}.jsonl.gz"
    batch.immutable(path, artifact)
    matched = [r for r in normalized if r["raw_reconciliation"]["status"] == "matched"]
    return {"session": session, "status": "validated", "capture": receipt, "csv_sha256": sha(body),
        "master_rows": len(rows), "raw_receipt": parent[session], "schema_version": normalized[0]["schema_version"],
        "normalized_rows": {"path": str(path), "sha256": sha(artifact), "bytes": len(artifact)},
        "screen_counts_all_master": dict(Counter(r["screen_status"] for r in normalized)),
        "screen_counts_matched_observations": dict(Counter(r["screen_status"] for r in matched)),
        "unknown_code_counts": dict(Counter(f for r in normalized for f in r["unknown_code_fields"])),
        "cas_raw_counts": dict(Counter(r["ElgbltyClsgAuctnSsn"] for r in rows)) if session >= CAS_START else None,
        "new_schema_filler_raw_counts": {f: dict(Counter(r[f] for r in rows)) for f in ("SctyStsRETDBTMkt", "XchgExclsv")} if session >= CAS_START else None,
        "identity_diagnostics": diagnostics, "reconciliation": comparison}


def audit(plan_path, cache, output):
    plan, sample, parent, blocks, plan_hash = load_plan(plan_path)
    results = [audit_session(s, sample, parent, plan["identity_events"], cache, output) for s in plan["sessions"]]
    summaries = [coverage_summary(block, results) for block in blocks]
    result = {"authority": "RESEARCH_ONLY", "can_trade": False, "admissible": False, "admitted_members": 0,
        "plan": plan, "plan_sha256": plan_hash, "sessions": results, "windows": summaries,
        "decision": "DATED_METADATA_EVIDENCE_ONLY",
        "limitations": ["Validated source coverage does not establish historical first availability or ordinary-share eligibility",
            "Identity notices explain discrepancies without rewriting source rows or repairing return histories",
            "No stock universe or strategy performance is certified"]}
    content = batch.payload(result)
    path = output / sha(content) / "report.json"
    batch.immutable(path, content)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("capture", "audit"))
    parser.add_argument("--plan", type=Path, default=ROOT / "config/security-master-daily-v1.json")
    parser.add_argument("--cache", type=Path, default=ROOT / "data/research/nse-master-batch/v1")
    parser.add_argument("--output", type=Path, default=ROOT / "data/reports/security-master-daily")
    args = parser.parse_args()
    print(capture(args.plan, args.cache) if args.action == "capture" else audit(args.plan, args.cache, args.output))


if __name__ == "__main__":
    main()
