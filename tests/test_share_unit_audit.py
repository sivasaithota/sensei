import copy
import hashlib
import json

import pytest

from sensei.research.share_unit_audit import audit_screen, audit_trade, run_audit


def example(quantity=35):
    event = dict(exchange_symbol="A", old_isin="old", new_isin="new",
        effective_date="2024-12-27", new_shares_per_old_share=2, sources=["https://exchange.example/split"])
    endpoint = dict(status="matched", raw_identity=dict(symbol="A", isin="old", series="EQ"),
        raw=dict(open=100., high=110., low=90., close=100., volume=1000.),
        kite=dict(open=50., high=55., low=45., close=50., volume=2000.))
    record = dict(source_run_id="source", trade_number=0, snapshot_id="snapshot",
        current_reference=dict(symbol="A-BE", exchange_symbol="A", isin="new"),
        trade=dict(symbol="A-BE", entry_date="2024-05-30", exit_date="2024-05-31", quantity=quantity),
        endpoints=dict(entry_date=copy.deepcopy(endpoint), exit_date=copy.deepcopy(endpoint)))
    screen = dict(can_trade=False, decision="DATA_BLOCKED", source_proofs=[], trades=[record],
        snapshots={"snapshot": {"identity": {"scope_end": "2026-09-04"}}})
    return screen, event


def test_fractional_physical_shares_are_detected_without_mutating_source_trades():
    screen, event = example()
    original = copy.deepcopy(screen)
    result = audit_screen(screen, [event])[0]
    assert result["trade"] == original["trades"][0]["trade"]
    assert screen == original
    assert result["audit"]["status"] == "fractional_physical_equivalent"
    assert (result["audit"]["physical_quantity_numerator"], result["audit"]["physical_quantity_denominator"]) == (35, 2)
    assert result["audit"]["whole_physical_quantity_floor"] == 17
    assert result["audit"]["adjusted_quantity_floor"] == 34
    screen["trades"][0]["trade"]["quantity"] = 30
    assert audit_screen(screen, [event])[0]["audit"]["status"] == "integral_physical_equivalent"


def test_small_synthetic_position_can_round_to_zero_and_duplicates_remain():
    screen, event = example(quantity=1)
    screen["trades"].append(copy.deepcopy(screen["trades"][0]))
    result = audit_screen(screen, [event])
    assert len(result) == 2
    assert all(row["audit"]["adjusted_quantity_floor"] == 0 for row in result)


@pytest.mark.parametrize("entry,exit,as_of,expected", [
    ("2024-12-27", "2024-12-27", "2026-09-04", "outside_pre_split_scope"),
    ("2024-12-26", "2024-12-27", "2026-09-04", "crosses_split_unsupported"),
    ("2024-05-30", "2024-05-31", "2024-12-26", "outside_pre_split_scope"),
])
def test_effective_date_and_capture_boundaries(entry, exit, as_of, expected):
    screen, event = example()
    record = screen["trades"][0]
    record["trade"].update(entry_date=entry, exit_date=exit)
    assert audit_trade(record, [event], as_of=as_of)["status"] == expected


def test_missing_identity_or_scaling_evidence_cannot_pass():
    screen, event = example()
    record = screen["trades"][0]
    assert audit_screen(screen, [])[0]["audit"]["status"] == "outside_evidence_ledger"
    assert audit_screen(screen, [event, event])[0]["audit"]["status"] == "ambiguous_split_evidence"
    endpoint = record["endpoints"]["exit_date"]
    endpoint["raw_identity"]["isin"] = "unknown"
    assert audit_screen(screen, [event])[0]["audit"]["status"] == "identity_mismatch"
    endpoint["raw_identity"]["isin"] = "old"
    endpoint["kite"]["high"] += .1
    assert audit_screen(screen, [event])[0]["audit"]["status"] == "scaling_mismatch"
    endpoint["kite"]["high"] -= .1
    endpoint["raw"]["volume"] = 0
    assert audit_screen(screen, [event])[0]["audit"]["status"] == "scaling_unavailable"
    del record["endpoints"]["exit_date"]
    assert audit_screen(screen, [event])[0]["audit"]["status"] == "endpoint_unavailable"


@pytest.mark.parametrize("field,value", [("quantity", 0), ("quantity", True),
    ("entry_date", "bad"), ("exit_date", "2024-01-01"), ("exit_date", "2027-01-01")])
def test_invalid_trade_inputs_fail(field, value):
    screen, event = example()
    screen["trades"][0]["trade"][field] = value
    with pytest.raises(ValueError):
        audit_screen(screen, [event])


@pytest.mark.parametrize("multiplier", [0, 1, True, 2.5])
def test_invalid_split_multiplier_fails(multiplier):
    screen, event = example()
    event["new_shares_per_old_share"] = multiplier
    with pytest.raises(ValueError):
        audit_screen(screen, [event])


def test_artifact_pins_screen_note_and_source_proof(tmp_path):
    screen, event = example()
    proof_path = tmp_path / "proof.json"
    proof_path.write_text("{}")
    screen["source_proofs"] = [{"proof_path": str(proof_path),
        "proof_sha256": hashlib.sha256(proof_path.read_bytes()).hexdigest()}]
    content = json.dumps(screen).encode()
    digest = hashlib.sha256(content).hexdigest()
    screen_path = tmp_path / digest / "report.json"
    screen_path.parent.mkdir()
    screen_path.write_bytes(content)
    screen_path.with_name("report.sha256").write_text(digest)
    note_path = tmp_path / "note.md"
    note_path.write_text("Evidence note")
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps(dict(events=[event], research_note="note.md",
        research_note_sha256=hashlib.sha256(note_path.read_bytes()).hexdigest())))
    result_path = run_audit(screen_path, ledger_path, tmp_path / "output")
    result = json.loads(result_path.read_text())
    assert result["can_trade"] is False and len(result["trades"]) == 1
    assert hashlib.sha256(result_path.read_bytes()).hexdigest() == result_path.parent.name
    note_path.write_text("changed")
    with pytest.raises(ValueError, match="research note changed"):
        run_audit(screen_path, ledger_path, tmp_path / "output")
    proof_path.write_text("changed")
    with pytest.raises(ValueError, match="source proof changed"):
        run_audit(screen_path, ledger_path, tmp_path / "output")
    screen_path.write_bytes(content + b" ")
    with pytest.raises(ValueError, match="checksum mismatch"):
        run_audit(screen_path, ledger_path, tmp_path / "output")
