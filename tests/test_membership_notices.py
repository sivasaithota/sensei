import copy
import json
from pathlib import Path

import pytest

from sensei.research.membership_notices import (
    audit_register, classify_events, digest, load_verified_register, validate_register,
)


@pytest.fixture
def register():
    return json.loads(Path("config/nifty500-notice-register-v1.json").read_text())


def indexed(register):
    return {e["id"]: e for e in classify_events(register)}


def test_march_correction_cancels_both_original_rows(register):
    rows = indexed(register)
    for action, symbol in [("include", "IREDA"), ("exclude", "VGUARD")]:
        original = rows[f"ind_prs28022024:{action}:{symbol}"]
        correction = rows[f"ind_prs19032024:revoke_{action}:{symbol}"]
        assert original["status"] == "revoked"
        assert original["revoked_by"] == correction["id"]
        assert correction["status"] == "revocation_record"


@pytest.mark.parametrize("known", ["2024-03-18", "20240318"])
def test_correction_cannot_cancel_before_publication(register, known):
    register["known_through_date"] = known
    rows = indexed(register)
    original = rows["ind_prs28022024:include:IREDA"]
    assert original["status"] == "future_effective"
    assert original["revoked_by"] is None
    assert rows["ind_prs19032024:revoke_include:IREDA"]["status"] == "not_yet_announced"


def test_future_announcements_and_dummy_are_not_historical_membership(register):
    rows = indexed(register)
    dummy = rows["ind_prs03092026:dummy_include:DUMMYHEG"]
    assert dummy["status"] == "future_effective"
    assert dummy["index_placeholder"] is True
    assert all(e["status"] == "future_effective" for e in rows.values()
        if e["notice_id"] == "ind_prs10082026")
    register["known_through_date"] = "2026-09-02"
    assert indexed(register)[dummy["id"]]["status"] == "not_yet_announced"


@pytest.mark.parametrize("field,value", [
    ("authority", "LIVE"), ("can_trade", True), ("completeness", "COMPLETE"),
    ("membership_intervals", [{"symbol": "IREDA"}]), ("missing_requirements", []),
])
def test_partial_register_cannot_certify_eligibility(register, field, value):
    register[field] = value
    with pytest.raises(ValueError, match="cannot certify"):
        validate_register(register)


@pytest.mark.parametrize("target", ["missing", "ind_prs28022024:exclude:VGUARD"])
def test_revocation_must_match_original(register, target):
    correction = next(d for d in register["documents"] if d["kind"] == "correction")
    correction["events"][0]["revokes"] = target
    with pytest.raises(ValueError, match="revocation must"):
        validate_register(register)


def test_duplicate_source_rejected_even_with_another_notice_id(register):
    duplicate = copy.deepcopy(register["documents"][0])
    duplicate["notice_id"] = "another_name"
    register["documents"].append(duplicate)
    with pytest.raises(ValueError, match="duplicate"):
        validate_register(register)


def test_invalid_source_page_rejected(register):
    register["documents"][0]["events"][0]["source_page"] = 0
    with pytest.raises(ValueError, match="PDF page"):
        validate_register(register)


def local_capture(tmp_path, register):
    # Synthetic PDF envelope tests byte provenance without requiring local market data.
    register["documents"] = [register["documents"][0]]
    notice = register["documents"][0]
    pdf = b"%PDF-1.7\nsynthetic fixture\n"
    (tmp_path / "source.pdf").write_bytes(pdf)
    notice["pdf_path"] = "source.pdf"
    notice["pdf_sha256"] = digest(pdf)
    capture = json.dumps({"captures": [{"url": notice["url"], "final_url": notice["url"], "http_status": 200,
        "sha256": digest(pdf), "bytes": len(pdf)}]}).encode()
    (tmp_path / "manifest.json").write_bytes(capture)
    register["capture_manifest_path"] = "manifest.json"
    register["capture_manifest_sha256"] = digest(capture)
    path = tmp_path / "register.json"
    path.write_text(json.dumps(register))
    return path


@pytest.mark.parametrize("filename,message", [
    ("source.pdf", "pinned capture"), ("manifest.json", "manifest changed"),
])
def test_capture_tampering_rejected(tmp_path, register, filename, message):
    path = local_capture(tmp_path, register)
    assert load_verified_register(path)[0] == register
    with (tmp_path / filename).open("ab") as changed:
        changed.write(b" ")
    with pytest.raises(ValueError, match=message):
        load_verified_register(path)


def test_audit_remains_inadmissible_and_reproducible(tmp_path, register):
    path = local_capture(tmp_path, register)
    first = audit_register(path, tmp_path / "reports")
    assert audit_register(path, tmp_path / "reports") == first
    report = json.loads(first.read_text())
    assert report["decision"] == "DATA_BLOCKED"
    assert report["can_trade"] is False
    assert report["entry_eligibility"] is None
    assert report["membership_intervals"] == []
    assert report["registry_sha256"] == digest(path.read_bytes())


def test_pinned_official_request_cannot_certify_unofficial_redirect(tmp_path, register):
    path = local_capture(tmp_path, register)
    capture_path = tmp_path / "manifest.json"
    capture = json.loads(capture_path.read_text())
    capture["captures"][0]["final_url"] = "https://example.org/Press_Release/fake.pdf"
    capture_path.write_text(json.dumps(capture))
    register["capture_manifest_sha256"] = digest(capture_path.read_bytes())
    path.write_text(json.dumps(register))
    with pytest.raises(ValueError, match="unexpected notice source"):
        load_verified_register(path)
