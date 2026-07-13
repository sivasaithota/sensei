from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sensei.operations.authority import HmacFactSigner, HmacFactVerifier


NOW = datetime(2026, 7, 14, 9, 15, tzinfo=timezone.utc)
SECRET = b"test-only-authority-secret-32-bytes"


def test_signed_fact_verifies_only_for_exact_type_issuer_and_content():
    signer = HmacFactSigner("historian-1", SECRET)
    verifier = HmacFactVerifier({"historian-1": SECRET})
    fact = {"plan_id": "plan:1", "observed_at": NOW.isoformat()}
    signature = signer.sign("PlanDecisionTraceProduced", fact)

    assert verifier.verify(
        issuer_id="historian-1",
        fact_type="PlanDecisionTraceProduced",
        fact=fact,
        signature=signature,
    )
    assert not verifier.verify(
        issuer_id="historian-1",
        fact_type="PlanDecisionTraceProduced",
        fact={**fact, "plan_id": "plan:forged"},
        signature=signature,
    )
    assert not verifier.verify(
        issuer_id="unknown-historian",
        fact_type="PlanDecisionTraceProduced",
        fact=fact,
        signature=signature,
    )


def test_fact_authority_rejects_weak_keys_and_non_json_facts():
    with pytest.raises(ValueError, match="at least 32 bytes"):
        HmacFactSigner("historian-1", b"weak")

    signer = HmacFactSigner("historian-1", SECRET)
    with pytest.raises((TypeError, ValueError)):
        signer.sign("bad", {"not-json": object()})
