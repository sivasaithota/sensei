"""Dated classification coverage only; never an entry-eligibility certificate."""

from dataclasses import dataclass
from dataclasses import asdict
import argparse
import json
from pathlib import Path
import re

import pandas as pd


@dataclass(frozen=True)
class DatedClassification:
    symbol: str
    series: str
    isin: str
    effective_from: pd.Timestamp
    effective_through: pd.Timestamp
    known_from: pd.Timestamp
    security_type: str | None
    board: str | None
    source_sha256: str


def _session(stamp):
    if (not isinstance(stamp, pd.Timestamp) or pd.isna(stamp) or stamp.tz is not None
            or stamp != stamp.normalize()):
        raise ValueError("classification dates require explicit midnight sessions")


def classification_coverage(observed, evidence, *, session, as_of):
    """Reconcile exact observed tuples against caller-transcribed dated facts.

    Evidence hashes identify sources, but this pure checker does not certify their
    content. Intervals and next-session knowledge conventions must be sourced by
    ingestion. An observation is not a complete listing register or stable identity.
    """
    _session(session)
    _session(as_of)
    if as_of > session:
        raise ValueError("classification coverage cannot use later knowledge")
    keys = ["symbol", "series", "isin"]
    if observed.empty or observed[keys].duplicated().any():
        raise ValueError("observed identities must be nonempty and unique")
    identities = [tuple(v if isinstance(v, str) and v.strip() else None for v in row)
        for row in observed[keys].itertuples(index=False, name=None)]
    if len(set(identities)) != len(identities):
        raise ValueError("normalized observed identities must be unique")
    facts = {}
    excluded = {"etf", "reit", "invit", "debt", "preference", "rights", "warrant", "other_nonordinary"}
    for row in evidence:
        for stamp in (row.effective_from, row.effective_through, row.known_from):
            _session(stamp)
        if (row.effective_from > row.effective_through
                or row.security_type not in excluded | {"ordinary_equity", None}
                or row.board not in {"main", "sme", None}
                or not isinstance(row.source_sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", row.source_sha256) is None
                or not all(isinstance(getattr(row, k), str) and getattr(row, k).strip() for k in keys)):
            raise ValueError("invalid dated classification evidence")
        if row.effective_from <= session <= row.effective_through and row.known_from <= as_of:
            identity = tuple(getattr(row, k) for k in keys)
            if identity in facts:
                raise ValueError("overlapping known classification evidence")
            facts[identity] = row
    rows = []
    for identity in identities:
        fact = facts.get(identity)
        if any(v is None for v in identity):
            status = "unresolved_observed_identity"
        elif fact is None:
            status = "unresolved_missing_dated_evidence"
        elif fact.security_type is None:
            status = "unresolved_security_type"
        elif fact.security_type in excluded:
            status = "confirmed_nonordinary"
        elif fact.board is None:
            status = "unresolved_board"
        elif fact.board == "sme":
            status = "confirmed_sme"
        else:
            status = "confirmed_main_board_ordinary"
        rows.append({**dict(zip(keys, identity)), "classification_status": status,
            "source_sha256": fact.source_sha256 if fact else None})
    rows.sort(key=lambda r: tuple(r[k] or "" for k in keys))
    counts = {status: sum(r["classification_status"] == status for r in rows)
        for status in sorted({r["classification_status"] for r in rows})}
    return {"authority": "RESEARCH_ONLY", "can_trade": False, "admissible": False,
        "scope": "Observed tuples only; classification coverage is not universe eligibility",
        "session": str(session.date()), "as_of": str(as_of.date()),
        "observed_count": len(rows), "counts": counts, "rows": rows,
        "unresolved_count": sum(v for k, v in counts.items() if k.startswith("unresolved_")),
        "limitations": ["Caller-transcribed source hashes are not certified classifications",
            "No stable identity, complete listed universe, tradability, liquidity or source-vintage certification",
            "No forward fill beyond explicit evidence intervals; later knowledge remains unavailable"]}


def run(plan_path, output):
    from sensei.data.bhavcopy import QuarantinedRawBhavcopy
    from sensei.research.split_reproduction import pinned, sha

    content = plan_path.read_bytes()
    plan = json.loads(content)
    if (plan["authority"] != "RESEARCH_ONLY" or plan["can_trade"] is not False
            or plan["classification_evidence"] != []
            or plan["sessions"] != ["2024-01-01", "2026-09-03"]):
        raise ValueError("unsupported initial classification gap scope")
    for spec in [plan["contract"], *plan["implementations"]]:
        pinned(spec)
    parent = json.loads(pinned(plan["parent_manifest"]))["identity"]["raw_evidence"]
    store, receipts, reports = QuarantinedRawBhavcopy(), {}, []
    for stamp in plan["sessions"]:
        day = pd.Timestamp(stamp)
        verified = store.verified_session(day.date())
        receipt = json.loads(json.dumps(asdict(verified.reference), default=str))
        if receipt != parent["raw_receipts"][stamp]:
            raise ValueError("classification observation receipt changed")
        receipts[stamp] = receipt
        reports.append(classification_coverage(verified.frame, (), session=day, as_of=day))
    result = {"authority": "RESEARCH_ONLY", "can_trade": False, "admissible": False,
        "decision": "CLASSIFICATION_DATA_BLOCKED", "plan": plan, "plan_sha256": sha(content),
        "implementation_sha256": sha(Path(__file__).read_bytes()), "raw_receipts": receipts,
        "coverage": reports, "limitation": "Two observed endpoint files; no listing-register or intervening-session completeness claim"}
    payload = (json.dumps(result, sort_keys=True, indent=2) + "\n").encode()
    path = output / sha(payload) / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != payload:
        raise ValueError("existing classification report changed")
    path.write_bytes(payload)
    return path


def main():
    from sensei.research.split_reproduction import ROOT

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=ROOT / "config/classification-coverage-sample-v1.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/reports/classification-coverage")
    args = parser.parse_args()
    print(run(args.plan, args.output))


if __name__ == "__main__":
    main()
