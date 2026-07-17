"""Durable invocation facts and read-only agent-value projections."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from time import perf_counter_ns

from sensei.memory import AgentMemoryRole, ContextPackAuditTrail, MemoryContextPack
from sensei.operations import EventAppend, JournalIntegrityError, OperationalJournal

from .models import (
    AgentEvaluationReport,
    AgentVariantReport,
    AgentVariantDecision,
    CounterfactualReplayResult,
    AgentInvocation,
    AgentOutcome,
    RoleEvaluation,
)


class AgentInvocationLedger:
    def __init__(self, journal: OperationalJournal) -> None:
        self._journal = journal

    def record(self, invocation: AgentInvocation, *, command_id: str):
        if not isinstance(invocation, AgentInvocation):
            raise TypeError("invocation must be an AgentInvocation")
        if not command_id.strip():
            raise ValueError("command_id is required")
        if not self._journal.verify().ok:
            raise JournalIntegrityError("agent invocation requires an intact journal")
        audit = next(
            (
                event
                for event in self._journal.read_all()
                if event.event_id == invocation.context_pack_audit_event_id
                and event.event_type == "MemoryContextPackAssembled"
            ),
            None,
        )
        if (
            audit is None
            or audit.payload.get("context_pack_id") != invocation.context_pack_id
            or audit.payload.get("query", {}).get("role") != invocation.role.value
            or audit.payload.get("consumer_command_id")
            != f"{invocation.cycle_id}:{invocation.role.value}:memory"
        ):
            raise ValueError("agent invocation requires its exact audited context pack")
        if invocation.occurred_at < max(audit.occurred_at, audit.recorded_at):
            raise ValueError("agent invocation cannot predate its context pack")
        identity = hashlib.sha256(
            f"{invocation.cycle_id}|{invocation.role.value}".encode()
        ).hexdigest()
        return self._journal.append(
            EventAppend(
                stream_id="agent-invocation:" + identity,
                event_type="AgentInvocationRecorded",
                payload=invocation.to_payload(),
                idempotency_key="agent-invocation:" + identity,
                expected_version=0,
                occurred_at=invocation.occurred_at,
                correlation_id=invocation.cycle_id,
            )
        )

    def label_outcome(
        self,
        invocation_event_id: str,
        *,
        positive: bool,
        occurred_at: datetime,
        command_id: str,
        evidence_event_ids: tuple[str, ...],
    ):
        if not self._journal.verify().ok:
            raise JournalIntegrityError("outcome labeling requires an intact journal")
        if type(positive) is not bool:
            raise TypeError("positive must be boolean")
        if not command_id.strip():
            raise ValueError("command_id is required")
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        invocation = next(
            (
                event
                for event in self._journal.read_all()
                if event.event_id == invocation_event_id
                and event.event_type == "AgentInvocationRecorded"
            ),
            None,
        )
        if invocation is None:
            raise ValueError("agent invocation event does not exist")
        if occurred_at < max(invocation.occurred_at, invocation.recorded_at):
            raise ValueError("outcome label cannot predate the invocation")
        if not evidence_event_ids:
            raise ValueError("outcome label requires reconciled evidence")
        evidence = tuple(
            event
            for event in self._journal.read_all()
            if event.event_id in evidence_event_ids
        )
        if (
            invocation.payload.get("episode_id") is None
            or len(evidence) != 1
            or len(set(evidence_event_ids)) != 1
            or any(
                event.event_type != "OutcomeAttributed"
                or event.payload.get("reconciles") is not True
                or event.payload.get("episode_id")
                != invocation.payload.get("episode_id")
                or max(event.occurred_at, event.recorded_at) > occurred_at
                for event in evidence
            )
        ):
            raise ValueError(
                "outcome label evidence is not episode-linked and reconciled"
            )
        try:
            pnl = Decimal(str(evidence[0].payload["realized_net_pnl"]))
        except (KeyError, InvalidOperation):
            raise ValueError("outcome label evidence has invalid realized P&L") from None
        if (pnl > 0) is not positive:
            raise ValueError("outcome label conflicts with reconciled P&L")
        identity = hashlib.sha256(invocation_event_id.encode()).hexdigest()
        return self._journal.append(
            EventAppend(
                stream_id="agent-outcome-label:" + identity,
                event_type="AgentInvocationOutcomeLabeled",
                payload={
                    "invocation_event_id": invocation_event_id,
                    "positive": positive,
                    "label_kind": "realized",
                    "evidence_event_ids": list(evidence_event_ids),
                    "authority": "EVALUATION_ONLY",
                },
                idempotency_key="agent-outcome-label:"
                + hashlib.sha256(command_id.encode()).hexdigest(),
                expected_version=0,
                occurred_at=occurred_at,
                correlation_id=invocation.correlation_id,
                causation_id=invocation_event_id,
            )
        )

    def label_counterfactual(
        self,
        invocation_event_id: str,
        *,
        occurred_at: datetime,
        command_id: str,
        evidence_event_id: str,
    ):
        if not self._journal.verify().ok:
            raise JournalIntegrityError(
                "counterfactual labeling requires an intact journal"
            )
        if not command_id.strip() or not evidence_event_id.strip():
            raise ValueError("command and evidence IDs are required")
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        events = self._journal.read_all()
        invocation = next(
            (
                event
                for event in events
                if event.event_id == invocation_event_id
                and event.event_type == "AgentInvocationRecorded"
            ),
            None,
        )
        evidence = next(
            (event for event in events if event.event_id == evidence_event_id),
            None,
        )
        if invocation is None or invocation.payload.get("episode_id") is not None:
            raise ValueError("counterfactual labels require a no-trade invocation")
        if invocation.payload.get("outcome") not in {
            AgentOutcome.VETO.value,
            AgentOutcome.ABSTAIN.value,
        }:
            raise ValueError("only vetoed or abstained invocations are counterfactual")
        if (
            evidence is None
            or evidence.event_type != "CounterfactualOutcomeAttributed"
            or evidence.payload.get("invocation_event_id") != invocation_event_id
            or evidence.payload.get("horizon_closed") is not True
            or evidence.payload.get("authority") != "EVALUATION_ONLY"
            or not str(evidence.payload.get("methodology_id", "")).strip()
            or max(evidence.occurred_at, evidence.recorded_at) > occurred_at
            or occurred_at < max(invocation.occurred_at, invocation.recorded_at)
        ):
            raise ValueError("counterfactual evidence is incomplete or not point-in-time")
        positive = evidence.payload.get("positive")
        if type(positive) is not bool:
            raise ValueError("counterfactual evidence needs a boolean outcome")
        try:
            pnl = Decimal(str(evidence.payload["simulated_net_pnl"]))
        except (KeyError, InvalidOperation):
            raise ValueError("counterfactual evidence has invalid simulated P&L") from None
        if not pnl.is_finite() or (pnl > 0) is not positive:
            raise ValueError("counterfactual outcome conflicts with simulated P&L")
        identity = hashlib.sha256(invocation_event_id.encode()).hexdigest()
        return self._journal.append(
            EventAppend(
                stream_id="agent-outcome-label:" + identity,
                event_type="AgentInvocationOutcomeLabeled",
                payload={
                    "invocation_event_id": invocation_event_id,
                    "positive": positive,
                    "label_kind": "counterfactual",
                    "evidence_event_ids": [evidence_event_id],
                    "authority": "EVALUATION_ONLY",
                },
                idempotency_key="agent-counterfactual-label:"
                + hashlib.sha256(command_id.encode()).hexdigest(),
                expected_version=0,
                occurred_at=occurred_at,
                correlation_id=invocation.correlation_id,
                causation_id=invocation_event_id,
            )
        )


class AgentEvaluationService:
    """Score recorded agent behavior without execution or lifecycle authority."""

    def __init__(self, journal: OperationalJournal) -> None:
        self._journal = journal

    def report(self, *, as_of: datetime) -> AgentEvaluationReport:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if not self._journal.verify().ok:
            raise JournalIntegrityError("agent evaluation requires an intact journal")
        events = tuple(
            event
            for event in self._journal.read_all()
            if max(event.occurred_at, event.recorded_at) <= as_of
        )
        labels = {
            str(event.payload["invocation_event_id"]): (
                bool(event.payload["positive"]),
                str(event.payload.get("label_kind", "realized")),
            )
            for event in events
            if event.event_type == "AgentInvocationOutcomeLabeled"
        }
        grouped = defaultdict(list)
        for event in events:
            if event.event_type != "AgentInvocationRecorded":
                continue
            payload = dict(event.payload)
            label = labels.get(event.event_id)
            payload["outcome_label"] = label[0] if label is not None else None
            payload["label_kind"] = label[1] if label is not None else None
            grouped[AgentMemoryRole(str(payload["role"]))].append(payload)
        roles = {
            role: _evaluate(rows)
            for role, rows in sorted(grouped.items(), key=lambda item: item[0].value)
        }
        return AgentEvaluationReport(as_of=as_of, roles=roles)

    def variant_report(
        self, *, role: AgentMemoryRole, as_of: datetime
    ) -> AgentVariantReport:
        if not isinstance(role, AgentMemoryRole):
            raise TypeError("role must be an AgentMemoryRole")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if not self._journal.verify().ok:
            raise JournalIntegrityError("agent evaluation requires an intact journal")
        events = tuple(
            event
            for event in self._journal.read_all()
            if max(event.occurred_at, event.recorded_at) <= as_of
        )
        labels = {
            str(event.payload["invocation_event_id"]): (
                bool(event.payload["positive"]),
                str(event.payload.get("label_kind", "realized")),
            )
            for event in events
            if event.event_type == "AgentInvocationOutcomeLabeled"
        }
        grouped = defaultdict(list)
        for event in events:
            if (
                event.event_type != "AgentInvocationRecorded"
                or event.payload.get("role") != role.value
            ):
                continue
            payload = dict(event.payload)
            label = labels.get(event.event_id)
            payload["outcome_label"] = label[0] if label is not None else None
            payload["label_kind"] = label[1] if label is not None else None
            key = f"{payload['prompt_id']}|{payload['model_id']}"
            grouped[key].append(payload)
        return AgentVariantReport(
            as_of=as_of,
            variants={key: _evaluate(rows) for key, rows in sorted(grouped.items())},
        )


class CounterfactualReplayProducer:
    """Attribute mature no-trade invocations through a governed market replay."""

    def __init__(self, journal: OperationalJournal) -> None:
        self._journal = journal
        self._ledger = AgentInvocationLedger(journal)

    def run_pending(
        self,
        *,
        as_of: datetime,
        methodology_id: str,
        replay: Callable[[object], CounterfactualReplayResult | None],
    ) -> tuple[str, ...]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if not methodology_id.strip():
            raise ValueError("methodology_id is required")
        if not self._journal.verify().ok:
            raise JournalIntegrityError("counterfactual replay requires an intact journal")
        events = self._journal.read_all()
        labeled = {
            str(event.payload["invocation_event_id"])
            for event in events
            if event.event_type == "AgentInvocationOutcomeLabeled"
        }
        by_id = {event.event_id: event for event in events}
        produced = []
        for invocation in events:
            if (
                invocation.event_type != "AgentInvocationRecorded"
                or invocation.event_id in labeled
                or invocation.payload.get("episode_id") is not None
                or invocation.payload.get("outcome")
                not in {AgentOutcome.VETO.value, AgentOutcome.ABSTAIN.value}
                or max(invocation.occurred_at, invocation.recorded_at) > as_of
            ):
                continue
            result = replay(invocation)
            if result is None:
                continue
            if not isinstance(result, CounterfactualReplayResult):
                raise TypeError("replay must return CounterfactualReplayResult or None")
            if result.horizon_closed_at > as_of:
                continue
            evidence = tuple(by_id.get(event_id) for event_id in result.evidence_event_ids)
            if any(
                event is None or max(event.occurred_at, event.recorded_at) > result.horizon_closed_at
                for event in evidence
            ):
                raise ValueError("counterfactual replay evidence is missing or future-known")
            identity = hashlib.sha256(
                f"{invocation.event_id}|{methodology_id}".encode()
            ).hexdigest()
            attributed = self._journal.append(
                EventAppend(
                    stream_id="counterfactual-outcome:" + identity,
                    event_type="CounterfactualOutcomeAttributed",
                    payload={
                        "invocation_event_id": invocation.event_id,
                        "methodology_id": methodology_id,
                        "horizon_closed": True,
                        "horizon_closed_at": result.horizon_closed_at.isoformat(),
                        "simulated_net_pnl": str(result.simulated_net_pnl),
                        "positive": result.simulated_net_pnl > 0,
                        "evidence_event_ids": list(result.evidence_event_ids),
                        "authority": "EVALUATION_ONLY",
                    },
                    idempotency_key="counterfactual-outcome:" + identity,
                    expected_version=0,
                    occurred_at=result.horizon_closed_at,
                    correlation_id=invocation.correlation_id,
                    causation_id=invocation.event_id,
                )
            )
            label = self._ledger.label_counterfactual(
                invocation.event_id,
                occurred_at=result.horizon_closed_at,
                command_id="counterfactual-label:" + identity,
                evidence_event_id=attributed.event_id,
            )
            produced.append(label.event_id)
        return tuple(produced)


class AgentVariantShadowRunner:
    """Execute paired prompt/model challengers with evaluation-only authority."""

    def __init__(self, journal: OperationalJournal) -> None:
        self._journal = journal
        self._ledger = AgentInvocationLedger(journal)
        self._audit = ContextPackAuditTrail(journal)

    def run(
        self,
        *,
        trial_id: str,
        role: AgentMemoryRole,
        context: MemoryContextPack,
        variants: Mapping[str, Callable[[MemoryContextPack], AgentVariantDecision]],
        occurred_at: datetime,
    ) -> tuple[str, ...]:
        if not trial_id.strip() or len(variants) < 2:
            raise ValueError("shadow trial requires an ID and at least two variants")
        if context.query.role is not role or context.authority != "CONTEXT_ONLY":
            raise ValueError("shadow variants require exact role-scoped context")
        recorded = []
        for name, invoke in sorted(variants.items()):
            if not name.strip():
                raise ValueError("variant names are required")
            child_cycle = f"{trial_id}:variant:{hashlib.sha256(name.encode()).hexdigest()}"
            audit = self._audit.record(
                context,
                command_id=f"{child_cycle}:{role.value}:memory",
                occurred_at=occurred_at,
            )
            started = perf_counter_ns()
            decision = invoke(context)
            latency_ms = (perf_counter_ns() - started + 999_999) // 1_000_000
            if not isinstance(decision, AgentVariantDecision):
                raise TypeError("variant must return an AgentVariantDecision")
            event = self._ledger.record(
                AgentInvocation(
                    cycle_id=child_cycle,
                    episode_id=None,
                    role=role,
                    context_pack_id=context.context_pack_id,
                    context_pack_audit_event_id=audit.event_id,
                    prompt_id=decision.prompt_id,
                    model_id=decision.model_id,
                    outcome=decision.outcome,
                    confidence=decision.confidence,
                    latency_ms=latency_ms,
                    cost_microunits=decision.cost_microunits,
                    occurred_at=max(occurred_at, audit.recorded_at),
                ),
                command_id=f"{child_cycle}:invocation",
            )
            recorded.append(event.event_id)
        return tuple(recorded)


def _evaluate(rows) -> RoleEvaluation:
    outcomes = [AgentOutcome(str(row["outcome"])) for row in rows]
    latency = [int(row["latency_ms"]) for row in rows]
    labeled = [
        (
            (
                float(row["confidence"])
                if AgentOutcome(str(row["outcome"])) is AgentOutcome.PROCEED
                else 1 - float(row["confidence"])
            ),
            bool(row["outcome_label"]),
        )
        for row in rows
        if row.get("confidence") is not None
        and row.get("outcome_label") is not None
        and AgentOutcome(str(row["outcome"]))
        in {AgentOutcome.PROCEED, AgentOutcome.VETO}
    ]
    brier = (
        round(
            sum((confidence - int(label)) ** 2 for confidence, label in labeled)
            / len(labeled),
            6,
        )
        if labeled
        else None
    )
    false_vetoes = sum(
        outcome is AgentOutcome.VETO and row.get("outcome_label") is True
        for outcome, row in zip(outcomes, rows, strict=True)
    )
    false_approvals = sum(
        outcome is AgentOutcome.PROCEED and row.get("outcome_label") is False
        for outcome, row in zip(outcomes, rows, strict=True)
    )
    return RoleEvaluation(
        invocations=len(rows),
        abstentions=outcomes.count(AgentOutcome.ABSTAIN),
        vetoes=outcomes.count(AgentOutcome.VETO),
        errors=outcomes.count(AgentOutcome.ERROR),
        false_vetoes=false_vetoes,
        false_approvals=false_approvals,
        average_latency_ms=round(sum(latency) / len(latency)),
        total_cost_microunits=sum(int(row["cost_microunits"]) for row in rows),
        brier_score=brier,
        counterfactual_labels=sum(
            row.get("label_kind") == "counterfactual" for row in rows
        ),
    )
