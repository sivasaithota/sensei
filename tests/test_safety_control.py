import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from sensei.operations import (
    EventAppend,
    HmacFactSigner,
    HmacFactVerifier,
    OperationalJournal,
)
from sensei.portfolio_risk import (
    OwnerAuthorization,
    ReconciliationHealth,
    SafetyAction,
    SafetyBlocked,
    SafetyResetRejected,
    SafetyControl,
    SafetyResetAuthority,
)


NOW = datetime(2026, 7, 13, 4, 0, tzinfo=timezone.utc)
OWNER_SECRET = b"owner-reset-test-secret-at-least-32-bytes"
RECON_SECRET = b"reconciler-test-secret-at-least-32-bytes"
UNTRUSTED_SECRET = b"untrusted-test-secret-at-least-32-bytes"


def _journal(path):
    return OperationalJournal(path, clock=lambda: NOW)


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


def _owner(journal, authority, *, scopes=None, occurred_at=NOW, suffix="1"):
    del journal
    return authority.authorize_owner(
        owner_id="owner-1",
        scopes=frozenset({"safety:reset"} if scopes is None else scopes),
        signer=HmacFactSigner("owner-1", OWNER_SECRET),
        occurred_at=occurred_at,
        command_id=f"owner-{suffix}",
    )


def _append_reset(
    journal,
    *,
    owner,
    reconciliation,
    occurred_at,
    suffix,
):
    events = journal.read_stream("safety:global")
    return journal.append(
        EventAppend(
            stream_id="safety:global",
            event_type="SafetyReset",
            payload={
                "owner_id": owner.owner_id,
                "owner_authorization_event_id": owner.event_id,
                "authenticated_at": owner.authenticated_at.isoformat(),
                "reconciliation_observed_at": (
                    reconciliation.observed_at.isoformat()
                ),
                "reconciliation_event_id": reconciliation.event_id,
            },
            idempotency_key=f"forged-reset-{suffix}",
            expected_version=len(events),
            occurred_at=occurred_at,
        )
    )


def _canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _owner_with_signature(journal, *, secret, occurred_at, suffix):
    fact = {
        "owner_id": "owner-1",
        "scopes": ["safety:reset"],
        "authenticated_at": occurred_at.isoformat(),
    }
    event = journal.append(
        EventAppend(
            stream_id="owner-reset:" + _digest(_canonical(fact)),
            event_type="OwnerSafetyResetAuthorized",
            payload={
                "schema_version": "1.0",
                "authority": "OWNER_SAFETY_RESET",
                "issuer_id": "owner-1",
                "fact": fact,
                "signature": HmacFactSigner("owner-1", secret).sign(
                    "OwnerSafetyResetAuthorized",
                    fact,
                ),
            },
            idempotency_key=f"forged-owner-{suffix}",
            expected_version=0,
            occurred_at=occurred_at,
            correlation_id="owner-1",
        )
    )
    return OwnerAuthorization(
        event_id=event.event_id,
        owner_id="owner-1",
        scopes=frozenset({"safety:reset"}),
        authenticated_at=occurred_at,
        issuer_id="owner-1",
    )


def _reconciliation_with_signature(
    journal,
    *,
    secret,
    linked,
    occurred_at,
    suffix,
):
    broker_event_id = "event:" + suffix * 64
    snapshot_id = "broker-snapshot:" + suffix * 64
    kernel_snapshot_id = snapshot_id if linked else "broker-snapshot:" + "f" * 64
    kernel_event = journal.append(
        EventAppend(
            stream_id="kernel:paper",
            event_type="ReconciliationClean",
            payload={
                "snapshot_id": kernel_snapshot_id,
                "broker_snapshot_event_id": broker_event_id,
                "issues": (),
            },
            idempotency_key=f"forged-kernel-reconciliation-{suffix}",
            expected_version=len(journal.read_stream("kernel:paper")),
            occurred_at=occurred_at,
        )
    )
    fact = {
        "kernel_event_id": kernel_event.event_id,
        "broker_snapshot_event_id": broker_event_id,
        "snapshot_id": snapshot_id,
        "clean": True,
        "issues": [],
        "observed_at": occurred_at.isoformat(),
    }
    event = journal.append(
        EventAppend(
            stream_id="reconciliation-attestation:"
            + _digest(kernel_event.event_id),
            event_type="ReconciliationOutcomeAttested",
            payload={
                "schema_version": "1.0",
                "authority": "KERNEL_RECONCILIATION",
                "issuer_id": "kernel-reconciler",
                "fact": fact,
                "signature": HmacFactSigner("kernel-reconciler", secret).sign(
                    "ReconciliationOutcomeAttested",
                    fact,
                ),
            },
            idempotency_key=f"forged-reconciliation-{suffix}",
            expected_version=0,
            occurred_at=occurred_at,
            causation_id=kernel_event.event_id,
            correlation_id=snapshot_id,
        )
    )
    return ReconciliationHealth(
        event_id=event.event_id,
        kernel_event_id=kernel_event.event_id,
        broker_snapshot_event_id=broker_event_id,
        snapshot_id=snapshot_id,
        clean=True,
        issues=(),
        observed_at=occurred_at,
        issuer_id="kernel-reconciler",
    )


