from datetime import timedelta
from dataclasses import replace

from sensei.kernel import KernelAdmissionAuthority
from sensei.operations import HmacFactSigner, HmacFactVerifier, OperationalJournal
from tests.test_trading_kernel import NOW, _intent


SECRET = b"paper-admission-test-secret-at-least-32b"
EVENTS = {
    "trace_attestation_event_id": "event:" + "1" * 64,
    "lifecycle_event_id": "event:" + "2" * 64,
    "health_event_id": "event:" + "3" * 64,
    "committee_event_id": "event:" + "4" * 64,
}


def test_kernel_admission_authority_binds_exact_intent_and_governance_chain(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    authority = KernelAdmissionAuthority(
        journal,
        HmacFactVerifier({"paper-admission": SECRET}),
    )
    intent = _intent()
    admission = authority.issue(
        intent,
        lineage_id="hammer-follow-through",
        committee_approval_id="approval:" + "5" * 64,
        verdict_evidence_event_ids=tuple(
            "event:" + str(number) * 64 for number in range(5, 9)
        ),
        provenance_claim_ids=("claim:" + "9" * 64,),
        signer=HmacFactSigner("paper-admission", SECRET),
        occurred_at=NOW,
        command_id="admit-infy",
        **EVENTS,
    )

    assert authority.verify(
        admission.event_id,
        intent=intent,
        no_later_than=NOW + timedelta(seconds=1),
    )
    forged = replace(intent, quantity=intent.quantity + 1)
    assert not authority.verify(
        admission.event_id,
        intent=forged,
        no_later_than=NOW + timedelta(seconds=1),
    )
