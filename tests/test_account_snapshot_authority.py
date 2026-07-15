import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from sensei.operations import (
    EventAppend,
    HmacFactSigner,
    HmacFactVerifier,
    OperationalJournal,
)
from sensei.portfolio_risk import (
    AccountSnapshot,
    AccountSnapshotAuthority,
)


NOW = datetime(2026, 7, 15, 9, 15, tzinfo=timezone.utc)
SECRET = b"account-snapshot-authority-test-secret-32bytes"


def _snapshot() -> AccountSnapshot:
    return AccountSnapshot(
        available_cash_paise=10_000_000,
        marked_equity_paise=10_000_000,
        high_water_mark_paise=10_000_000,
        day_pnl_paise=0,
        week_pnl_paise=0,
        positions=(),
        included_reservation_ids=(),
        reconciled=True,
        captured_at=NOW,
    )


def test_account_snapshot_is_content_addressed_and_authenticated(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    authority = AccountSnapshotAuthority(
        journal,
        HmacFactVerifier({"account-adapter": SECRET}),
        expected_issuer_id="account-adapter",
    )
    snapshot = _snapshot()
    evidence = authority.record(
        snapshot,
        signer=HmacFactSigner("account-adapter", SECRET),
        occurred_at=NOW,
        command_id="account-snapshot-1",
    )

    assert evidence.snapshot_id == snapshot.snapshot_id
    assert evidence.issuer_id == "account-adapter"
    assert authority.verify(
        evidence.event_id,
        snapshot=snapshot,
        no_later_than=NOW + timedelta(seconds=1),
    )

    changed_content = replace(snapshot, available_cash_paise=9_000_000)
    assert not authority.verify(
        evidence.event_id,
        snapshot=changed_content,
        no_later_than=NOW + timedelta(seconds=1),
    )


def test_account_snapshot_authority_requires_the_configured_trusted_issuer(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    authority = AccountSnapshotAuthority(
        journal,
        HmacFactVerifier({"account-adapter": SECRET}),
        expected_issuer_id="account-adapter",
    )

    with pytest.raises(ValueError, match="configured account adapter"):
        authority.record(
            _snapshot(),
            signer=HmacFactSigner("untrusted-adapter", SECRET),
            occurred_at=NOW,
            command_id="wrong-account-source",
        )

    wrong_secret = b"wrong-account-snapshot-secret-at-least-32bytes"
    with pytest.raises(ValueError, match="signer is not trusted"):
        authority.record(
            _snapshot(),
            signer=HmacFactSigner("account-adapter", wrong_secret),
            occurred_at=NOW,
            command_id="wrong-account-secret",
        )

    assert journal.read_all() == ()


def test_account_snapshot_authority_rejects_forged_identity_and_time_order(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    authority = AccountSnapshotAuthority(
        journal,
        HmacFactVerifier({"account-adapter": SECRET}),
        expected_issuer_id="account-adapter",
    )
    signer = HmacFactSigner("account-adapter", SECRET)
    forged = _snapshot()
    object.__setattr__(forged, "available_cash_paise", 1)

    with pytest.raises(ValueError, match="content identity is invalid"):
        authority.record(
            forged,
            signer=signer,
            occurred_at=NOW,
            command_id="forged-account-content",
        )

    with pytest.raises(ValueError, match="observed before capture"):
        authority.record(
            _snapshot(),
            signer=signer,
            occurred_at=NOW - timedelta(microseconds=1),
            command_id="account-observed-too-early",
        )

    assert journal.read_all() == ()


def test_account_snapshot_evidence_replays_once_and_respects_cutoff(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    authority = AccountSnapshotAuthority(
        journal,
        HmacFactVerifier({"account-adapter": SECRET}),
        expected_issuer_id="account-adapter",
    )
    snapshot = _snapshot()
    signer = HmacFactSigner("account-adapter", SECRET)

    first = authority.record(
        snapshot,
        signer=signer,
        occurred_at=NOW,
        command_id="replayed-account-snapshot",
    )
    repeated = authority.record(
        snapshot,
        signer=signer,
        occurred_at=NOW,
        command_id="replayed-account-snapshot",
    )

    assert repeated == first
    assert len(journal.read_all()) == 1
    assert not authority.verify(
        first.event_id,
        snapshot=snapshot,
        no_later_than=NOW - timedelta(microseconds=1),
    )


def test_account_snapshot_verification_rejects_wrong_durable_authority(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    signer = HmacFactSigner("account-adapter", SECRET)
    authority = AccountSnapshotAuthority(
        journal,
        HmacFactVerifier({"account-adapter": SECRET}),
        expected_issuer_id="account-adapter",
    )
    snapshot = _snapshot()
    fact = {
        "snapshot": snapshot.to_payload(),
        "observed_at": NOW.isoformat(),
    }
    event = journal.append(
        EventAppend(
            stream_id=(
                "account-snapshot:"
                + snapshot.snapshot_id.removeprefix("snapshot:")
            ),
            event_type="AccountSnapshotAuthenticated",
            payload={
                "schema_version": "1.0",
                "authority": "CALLER_ASSERTED_ACCOUNT_SNAPSHOT",
                "issuer_id": signer.issuer_id,
                "fact": fact,
                "signature": signer.sign("AccountSnapshotObserved", fact),
            },
            idempotency_key="malformed-account-authority",
            expected_version=0,
            occurred_at=NOW,
            correlation_id=snapshot.snapshot_id,
        )
    )

    assert not authority.verify(
        event.event_id,
        snapshot=snapshot,
        no_later_than=NOW + timedelta(seconds=1),
    )


def test_account_snapshot_verification_fails_on_journal_tampering(tmp_path):
    journal_path = tmp_path / "journal.sqlite3"
    journal = OperationalJournal(journal_path)
    authority = AccountSnapshotAuthority(
        journal,
        HmacFactVerifier({"account-adapter": SECRET}),
        expected_issuer_id="account-adapter",
    )
    snapshot = _snapshot()
    evidence = authority.record(
        snapshot,
        signer=HmacFactSigner("account-adapter", SECRET),
        occurred_at=NOW,
        command_id="tampered-account-snapshot",
    )

    with sqlite3.connect(journal_path) as connection:
        connection.execute("DROP TRIGGER journal_events_no_update")
        connection.execute(
            "UPDATE journal_events SET event_type = ? WHERE event_id = ?",
            ("AccountSnapshotRewritten", evidence.event_id),
        )

    assert not authority.verify(
        evidence.event_id,
        snapshot=snapshot,
        no_later_than=NOW + timedelta(seconds=1),
    )
