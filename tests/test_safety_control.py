from datetime import datetime, timedelta, timezone

import pytest

from sensei.operations import (
    EventAppend,
    HmacFactSigner,
    HmacFactVerifier,
    OperationalJournal,
)
from sensei.portfolio_risk import (
    SafetyAction,
    SafetyBlocked,
    SafetyResetRejected,
    SafetyControl,
    SafetyResetAuthority,
)


NOW = datetime(2026, 7, 13, 4, 0, tzinfo=timezone.utc)
OWNER_SECRET = b"owner-reset-test-secret-at-least-32-bytes"
RECON_SECRET = b"reconciler-test-secret-at-least-32-bytes"


def _authority(journal):
    return SafetyResetAuthority(
        journal,
        owner_verifier=HmacFactVerifier({"owner-1": OWNER_SECRET}),
        reconciliation_verifier=HmacFactVerifier(
            {"kernel-reconciler": RECON_SECRET}
        ),
        expected_reconciliation_issuer_id="kernel-reconciler",
    )


def _reconciliation(journal, authority, *, clean, suffix, occurred_at=NOW):
    broker_event_id = "event:" + suffix * 64
    snapshot_id = "broker-snapshot:" + suffix * 64
    issues = () if clean else ("still mismatched",)
    kernel_events = journal.read_stream("kernel:paper")
    kernel_event = journal.append(
        EventAppend(
            stream_id="kernel:paper",
            event_type="ReconciliationClean" if clean else "QuarantineRaised",
            payload={
                "snapshot_id": snapshot_id,
                "broker_snapshot_event_id": broker_event_id,
                "issues": list(issues),
            },
            idempotency_key=f"kernel-reconciliation-{suffix}",
            expected_version=len(kernel_events),
            occurred_at=occurred_at,
        )
    )
    return authority.attest_reconciliation(
        kernel_event_id=kernel_event.event_id,
        broker_snapshot_event_id=broker_event_id,
        snapshot_id=snapshot_id,
        clean=clean,
        issues=issues,
        signer=HmacFactSigner("kernel-reconciler", RECON_SECRET),
        occurred_at=occurred_at,
        command_id=f"attest-reconciliation-{suffix}",
    )


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
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    authority = _authority(journal)
    safety = SafetyControl(journal, reset_authority=authority)
    safety.latch(
        reason_code="BROKER_MISMATCH",
        detail="unknown position",
        occurred_at=NOW,
        idempotency_key="latch-1",
    )
    no_scope = authority.authorize_owner(
        owner_id="owner-1",
        scopes=frozenset(),
        signer=HmacFactSigner("owner-1", OWNER_SECRET),
        occurred_at=NOW,
        command_id="owner-no-scope",
    )
    owner = authority.authorize_owner(
        owner_id="owner-1",
        scopes=frozenset({"safety:reset"}),
        signer=HmacFactSigner("owner-1", OWNER_SECRET),
        occurred_at=NOW,
        command_id="owner-with-scope",
    )
    clean_before_dirty = _reconciliation(
        journal, authority, clean=True, suffix="1"
    )

    with pytest.raises(SafetyResetRejected, match="owner authorization"):
        safety.reset(
            no_scope,
            clean_before_dirty,
            occurred_at=NOW,
            idempotency_key="reset-1",
        )
    dirty = _reconciliation(journal, authority, clean=False, suffix="2")
    with pytest.raises(SafetyResetRejected, match="clean reconciliation"):
        safety.reset(
            owner,
            dirty,
            occurred_at=NOW,
            idempotency_key="reset-2",
        )

    clean = _reconciliation(journal, authority, clean=True, suffix="3")
    safety.reset(
        owner,
        clean,
        occurred_at=NOW,
        idempotency_key="reset-3",
    )
    assert safety.state().latched is False
    safety.assert_allowed(SafetyAction.ENTRY)


def test_safety_reset_rejects_stale_clean_reconciliation(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    authority = _authority(journal)
    safety = SafetyControl(
        journal,
        reset_authority=authority,
        maximum_reconciliation_age=timedelta(minutes=2),
    )
    safety.latch(
        reason_code="BROKER_MISMATCH",
        detail="unknown position",
        occurred_at=NOW,
        idempotency_key="latch-stale-reconciliation",
    )
    clean = _reconciliation(
        journal,
        authority,
        clean=True,
        suffix="4",
        occurred_at=NOW + timedelta(minutes=1),
    )
    reset_at = NOW + timedelta(minutes=10)
    owner = authority.authorize_owner(
        owner_id="owner-1",
        scopes=frozenset({"safety:reset"}),
        signer=HmacFactSigner("owner-1", OWNER_SECRET),
        occurred_at=reset_at,
        command_id="owner-stale-reconciliation",
    )

    with pytest.raises(SafetyResetRejected, match="reconciliation is stale"):
        safety.reset(
            owner,
            clean,
            occurred_at=reset_at,
            idempotency_key="reset-stale-reconciliation",
        )
    assert safety.state().latched is True
