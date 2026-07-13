from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from sensei.migration.legacy import (
    LegacyFileKind,
    LegacyImportManifest,
    LegacyImporter,
    LegacySource,
)
from sensei.operations.journal import OperationalJournal


NOW = datetime(2026, 7, 13, 9, 15, tzinfo=timezone.utc)


def _jsonl(*records: dict) -> bytes:
    return b"".join(
        json.dumps(record, sort_keys=True).encode("utf-8") + b"\n"
        for record in records
    )


def test_import_is_read_only_content_fingerprinted_and_idempotent(tmp_path):
    first_thesis = {
        "id": "TH-REUSED",
        "symbol": "AAA",
        "entry_zone_low": 100,
        "entry_zone_high": 101,
        "evidence": ["legacy price scan"],
    }
    revised_thesis = {
        **first_thesis,
        "symbol": "BBB",
        "entry_zone_low": 200,
        "entry_zone_high": 202,
        "evidence": [],
    }
    audit = tmp_path / "audit.jsonl"
    audit.write_bytes(
        _jsonl(
            {"ts": NOW.isoformat(), "event": "thesis_submitted", "thesis": first_thesis},
            {
                "ts": (NOW + timedelta(minutes=1)).isoformat(),
                "event": "thesis_submitted",
                "thesis": revised_thesis,
            },
            {
                "ts": (NOW + timedelta(minutes=2)).isoformat(),
                "event": "verdict",
                "thesis_id": "TH-REUSED",
                "approved": True,
            },
        )
    )
    pending = tmp_path / "pending.json"
    pending.write_text(
        json.dumps(
            [
                {
                    "queued": "2026-07-13",
                    "record": {"thesis": first_thesis, "verdicts": []},
                }
            ]
        )
    )
    positions = tmp_path / "positions.json"
    positions.write_text(
        json.dumps(
            {
                "cash": 40_000,
                "positions": [
                    {
                        "thesis_id": "TH-REUSED",
                        "symbol": "AAA",
                        "quantity": 10,
                    }
                ],
            }
        )
    )
    closed = tmp_path / "closed.jsonl"
    closed.write_bytes(
        _jsonl(
            {
                "thesis_id": "TH-OLD",
                "symbol": "OLD",
                "pnl": 999.0,
                "closed": "2026-07-12",
            }
        )
    )
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_bytes(
        _jsonl(
            {
                "ts": NOW.isoformat(),
                "thesis_id": "TH-OLD",
                "pattern": "late chase",
            }
        )
    )
    missing = tmp_path / "submissions-that-do-not-exist.jsonl"
    sources = (
        LegacySource("audit", LegacyFileKind.AUDIT, audit),
        LegacySource("pending", LegacyFileKind.PENDING, pending),
        LegacySource("paper-positions", LegacyFileKind.PAPER_POSITIONS, positions),
        LegacySource("paper-closed", LegacyFileKind.PAPER_CLOSED, closed),
        LegacySource("mistake-ledger", LegacyFileKind.LEDGER, ledger),
        LegacySource("standalone-submissions", LegacyFileKind.SUBMISSIONS, missing),
    )
    before = {source.label: source.path.read_bytes() for source in sources if source.path.exists()}
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    importer = LegacyImporter(journal)

    first = importer.import_manifest(LegacyImportManifest(sources), imported_at=NOW)
    repeated = importer.import_manifest(
        LegacyImportManifest(sources),
        imported_at=NOW + timedelta(days=1),
    )

    assert first.imported_facts == 8
    assert first.previously_imported_facts == 0
    assert first.missing_sources == ("standalone-submissions",)
    assert repeated.imported_facts == 0
    assert repeated.previously_imported_facts == 8
    assert len(journal.read_stream("legacy:imports")) == 8
    assert {source.label: source.path.read_bytes() for source in sources if source.path.exists()} == before

    events = journal.read_stream("legacy:imports")
    audit_events = [event for event in events if event.payload["source_label"] == "audit"]
    assert all(
        event.payload["source_sha256"]
        == "sha256:" + hashlib.sha256(audit.read_bytes()).hexdigest()
        for event in audit_events
    )
    submissions = [
        event
        for event in audit_events
        if event.payload["fact_type"] == "thesis_submitted"
    ]
    assert [event.payload["legacy_thesis_id"] for event in submissions] == [
        "TH-REUSED",
        "TH-REUSED",
    ]
    assert len({event.payload["thesis_fingerprint"] for event in submissions}) == 2
    assert submissions[0].payload["evidence_status"] == "PARTIAL"
    assert submissions[1].payload["evidence_status"] == "MISSING"
    assert "legacy_thesis_evidence" in submissions[1].payload["missing_evidence"]

    for event in events:
        assert event.event_type == "LegacyFactImported"
        assert event.payload["authority"] == "HISTORICAL_FACT_ONLY"
        assert event.payload["can_authorize_lifecycle"] is False
        assert event.payload["can_authorize_trading"] is False

    absent = next(event for event in events if event.payload["source_label"] == "standalone-submissions")
    assert absent.payload["fact_type"] == "missing_source"
    assert absent.payload["source_sha256"] is None
    assert absent.payload["evidence_status"] == "MISSING"


def test_unparseable_legacy_line_is_preserved_as_a_non_authoritative_fact(tmp_path):
    audit = tmp_path / "audit.jsonl"
    audit.write_bytes(b'{"event":"verdict","approved":true}\nnot-json\n')
    original = audit.read_bytes()
    journal = OperationalJournal(tmp_path / "journal.sqlite3")

    summary = LegacyImporter(journal).import_manifest(
        LegacyImportManifest((LegacySource("audit", LegacyFileKind.AUDIT, audit),)),
        imported_at=NOW,
    )

    assert summary.imported_facts == 2
    invalid = journal.read_stream("legacy:imports")[1]
    assert invalid.payload["fact_type"] == "unparseable_record"
    assert invalid.payload["parse_status"] == "INVALID"
    assert invalid.payload["evidence_status"] == "MISSING"
    assert invalid.payload["record_sha256"].startswith("sha256:")
    assert "record" not in invalid.payload
    assert audit.read_bytes() == original
