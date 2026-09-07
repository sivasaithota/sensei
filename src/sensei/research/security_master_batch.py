"""Bounded NSE master capture and offline candidate audit; never a live universe."""

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime, timezone
import csv
import io
import json
from pathlib import Path
import time
from urllib.parse import parse_qs, urlencode, urlparse
import zipfile
import zlib

import httpx

from sensei.data.bhavcopy import QuarantinedRawBhavcopy
from sensei.research.security_master_sample import read_master, reconcile
from sensei.research.split_reproduction import ROOT, pinned, sha


DESCRIPTOR = [{"name": "CM - MII - Security File (.gz) (NSE Listed securities)",
    "type": "daily-reports", "category": "capital-market", "section": "equities"}]
BODY_LIMIT = 4 * 1024 * 1024
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/138 Safari/537.36",
    "Accept": "*/*", "Referer": "https://www.nseindia.com/all-reports"}
DICTIONARIES = {
    "SctyTpFlg": {"0": "equities", "1": "preference_shares", "2": "debentures", "3": "warrants", "4": "miscellaneous"},
    "CallAuctnInd": {"1": "normal_market", "2": "ipo_session", "3": "relisting_session", "4": "call_auction_2", "5": "sme"},
    "SctyStsNrmlMkt": {"1": "preopen", "2": "open", "3": "suspended", "4": "extended_preopen", "5": "opens_with_market", "6": "price_discovery"},
    "ElgbltyNrmlMkt": {"0": "ineligible", "1": "eligible"},
    "PrtdToTrad": {"0": "listed", "1": "permitted_to_trade"},
}
SME_SERIES = {"SM", "ST", "SZ", "SL", "SO", "SQ"}


