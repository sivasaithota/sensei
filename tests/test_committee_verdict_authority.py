from datetime import timedelta

import pytest

from sensei.operations import HmacFactSigner, HmacFactVerifier, OperationalJournal
from sensei.orchestration import CommitteeVerdictAuthority
from tests.test_trade_committee_gate import NOW, _approval


SECRETS = {
    "risk-officer": b"risk-officer-test-secret-at-least-32b",
    "devils-advocate": b"devils-advocate-test-secret-at-least-32b",
    "compliance": b"compliance-test-secret-at-least-32bytes",
    "orchestrator": b"orchestrator-test-secret-at-least-32b",
}


def test_each_committee_role_attests_its_exact_verdict(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    authority = CommitteeVerdictAuthority(journal, HmacFactVerifier(SECRETS))
    approval = _approval()
    verdict = approval.verdicts[0]
    evidence = authority.record(
        approval.thesis,
        verdict,
        signer=HmacFactSigner(verdict.agent, SECRETS[verdict.agent]),
        occurred_at=verdict.checked_at,
        command_id="risk-verdict-1",
    )

    assert authority.verify(
        evidence.event_id,
        thesis=approval.thesis,
        verdict=verdict,
        no_later_than=NOW + timedelta(minutes=1),
    )
    forged = verdict.model_copy(update={"reasoning": "invented after approval"})
    assert not authority.verify(
        evidence.event_id,
        thesis=approval.thesis,
        verdict=forged,
        no_later_than=NOW + timedelta(minutes=1),
    )


def test_role_cannot_sign_another_committee_seat(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    authority = CommitteeVerdictAuthority(journal, HmacFactVerifier(SECRETS))
    approval = _approval()

    with pytest.raises(ValueError, match="own committee verdict"):
        authority.record(
            approval.thesis,
            approval.verdicts[0],
            signer=HmacFactSigner(
                "devils-advocate", SECRETS["devils-advocate"]
            ),
            occurred_at=approval.verdicts[0].checked_at,
            command_id="wrong-role",
        )
