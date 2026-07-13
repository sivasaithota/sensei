from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sensei.learning.attribution import (
    AttributionInput,
    OutcomeAttributionService,
    OutcomeAttributor,
)
from sensei.learning.episodes import (
    EpisodeCommand,
    EpisodeEventType,
    EpisodeInvariantError,
    EpisodeStatus,
    TradeEpisodeJournal,
)
from sensei.learning.outcomes import (
    LearningObservation,
    LearningScope,
    OutcomeLearner,
)
from sensei.operations.journal import OperationalJournal


NOW = datetime(2026, 7, 13, 9, 15, tzinfo=timezone.utc)


def complete_episode_for_learning(
    journal: OperationalJournal, episode_id: str, *, day: int
) -> tuple[str, str]:
    base = NOW + timedelta(days=day)
    suffix = episode_id.lower()
    episodes = TradeEpisodeJournal(journal)
    episodes.start(
        episode_id=episode_id,
        strategy_lineage_id="hammer-follow-through",
        plan_version_id="plan:abc123",
        decision_trace_id=f"trace:{suffix}",
        market_snapshot_id=f"snapshot:market-{suffix}",
        account_snapshot_id=f"snapshot:account-{suffix}",
        intent_id=f"intent:{suffix}",
        instrument_id="INE-ONE",
        timeframe="1d",
        planned_entry_price_paise=10_000,
        planned_exit_price_paise=10_500,
        signal_time=base,
        command_id=f"start-{suffix}",
    )
    commands = (
        (EpisodeEventType.APPROVAL_RECORDED, {"approved": True}, "approve"),
        (
            EpisodeEventType.INTENT_ACCEPTED,
            {"intent_id": f"intent:{suffix}"},
            "intent",
        ),
        (EpisodeEventType.ORDER_SUBMITTED, {"order_id": f"O-{suffix}", "quantity": 1}, "order"),
        (
            EpisodeEventType.ENTRY_FILL_RECORDED,
            {"quantity": 1, "price": "100", "fill_id": f"F-IN-{suffix}"},
            "entry",
        ),
        (
            EpisodeEventType.PROTECTION_VERIFIED,
            {"protected_quantity": 1, "stop_price": "95"},
            "protect",
        ),
        (
            EpisodeEventType.EXIT_FILL_RECORDED,
            {"quantity": 1, "price": "98", "fill_id": f"F-OUT-{suffix}"},
            "exit",
        ),
        (EpisodeEventType.EPISODE_CLOSED, {"reason": "STOP"}, "close"),
        (
            EpisodeEventType.COSTS_RECONCILED,
            {
                "reconciliation_id": f"costs:{suffix}",
                "fees": "0.00",
                "currency": "INR",
                "source_ref": f"paper-ledger:{suffix}",
            },
            "costs",
        ),
    )
    for minute, (event_type, payload, command) in enumerate(commands, start=1):
        episodes.record(
            EpisodeCommand(
                episode_id=episode_id,
                event_type=event_type,
                payload=payload,
                occurred_at=base + timedelta(minutes=minute),
                command_id=f"{command}-{suffix}",
            )
        )
    episode_events = journal.read_stream(f"episode:{episode_id}")
    entry_ref = next(
        event.event_id for event in episode_events if event.event_type == "EntryFillRecorded"
    )
    exit_ref = next(
        event.event_id for event in episode_events if event.event_type == "ExitFillRecorded"
    )
    review = episodes.record(
        EpisodeCommand(
            episode_id=episode_id,
            event_type=EpisodeEventType.REVIEW_RECORDED,
            payload={
                "review_id": f"review:{suffix}",
                "assessment": "late entry",
                "authority": "ADVISORY_ONLY",
                "market_regime": "trend",
                "failure_type": "late_entry",
            },
            occurred_at=base + timedelta(minutes=9),
            command_id=f"review-{suffix}",
        )
    )
    outcome = OutcomeAttributionService(journal).record(
        AttributionInput(
            episode_id=episode_id,
            quantity=1,
            planned_entry=Decimal("100"),
            planned_exit=Decimal("105"),
            actual_entry=Decimal("100"),
            actual_exit=Decimal("98"),
            fees=Decimal("0"),
            reasoning_quality_passed=False,
        ),
        evidence_refs=(
            entry_ref,
            exit_ref,
            next(
                event.event_id
                for event in journal.read_stream(f"episode:{episode_id}")
                if event.event_type == "CostsReconciled"
            ),
        ),
        currency="INR",
        occurred_at=base + timedelta(minutes=10),
        command_id=f"outcome-{suffix}",
    )
    return outcome.event.event_id, review.event_id


