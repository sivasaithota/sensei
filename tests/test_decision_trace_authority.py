from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sensei.operations import HmacFactSigner, HmacFactVerifier, OperationalJournal
from sensei.strategy import (
    DecisionTraceAuthority,
    PlanEvaluationRequest,
    StrategyPlanEngine,
)
from tests.test_strategy_plan import hammer_bars, hammer_follow_through_plan


NOW = datetime(2026, 7, 14, 9, 15, tzinfo=timezone.utc)
SECRET = b"historian-test-secret-at-least-32-bytes"


def test_trace_authority_binds_engine_trace_to_exact_market_snapshot(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    authority = DecisionTraceAuthority(
        journal,
        HmacFactVerifier({"historian-1": SECRET}),
    )
    plan = hammer_follow_through_plan()
    bars = hammer_bars()
    trace = StrategyPlanEngine().evaluate(
        PlanEvaluationRequest(
            plan=plan,
            instrument_id="NSE:TEST",
            bars=bars,
            evaluation_session=bars.index[-1].date(),
        )
    )
    attestation = authority.record(
        trace,
        market_snapshot_id="snapshot:" + "a" * 64,
        signer=HmacFactSigner("historian-1", SECRET),
        occurred_at=NOW,
        command_id="trace-produced-1",
    )

    assert authority.verify(
        attestation.event_id,
        trace=trace,
        market_snapshot_id="snapshot:" + "a" * 64,
        no_later_than=NOW + timedelta(seconds=1),
    )
    forged = trace.model_copy(
        update={
            "exit_intent": trace.exit_intent.model_copy(
                update={"stop_loss_pct": 25.0}
            )
        }
    )
    assert not authority.verify(
        attestation.event_id,
        trace=forged,
        market_snapshot_id="snapshot:" + "a" * 64,
        no_later_than=NOW + timedelta(seconds=1),
    )
    assert not authority.verify(
        attestation.event_id,
        trace=trace,
        market_snapshot_id="snapshot:" + "b" * 64,
        no_later_than=NOW + timedelta(seconds=1),
    )
