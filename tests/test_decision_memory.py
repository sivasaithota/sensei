from datetime import datetime, timedelta, timezone

import pytest

from sensei.memory import (
    AgentMemoryRole,
    ContextPackAuditTrail,
    DeskMemoryCoordinator,
    DeskMemoryScope,
    DecisionMemoryService,
    MemoryKind,
    MemoryContextPack,
    MemoryPolarity,
    MemoryQuery,
)
from sensei.operations import EventAppend, OperationalJournal


BASE = datetime(2026, 7, 17, 9, 0, tzinfo=timezone.utc)
PLAN = "sha256:" + "a" * 64


def _append(journal, clock, *, event_type, payload, sequence, occurred_at=None):
    clock[0] = BASE + timedelta(hours=sequence)
    return journal.append(
        EventAppend(
            stream_id=f"memory-fixture:{sequence}",
            event_type=event_type,
            payload=payload,
            idempotency_key=f"memory-fixture:{sequence}",
            expected_version=0,
            occurred_at=occurred_at or clock[0],
            correlation_id="episode-1",
        )
    )


def _memory(tmp_path):
    clock = [BASE]
    journal = OperationalJournal(tmp_path / "journal.sqlite3", clock=lambda: clock[0])
    started = _append(
        journal,
        clock,
        event_type="EpisodeStarted",
        payload={
            "episode_id": "episode-1",
            "instrument_id": "NSE:INFY",
            "strategy_lineage_id": "lineage-1",
            "plan_version_id": PLAN,
            "timeframe": "swing",
            "market_regime": "bullish",
        },
        sequence=0,
    )
    halted = _append(
        journal,
        clock,
        event_type="SchedulerTaskHalted",
        payload={
            "reason": "MISSED_ENTRY_WINDOW",
            "task": {"kind": "ENTRY_SESSION", "trading_date": "2026-07-17"},
            "instrument_id": "NSE:INFY",
            "plan_version_id": PLAN,
        },
        sequence=1,
    )
    outcome = _append(
        journal,
        clock,
        event_type="OutcomeAttributed",
        payload={
            "episode_id": "episode-1",
            "instrument_id": "NSE:INFY",
            "plan_version_id": PLAN,
            "realized_pnl_paise": -12500,
            "reconciles": True,
        },
        sequence=2,
    )
    # Backdated occurrence must still remain invisible before it was recorded.
    reflection = _append(
        journal,
        clock,
        event_type="LearningObservationRecorded",
        payload={
            "episode_id": "episode-1",
            "scope": {
                "strategy_lineage_id": "lineage-1",
                "plan_version_id": PLAN,
                "timeframe": "swing",
                "market_regime": "bullish",
                "failure_type": "late_entry",
            },
            "summary": "Late entries had adverse slippage",
            "evidence_refs": [outcome.event_id],
        },
        sequence=3,
        occurred_at=BASE,
    )
    return DecisionMemoryService(journal), (started, halted, outcome, reflection), journal


def test_query_reconstructs_point_in_time_and_prioritizes_counter_evidence(tmp_path):
    memory, events, _journal = _memory(tmp_path)

    result = memory.query(
        MemoryQuery(
            role=AgentMemoryRole.ANALYST,
            as_of=BASE + timedelta(hours=1, minutes=30),
            instrument_id="NSE:INFY",
            plan_version_id=PLAN,
        )
    )

    assert [item.event_id for item in result.items] == [
        events[1].event_id,
        events[0].event_id,
    ]
    assert result.items[0].kind is MemoryKind.COUNTER_EVIDENCE
    assert result.items[0].polarity is MemoryPolarity.ABSTENTION
    assert all(item.known_at <= result.query.as_of for item in result.items)
    assert all(item.event_id in item.source_event_ids for item in result.items)


