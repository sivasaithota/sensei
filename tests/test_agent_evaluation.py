from datetime import datetime, timedelta, timezone

from sensei.evaluation import (
    AgentEvaluationService,
    AgentInvocation,
    AgentInvocationLedger,
    AgentOutcome,
)
from sensei.memory import AgentMemoryRole
from sensei.memory import ContextPackAuditTrail, DecisionMemoryService, MemoryQuery
from sensei.operations import EventAppend, OperationalJournal


NOW = datetime(2026, 7, 17, 10, 0, tzinfo=timezone.utc)


def _context(journal, role, cycle_id):
    pack = DecisionMemoryService(journal).build_context_pack(
        MemoryQuery(role=role, as_of=NOW)
    )
    event = ContextPackAuditTrail(journal).record(
        pack,
        command_id=f"{cycle_id}:{role.value}:memory",
        occurred_at=NOW,
    )
    return pack.context_pack_id, event.event_id


def _outcome(journal, name, pnl):
    return journal.append(
        EventAppend(
            stream_id=f"outcome:{name}",
            event_type="OutcomeAttributed",
            payload={
                "episode_id": f"episode:{name}",
                "realized_net_pnl": str(pnl),
                "reconciles": True,
                "evidence_refs": ["event:" + "e" * 64],
            },
            idempotency_key=f"outcome:{name}",
            expected_version=0,
            occurred_at=NOW + timedelta(minutes=3),
        )
    )


def test_agent_evaluation_scores_cost_latency_abstention_and_calibration(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    ledger = AgentInvocationLedger(journal)
    contexts = [
        _context(journal, AgentMemoryRole.ANALYST, f"cycle:{name}")
        for name in ("one", "two", "three")
    ]
    rows = (
        AgentInvocation(
            cycle_id="cycle:one",
            episode_id="episode:one",
            role=AgentMemoryRole.ANALYST,
            context_pack_id=contexts[0][0],
            context_pack_audit_event_id=contexts[0][1],
            prompt_id="prompt:analyst:v1",
            model_id="deterministic:analyst:v1",
            outcome=AgentOutcome.PROCEED,
            confidence=0.8,
            latency_ms=120,
            cost_microunits=0,
            occurred_at=NOW,
        ),
        AgentInvocation(
            cycle_id="cycle:two",
            episode_id=None,
            role=AgentMemoryRole.ANALYST,
            context_pack_id=contexts[1][0],
            context_pack_audit_event_id=contexts[1][1],
            prompt_id="prompt:analyst:v1",
            model_id="deterministic:analyst:v1",
            outcome=AgentOutcome.ABSTAIN,
            confidence=None,
            latency_ms=80,
            cost_microunits=0,
            occurred_at=NOW + timedelta(minutes=1),
        ),
        AgentInvocation(
            cycle_id="cycle:three",
            episode_id="episode:three",
            role=AgentMemoryRole.ANALYST,
            context_pack_id=contexts[2][0],
            context_pack_audit_event_id=contexts[2][1],
            prompt_id="prompt:analyst:v1",
            model_id="deterministic:analyst:v1",
            outcome=AgentOutcome.VETO,
            confidence=0.7,
            latency_ms=100,
            cost_microunits=5,
            occurred_at=NOW + timedelta(minutes=2),
        ),
    )
    recorded = [
        ledger.record(row, command_id=f"invocation-{index}")
        for index, row in enumerate(rows)
    ]
    positive_one = _outcome(journal, "one", 100)
    positive_three = _outcome(journal, "three", 100)
    ledger.label_outcome(
        recorded[0].event_id,
        positive=True,
        occurred_at=NOW + timedelta(minutes=3),
        command_id="label-0",
        evidence_event_ids=(positive_one.event_id,),
    )
    ledger.label_outcome(
        recorded[2].event_id,
        positive=True,
        occurred_at=NOW + timedelta(minutes=3),
        command_id="label-2",
        evidence_event_ids=(positive_three.event_id,),
    )

    report = AgentEvaluationService(journal).report(
        as_of=NOW + timedelta(minutes=4)
    )
    analyst = report.roles[AgentMemoryRole.ANALYST]

    assert analyst.invocations == 3
    assert analyst.abstentions == 1
    assert analyst.vetoes == 1
    assert analyst.false_vetoes == 1
    assert analyst.average_latency_ms == 100
    assert analyst.total_cost_microunits == 5
    assert analyst.brier_score == 0.265
    assert report.authority == "EVALUATION_ONLY"
    assert report.can_authorize_trading is False


def test_agent_evaluation_is_point_in_time_and_has_no_mutation_api(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    ledger = AgentInvocationLedger(journal)
    context_pack_id, context_event_id = _context(
        journal, AgentMemoryRole.COACH, "cycle:future"
    )
    ledger.record(
        AgentInvocation(
            cycle_id="cycle:future",
            episode_id=None,
            role=AgentMemoryRole.COACH,
            context_pack_id=context_pack_id,
            context_pack_audit_event_id=context_event_id,
            prompt_id="prompt:coach:v1",
            model_id="deterministic:coach:v1",
            outcome=AgentOutcome.ABSTAIN,
            confidence=None,
            latency_ms=10,
            cost_microunits=0,
            occurred_at=NOW + timedelta(days=1),
        ),
        command_id="future",
    )
    service = AgentEvaluationService(journal)

    report = service.report(as_of=NOW)

    assert report.roles == {}
    assert not hasattr(service, "approve_trade")
    assert not hasattr(service, "promote_strategy")
