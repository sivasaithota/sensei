"""Offline validation of one captured NSE MII master; no eligibility inference."""

import argparse
from collections import Counter
from dataclasses import asdict
import csv
import gzip
import io
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import zipfile

import pandas as pd

from sensei.data.bhavcopy import QuarantinedRawBhavcopy
from sensei.research.split_reproduction import ROOT, pinned, sha


def read_master(content, expected_header):
    if len(content) > 4 * 1024 * 1024 or not content.startswith(b"\x1f\x8b"):
        raise ValueError("invalid or oversized gzip master")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(content)) as stream:
            body = stream.read(32 * 1024 * 1024 + 1)
        if len(body) > 32 * 1024 * 1024:
            raise ValueError("master decompression limit exceeded")
        reader = csv.reader(io.StringIO(body.decode("utf-8-sig")), strict=True)
        header = next(reader)
        if header != expected_header or len(header) != len(set(header)):
            raise ValueError("master header differs from pinned sample schema")
        rows, identities, tokens = [], set(), set()
        for fields in reader:
            if len(fields) != len(header) or len(rows) >= 100_000:
                raise ValueError("master row shape or count limit violated")
            row = dict(zip(header, fields))
            key = tuple(row[k] for k in ("TckrSymb", "SctySrs", "ISIN"))
            token = row["FinInstrmId"]
            if key in identities or not token or token in tokens:
                raise ValueError("master duplicate identity or token")
            identities.add(key)
            tokens.add(token)
            rows.append(row)
        if not rows:
            raise ValueError("empty master")
        return body, rows
    except (OSError, EOFError, UnicodeError, csv.Error, StopIteration, KeyError) as exc:
        raise ValueError("malformed master") from exc


def reconcile(master, observations):
    keys = ("TckrSymb", "SctySrs", "ISIN")
    index = {tuple(r[k] for k in keys): r for r in master}
    observed_keys = [tuple(r[k] for k in keys) for r in observations]
    if not observations or len(set(observed_keys)) != len(observed_keys) or len(index) != len(master):
        raise ValueError("empty or ambiguous reconciliation inputs")
    matches, missing, mismatches = [], [], []
    for row, key in zip(observations, observed_keys):
        match = index.get(key)
        if match is None:
            missing.append({**dict(zip(keys, key)), "raw_token": row["FinInstrmId"]})
        elif match["FinInstrmId"] != row["FinInstrmId"]:
            mismatches.append({**dict(zip(keys, key)), "master_token": match["FinInstrmId"], "raw_token": row["FinInstrmId"]})
        else:
            matches.append(match)
    return {"observed_count": len(observations), "matched_count": len(matches),
        "matched_rows": [{k: r[k] for k in (*keys, "FinInstrmId", "SctyTpFlg")} for r in matches],
        "missing_count": len(missing), "token_mismatch_count": len(mismatches),
        "missing": missing, "token_mismatches": mismatches,
        "master_only_count": len(set(index) - set(observed_keys)),
        "matched_raw_type_flags": dict(sorted(Counter(r["SctyTpFlg"] for r in matches).items())),
        "classification_inference": "None: code meanings, board, status and knowledge require separate evidence"}


def run(plan_path, output):
    content = plan_path.read_bytes()
    plan = json.loads(content)
    if plan["authority"] != "RESEARCH_ONLY" or plan["can_trade"] is not False or plan["session"] != "2025-01-06":
        raise ValueError("unsupported master sample scope")
    for spec in [plan["contract"], *plan["implementations"], *plan["schema_evidence"]]:
        pinned(spec)
    capture = json.loads(pinned(plan["capture"]))
    for url in (capture["url"], capture["final_url"]):
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        expected = [{"name": "CM - MII - Security File (.gz) (NSE Listed securities)",
            "type": "daily-reports", "category": "capital-market", "section": "equities"}]
        if (parsed.scheme != "https" or parsed.netloc != "www.nseindia.com" or parsed.path != "/api/reports"
                or query.get("date") != ["06-Jan-2025"] or query.get("type") != ["equities"]
                or query.get("mode") != ["single"] or json.loads(query.get("archives", ["null"])[0]) != expected):
            raise ValueError("wrong dated master or exchange scope")
    if (capture["status"] != 200 or capture["requested_date"] != plan["session"]
            or capture["content_disposition"] != 'attachment; filename="NSE_CM_security_06012025.csv.gz"'):
        raise ValueError("master response metadata mismatch")
    compressed = pinned(capture)
    body, master = read_master(compressed, plan["header"])
    if len(compressed) != capture["bytes"] or sha(body) != plan["csv_sha256"]:
        raise ValueError("master size or decompressed hash changed")
    verified = QuarantinedRawBhavcopy().verified_session(pd.Timestamp(plan["session"]).date())
    receipt = json.loads(json.dumps(asdict(verified.reference), default=str))
    parent = json.loads(pinned(plan["parent_manifest"]))["identity"]["raw_evidence"]
    if receipt != parent["raw_receipts"][plan["session"]]:
        raise ValueError("raw receipt changed")
    with zipfile.ZipFile(io.BytesIO(pinned(plan["raw_zip"]))) as archive:
        names = archive.namelist()
        if len(names) != 1 or archive.getinfo(names[0]).file_size > 32 * 1024 * 1024:
            raise ValueError("unexpected raw archive")
        raw = archive.read(names[0])
    if sha(raw) != receipt["csv_sha256"]:
        raise ValueError("raw CSV changed")
    observations = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    if {r["TradDt"] for r in observations} != {plan["session"]}:
        raise ValueError("raw observation date mismatch")
    result = {"authority": "RESEARCH_ONLY", "can_trade": False, "admissible": False,
        "plan": plan, "plan_sha256": sha(content), "implementation_sha256": sha(Path(__file__).read_bytes()),
        "capture": capture, "raw_receipt": receipt, "master_rows": len(master), "header_fields": len(plan["header"]),
        "master_raw_type_flags": dict(sorted(Counter(r["SctyTpFlg"] for r in master).items())),
        "blank_columns": [k for k in plan["header"] if all(not r[k] for r in master)],
        "reconciliation": reconcile(master, observations),
        "examples": [r for r in master if r["TckrSymb"] in {"SBIN", "BANKBEES", "HEG", "MAZDOCK"} and r["SctySrs"] == "EQ"],
        "date_limitation": "Requested date and server filename verified; no body business-date field or historical publication timestamp certified",
        "decision": "METADATA_SAMPLE_CAPTURED_NOT_CLASSIFIED"}
    payload = (json.dumps(result, sort_keys=True, indent=2) + "\n").encode()
    path = output / sha(payload) / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != payload:
        raise ValueError("existing sample report changed")
    path.write_bytes(payload)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=ROOT / "config/security-master-sample-v1.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/reports/security-master-sample")
    args = parser.parse_args()
    print(run(args.plan, args.output))


if __name__ == "__main__":
    main()
