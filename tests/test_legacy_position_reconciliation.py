import json
from datetime import datetime, timezone

import pytest

from sensei.automation.migration import adopt_legacy_positions
from sensei.operations import OperationalJournal
from sensei.runtime.adoption import LegacyPositionAdoptionRegistry, LegacyPositionDrift


NOW = datetime(2026, 7, 16, tzinfo=timezone.utc)


def write_positions(path, *, quantity=2):
    path.write_text(json.dumps({"cash": 10_000.0, "positions": [{
        "symbol": "INFY", "quantity": quantity, "entry_price": 100.0,
        "stop_loss": 95.0, "targets": [110.0], "opened": "2026-07-01"
    }]}))


def test_reconciliation_projects_exact_protected_inventory_and_account(tmp_path):
    path = tmp_path / "positions.json"
    write_positions(path)
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    adopt_legacy_positions(journal, positions_path=path, occurred_at=NOW)
    registry = LegacyPositionAdoptionRegistry(journal, positions_path=path)

    truth = registry.reconcile(
        mark_prices_paise={"INFY": 10_500},
        captured_at=NOW,
        command_id="legacy-reconcile-1",
    )

    assert truth.broker_snapshot.positions[0].quantity == 2
    assert truth.broker_snapshot.protections[0].stop_price_paise == 9_500
    assert truth.account_snapshot.available_cash_paise == 1_000_000
    assert truth.account_snapshot.marked_equity_paise == 1_021_000
    assert truth.account_snapshot.reconciled is True
    assert truth.reconciliation_event_id.startswith("event:")


def test_reconciliation_fails_closed_when_legacy_inventory_changes(tmp_path):
    path = tmp_path / "positions.json"
    write_positions(path)
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    adopt_legacy_positions(journal, positions_path=path, occurred_at=NOW)
    registry = LegacyPositionAdoptionRegistry(journal, positions_path=path)
    write_positions(path, quantity=3)

    with pytest.raises(LegacyPositionDrift, match="changed"):
        registry.reconcile(
            mark_prices_paise={"INFY": 10_500},
            captured_at=NOW,
            command_id="legacy-reconcile-drift",
        )
