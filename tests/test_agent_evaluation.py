from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sensei.evaluation import (
    AgentEvaluationService,
    AgentInvocation,
    AgentInvocationLedger,
    AgentOutcome,
    CounterfactualReplayProducer,
    CounterfactualReplayResult,
    AgentVariantDecision,
    AgentVariantShadowRunner,
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


def test_veto_can_be_labeled_only_from_governed_counterfactual_evidence(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    ledger = AgentInvocationLedger(journal)
    context_pack_id, context_event_id = _context(
        journal, AgentMemoryRole.COMMITTEE, "cycle:veto"
    )
    invocation = ledger.record(
        AgentInvocation(
            cycle_id="cycle:veto",
            episode_id=None,
            role=AgentMemoryRole.COMMITTEE,
            context_pack_id=context_pack_id,
            context_pack_audit_event_id=context_event_id,
            prompt_id="prompt:committee:v1",
            model_id="deterministic:committee:v1",
            outcome=AgentOutcome.VETO,
            confidence=0.75,
            latency_ms=5,
            cost_microunits=0,
            occurred_at=NOW,
        ),
        command_id="record-veto",
    )
    evidence = journal.append(
        EventAppend(
            stream_id="counterfactual:veto",
            event_type="CounterfactualOutcomeAttributed",
            payload={
                "invocation_event_id": invocation.event_id,
                "methodology_id": "paper-replay:v1",
                "horizon_closed": True,
                "simulated_net_pnl": "125.50",
                "positive": True,
                "authority": "EVALUATION_ONLY",
            },
            idempotency_key="counterfactual:veto",
            expected_version=0,
            occurred_at=NOW + timedelta(days=5),
        )
    )

    ledger.label_counterfactual(
        invocation.event_id,
        occurred_at=NOW + timedelta(days=5),
        command_id="label-veto-counterfactual",
        evidence_event_id=evidence.event_id,
    )

    committee = AgentEvaluationService(journal).report(
        as_of=NOW + timedelta(days=6)
    ).roles[AgentMemoryRole.COMMITTEE]
    assert committee.false_vetoes == 1
    assert committee.counterfactual_labels == 1


def test_prompt_model_variants_are_compared_without_promotion_authority(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    ledger = AgentInvocationLedger(journal)
    for cycle, prompt in (("cycle:a", "prompt:analyst:champion"), ("cycle:b", "prompt:analyst:challenger")):
        pack_id, audit_id = _context(journal, AgentMemoryRole.ANALYST, cycle)
        ledger.record(
            AgentInvocation(
                cycle_id=cycle,
                episode_id=None,
                role=AgentMemoryRole.ANALYST,
                context_pack_id=pack_id,
                context_pack_audit_event_id=audit_id,
                prompt_id=prompt,
                model_id="model:test",
                outcome=AgentOutcome.ABSTAIN,
                confidence=None,
                latency_ms=1,
                cost_microunits=2,
                occurred_at=NOW,
            ),
            command_id=cycle,
        )

    report = AgentEvaluationService(journal).variant_report(
        role=AgentMemoryRole.ANALYST, as_of=NOW + timedelta(minutes=1)
    )

    assert set(report.variants) == {
        "prompt:analyst:champion|model:test",
        "prompt:analyst:challenger|model:test",
    }
    assert report.authority == "EVALUATION_ONLY"
    assert not hasattr(report, "promote")


def test_counterfactual_replay_producer_labels_mature_no_trade_invocations(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    ledger = AgentInvocationLedger(journal)
    pack_id, audit_id = _context(journal, AgentMemoryRole.COMMITTEE, "cycle:auto-veto")
    ledger.record(
        AgentInvocation(
            cycle_id="cycle:auto-veto",
            episode_id=None,
            role=AgentMemoryRole.COMMITTEE,
            context_pack_id=pack_id,
            context_pack_audit_event_id=audit_id,
            prompt_id="callable:test",
            model_id="python:test",
            outcome=AgentOutcome.VETO,
            confidence=0.8,
            latency_ms=1,
            cost_microunits=0,
            occurred_at=NOW,
        ),
        command_id="auto-veto",
    )
    market = journal.append(
        EventAppend(
            stream_id="market:closed-horizon",
            event_type="DecisionMarketSnapshotRecorded",
            payload={"snapshot_id": "snapshot:closed"},
            idempotency_key="market:closed-horizon",
            expected_version=0,
            occurred_at=NOW + timedelta(days=5),
        )
    )

    produced = CounterfactualReplayProducer(journal).run_pending(
        as_of=NOW + timedelta(days=6),
        methodology_id="paper-replay:v1",
        replay=lambda invocation: CounterfactualReplayResult(
            simulated_net_pnl=Decimal("25"),
            horizon_closed_at=NOW + timedelta(days=5),
            evidence_event_ids=(market.event_id,),
        ),
    )

    assert len(produced) == 1
    assert AgentEvaluationService(journal).report(
        as_of=NOW + timedelta(days=6)
    ).roles[AgentMemoryRole.COMMITTEE].false_vetoes == 1


def test_champion_and_challenger_execute_only_as_shadow_invocations(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    context = DecisionMemoryService(journal).build_context_pack(
        MemoryQuery(role=AgentMemoryRole.ANALYST, as_of=NOW)
    )

    recorded = AgentVariantShadowRunner(journal).run(
        trial_id="agent-trial:analyst:one",
        role=AgentMemoryRole.ANALYST,
        context=context,
        occurred_at=NOW,
        variants={
            "champion": lambda pack: AgentVariantDecision(
                "prompt:champion", "model:a", AgentOutcome.PROCEED, 0.7, 3
            ),
            "challenger": lambda pack: AgentVariantDecision(
                "prompt:challenger", "model:b", AgentOutcome.ABSTAIN, None, 4
            ),
        },
    )

    assert len(recorded) == 2
    report = AgentEvaluationService(journal).variant_report(
        role=AgentMemoryRole.ANALYST,
        as_of=NOW + timedelta(minutes=1),
    )
    assert set(report.variants) == {
        "prompt:champion|model:a",
        "prompt:challenger|model:b",
    }
    assert not hasattr(AgentVariantShadowRunner(journal), "execute_trade")
