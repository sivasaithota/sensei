"""Validate a partial notice register; never infer a historical constituent set."""

import argparse
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse


ACTIONS = {"include", "exclude", "dummy_include", "revoke_include", "revoke_exclude"}


def digest(content):
    return hashlib.sha256(content).hexdigest()


def validate_register(register):
    if (register["authority"] != "RESEARCH_ONLY" or register["can_trade"] is not False
            or register["completeness"] != "INCOMPLETE_NOTICE_REGISTER"
            or register["index"] != "Nifty 500" or register["membership_intervals"]
            or not register["missing_requirements"]):
        raise ValueError("partial notices cannot certify membership or trading eligibility")
    start, end = date.fromisoformat(register["window_start"]), date.fromisoformat(register["window_end"])
    if start > end:
        raise ValueError("invalid notice window")
    date.fromisoformat(register["known_through_date"])
    events, notices, urls = {}, set(), set()
    for notice in register["documents"]:
        key = notice["notice_id"]
        if key in notices or notice["url"] in urls or not notice["events"]:
            raise ValueError("duplicate or empty notice")
        notices.add(key)
        urls.add(notice["url"])
        published, effective, prior = (date.fromisoformat(notice[k]) for k in
            ("published_date", "effective_date", "prior_close_date"))
        if published > effective or prior >= effective:
            raise ValueError("invalid publication/effective/prior-close dates")
        if type(notice["page_count"]) is not int or notice["page_count"] < 1:
            raise ValueError("invalid source page count")
        for event in notice["events"]:
            identity = f"{key}:{event['action']}:{event['symbol']}"
            if event["id"] != identity or identity in events:
                raise ValueError("invalid or duplicate event identity")
            if (event["action"] not in ACTIONS or event["index"] != "Nifty 500"
                    or not event["symbol"] or not event["company_name"]
                    or event["stable_instrument_id"] is not None):
                raise ValueError("invalid partial membership event")
            if type(event["source_page"]) is not int or not 1 <= event["source_page"] <= notice["page_count"]:
                raise ValueError("event cites invalid PDF page")
            if event["symbol"].startswith("DUMMY") and event["action"] != "dummy_include":
                raise ValueError("dummy constituent must remain explicitly non-tradable")
            events[identity] = {**event, "notice_id": key,
                "published_date": str(published), "effective_date": str(effective),
                "prior_close_date": str(prior)}
    revoked = set()
    for event in events.values():
        if not event["action"].startswith("revoke_"):
            if "revokes" in event:
                raise ValueError("only revocations may name a target")
            continue
        target = events.get(event.get("revokes"))
        if (target is None or target["action"] != event["action"].removeprefix("revoke_")
                or target["symbol"] != event["symbol"] or target["effective_date"] != event["effective_date"]
                or target["published_date"] > event["published_date"] or target["id"] in revoked):
            raise ValueError("revocation must uniquely match the original announced change")
        revoked.add(target["id"])
    return events


def classify_events(register):
    events = validate_register(register)
    known = date.fromisoformat(register["known_through_date"])
    start, end = (date.fromisoformat(register[k]) for k in ("window_start", "window_end"))
    cancellations = {e["revokes"]: e["id"] for e in events.values()
        if e["action"].startswith("revoke_") and date.fromisoformat(e["published_date"]) <= known}
    result = []
    for event in sorted(events.values(), key=lambda x: (x["effective_date"], x["published_date"], x["id"])):
        if date.fromisoformat(event["published_date"]) > known:
            status = "not_yet_announced"
        elif event["id"] in cancellations:
            status = "revoked"
        elif event["action"].startswith("revoke_"):
            status = "revocation_record"
        elif date.fromisoformat(event["effective_date"]) > min(end, known):
            status = "future_effective"
        elif date.fromisoformat(event["effective_date"]) < start:
            status = "before_window"
        else:
            status = "effective_notice_row_in_window"
        result.append({**event, "status": status, "revoked_by": cancellations.get(event["id"]),
            "index_placeholder": event["action"] == "dummy_include"})
    return result


def load_verified_register(path):
    content = path.read_bytes()
    register = json.loads(content)
    validate_register(register)
    capture_path = (path.parent / register["capture_manifest_path"]).resolve()
    captured = capture_path.read_bytes()
    if digest(captured) != register["capture_manifest_sha256"]:
        raise ValueError("capture manifest changed")
    captures = json.loads(captured)["captures"]
    by_url = {c["url"]: c for c in captures}
    if len(by_url) != len(captures) or set(by_url) != {d["url"] for d in register["documents"]}:
        raise ValueError("notice register must account for every captured document")
    for notice in register["documents"]:
        receipt = by_url[notice["url"]]
        for source in (notice["url"], receipt.get("final_url", "")):
            url = urlparse(source)
            if url.scheme != "https" or url.hostname != "www.niftyindices.com" or not url.path.startswith("/Press_Release/"):
                raise ValueError("unexpected notice source")
        pdf = (path.parent / notice["pdf_path"]).resolve().read_bytes()
        if (receipt.get("http_status") != 200 or receipt["sha256"] != notice["pdf_sha256"]
                or not pdf.startswith(b"%PDF-") or digest(pdf) != notice["pdf_sha256"]
                or len(pdf) != receipt["bytes"]):
            raise ValueError("notice PDF does not match its pinned capture")
    return register, digest(content)


def audit_register(path, output):
    register, registry_sha = load_verified_register(path)
    events = classify_events(register)
    result = {"registry_path": str(path.resolve()), "registry_sha256": registry_sha,
        "implementation_sha256": digest(Path(__file__).read_bytes()),
        "capture_manifest_sha256": register["capture_manifest_sha256"],
        "window_start": register["window_start"], "window_end": register["window_end"],
        "known_through_date": register["known_through_date"], "notice_count": len(register["documents"]),
        "event_count": len(events), "status_counts": dict(Counter(e["status"] for e in events)),
        "events": events, "missing_requirements": register["missing_requirements"],
        "membership_intervals": [], "entry_eligibility": None,
        "authority": "RESEARCH_ONLY", "decision": "DATA_BLOCKED", "can_trade": False,
        "limitations": ["Observed announcements only; not a complete change register or constituent set",
            "Known-through date means end-of-day publication knowledge, not intraday availability",
            "No stable-instrument lineage or entry eligibility inferred; dummy inclusion is index accounting only",
            "Other uncollected corrections can supersede currently retained notice rows"]}
    content = (json.dumps(result, sort_keys=True, indent=2) + "\n").encode()
    sha = digest(content)
    destination = output / sha
    destination.mkdir(parents=True, exist_ok=True)
    report = destination / "report.json"
    if report.exists() and report.read_bytes() != content:
        raise ValueError("existing notice audit changed")
    report.write_bytes(content)
    report.with_name("report.sha256").write_text(sha + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--register", type=Path, default=Path("config/nifty500-notice-register-v1.json"))
    parser.add_argument("--output", type=Path, default=Path("data/reports/membership-notices"))
    args = parser.parse_args()
    print(audit_register(args.register, args.output))


if __name__ == "__main__":
    main()
