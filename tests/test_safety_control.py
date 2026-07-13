from datetime import datetime, timezone

import pytest

from sensei.operations.journal import OperationalJournal
from sensei.portfolio_risk import (
    OwnerAuthorization,
    ReconciliationHealth,
    SafetyAction,
    SafetyBlocked,
    SafetyResetRejected,
    SafetyControl,
)


NOW = datetime(2026, 7, 13, 4, 0, tzinfo=timezone.utc)


def test_latched_safety_blocks_entries_but_never_protection_or_cancel(tmp_path):
    safety = SafetyControl(OperationalJournal(tmp_path / "journal.sqlite3"))
    safety.latch(
        reason_code="UNPROTECTED_EXPOSURE",
        detail="INFY has 4 unprotected shares",
        occurred_at=NOW,
        idempotency_key="latch-infy-1",
    )

    assert safety.state().latched is True
    with pytest.raises(SafetyBlocked, match="UNPROTECTED_EXPOSURE"):
        safety.assert_allowed(SafetyAction.ENTRY)

    safety.assert_allowed(SafetyAction.PROTECTION)
    safety.assert_allowed(SafetyAction.CANCEL_ENTRY)


def test_safety_reset_requires_owner_scope_and_clean_reconciliation(tmp_path):
    safety = SafetyControl(OperationalJournal(tmp_path / "journal.sqlite3"))
    safety.latch(
        reason_code="BROKER_MISMATCH",
        detail="unknown position",
        occurred_at=NOW,
        idempotency_key="latch-1",
    )
    no_scope = OwnerAuthorization(
        owner_id="owner-1", scopes=frozenset(), authenticated_at=NOW
    )
    owner = OwnerAuthorization(
        owner_id="owner-1",
        scopes=frozenset({"safety:reset"}),
        authenticated_at=NOW,
    )

    with pytest.raises(SafetyResetRejected, match="owner authorization"):
        safety.reset(
            no_scope,
            ReconciliationHealth(clean=True, observed_at=NOW),
            occurred_at=NOW,
            idempotency_key="reset-1",
        )
    with pytest.raises(SafetyResetRejected, match="clean reconciliation"):
        safety.reset(
            owner,
            ReconciliationHealth(
                clean=False, observed_at=NOW, detail="still mismatched"
            ),
            occurred_at=NOW,
            idempotency_key="reset-2",
        )

    safety.reset(
        owner,
        ReconciliationHealth(clean=True, observed_at=NOW),
        occurred_at=NOW,
        idempotency_key="reset-3",
    )
    assert safety.state().latched is False
    safety.assert_allowed(SafetyAction.ENTRY)