def test_recorded_at_prevents_backdated_reflection_leakage(tmp_path):
    memory, events, _journal = _memory(tmp_path)

    before_recording = memory.query(
        MemoryQuery(
            role=AgentMemoryRole.COACH,
            as_of=BASE + timedelta(hours=2, minutes=30),
            plan_version_id=PLAN,
        )
    )
    after_recording = memory.query(
        MemoryQuery(
            role=AgentMemoryRole.COACH,
            as_of=BASE + timedelta(hours=3),
            plan_version_id=PLAN,
        )
    )

    assert events[3].event_id not in {item.event_id for item in before_recording.items}
    assert events[3].event_id in {item.event_id for item in after_recording.items}


def test_role_scope_blocks_research_memory_from_trader(tmp_path):
    memory, events, _journal = _memory(tmp_path)
    as_of = BASE + timedelta(hours=4)

    trader = memory.query(MemoryQuery(role=AgentMemoryRole.TRADER, as_of=as_of))
    coach = memory.query(MemoryQuery(role=AgentMemoryRole.COACH, as_of=as_of))

    assert events[3].event_id not in {item.event_id for item in trader.items}
    assert events[3].event_id in {item.event_id for item in coach.items}


def test_context_pack_is_deterministic_auditable_and_non_authoritative(tmp_path):
    memory, _events, _journal = _memory(tmp_path)
    query = MemoryQuery(
        role=AgentMemoryRole.COMMITTEE,
        as_of=BASE + timedelta(hours=4),
        instrument_id="NSE:INFY",
        limit=10,
    )

    first = memory.build_context_pack(query)
    second = memory.build_context_pack(query)

    assert second == first
    assert first.context_pack_id.startswith("memory-context:sha256:")
    assert first.authority == "CONTEXT_ONLY"
    assert first.can_authorize_trading is False
    assert first.can_mutate_strategy is False
    assert first.can_mutate_risk is False
    assert first.source_event_ids
    assert not hasattr(memory, "promote_strategy")
    assert not hasattr(memory, "change_risk_limit")


def test_unknown_event_types_fail_closed(tmp_path):
    memory, _events, journal = _memory(tmp_path)
    journal.append(
        EventAppend(
            stream_id="unknown:1",
            event_type="FutureSensitiveCredentialRecorded",
            payload={"secret": "must-not-enter-memory"},
            idempotency_key="unknown:1",
            expected_version=0,
            occurred_at=BASE,
        )
    )

    result = memory.query(
        MemoryQuery(
            role=AgentMemoryRole.SECRETARY,
            as_of=BASE + timedelta(hours=4),
        )
    )

    assert "FutureSensitiveCredentialRecorded" not in {
        item.event_type for item in result.items
    }


def test_context_pack_audit_is_idempotent_and_records_no_mutation_authority(tmp_path):
    memory, _events, journal = _memory(tmp_path)
    pack = memory.build_context_pack(
        MemoryQuery(
            role=AgentMemoryRole.HISTORIAN,
            as_of=BASE + timedelta(hours=4),
        )
    )
    audit = ContextPackAuditTrail(journal)

    first = audit.record(
        pack,
        command_id="desk-cycle-1:historian-memory",
        occurred_at=BASE + timedelta(hours=4),
    )
    replay = audit.record(
        pack,
        command_id="desk-cycle-1:historian-memory",
        occurred_at=BASE + timedelta(hours=4),
    )

    assert replay.event_id == first.event_id
    assert first.event_type == "MemoryContextPackAssembled"
    assert first.payload["context_pack_id"] == pack.context_pack_id
    assert first.payload["authority"] == "CONTEXT_ONLY"
    assert first.payload["can_authorize_trading"] is False
    assert first.payload["source_event_ids"] == pack.source_event_ids

    second_consumer = audit.record(
        pack,
        command_id="desk-cycle-2:historian-memory",
        occurred_at=BASE + timedelta(hours=5),
    )
    assert second_consumer.event_id != first.event_id
    assert second_consumer.payload["consumer_command_id"] == (
        "desk-cycle-2:historian-memory"
    )


