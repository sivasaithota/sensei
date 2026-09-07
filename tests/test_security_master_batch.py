import gzip
import json

import httpx
import pytest

from sensei.research import security_master_batch as batch


ROW = {"TckrSymb": "SBIN", "SctySrs": "EQ", "ISIN": "INE062A01020", "FinInstrmId": "3045",
    "SctyTpFlg": "0", "CallAuctnInd": "1", "SctyStsNrmlMkt": "6", "ElgbltyNrmlMkt": "1",
    "PrtdToTrad": "0", "DelFlg": "N", "NewBrdLotQty": "1"}
SESSION = "2025-01-06"


def setup_plan(monkeypatch, sessions=(SESSION,)):
    plan = {"sessions": list(sessions), "seeds": {}}
    monkeypatch.setattr(batch, "load_plan", lambda path: (plan, {"header": list(ROW)}, {s: {} for s in sessions}, "plan-hash"))
    return plan


def response(status=200, content=None, filename="06012025"):
    if content is None:
        content = gzip.compress((",".join(ROW) + "\n" + ",".join(ROW.values()) + "\n").encode())
    return httpx.Response(status, content=content,
        headers={"content-disposition": f'attachment; filename="NSE_CM_security_{filename}.csv.gz"'})


def test_candidate_is_never_admitted_and_raw_fields_are_retained():
    result = batch.normalize(ROW, SESSION)
    assert result["screen_status"] == "provisional_candidate"
    assert result["raw"] == ROW
    assert result["decoded"]["SctyStsNrmlMkt"] == "price_discovery"
    assert not result["can_trade"] and not result["admissible"]
    assert len(result["admission_blockers"]) == 4


@pytest.mark.parametrize("change,state,reason", [
    ({"SctyTpFlg": "4"}, "excluded_known_non_target", "non_equity_broad_class"),
    ({"CallAuctnInd": "5"}, "excluded_known_non_target", "documented_sme_marker"),
    ({"SctySrs": "SM"}, "excluded_known_non_target", "documented_sme_marker"),
    ({"SctyTpFlg": "9"}, "unresolved_metadata", "unknown_code:SctyTpFlg"),
    ({"SctyStsNrmlMkt": "3"}, "unresolved_metadata", "suspended"),
    ({"CallAuctnInd": "2"}, "unresolved_metadata", "candidate_filter:CallAuctnInd"),
    ({"ISIN": ""}, "unresolved_metadata", "incomplete_identity"),
    ({"ElgbltyNrmlMkt": "0"}, "unresolved_metadata", "candidate_filter:ElgbltyNrmlMkt"),
])
def test_unknown_nonordinary_sme_and_unavailable_records_do_not_enter_candidates(change, state, reason):
    result = batch.normalize({**ROW, **change}, SESSION)
    assert result["screen_status"] == state
    assert reason in result["screen_reasons"]


def test_permission_extension_is_date_bounded_and_still_not_nse_candidate():
    row = {**ROW, "PrtdToTrad": "2"}
    before = batch.normalize(row, "2025-03-31")
    after = batch.normalize(row, "2025-04-01")
    assert before["decoded"]["PrtdToTrad"] is None
    assert "PrtdToTrad" in before["unknown_code_fields"]
    assert after["decoded"]["PrtdToTrad"] == "bse_listed"
    assert after["screen_status"] == "unresolved_metadata"


@pytest.mark.parametrize("change", [
    lambda url: url.replace("www.nseindia.com", "example.com"),
    lambda url: url.replace("06-Jan-2025", "07-Jan-2025"),
    lambda url: url.replace("NSE+Listed", "BSE+Listed"),
    lambda url: url + "&date=06-Jan-2025",
])
def test_wrong_source_date_venue_and_ambiguous_query_reject(change):
    with pytest.raises(ValueError, match="scope"):
        batch.validate_url(change(batch.report_url(SESSION)), SESSION)


def test_capture_resume_reuses_success_and_failure_without_requests(monkeypatch, tmp_path):
    setup_plan(monkeypatch, (SESSION, "2025-04-01"))
    seen, pauses = [], []
    def handler(request):
        seen.append(str(request.url))
        return response() if len(seen) == 1 else response(404, b"missing")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first = batch.capture(None, tmp_path, client, pauses.append)
        second = batch.capture(None, tmp_path, client, pauses.append)
    assert first["network_requests"] == 2 and second["network_requests"] == 0
    assert len(seen) == 2 and pauses == [1]
    assert batch.read_capture(tmp_path / "2025-04-01", "2025-04-01")[0]["status"] == 404
    (tmp_path / SESSION / "response.bin").write_bytes(b"changed")
    with pytest.raises(ValueError, match="cache bytes"):
        batch.capture(None, tmp_path, client)


def test_capture_timeout_is_saved_and_not_retried(monkeypatch, tmp_path):
    setup_plan(monkeypatch)
    def handler(request):
        raise httpx.ReadTimeout("timeout")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        batch.capture(None, tmp_path, client)
        assert batch.capture(None, tmp_path, client)["network_requests"] == 0
    receipt, body = batch.read_capture(tmp_path / SESSION, SESSION)
    assert receipt["error"] == "ReadTimeout" and body == b""


