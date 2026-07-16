"""Durable invocation facts and read-only agent-value projections."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sensei.memory import AgentMemoryRole
from sensei.operations import EventAppend, JournalIntegrityError, OperationalJournal

from .models import (
    AgentEvaluationReport,
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
            str(event.payload["invocation_event_id"]): bool(event.payload["positive"])
            for event in events
            if event.event_type == "AgentInvocationOutcomeLabeled"
        }
        grouped = defaultdict(list)
        for event in events:
            if event.event_type != "AgentInvocationRecorded":
                continue
            payload = dict(event.payload)
            payload["outcome_label"] = labels.get(event.event_id)
            grouped[AgentMemoryRole(str(payload["role"]))].append(payload)
        roles = {
            role: _evaluate(rows)
            for role, rows in sorted(grouped.items(), key=lambda item: item[0].value)
        }
        return AgentEvaluationReport(as_of=as_of, roles=roles)


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
    )
