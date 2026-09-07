import gzip
import json

import pytest

from sensei.research import security_master_daily as daily


HEADER = [f"field{i}" for i in range(120)]
HEADER[23], HEADER[58] = "ElgbltyRETDBTMkt", "Rsvd01"
EVENT = {"old_symbol": "AHL", "new_symbol": "AFSL", "announced_on": "2025-03-25",
    "effective_from": "2025-04-01", "source_sha256": "a" * 64}
RAW = {"TckrSymb": "AHL", "SctySrs": "BE", "ISIN": "INE00ZE01026", "FinInstrmId": "13293"}
MASTER = {**RAW, "TckrSymb": "AFSL"}
QUALIFYING = {**RAW, "SctySrs": "EQ", "SctyTpFlg": "0", "CallAuctnInd": "1",
    "SctyStsNrmlMkt": "2", "ElgbltyNrmlMkt": "1", "PrtdToTrad": "0", "DelFlg": "N", "NewBrdLotQty": "1"}


def test_schema_boundary_is_exact_and_does_not_rename_other_fields():
    assert daily.expected_header(HEADER, "2026-08-02") == HEADER
    result = daily.expected_header(HEADER, "2026-08-03")
    assert [(i, value) for i, value in enumerate(result) if value != HEADER[i]] == [
        (23, "ElgbltyClsgAuctnSsn"), (58, "XchgExclsv")]
    assert HEADER[23] == "ElgbltyRETDBTMkt"


def test_announced_future_symbol_explains_but_does_not_repair_exact_identity():
    result = daily.identity_diagnostics([MASTER], [RAW], [EVENT], "2025-03-28")
    assert result[0]["status"] == "master_ahead_of_effective_symbol"
    assert result[0]["raw"] == RAW and result[0]["master"] == MASTER
    assert result[0]["source_sha256"] == "a" * 64
    assert MASTER["TckrSymb"] == "AFSL" and RAW["TckrSymb"] == "AHL"


@pytest.mark.parametrize("session,raw,master,status", [
    ("2025-03-24", RAW, MASTER, "unexplained_identity_difference"),
    ("2025-04-01", RAW, MASTER, "raw_symbol_outside_notice_interval"),
    ("2025-04-01", MASTER, RAW, "master_stale_after_effective_symbol"),
    ("2025-03-28", MASTER, RAW, "raw_symbol_outside_notice_interval"),
    ("2025-03-28", RAW, {**MASTER, "ISIN": "OTHER"}, "unexplained_identity_difference"),
    ("2025-03-28", RAW, {**MASTER, "SctySrs": "EQ"}, "unexplained_identity_difference"),
])
def test_notice_is_not_a_generic_token_alias(session, raw, master, status):
    assert daily.identity_diagnostics([master], [raw], [EVENT], session)[0]["status"] == status


def test_different_token_does_not_create_an_identity_event():
    assert daily.identity_diagnostics([{**MASTER, "FinInstrmId": "999"}], [RAW], [EVENT], "2025-03-28") == []


def test_contiguous_windows_use_all_exchange_sessions_and_cannot_drop_a_failure():
    calendar = ["2025-03-27", "2025-03-28", "2025-04-01", "2025-04-02"]
    windows = [{"start": calendar[0], "end": calendar[-1]}]
    assert daily.window_sessions(windows, calendar) == [calendar]
    rows = [{"session": day, "status": "validated", "reconciliation": {"missing_count": 0, "token_mismatch_count": 0}} for day in calendar]
    rows[1] = {"session": calendar[1], "status": "capture_invalid"}
    summary = daily.coverage_summary(calendar, rows)
    assert summary["requested_sessions"] == 4 and summary["validated_sessions"] == 3
    assert summary["longest_validated_run"] == {"start": "2025-04-01", "end": "2025-04-02", "sessions": 2}
    assert not summary["exact_reconciliation_complete"]


def test_schema_coverage_and_exact_reconciliation_are_distinct():
    calendar = ["2025-03-28", "2025-04-01"]
    rows = [{"session": day, "status": "validated", "reconciliation": {"missing_count": int(i == 0), "token_mismatch_count": 0}} for i, day in enumerate(calendar)]
    summary = daily.coverage_summary(calendar, rows)
    assert summary["longest_validated_run"]["sessions"] == 2
    assert not summary["exact_reconciliation_complete"]


def test_gzip_rows_are_deterministic_and_retain_all_fields():
    rows = [{"raw": RAW, "can_trade": False}, {"raw": MASTER, "can_trade": False}]
    first = daily.compressed_rows(rows)
    assert first == daily.compressed_rows(rows)
    assert [json.loads(line) for line in gzip.decompress(first).splitlines()] == rows