def payload(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def immutable(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError(f"immutable artifact changed: {path}")
    else:
        with path.open("xb") as stream:
            stream.write(content)


def report_url(session):
    day = date.fromisoformat(session)
    return "https://www.nseindia.com/api/reports?" + urlencode({
        "archives": json.dumps(DESCRIPTOR, separators=(",", ":")),
        "date": day.strftime("%d-%b-%Y"), "type": "equities", "mode": "single"})


def validate_url(url, session):
    expected, actual = urlparse(report_url(session)), urlparse(url)
    if ((actual.scheme, actual.netloc, actual.path, actual.fragment) !=
            (expected.scheme, expected.netloc, expected.path, "")
            or parse_qs(actual.query) != parse_qs(expected.query)):
        raise ValueError("wrong dated master or exchange scope")


def load_plan(path):
    content = path.read_bytes()
    plan = json.loads(content)
    sessions = plan["sessions"]
    if (plan["authority"] != "RESEARCH_ONLY" or plan["can_trade"] is not False
            or not 1 <= len(sessions) <= 6 or sorted(set(sessions)) != sessions
            or any(date.fromisoformat(s).isoformat() != s for s in sessions)):
        raise ValueError("unsupported batch scope")
    for spec in [plan["contract"], *plan["implementations"], *plan["schema_evidence"], *plan.get("capture_evidence", [])]:
        pinned(spec)
    sample = json.loads(pinned(plan["sample_plan"]))
    parent = json.loads(pinned(sample["parent_manifest"]))["identity"]["raw_evidence"]["raw_receipts"]
    if not set(sessions) <= set(parent) or not set(plan["seeds"]) <= set(sessions):
        raise ValueError("batch dates lack frozen raw coverage")
    return plan, sample, parent, sha(content)


def read_capture(directory, session):
    receipt = json.loads((directory / "capture.json").read_bytes())
    if receipt["requested_date"] != session:
        raise ValueError("cache date changed")
    validate_url(receipt["url"], session)
    body = (directory / "response.bin").read_bytes()
    if len(body) != receipt["bytes"] or len(body) > BODY_LIMIT or sha(body) != receipt["sha256"]:
        raise ValueError("cache bytes changed")
    return receipt, body


def capture(plan_path, cache, client=None, pause=time.sleep):
    plan, _, _, plan_hash = load_plan(plan_path)
    if client is None:
        with httpx.Client(headers=HEADERS, timeout=15, follow_redirects=False) as connection:
            return capture(plan_path, cache, connection, pause)
    requests = 0
    for session in plan["sessions"]:
        directory = cache / session
        if (directory / "capture.json").exists():
            read_capture(directory, session)
            continue
        if (directory / "response.bin").exists():
            raise ValueError("incomplete cache requires inspection")
        if session in plan["seeds"]:
            source = json.loads(pinned(plan["seeds"][session]))
            body = pinned(source)
            if source["requested_date"] != session or len(body) != source["bytes"]:
                raise ValueError("seed capture mismatch")
            validate_url(source["url"], session)
            receipt = {**source, "seed_receipt": plan["seeds"][session]}
        else:
            if requests:
                pause(1)
            requests += 1
            body = bytearray()
            receipt = {"requested_date": session, "url": report_url(session), "status": None,
                "final_url": report_url(session), "content_disposition": "", "content_type": ""}
            try:
                with client.stream("GET", receipt["url"]) as response:
                    receipt.update(status=response.status_code, final_url=str(response.url),
                        content_type=response.headers.get("content-type", ""),
                        content_disposition=response.headers.get("content-disposition", ""))
                    for chunk in response.iter_bytes(chunk_size=65536):
                        if len(body) + len(chunk) > BODY_LIMIT:
                            raise ValueError("response body limit exceeded")
                        body.extend(chunk)
            except (httpx.HTTPError, ValueError) as exc:
                receipt["error"] = type(exc).__name__
            receipt["captured_at_utc"] = datetime.now(timezone.utc).isoformat()
        receipt.update(bytes=len(body), sha256=sha(bytes(body)), plan_sha256=plan_hash)
        receipt.pop("path", None)
        immutable(directory / "response.bin", bytes(body))
        immutable(directory / "capture.json", payload(receipt))
    return {"network_requests": requests, "sessions": len(plan["sessions"]), "kite_requests": 0}


def normalize(row, session):
    decoded, unknown = {}, []
    for field, dictionary in DICTIONARIES.items():
        values = dict(dictionary)
        if field == "PrtdToTrad" and session >= "2025-04-01":
            values["2"] = "bse_listed"
        decoded[field] = values.get(row[field])
        if decoded[field] is None:
            unknown.append(field)
    reasons = ["unknown_code:" + key for key in unknown]
    if row["PrtdToTrad"] == "2":
        reasons.append("nse_only_scope_permission_2")
    if row["SctyTpFlg"] in {"1", "2", "3", "4"}:
        reasons.append("non_equity_broad_class")
    if row["CallAuctnInd"] == "5" or row["SctySrs"] in SME_SERIES:
        reasons.append("documented_sme_marker")
    excluded = bool(set(reasons) & {"non_equity_broad_class", "documented_sme_marker"})
    for field, expected in {"SctyTpFlg": "0", "SctySrs": "EQ", "CallAuctnInd": "1",
            "ElgbltyNrmlMkt": "1", "PrtdToTrad": "0", "DelFlg": "N", "NewBrdLotQty": "1"}.items():
        if row[field] != expected:
            reasons.append("candidate_filter:" + field)
    if row["SctyStsNrmlMkt"] == "3":
        reasons.append("suspended")
    if not all(row[k] for k in ("TckrSymb", "SctySrs", "ISIN", "FinInstrmId")):
        reasons.append("incomplete_identity")
    state = "excluded_known_non_target" if excluded else "unresolved_metadata" if reasons else "provisional_candidate"
    return {"session": session, "raw": row, "decoded": decoded, "screen_status": state,
        "screen_reasons": reasons, "unknown_code_fields": unknown,
        "admission_blockers": ["ordinary_share_subtype", "main_board_evidence", "historical_schema_applicability", "historical_first_availability"],
        "admissible": False, "can_trade": False}


def annotate_reconciliation(normalized, observations):
    keys = ("TckrSymb", "SctySrs", "ISIN")
    observed = {tuple(r[k] for k in keys): r for r in observations}
    for row in normalized:
        match = observed.get(tuple(row["raw"][k] for k in keys))
        if match is None:
            row["raw_reconciliation"] = {"status": "master_only"}
        elif match["FinInstrmId"] == row["raw"]["FinInstrmId"]:
            row["raw_reconciliation"] = {"status": "matched", "raw_token": match["FinInstrmId"]}
        else:
            row["raw_reconciliation"] = {"status": "token_conflict", "raw_token": match["FinInstrmId"]}
            row["screen_status"] = "unresolved_metadata"
            row["screen_reasons"].append("raw_identity_token_conflict")
            row["admission_blockers"].append("raw_identity_token_conflict")


def raw_observations(session, expected):
    verified = QuarantinedRawBhavcopy().verified_session(date.fromisoformat(session))
    receipt = json.loads(json.dumps(asdict(verified.reference), default=str))
    if receipt != expected:
        raise ValueError("raw receipt changed")
    path = ROOT / "data/nse_bhavcopy_raw" / session[:4] / f"BhavCopy_{session.replace('-', '')}.csv.zip"
    body = path.read_bytes()
    # The receipt's source ZIP hash is checked independently of the normalized file.
    if sha(body) != receipt["zip_sha256"]:
        raise ValueError("raw ZIP changed")
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        names = archive.namelist()
        if len(names) != 1 or archive.getinfo(names[0]).file_size > 32 * 1024 * 1024:
            raise ValueError("unexpected raw archive")
        raw = archive.read(names[0])
    if sha(raw) != receipt["csv_sha256"]:
        raise ValueError("raw CSV changed")
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    if not rows or {r["TradDt"] for r in rows} != {session}:
        raise ValueError("raw observation date mismatch")
    return rows


def audit(plan_path, cache, output):
    plan, sample, parent, plan_hash = load_plan(plan_path)
    results = []
    for session in plan["sessions"]:
        directory = cache / session
        if not (directory / "capture.json").exists():
            results.append({"session": session, "status": "capture_missing"})
            continue
        receipt, content = read_capture(directory, session)
        try:
            validate_url(receipt["final_url"], session)
            filename = date.fromisoformat(session).strftime("NSE_CM_security_%d%m%Y.csv.gz")
            if (receipt.get("error") or receipt["status"] != 200
                    or receipt["content_disposition"] != f'attachment; filename="{filename}"'):
                raise ValueError("unsuccessful or wrong attachment response")
            body, rows = read_master(content, sample["header"])
        except (ValueError, zlib.error) as exc:
            results.append({"session": session, "status": "capture_invalid", "reason": str(exc), "capture": receipt})
            continue
        observations = raw_observations(session, parent[session])
        comparison = reconcile(rows, observations)
        normalized = [normalize(row, session) for row in rows]
        annotate_reconciliation(normalized, observations)
        matched = [r for r in normalized if r["raw_reconciliation"]["status"] == "matched"]
        artifact = b"".join((json.dumps(r, sort_keys=True) + "\n").encode() for r in normalized)
        artifact_hash = sha(artifact)
        artifact_path = output / "rows" / f"{artifact_hash}.jsonl"
        immutable(artifact_path, artifact)
        results.append({"session": session, "status": "validated", "capture": receipt,
            "csv_sha256": sha(body), "master_rows": len(rows), "raw_receipt": parent[session],
            "normalized_rows": {"path": str(artifact_path), "sha256": artifact_hash},
            "screen_counts_all_master": dict(Counter(r["screen_status"] for r in normalized)),
            "screen_counts_matched_observations": dict(Counter(r["screen_status"] for r in matched)),
            "unknown_code_counts": dict(Counter(f for r in normalized for f in r["unknown_code_fields"])),
            "raw_code_counts": {field: dict(Counter(r[field] for r in rows)) for field in DICTIONARIES},
            "reconciliation": comparison})
    complete = all(r["status"] == "validated" and r["reconciliation"]["missing_count"] == 0
        and r["reconciliation"]["token_mismatch_count"] == 0 for r in results)
    result = {"authority": "RESEARCH_ONLY", "can_trade": False, "admissible": False,
        "admitted_members": 0, "plan": plan, "plan_sha256": plan_hash, "sessions": results,
        "all_sampled_observations_reconciled": complete,
        "decision": "CANDIDATE_EVIDENCE_ONLY" if complete else "SAMPLED_COVERAGE_GAPS",
        "limitations": ["Five isolated snapshots do not establish daily coverage",
            "Request date and attachment filename are not original publication time",
            "Decoded codes and candidate screen do not certify a historical stock universe"]}
    content = payload(result)
    path = output / sha(content) / "report.json"
    immutable(path, content)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("capture", "audit"))
    parser.add_argument("--plan", type=Path, default=ROOT / "config/security-master-batch-v2.json")
    parser.add_argument("--cache", type=Path, default=ROOT / "data/research/nse-master-batch/v1")
    parser.add_argument("--output", type=Path, default=ROOT / "data/reports/security-master-batch")
    args = parser.parse_args()
    print(capture(args.plan, args.cache) if args.action == "capture" else audit(args.plan, args.cache, args.output))


if __name__ == "__main__":
    main()