def test_context_pack_authority_cannot_be_forged(tmp_path):
    memory, _events, _journal = _memory(tmp_path)
    canonical = memory.build_context_pack(
        MemoryQuery(role=AgentMemoryRole.ANALYST, as_of=BASE + timedelta(hours=4))
    )

    with pytest.raises(ValueError, match="CONTEXT_ONLY"):
        MemoryContextPack(
            context_pack_id=canonical.context_pack_id,
            query=canonical.query,
            items=canonical.items,
            source_event_ids=canonical.source_event_ids,
            authority="OWNER",
            can_authorize_trading=True,
        )


def test_unresolved_or_future_evidence_fails_closed(tmp_path):
    memory, _events, journal = _memory(tmp_path)
    journal.append(
        EventAppend(
            stream_id="learning:unresolved",
            event_type="LearningObservationRecorded",
            payload={
                "summary": "unsupported memory",
                "evidence_refs": ["event:" + "f" * 64],
            },
            idempotency_key="learning:unresolved",
            expected_version=0,
            occurred_at=BASE,
        )
    )

    result = memory.query(
        MemoryQuery(role=AgentMemoryRole.COACH, as_of=BASE + timedelta(hours=4))
    )

    assert "unsupported memory" not in {item.facts.get("summary") for item in result.items}


def test_referenced_evidence_is_included_even_when_it_has_no_query_scope(tmp_path):
    clock = [BASE]
    journal = OperationalJournal(tmp_path / "journal.sqlite3", clock=lambda: clock[0])
    evidence = _append(
        journal,
        clock,
        event_type="OutcomeAttributed",
        payload={"episode_id": "episode-2", "realized_pnl_paise": -500},
        sequence=0,
    )
    _append(
        journal,
        clock,
        event_type="LearningObservationRecorded",
        payload={
            "summary": "scoped observation",
            "scope": {"plan_version_id": PLAN},
            "evidence_refs": [evidence.event_id],
        },
        sequence=1,
    )

    result = DecisionMemoryService(journal).query(
        MemoryQuery(
            role=AgentMemoryRole.COACH,
            as_of=BASE + timedelta(hours=2),
            plan_version_id=PLAN,
        )
    )

    assert {item.event_id for item in result.items} == {
        evidence.event_id,
        next(
            event.event_id
            for event in journal.read_all()
            if event.event_type == "LearningObservationRecorded"
        ),
    }