def test_oversized_response_is_bounded_and_recorded(monkeypatch, tmp_path):
    setup_plan(monkeypatch)
    monkeypatch.setattr(batch, "BODY_LIMIT", 20)
    with httpx.Client(transport=httpx.MockTransport(lambda req: response(content=b"x" * 21))) as client:
        batch.capture(None, tmp_path, client)
    receipt, body = batch.read_capture(tmp_path / SESSION, SESSION)
    assert len(body) <= 20 and receipt["error"] == "ValueError"


def test_audit_conserves_all_rows_and_surfaces_partial_batch(monkeypatch, tmp_path):
    setup_plan(monkeypatch, (SESSION, "2025-04-01"))
    monkeypatch.setattr(batch, "raw_observations", lambda session, expected: [ROW, {**ROW, "ISIN": "OTHER"}])
    def handler(request):
        return response() if "06-Jan" in str(request.url) else response(404, b"missing")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        batch.capture(None, tmp_path / "cache", client, lambda _: None)
    path = batch.audit(None, tmp_path / "cache", tmp_path / "out")
    report = json.loads(path.read_text())
    assert report["decision"] == "SAMPLED_COVERAGE_GAPS"
    assert not report["all_sampled_observations_reconciled"]
    assert report["sessions"][1]["status"] == "capture_invalid"
    first = report["sessions"][0]
    assert first["reconciliation"]["observed_count"] == 2
    assert first["reconciliation"]["matched_count"] == first["reconciliation"]["missing_count"] == 1
    assert first["screen_counts_matched_observations"] == {"provisional_candidate": 1}
    assert report["admitted_members"] == 0
    assert batch.audit(None, tmp_path / "cache", tmp_path / "out") == path


def test_corrupt_cache_is_a_hard_error_not_an_absence(monkeypatch, tmp_path):
    setup_plan(monkeypatch)
    with httpx.Client(transport=httpx.MockTransport(lambda req: response())) as client:
        batch.capture(None, tmp_path / "cache", client)
    (tmp_path / "cache" / SESSION / "response.bin").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="cache bytes"):
        batch.audit(None, tmp_path / "cache", tmp_path / "out")


def test_wrong_attachment_and_missing_capture_are_explicit_gaps(monkeypatch, tmp_path):
    setup_plan(monkeypatch)
    missing = json.loads(batch.audit(None, tmp_path / "cache", tmp_path / "out").read_text())
    assert missing["sessions"][0]["status"] == "capture_missing"
    with httpx.Client(transport=httpx.MockTransport(lambda req: response(filename="07012025"))) as client:
        batch.capture(None, tmp_path / "cache", client)
    wrong = json.loads(batch.audit(None, tmp_path / "cache", tmp_path / "out").read_text())
    assert wrong["sessions"][0]["status"] == "capture_invalid"


def test_bad_deflate_does_not_prevent_auditing_subsequent_dates(monkeypatch, tmp_path):
    setup_plan(monkeypatch, (SESSION, "2025-04-01"))
    monkeypatch.setattr(batch, "raw_observations", lambda session, expected: [ROW])
    def handler(request):
        if "06-Jan" in str(request.url):
            return response(content=bytes.fromhex("1f8b0800000000000003ff"))
        return response(filename="01042025")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        batch.capture(None, tmp_path / "cache", client, lambda _: None)
    report = json.loads(batch.audit(None, tmp_path / "cache", tmp_path / "out").read_text())
    assert [r["status"] for r in report["sessions"]] == ["capture_invalid", "validated"]
    assert not report["all_sampled_observations_reconciled"]


def test_normalized_artifact_retains_token_conflict_and_master_only_status(monkeypatch, tmp_path):
    setup_plan(monkeypatch)
    monkeypatch.setattr(batch, "raw_observations", lambda session, expected: [{**ROW, "FinInstrmId": "999"}])
    with httpx.Client(transport=httpx.MockTransport(lambda req: response())) as client:
        batch.capture(None, tmp_path / "cache", client)
    report = json.loads(batch.audit(None, tmp_path / "cache", tmp_path / "out").read_text())
    session = report["sessions"][0]
    assert session["reconciliation"]["token_mismatch_count"] == 1
    assert session["screen_counts_matched_observations"] == {}
    artifact = batch.Path(session["normalized_rows"]["path"])
    row = json.loads(artifact.read_text())
    assert row["screen_status"] == "unresolved_metadata"
    assert row["raw_reconciliation"] == {"status": "token_conflict", "raw_token": "999"}
    assert "raw_identity_token_conflict" in row["admission_blockers"]
    standalone = [batch.normalize(ROW, SESSION)]
    batch.annotate_reconciliation(standalone, [])
    assert standalone[0]["raw_reconciliation"] == {"status": "master_only"}
