from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from sensei.operations import EventAppend, OperationalJournal
import sensei.reporting.prelive as prelive
from sensei.reporting.prelive import PreLiveCertifier


NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


def _append(journal, stream, event_type, payload, *, correlation_id=None):
    return journal.append(
        EventAppend(
            stream_id=stream,
            event_type=event_type,
            payload=payload,
            idempotency_key=f"{stream}:{event_type}",
            expected_version=len(journal.read_stream(stream)),
            occurred_at=NOW,
            correlation_id=correlation_id,
        )
    )


def test_certification_blocks_live_capital_until_exit_learning_is_proven(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    _append(
        journal,
        "lifecycle:plan",
        "StrategyLifecycleTransitioned",
        {"plan_version_id": "sha256:" + "a" * 64, "target_stage": "paper"},
    )

    report = PreLiveCertifier(
        journal_path=tmp_path / "operations.sqlite3",
        strategy_study=lambda: (
            {
                "name": "verified-strategy",
                "adopted": True,
                "out_of_sample": {
                    "trades": 100,
                    "expectancy_pct": 1.0,
                    "hit_rate": 0.45,
                },
            },
        ),
    ).run(generated_at=NOW)

    assert report.ready_for_live_capital is False
    assert "closed_episode_learning_chain" in report.blockers
    exit_check = next(
        check for check in report.checks
        if check.name == "governed_exit_capability"
    )
    assert exit_check.passed is True


def test_certification_requires_one_complete_nine_role_cycle(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    cycle = "cycle:one"
    _append(
        journal,
        "desk-cycle:one",
        "DeskCycleCompleted",
        {"cycle_id": cycle},
        correlation_id=cycle,
    )
    for role in ("orchestrator", "historian", "reporter"):
        _append(
            journal,
            f"role:{role}",
            "DeskRoleCompleted",
            {"role": role},
            correlation_id=cycle,
        )

    report = PreLiveCertifier(
        journal_path=tmp_path / "operations.sqlite3",
        strategy_study=lambda: (
            {"name": "verified-strategy", "adopted": True, "out_of_sample": {}},
        ),
    ).run(generated_at=NOW)

    check = next(
        item for item in report.checks
        if item.name == "nine_agent_production_cycle"
    )
    assert check.passed is False
    assert check.evidence["roles_observed"] == [
        "historian",
        "orchestrator",
        "reporter",
    ]


def test_certification_rejects_a_fresh_strategy_replay_failure(tmp_path):
    OperationalJournal(tmp_path / "operations.sqlite3")

    report = PreLiveCertifier(
        journal_path=tmp_path / "operations.sqlite3",
        strategy_study=lambda: (
            {"name": "good", "adopted": True, "out_of_sample": {}},
            {"name": "bad", "adopted": False, "out_of_sample": {}},
        ),
    ).run(generated_at=NOW)

    check = next(
        item for item in report.checks
        if item.name == "fresh_historical_strategy_replay"
    )
    assert check.passed is False
    assert check.evidence["failed_names"] == ["bad"]


def test_live_entry_and_protection_must_share_one_filled_intent(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    for index, (kind, intent, filled) in enumerate((
        ("ENTRY", "intent:one", 1),
        ("PROTECTION", "intent:two", 0),
    )):
        _append(
            journal,
            f"gateway:{index}",
            "PaperGatewayCommandExecuted",
            {
                "command": {"kind": kind, "intent_id": intent},
                "receipt": {
                    "accepted": True,
                    "cumulative_fill_quantity": filled,
                },
            },
        )

    report = PreLiveCertifier(
        journal_path=tmp_path / "operations.sqlite3",
        strategy_study=lambda: (
            {"name": "verified", "adopted": True, "out_of_sample": {}},
        ),
    ).run(generated_at=NOW)

    check = next(
        item for item in report.checks
        if item.name == "paper_entry_and_protection"
    )
    assert check.passed is False
    assert check.evidence["qualifying_live_intent_ids"] == []


def test_isolated_production_rehearsal_proves_agents_committee_and_protection(
    tmp_path,
):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    config = tmp_path / "scheduler.json"
    config.write_text("{}")
    code_root = Path(prelive.__file__).resolve().parents[1]
    code_digest = hashlib.sha256()
    for item in sorted(code_root.rglob("*.py")):
        code_digest.update(str(item.relative_to(code_root)).encode())
        code_digest.update(item.read_bytes())
    rehearsal = tmp_path / "rehearsal.json"
    rehearsal.write_text(json.dumps({
        "as_of": NOW.isoformat(),
        "state": "WOULD_TRADE",
        "production_state_unchanged": True,
        "real_order_submitted": False,
        "diagnostics": {
            "roles_completed": [
                "orchestrator", "historian", "reporter", "crowd-reader",
                "analyst", "committee", "trader", "coach", "secretary",
            ],
            "committee_verdicts": [
                {"level": level} for level in ("L1", "L2", "L3", "L4")
            ],
            "sandbox_gateway_commands": 2,
            "gateway_command_kinds": ["ENTRY", "PROTECTION"],
            "gateway_command_intent_ids": ["intent:one", "intent:one"],
            "evidence_binding": {
                "source_journal_sha256": hashlib.sha256(
                    journal_path.read_bytes()
                ).hexdigest(),
                "scheduler_config_sha256": hashlib.sha256(
                    config.read_bytes()
                ).hexdigest(),
                "source_code_sha256": code_digest.hexdigest(),
                "source_events": 0,
            },
        },
    }))

    report = PreLiveCertifier(
        journal_path=journal_path,
        rehearsal_path=rehearsal,
        config_path=config,
        strategy_study=lambda: (
            {"name": "verified-strategy", "adopted": True, "out_of_sample": {}},
        ),
    ).run(generated_at=NOW)
    by_name = {check.name: check for check in report.checks}

    assert by_name["nine_agent_production_cycle"].passed is True
    assert by_name["l1_l4_committee_evidence"].passed is True
    assert by_name["paper_entry_and_protection"].passed is True
    assert by_name["governed_exit_capability"].passed is True
    assert by_name["closed_episode_learning_chain"].passed is False
    assert report.ready_for_unattended_paper is False
    assert report.ready_for_live_capital is False