@pytest.mark.parametrize(
    ("role", "expected"),
    (
        (AgentMemoryRole.DESK_HEAD, set(MemoryKind)),
        (
            AgentMemoryRole.HISTORIAN,
            {
                MemoryKind.EPISODE,
                MemoryKind.OUTCOME,
                MemoryKind.COUNTER_EVIDENCE,
                MemoryKind.KNOWLEDGE,
                MemoryKind.GOVERNANCE,
                MemoryKind.MARKET_CONTEXT,
            },
        ),
        (
            AgentMemoryRole.REPORTER,
            {
                MemoryKind.EPISODE,
                MemoryKind.OUTCOME,
                MemoryKind.COUNTER_EVIDENCE,
                MemoryKind.KNOWLEDGE,
                MemoryKind.MARKET_CONTEXT,
            },
        ),
        (
            AgentMemoryRole.CROWD_READER,
            {
                MemoryKind.OUTCOME,
                MemoryKind.COUNTER_EVIDENCE,
                MemoryKind.MARKET_CONTEXT,
            },
        ),
        (AgentMemoryRole.ANALYST, set(MemoryKind) - {MemoryKind.OPERATIONS}),
        (AgentMemoryRole.COMMITTEE, set(MemoryKind)),
        (
            AgentMemoryRole.TRADER,
            {
                MemoryKind.EPISODE,
                MemoryKind.COUNTER_EVIDENCE,
                MemoryKind.GOVERNANCE,
                MemoryKind.RISK,
                MemoryKind.MARKET_CONTEXT,
                MemoryKind.OPERATIONS,
            },
        ),
        (
            AgentMemoryRole.COACH,
            {
                MemoryKind.EPISODE,
                MemoryKind.OUTCOME,
                MemoryKind.COUNTER_EVIDENCE,
                MemoryKind.LEARNING,
                MemoryKind.MARKET_CONTEXT,
            },
        ),
        (AgentMemoryRole.SECRETARY, set(MemoryKind)),
    ),
)
def test_all_nine_roles_have_explicit_memory_scopes(tmp_path, role, expected):
    clock = [BASE]
    journal = OperationalJournal(tmp_path / "journal.sqlite3", clock=lambda: clock[0])
    event_types = (
        "EpisodeStarted",
        "OutcomeAttributed",
        "SchedulerTaskHalted",
        "SourceClaimRecorded",
        "MistakeHypothesisProposed",
        "StageDossierIssued",
        "RiskReserved",
        "MarketDataIngestionCompleted",
        "SchedulerTaskCompleted",
    )
    for sequence, event_type in enumerate(event_types):
        _append(
            journal,
            clock,
            event_type=event_type,
            payload={"fixture": event_type},
            sequence=sequence,
        )

    result = DecisionMemoryService(journal).query(
        MemoryQuery(
            role=role,
            as_of=BASE + timedelta(hours=len(event_types)),
            limit=100,
        )
    )

    assert {item.kind for item in result.items} == expected


def test_scope_filter_uses_event_subject_not_incidental_nested_values(tmp_path):
    clock = [BASE]
    journal = OperationalJournal(tmp_path / "journal.sqlite3", clock=lambda: clock[0])
    event = _append(
        journal,
        clock,
        event_type="OutcomeAttributed",
        payload={
            "instrument_id": "NSE:INFY",
            "realized_pnl_paise": -100,
            "counterfactual": {"symbol": "NSE:TCS"},
        },
        sequence=0,
    )
    memory = DecisionMemoryService(journal)

    actual = memory.query(
        MemoryQuery(
            role=AgentMemoryRole.COACH,
            as_of=BASE + timedelta(hours=1),
            instrument_id="NSE:INFY",
        )
    )
    incidental = memory.query(
        MemoryQuery(
            role=AgentMemoryRole.COACH,
            as_of=BASE + timedelta(hours=1),
            instrument_id="NSE:TCS",
        )
    )

    assert {item.event_id for item in actual.items} == {event.event_id}
    assert incidental.items == ()


def test_desk_memory_coordinator_binds_one_audited_pack_per_role(tmp_path):
    memory, _events, journal = _memory(tmp_path)
    coordinator = DeskMemoryCoordinator(journal)
    scope = DeskMemoryScope(
        instrument_id="NSE:INFY",
        plan_version_id=PLAN,
        strategy_lineage_id="lineage-1",
        market_regime="bullish",
        timeframe="swing",
    )

    first = coordinator.prepare_cycle_contexts(
        cycle_id="cycle:memory-one",
        as_of=BASE + timedelta(hours=4),
        occurred_at=BASE + timedelta(hours=4),
        scope=scope,
    )
    replay = coordinator.prepare_cycle_contexts(
        cycle_id="cycle:memory-one",
        as_of=BASE + timedelta(hours=4),
        occurred_at=BASE + timedelta(hours=4),
        scope=scope,
    )

    assert set(first.contexts) == set(AgentMemoryRole)
    assert replay == first
    assert len(first.audit_event_ids) == len(AgentMemoryRole)
    assert len(set(first.audit_event_ids.values())) == len(AgentMemoryRole)
    assert all(pack.query.role is role for role, pack in first.contexts.items())
    assert all(pack.can_authorize_trading is False for pack in first.contexts.values())
