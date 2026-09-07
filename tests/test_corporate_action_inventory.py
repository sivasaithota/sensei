import copy
import hashlib
import json

import pytest

from sensei.research.corporate_action_inventory import build_inventory, summarize


def example():
    record = dict(source_run_id="source", trade_number=0,
        trade=dict(symbol="A", entry_date="2024-01-01", exit_date="2024-01-02"),
        current_reference=dict(symbol="A", isin="new"),
        endpoints=dict(entry_date=dict(status="matched", kite_over_raw_volume=2.,
            raw_identity=dict(symbol="A", isin="old")),
            exit_date=dict(status="raw_session_not_captured")))
    screen = dict(can_trade=False, decision="DATA_BLOCKED", source_proofs=[], trades=[record])
    registry = {"A": dict(kind="split", note_ids=["note"])}
    return screen, registry


def test_inventory_preserves_duplicate_trades_missing_records_and_observation_ranges():
    screen, registry = example()
    screen["trades"].append(copy.deepcopy(screen["trades"][0]))
    screen["trades"][1]["source_run_id"] = "second_source"
    before = copy.deepcopy(screen)
    result = summarize(screen, registry)
    assert screen == before
    assert result["trade_records"] == 2 and result["flagged_symbols"] == 1
    assert result["endpoint_statuses"] == dict(matched=2, raw_session_not_captured=2)
    assert result["unknown_volume_endpoint_count"] == 2
    assert result["class_endpoint_counts"] == {"split": 2}
    assert result["symbols"]["A"]["observed_volume_ratio_range"] == [2., 2.]
    assert [r["source_run_id"] for r in result["symbols"]["A"]["trade_records"]] == ["source", "second_source"]


def test_unflagged_symbols_are_not_implicitly_certified_and_unknown_classes_remain_unknown():
    screen, registry = example()
    extra = copy.deepcopy(screen["trades"][0])
    extra["trade"]["symbol"] = "B"
    extra["endpoints"]["entry_date"]["kite_over_raw_volume"] = 1.
    screen["trades"].append(extra)
    registry["A"]["kind"] = "unresolved"
    result = summarize(screen, registry)
    assert result["symbols"]["B"]["classification"] is None
    assert result["class_symbol_counts"] == {"unresolved": 1}


def test_registry_cannot_omit_or_add_flagged_symbols_or_invent_classes():
    screen, registry = example()
    with pytest.raises(ValueError, match="exactly"):
        summarize(screen, {})
    with pytest.raises(ValueError, match="exactly"):
        summarize(screen, {**registry, "B": registry["A"]})
    registry["A"]["kind"] = "volume_inferred_split"
    with pytest.raises(ValueError, match="invalid action classification"):
        summarize(screen, registry)
    del screen["trades"][0]["endpoints"]["exit_date"]
    with pytest.raises(ValueError, match="both endpoint records"):
        summarize(screen, {})


def test_inventory_pins_screen_proof_and_research_note(tmp_path):
    screen, symbols = example()
    proof = tmp_path / "proof.json"
    proof.write_text("{}")
    screen["source_proofs"] = [dict(proof_path=str(proof),
        proof_sha256=hashlib.sha256(proof.read_bytes()).hexdigest())]
    content = json.dumps(screen).encode()
    digest = hashlib.sha256(content).hexdigest()
    source = tmp_path / digest / "report.json"
    source.parent.mkdir()
    source.write_bytes(content)
    source.with_name("report.sha256").write_text(digest)
    note = tmp_path / "note.md"
    note.write_text("Primary source note")
    registry = dict(symbols=symbols, notes={"note": dict(path="note.md",
        sha256=hashlib.sha256(note.read_bytes()).hexdigest())})
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(registry))
    result_path = build_inventory(source, registry_path, tmp_path / "output")
    result = json.loads(result_path.read_text())
    assert result["can_trade"] is False and result["inventory"]["trade_records"] == 1
    assert hashlib.sha256(result_path.read_bytes()).hexdigest() == result_path.parent.name
    note.write_text("changed")
    with pytest.raises(ValueError, match="research note changed"):
        build_inventory(source, registry_path, tmp_path / "output")
    proof.write_text("changed")
    with pytest.raises(ValueError, match="source proof changed"):
        build_inventory(source, registry_path, tmp_path / "output")
    source.write_bytes(content + b" ")
    with pytest.raises(ValueError, match="checksum mismatch"):
        build_inventory(source, registry_path, tmp_path / "output")