def test_trade_episode_is_a_projection_over_the_shared_journal(tmp_path):
    journal = OperationalJournal(tmp_path / "sensei.sqlite3")
    episodes = TradeEpisodeJournal(journal)
    started = episodes.start(
        episode_id="EP-1",
        strategy_lineage_id="hammer-follow-through",
        plan_version_id="plan:abc123",
        decision_trace_id="trace:abc123",
        market_snapshot_id="snapshot:market-1",
        account_snapshot_id="snapshot:account-1",
        intent_id="intent:abc123",
        instrument_id="INE-ONE",
        timeframe="1d",
        planned_entry_price_paise=10_000,
        planned_exit_price_paise=11_000,
        signal_time=NOW,
        command_id="start-ep-1",
    )
    assert episodes.start(
        episode_id="EP-1",
        strategy_lineage_id="hammer-follow-through",
        plan_version_id="plan:abc123",
        decision_trace_id="trace:abc123",
        market_snapshot_id="snapshot:market-1",
        account_snapshot_id="snapshot:account-1",
        intent_id="intent:abc123",
        instrument_id="INE-ONE",
        timeframe="1d",
        planned_entry_price_paise=10_000,
        planned_exit_price_paise=11_000,
        signal_time=NOW,
        command_id="start-ep-1",
    ) == started

    with pytest.raises(EpisodeInvariantError, match="order"):
        episodes.record(
            EpisodeCommand(
                episode_id="EP-1",
                event_type=EpisodeEventType.ENTRY_FILL_RECORDED,
                payload={"quantity": 10, "price": "100.00", "fill_id": "F-1"},
                occurred_at=NOW + timedelta(minutes=1),
                command_id="fill-too-early",
            )
        )

    commands = (
        (EpisodeEventType.APPROVAL_RECORDED, {"approved": True}, "approve"),
        (
            EpisodeEventType.INTENT_ACCEPTED,
            {"intent_id": "intent:abc123"},
            "accept-intent",
        ),
        (EpisodeEventType.ORDER_SUBMITTED, {"order_id": "O-1", "quantity": 10}, "order"),
        (
            EpisodeEventType.ENTRY_FILL_RECORDED,
            {"quantity": 10, "price": "100.00", "fill_id": "F-1"},
            "entry-fill",
        ),
        (
            EpisodeEventType.PROTECTION_VERIFIED,
            {"protected_quantity": 10, "stop_price": "95.00"},
            "protect",
        ),
        (
            EpisodeEventType.EXIT_FILL_RECORDED,
            {"quantity": 10, "price": "108.00", "fill_id": "F-2"},
            "exit-fill",
        ),
        (EpisodeEventType.EPISODE_CLOSED, {"reason": "TARGET"}, "close"),
    )
    for offset, (event_type, payload, command_id) in enumerate(commands, start=1):
        episodes.record(
            EpisodeCommand(
                episode_id="EP-1",
                event_type=event_type,
                payload=payload,
                occurred_at=NOW + timedelta(minutes=offset),
                command_id=command_id,
            )
        )

    episode = episodes.get("EP-1")
    assert episode.strategy_lineage_id == "hammer-follow-through"
    assert episode.plan_version_id == "plan:abc123"
    assert episode.decision_trace_id == "trace:abc123"
    assert episode.intent_id == "intent:abc123"
    assert episode.status is EpisodeStatus.CLOSED
    assert episode.open_quantity == 0
    assert episode.protected_quantity == 0
    assert len(journal.read_stream("episode:EP-1")) == 8


def test_outcome_attribution_reconciles_plan_execution_and_costs():
    result = OutcomeAttributor.attribute(
        AttributionInput(
            episode_id="EP-1",
            quantity=10,
            planned_entry=Decimal("100.00"),
            planned_exit=Decimal("110.00"),
            actual_entry=Decimal("101.00"),
            actual_exit=Decimal("108.00"),
            fees=Decimal("5.00"),
            reasoning_quality_passed=True,
        )
    )

    assert result.plan_pnl == Decimal("100.00")
    assert result.entry_execution_impact == Decimal("-10.00")
    assert result.exit_execution_impact == Decimal("-20.00")
    assert result.cost_impact == Decimal("-5.00")
    assert result.realized_net_pnl == Decimal("65.00")
    assert result.reconciles is True
    assert result.process_outcome == "RIGHT_PROCESS_RIGHT_OUTCOME"


