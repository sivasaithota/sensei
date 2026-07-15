import json
from datetime import datetime, timezone

from sensei.automation.migration import adopt_legacy_positions, migrate_adopted_strategies
from sensei.operations import OperationalJournal
from sensei.strategy import StrategyPlanCatalog


NOW = datetime(2026, 7, 16, tzinfo=timezone.utc)


def test_migration_registers_only_adopted_rules(tmp_path):
    playbook = tmp_path / "playbook.json"
    rules = tmp_path / "rules.json"
    playbook.write_text(json.dumps({"strategies": [
        {"name": "accepted", "adopted": True},
        {"name": "rejected", "adopted": False},
    ]}))
    rules.write_text(json.dumps([
        {"name": "accepted", "source": "book", "principle": "trend", "conditions": [
            {"left": "close", "op": ">", "right": "sma_20", "factor": 1.0}
        ], "stop_pct": 5.0, "target_pct": 10.0, "max_hold_days": 20},
        {"name": "rejected", "source": "book", "principle": "trend", "conditions": [
            {"left": "close", "op": ">", "right": "sma_20", "factor": 1.0}
        ], "stop_pct": 5.0, "target_pct": 10.0, "max_hold_days": 20},
    ]))
    journal = OperationalJournal(tmp_path / "operations.sqlite3")

    result = migrate_adopted_strategies(
        journal, playbook_path=playbook, rules_path=rules, occurred_at=NOW
    )

    assert [item.source_rule_name for item in result.registered] == ["accepted"]
    assert len(StrategyPlanCatalog(journal).list()) == 1


def test_position_adoption_is_observation_only_and_restart_safe(tmp_path):
    positions = tmp_path / "positions.json"
    positions.write_text(json.dumps({"cash": 1000, "positions": [{
        "symbol": "INFY", "quantity": 2, "entry_price": 100.0,
        "stop_loss": 95.0, "targets": [110.0], "opened": "2026-07-01"
    }]}))
    journal = OperationalJournal(tmp_path / "operations.sqlite3")

    first = adopt_legacy_positions(journal, positions_path=positions, occurred_at=NOW)
    second = adopt_legacy_positions(journal, positions_path=positions, occurred_at=NOW)

    assert first == second
    events = journal.read_stream("legacy-paper-position-adoption")
    assert len(events) == 1
    assert events[0].payload["authority"] == "OBSERVATION_ONLY"
    assert events[0].payload["requires_broker_reconciliation"] is True