def test_latched_safety_blocks_entries_but_never_protection_or_cancel(tmp_path):
    safety = SafetyControl(_journal(tmp_path / "journal.sqlite3"))
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
    journal = _journal(tmp_path / "journal.sqlite3")
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
    journal = _journal(tmp_path / "journal.sqlite3")
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


def test_hash_valid_reset_with_non_latest_reconciliation_cannot_clear_latch(
    tmp_path,
):
    journal = _journal(tmp_path / "journal.sqlite3")
    authority = _authority(journal)
    safety = SafetyControl(journal, reset_authority=authority)
    safety.latch(
        reason_code="BROKER_MISMATCH",
        detail="unknown position",
        occurred_at=NOW,
        idempotency_key="latch-non-latest",
    )
    owner = _owner(
        journal,
        authority,
        occurred_at=NOW,
        suffix="non-latest",
    )
    superseded = _reconciliation(
        journal,
        authority,
        clean=True,
        suffix="5",
        occurred_at=NOW + timedelta(seconds=20),
    )
    _reconciliation(
        journal,
        authority,
        clean=True,
        suffix="6",
        occurred_at=NOW + timedelta(seconds=30),
    )
    _append_reset(
        journal,
        owner=owner,
        reconciliation=superseded,
        occurred_at=NOW + timedelta(seconds=40),
        suffix="non-latest",
    )

    state = safety.state()

    assert state.latched is True
    assert {reason.reason_code for reason in state.reasons} == {
        "BROKER_MISMATCH",
        "SAFETY_HISTORY_INVALID",
    }
    with pytest.raises(SafetyBlocked, match="SAFETY_HISTORY_INVALID"):
        safety.assert_allowed(SafetyAction.ENTRY)


def test_hash_valid_reset_cannot_reuse_evidence_created_before_latch(tmp_path):
    journal = _journal(tmp_path / "journal.sqlite3")
    authority = _authority(journal)
    safety = SafetyControl(journal, reset_authority=authority)
    owner = _owner(journal, authority, suffix="pre-latch")
    clean = _reconciliation(
        journal,
        authority,
        clean=True,
        suffix="7",
    )
    safety.latch(
        reason_code="BROKER_MISMATCH",
        detail="unknown position",
        occurred_at=NOW,
        idempotency_key="latch-after-evidence",
    )
    _append_reset(
        journal,
        owner=owner,
        reconciliation=clean,
        occurred_at=NOW + timedelta(seconds=10),
        suffix="pre-latch",
    )

    state = safety.state()

    assert state.latched is True
    assert "SAFETY_HISTORY_INVALID" in {
        reason.reason_code for reason in state.reasons
    }


@pytest.mark.parametrize("invalid_evidence", ["OWNER_SCOPE", "DIRTY", "STALE"])
def test_hash_valid_reset_event_cannot_bypass_reset_policy(
    tmp_path,
    invalid_evidence,
):
    journal = _journal(tmp_path / "journal.sqlite3")
    authority = _authority(journal)
    safety = SafetyControl(journal, reset_authority=authority)
    safety.latch(
        reason_code="BROKER_MISMATCH",
        detail="unknown position",
        occurred_at=NOW,
        idempotency_key=f"latch-policy-{invalid_evidence}",
    )
    reset_at = (
        NOW + timedelta(minutes=10)
        if invalid_evidence == "STALE"
        else NOW + timedelta(seconds=30)
    )
    owner = _owner(
        journal,
        authority,
        scopes=(set() if invalid_evidence == "OWNER_SCOPE" else None),
        occurred_at=(
            reset_at
            if invalid_evidence == "STALE"
            else NOW + timedelta(seconds=10)
        ),
        suffix=f"policy-{invalid_evidence}",
    )
    reconciliation = _reconciliation(
        journal,
        authority,
        clean=invalid_evidence != "DIRTY",
        suffix={"OWNER_SCOPE": "a", "DIRTY": "b", "STALE": "c"}[
            invalid_evidence
        ],
        occurred_at=NOW + timedelta(seconds=20),
    )
    _append_reset(
        journal,
        owner=owner,
        reconciliation=reconciliation,
        occurred_at=reset_at,
        suffix=f"policy-{invalid_evidence}",
    )

    state = safety.state()

    assert state.latched is True
    assert "SAFETY_HISTORY_INVALID" in {
        reason.reason_code for reason in state.reasons
    }


