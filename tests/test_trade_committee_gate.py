from datetime import datetime, timedelta, timezone

import pytest

from sensei.agents.thesis import (
    ApprovalRecord,
    Direction,
    PlaybookCitation,
    TradeThesis,
    Verdict,
)
from sensei.operations.journal import OperationalJournal
from sensei.orchestration.committee import TradeCommitteeGate
from sensei.portfolio_risk import TradeIntent


NOW = datetime(2026, 7, 13, 4, 0, tzinfo=timezone.utc)
CLAIM = "claim:" + "c" * 64


def _intent() -> TradeIntent:
    return TradeIntent(
        strategy_plan_id="sha256:" + "a" * 64,
        decision_trace_id="trace:" + "b" * 64,
        market_snapshot_id="snapshot:market-1",
        account_snapshot_id="snapshot:account-1",
        instrument_id="INFY",
        quantity=10,
        limit_price_paise=150_000,
        stop_price_paise=145_000,
        target_price_paise=160_000,
        created_at=NOW,
    )


def _approval(**thesis_updates) -> ApprovalRecord:
    thesis_fields = dict(
        id="TH-FOUNDATION-1",
        created_at=NOW,
        symbol="INFY",
        direction=Direction.BUY,
        entry_zone_low=1499.0,
        entry_zone_high=1501.0,
        quantity=10,
        stop_loss=1450.0,
        targets=[1600.0],
        time_horizon_days=20,
        invalidation="The exact plan invalidates or the stop is reached.",
        evidence=[CLAIM],
        playbook_citations=[
            PlaybookCitation(
                strategy="sha256:" + "a" * 64,
                oos_expectancy_pct=1.0,
                oos_hit_rate=0.45,
                oos_trades=100,
            )
        ],
        narrative="Follow-through plan with bounded downside.",
    )
    thesis_fields.update(thesis_updates)
    thesis = TradeThesis(**thesis_fields)
    verdicts = [
        Verdict(
            level=level,
            agent=agent,
            approved=True,
            reasoning="Exact plan and supplied facts passed this independent gate.",
            checked_at=NOW + timedelta(seconds=index),
        )
        for index, (level, agent) in enumerate(
            (
                ("L1", "risk-officer"),
                ("L2", "devils-advocate"),
                ("L3", "compliance"),
                ("L4", "orchestrator"),
            ),
            start=1,
        )
    ]
    return ApprovalRecord(thesis=thesis, verdicts=verdicts)


def test_committee_gate_pins_all_four_approvals_to_exact_intent(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    gate = TradeCommitteeGate(journal)
    accepted = gate.record(
        _approval(),
        intent=_intent(),
        lineage_id="hammer-follow-through",
        allowed_claim_ids=frozenset({CLAIM}),
        maximum_holding_sessions=20,
        signal_observed_at=NOW,
        occurred_at=NOW + timedelta(minutes=1),
        command_id="committee-accept-1",
    )
    repeated = gate.record(
        _approval(),
        intent=_intent(),
        lineage_id="hammer-follow-through",
        allowed_claim_ids=frozenset({CLAIM}),
        maximum_holding_sessions=20,
        signal_observed_at=NOW,
        occurred_at=NOW + timedelta(minutes=1),
        command_id="committee-accept-1",
    )

    assert repeated == accepted
    assert accepted.intent_id == _intent().intent_id
    assert accepted.approval_id.startswith("approval:")
    event = journal.read_stream(f"trade-approval:{_intent().intent_id.split(':')[1]}")[0]
    assert event.event_type == "TradeCommitteeApproved"
    assert event.payload["verdict_levels"] == ("L1", "L2", "L3", "L4")


def test_committee_gate_rejects_veto_or_thesis_drift(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    gate = TradeCommitteeGate(journal)
    vetoed = _approval()
    vetoed.verdicts[1].approved = False

    with pytest.raises(ValueError, match="four approved"):
        gate.record(
            vetoed,
            intent=_intent(),
            lineage_id="hammer-follow-through",
            allowed_claim_ids=frozenset({CLAIM}),
            maximum_holding_sessions=20,
            signal_observed_at=NOW,
            occurred_at=NOW + timedelta(minutes=1),
            command_id="committee-vetoed",
        )

    with pytest.raises(ValueError, match="quantity"):
        gate.record(
            _approval(quantity=9),
            intent=_intent(),
            lineage_id="hammer-follow-through",
            allowed_claim_ids=frozenset({CLAIM}),
            maximum_holding_sessions=20,
            signal_observed_at=NOW,
            occurred_at=NOW + timedelta(minutes=1),
            command_id="committee-wrong-quantity",
        )

    with pytest.raises(ValueError, match="provenance claims"):
        gate.record(
            _approval(evidence=["free-form model story"]),
            intent=_intent(),
            lineage_id="hammer-follow-through",
            allowed_claim_ids=frozenset({CLAIM}),
            maximum_holding_sessions=20,
            signal_observed_at=NOW,
            occurred_at=NOW + timedelta(minutes=1),
            command_id="committee-ungrounded",
        )