def test_learning_requires_recurrence_and_can_only_propose_research(tmp_path):
    journal = OperationalJournal(tmp_path / "sensei.sqlite3")
    learner = OutcomeLearner(journal, minimum_recurrence=3)
    scope = LearningScope(
        strategy_lineage_id="hammer-follow-through",
        plan_version_id="plan:abc123",
        timeframe="1d",
        market_regime="trend",
        failure_type="late_entry",
    )

    for number in range(1, 4):
        evidence_refs = complete_episode_for_learning(
            journal, f"EP-{number}", day=number
        )
        observation = LearningObservation(
            episode_id=f"EP-{number}",
            scope=scope,
            summary="Entry after extension degraded reward-to-risk.",
            evidence_refs=evidence_refs,
            occurred_at=NOW + timedelta(days=number, minutes=10),
        )
        learner.record(observation, command_id=f"observe-{number}")
        if number < 3:
            assert learner.propose(scope, command_id="propose", now=NOW) is None

    hypothesis = learner.propose(scope, command_id="propose", now=NOW)
    assert hypothesis is not None
    assert hypothesis.evidence_episode_ids == ("EP-1", "EP-2", "EP-3")
    assert hypothesis.authority == "RESEARCH_ONLY"
    assert hypothesis.requires_examination is True
    assert hypothesis.can_veto_trades is False

    # Replaying the command is stable and never adds a second proposal.
    assert learner.propose(scope, command_id="propose", now=NOW) == hypothesis
    events = journal.read_stream(f"learning:{scope.scope_id}")
    assert [event.event_type for event in events].count("MistakeHypothesisProposed") == 1


def test_learning_rejects_ungrounded_or_mismatched_episode_claims(tmp_path):
    journal = OperationalJournal(tmp_path / "sensei.sqlite3")
    learner = OutcomeLearner(journal, minimum_recurrence=2)
    evidence_refs = complete_episode_for_learning(journal, "EP-GROUNDED", day=1)
    scope = LearningScope(
        strategy_lineage_id="hammer-follow-through",
        plan_version_id="plan:abc123",
        timeframe="1d",
        market_regime="trend",
        failure_type="late_entry",
    )

    with pytest.raises(ValueError, match="evidence must belong"):
        learner.record(
            LearningObservation(
                episode_id="EP-NOT-REAL",
                scope=scope,
                summary="Invented narrative.",
                evidence_refs=evidence_refs,
                occurred_at=NOW + timedelta(days=1, minutes=10),
            ),
            command_id="observe-invented",
        )

    with pytest.raises(ValueError, match="plan version"):
        learner.record(
            LearningObservation(
                episode_id="EP-GROUNDED",
                scope=LearningScope(
                    strategy_lineage_id="hammer-follow-through",
                    plan_version_id="plan:different",
                    timeframe="1d",
                    market_regime="trend",
                    failure_type="late_entry",
                ),
                summary="Wrong plan attribution.",
                evidence_refs=evidence_refs,
                occurred_at=NOW + timedelta(days=1, minutes=10),
            ),
            command_id="observe-wrong-plan",
        )

    with pytest.raises(ValueError, match="outcome attribution and review"):
        learner.record(
            LearningObservation(
                episode_id="EP-GROUNDED",
                scope=scope,
                summary="Review alone is not an outcome.",
                evidence_refs=(evidence_refs[1],),
                occurred_at=NOW + timedelta(days=1, minutes=10),
            ),
            command_id="observe-review-only",
        )


