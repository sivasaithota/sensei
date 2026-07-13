from dataclasses import replace
from datetime import timedelta

from sensei.kernel import BrokerSnapshot, BrokerSnapshotAuthority
from sensei.operations import HmacFactSigner, HmacFactVerifier, OperationalJournal
from tests.test_trading_kernel import NOW


SECRET = b"paper-gateway-snapshot-test-secret-32bytes"


def test_broker_snapshot_is_content_addressed_and_authenticated(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    authority = BrokerSnapshotAuthority(
        journal,
        HmacFactVerifier({"paper-gateway": SECRET}),
        expected_issuer_id="paper-gateway",
    )
    snapshot = BrokerSnapshot(
        captured_at=NOW,
        positions=(),
        protections=(),
    )
    evidence = authority.record(
        snapshot,
        signer=HmacFactSigner("paper-gateway", SECRET),
        occurred_at=NOW,
        command_id="broker-snapshot-1",
    )

    assert snapshot.snapshot_id.startswith("broker-snapshot:")
    assert authority.verify(
        evidence.event_id,
        snapshot=snapshot,
        no_later_than=NOW + timedelta(seconds=1),
    )
    forged = replace(snapshot, captured_at=NOW - timedelta(seconds=1))
    assert not authority.verify(
        evidence.event_id,
        snapshot=forged,
        no_later_than=NOW + timedelta(seconds=1),
    )