@pytest.mark.parametrize(
    ("invalid_evidence", "suffix"),
    [
        ("OWNER_SIGNATURE", "d"),
        ("RECONCILIATION_SIGNATURE", "e"),
        ("KERNEL_LINK", "a"),
    ],
)
def test_hash_valid_reset_requires_authentic_linked_evidence(
    tmp_path,
    invalid_evidence,
    suffix,
):
    journal = _journal(tmp_path / "journal.sqlite3")
    authority = _authority(journal)
    safety = SafetyControl(journal, reset_authority=authority)
    safety.latch(
        reason_code="BROKER_MISMATCH",
        detail="unknown position",
        occurred_at=NOW,
        idempotency_key=f"latch-authentic-{invalid_evidence}",
    )
    evidence_at = NOW + timedelta(seconds=10)
    owner = (
        _owner_with_signature(
            journal,
            secret=UNTRUSTED_SECRET,
            occurred_at=evidence_at,
            suffix=suffix,
        )
        if invalid_evidence == "OWNER_SIGNATURE"
        else _owner(
            journal,
            authority,
            occurred_at=evidence_at,
            suffix=f"authentic-{invalid_evidence}",
        )
    )
    reconciliation_at = NOW + timedelta(seconds=20)
    if invalid_evidence == "OWNER_SIGNATURE":
        reconciliation = _reconciliation(
            journal,
            authority,
            clean=True,
            suffix=suffix,
            occurred_at=reconciliation_at,
        )
    else:
        reconciliation = _reconciliation_with_signature(
            journal,
            secret=(
                UNTRUSTED_SECRET
                if invalid_evidence == "RECONCILIATION_SIGNATURE"
                else RECON_SECRET
            ),
            linked=invalid_evidence != "KERNEL_LINK",
            occurred_at=reconciliation_at,
            suffix=suffix,
        )
    _append_reset(
        journal,
        owner=owner,
        reconciliation=reconciliation,
        occurred_at=NOW + timedelta(seconds=30),
        suffix=f"authentic-{invalid_evidence}",
    )

    state = safety.state()

    assert state.latched is True
    assert "SAFETY_HISTORY_INVALID" in {
        reason.reason_code for reason in state.reasons
    }


def test_valid_historical_reset_stays_valid_after_new_reconciliation(tmp_path):
    journal = _journal(tmp_path / "journal.sqlite3")
    authority = _authority(journal)
    safety = SafetyControl(journal, reset_authority=authority)
    safety.latch(
        reason_code="BROKER_MISMATCH",
        detail="unknown position",
        occurred_at=NOW,
        idempotency_key="latch-historical-valid",
    )
    owner = _owner(
        journal,
        authority,
        occurred_at=NOW,
        suffix="historical-valid",
    )
    clean = _reconciliation(
        journal,
        authority,
        clean=True,
        suffix="8",
        occurred_at=NOW,
    )
    safety.reset(
        owner,
        clean,
        occurred_at=NOW,
        idempotency_key="reset-historical-valid",
    )
    _reconciliation(
        journal,
        authority,
        clean=False,
        suffix="9",
        occurred_at=NOW,
    )

    state = safety.state()

    assert state.latched is False
    assert state.reasons == ()


def test_backdated_reset_cannot_make_stale_evidence_fresh(tmp_path):
    journal_time = [NOW]
    journal = OperationalJournal(
        tmp_path / "journal.sqlite3",
        clock=lambda: journal_time[0],
    )
    authority = _authority(journal)
    safety = SafetyControl(journal, reset_authority=authority)
    safety.latch(
        reason_code="BROKER_MISMATCH",
        detail="unknown position",
        occurred_at=NOW,
        idempotency_key="latch-backdated-reset",
    )
    owner = _owner(journal, authority, occurred_at=NOW, suffix="backdated")
    clean = _reconciliation(
        journal,
        authority,
        clean=True,
        suffix="f",
        occurred_at=NOW,
    )
    journal_time[0] = NOW + timedelta(minutes=10)
    _append_reset(
        journal,
        owner=owner,
        reconciliation=clean,
        occurred_at=NOW + timedelta(seconds=30),
        suffix="backdated",
    )

    state = safety.state()

    assert state.latched is True
    assert "SAFETY_HISTORY_INVALID" in {
        reason.reason_code for reason in state.reasons
    }


def test_duplicate_reset_is_rejected_without_corrupting_history(tmp_path):
    journal = _journal(tmp_path / "journal.sqlite3")
    authority = _authority(journal)
    safety = SafetyControl(journal, reset_authority=authority)
    safety.latch(
        reason_code="BROKER_MISMATCH",
        detail="unknown position",
        occurred_at=NOW,
        idempotency_key="latch-duplicate-reset",
    )
    owner = _owner(journal, authority, occurred_at=NOW, suffix="duplicate")
    clean = _reconciliation(
        journal,
        authority,
        clean=True,
        suffix="0",
        occurred_at=NOW,
    )
    safety.reset(
        owner,
        clean,
        occurred_at=NOW,
        idempotency_key="reset-duplicate",
    )
    safety_events = journal.read_stream("safety:global")

    with pytest.raises(SafetyResetRejected, match="not latched"):
        safety.reset(
            owner,
            clean,
            occurred_at=NOW,
            idempotency_key="reset-duplicate",
        )

    assert journal.read_stream("safety:global") == safety_events
    assert safety.state().latched is False
    assert safety.state().reasons == ()