def test_attribution_is_recorded_only_for_a_closed_episode_with_real_event_evidence(tmp_path):
    journal = OperationalJournal(tmp_path / "sensei.sqlite3")
    episodes = TradeEpisodeJournal(journal)
    episodes.start(
        episode_id="EP-ATTR",
        strategy_lineage_id="hammer-follow-through",
        plan_version_id="plan:abc123",
        decision_trace_id="trace:attr",
        market_snapshot_id="snapshot:market-attr",
        account_snapshot_id="snapshot:account-attr",
        intent_id="intent:attr",
        instrument_id="INE-ONE",
        timeframe="1d",
        planned_entry_price_paise=10_000,
        planned_exit_price_paise=11_000,
        signal_time=NOW,
        command_id="start-attr",
    )
    commands = (
        (EpisodeEventType.APPROVAL_RECORDED, {"approved": True}, "attr-approve"),
        (
            EpisodeEventType.INTENT_ACCEPTED,
            {"intent_id": "intent:attr"},
            "attr-accept-intent",
        ),
        (EpisodeEventType.ORDER_SUBMITTED, {"order_id": "O-A", "quantity": 2}, "attr-order"),
        (
            EpisodeEventType.ENTRY_FILL_RECORDED,
            {"quantity": 2, "price": "100.00", "fill_id": "F-A"},
            "attr-entry",
        ),
        (
            EpisodeEventType.PROTECTION_VERIFIED,
            {"protected_quantity": 2, "stop_price": "95.00"},
            "attr-protect",
        ),
        (
            EpisodeEventType.EXIT_FILL_RECORDED,
            {"quantity": 2, "price": "108.00", "fill_id": "F-B"},
            "attr-exit",
        ),
        (EpisodeEventType.EPISODE_CLOSED, {"reason": "TARGET"}, "attr-close"),
        (
            EpisodeEventType.COSTS_RECONCILED,
            {
                "reconciliation_id": "costs:attr",
                "fees": "1.00",
                "currency": "INR",
                "source_ref": "broker-contract-note:attr",
            },
            "attr-costs",
        ),
    )
    for offset, (kind, payload, command_id) in enumerate(commands, start=1):
        episodes.record(
            EpisodeCommand(
                episode_id="EP-ATTR",
                event_type=kind,
                payload=payload,
                occurred_at=NOW + timedelta(minutes=offset),
                command_id=command_id,
            )
        )
    episode_events = journal.read_stream("episode:EP-ATTR")
    entry_ref = next(
        event.event_id for event in episode_events if event.event_type == "EntryFillRecorded"
    )
    exit_ref = next(
        event.event_id for event in episode_events if event.event_type == "ExitFillRecorded"
    )
    costs_ref = next(
        event.event_id for event in episode_events if event.event_type == "CostsReconciled"
    )

    with pytest.raises(ValueError, match="actual entry"):
        OutcomeAttributionService(journal).record(
            AttributionInput(
                episode_id="EP-ATTR",
                quantity=2,
                planned_entry=Decimal("100"),
                planned_exit=Decimal("110"),
                actual_entry=Decimal("99"),
                actual_exit=Decimal("108"),
                fees=Decimal("1"),
                reasoning_quality_passed=True,
            ),
            evidence_refs=(entry_ref, exit_ref, costs_ref),
            currency="INR",
            occurred_at=NOW + timedelta(minutes=10),
            command_id="attribute-ep-attr-wrong-entry",
        )

    facts = AttributionInput(
        episode_id="EP-ATTR",
        quantity=2,
        planned_entry=Decimal("100"),
        planned_exit=Decimal("110"),
        actual_entry=Decimal("100"),
        actual_exit=Decimal("108"),
        fees=Decimal("1"),
        reasoning_quality_passed=True,
    )
    service = OutcomeAttributionService(journal)
    recorded = service.record(
        facts,
        evidence_refs=(entry_ref, exit_ref, costs_ref),
        currency="INR",
        occurred_at=NOW + timedelta(minutes=10),
        command_id="attribute-ep-attr",
    )
    assert service.record(
        facts,
        evidence_refs=(entry_ref, exit_ref, costs_ref),
        currency="INR",
        occurred_at=NOW + timedelta(minutes=10),
        command_id="attribute-ep-attr",
    ) == recorded
    with pytest.raises(ValueError, match="already has an outcome attribution"):
        service.record(
            facts,
            evidence_refs=(entry_ref, exit_ref, costs_ref),
            currency="INR",
            occurred_at=NOW + timedelta(minutes=10),
            command_id="attribute-ep-attr-again",
        )

    assert recorded.attribution.realized_net_pnl == Decimal("15.00")
    assert recorded.event.event_type == "OutcomeAttributed"
    assert recorded.event.payload["reconciles"] is True
    assert recorded.event.payload["evidence_refs"] == (
        entry_ref,
        exit_ref,
        costs_ref,
    )