@pytest.mark.parametrize("cas,expected", [("0", "ineligible"), ("1", "eligible"), ("9", None)])
def test_cas_schema_decodes_only_documented_field_and_retains_fillers(cas, expected):
    source = {**QUALIFYING, "ElgbltyClsgAuctnSsn": cas, "SctyStsRETDBTMkt": "3", "XchgExclsv": ""}
    rows, _ = daily.normalize_rows([source], [source], [], "2026-08-03")
    row = rows[0]
    assert row["decoded"]["ElgbltyClsgAuctnSsn"] == expected
    assert row["schema_version"] == "mii-cas-20260803"
    assert "SctyStsRETDBTMkt" not in row["decoded"] and "XchgExclsv" not in row["decoded"]
    assert row["raw"] == source and not row["admissible"] and not row["can_trade"]
    if expected is None:
        assert row["screen_status"] == "unresolved_metadata"
        assert "ElgbltyClsgAuctnSsn" in row["unknown_code_fields"]


def test_notice_counterpart_cannot_remain_a_provisional_candidate():
    master = {**QUALIFYING, "TckrSymb": "AFSL"}
    rows, diagnostics = daily.normalize_rows([master], [QUALIFYING], [EVENT], "2025-03-28")
    row = rows[0]
    assert row["screen_status"] == "unresolved_metadata"
    assert row["identity_diagnostics"] == diagnostics
    assert row["raw_reconciliation"]["status"] == "master_only"
    assert "dated_identity_difference" in row["admission_blockers"]


def test_plan_cannot_omit_requested_calendar_sessions(monkeypatch, tmp_path):
    calendar = {day: {} for day in ("2025-03-27", "2025-03-28", "2025-04-01")}
    plan = {"authority": "RESEARCH_ONLY", "can_trade": False, "contract": {"path": "contract"},
        "implementations": [], "schema_evidence": [], "reuse_evidence": [], "identity_events": [],
        "sample_plan": {"path": "sample"}, "windows": [{"start": "2025-03-27", "end": "2025-04-01"}],
        "probe_sessions": [], "sessions": ["2025-03-27", "2025-04-01"]}
    sources = {"contract": b"spec", "sample": json.dumps({"parent_manifest": {"path": "parent"}}).encode(),
        "parent": json.dumps({"identity": {"raw_evidence": {"raw_receipts": calendar}}}).encode()}
    monkeypatch.setattr(daily, "pinned", lambda spec: sources[spec["path"]])
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    with pytest.raises(ValueError, match="complete windows"):
        daily.load_plan(path)


def test_capture_partitions_preserve_dates_and_spacing(monkeypatch, tmp_path):
    sessions = [f"2025-01-{day:02d}" for day in range(1, 16)]
    plan = {key: [] for key in ("implementations", "schema_evidence")}
    plan.update(authority="RESEARCH_ONLY", can_trade=False, contract={}, sample_plan={}, sessions=sessions)
    monkeypatch.setattr(daily, "load_plan", lambda path: (plan, None, None, None, None))
    seen, pauses = [], []
    def capture(path, cache, pause):
        part = json.loads(path.read_text())
        seen.append(part["sessions"])
        return {"network_requests": len(part["sessions"])}
    monkeypatch.setattr(daily.batch, "capture", capture)
    result = daily.capture(None, tmp_path, pause=pauses.append)
    assert [len(part) for part in seen] == [6, 6, 3]
    assert [s for part in seen for s in part] == sessions
    assert pauses == [1, 1] and result["network_requests"] == 15


def test_bad_capture_is_a_gap_but_changed_cache_is_a_hard_error(monkeypatch, tmp_path):
    session = "2025-03-28"
    folder = tmp_path / session
    folder.mkdir()
    content = bytes.fromhex("1f8b0800000000000003ff")
    receipt = {"requested_date": session, "url": daily.batch.report_url(session), "final_url": daily.batch.report_url(session),
        "status": 200, "content_disposition": 'attachment; filename="NSE_CM_security_28032025.csv.gz"',
        "bytes": len(content), "sha256": daily.sha(content)}
    (folder / "capture.json").write_text(json.dumps(receipt))
    (folder / "response.bin").write_bytes(content)
    result = daily.audit_session(session, {"header": HEADER}, {}, [], tmp_path, tmp_path / "out")
    assert result["status"] == "capture_invalid"
    (folder / "response.bin").write_bytes(b"changed")
    with pytest.raises(ValueError, match="cache bytes"):
        daily.audit_session(session, {"header": HEADER}, {}, [], tmp_path, tmp_path / "out")
