"""Deterministic, reconcilable outcome attribution for long-only episodes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN

from sensei.operations.journal import (
    EventAppend,
    JournalEvent,
    OperationalJournal,
)

_PAISE = Decimal("0.01")


@dataclass(frozen=True)
class AttributionInput:
    episode_id: str
    quantity: int
    planned_entry: Decimal
    planned_exit: Decimal
    actual_entry: Decimal
    actual_exit: Decimal
    fees: Decimal
    reasoning_quality_passed: bool | None = None

    def __post_init__(self) -> None:
        if not self.episode_id:
            raise ValueError("episode_id is required")
        if isinstance(self.quantity, bool) or self.quantity <= 0:
            raise ValueError("quantity must be positive")
        for name in ("planned_entry", "planned_exit", "actual_entry", "actual_exit"):
            value = _decimal(getattr(self, name), name)
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if _decimal(self.fees, "fees") < 0:
            raise ValueError("fees must not be negative")


@dataclass(frozen=True)
class OutcomeAttribution:
    episode_id: str
    plan_pnl: Decimal
    entry_execution_impact: Decimal
    exit_execution_impact: Decimal
    cost_impact: Decimal
    realized_net_pnl: Decimal
    process_outcome: str

    @property
    def reconciles(self) -> bool:
        total = (
            self.plan_pnl
            + self.entry_execution_impact
            + self.exit_execution_impact
            + self.cost_impact
        )
        return total == self.realized_net_pnl


class OutcomeAttributor:
    @staticmethod
    def attribute(facts: AttributionInput) -> OutcomeAttribution:
        quantity = Decimal(facts.quantity)
        plan_pnl = _money(quantity * (facts.planned_exit - facts.planned_entry))
        entry_impact = _money(quantity * (facts.planned_entry - facts.actual_entry))
        exit_impact = _money(quantity * (facts.actual_exit - facts.planned_exit))
        cost_impact = _money(-facts.fees)
        realized = _money(plan_pnl + entry_impact + exit_impact + cost_impact)
        outcome = "RIGHT_OUTCOME" if realized > 0 else "WRONG_OUTCOME"
        if facts.reasoning_quality_passed is None:
            process_outcome = f"UNASSESSED_PROCESS_{outcome}"
        else:
            process = "RIGHT_PROCESS" if facts.reasoning_quality_passed else "WRONG_PROCESS"
            process_outcome = f"{process}_{outcome}"
        return OutcomeAttribution(
            episode_id=facts.episode_id,
            plan_pnl=plan_pnl,
            entry_execution_impact=entry_impact,
            exit_execution_impact=exit_impact,
            cost_impact=cost_impact,
            realized_net_pnl=realized,
            process_outcome=process_outcome,
        )


@dataclass(frozen=True)
class RecordedAttribution:
    attribution: OutcomeAttribution
    event: JournalEvent


class OutcomeAttributionService:
    """Persist deterministic attribution only against complete journal facts."""

    def __init__(self, journal: OperationalJournal) -> None:
        self._journal = journal

    def record(
        self,
        facts: AttributionInput,
        *,
        evidence_refs: tuple[str, ...],
        currency: str,
        occurred_at: datetime,
        command_id: str,
    ) -> RecordedAttribution:
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        normalized_currency = currency.strip().upper()
        if len(normalized_currency) != 3 or not normalized_currency.isalpha():
            raise ValueError("currency must be a three-letter code")
        if not evidence_refs or len(set(evidence_refs)) != len(evidence_refs):
            raise ValueError("unique evidence_refs are required")
        stream_id = f"episode:{facts.episode_id}"
        events = self._journal.read_stream(stream_id)
        if not events or not any(
            event.event_type == "EpisodeClosed" for event in events
        ):
            raise ValueError("outcome attribution requires a closed Trade Episode")
        episode_event_ids = {event.event_id for event in events}
        missing = set(evidence_refs) - episode_event_ids
        if missing:
            raise ValueError("attribution evidence must belong to the Trade Episode")
        referenced = {
            event.event_id: event
            for event in events
            if event.event_id in evidence_refs
        }
        if any(event.occurred_at > occurred_at for event in referenced.values()):
            raise ValueError("attribution evidence cannot postdate the outcome")
        entry_events = tuple(
            event for event in events if event.event_type == "EntryFillRecorded"
        )
        exit_events = tuple(
            event for event in events if event.event_type == "ExitFillRecorded"
        )
        required_fill_ids = {
            event.event_id for event in (*entry_events, *exit_events)
        }
        if not entry_events or not exit_events or not required_fill_ids <= set(
            evidence_refs
        ):
            raise ValueError("attribution requires every entry and exit fill")
        costs = tuple(
            event
            for event in referenced.values()
            if event.event_type == "CostsReconciled"
        )
        if len(costs) != 1:
            raise ValueError("attribution requires one reconciled cost record")

        started = events[0]
        planned_entry = Decimal(int(started.payload["planned_entry_price_paise"])) / 100
        planned_exit = Decimal(int(started.payload["planned_exit_price_paise"])) / 100
        if _decimal(facts.planned_entry, "planned_entry") != planned_entry:
            raise ValueError("planned entry does not match the Trade Episode")
        if _decimal(facts.planned_exit, "planned_exit") != planned_exit:
            raise ValueError("planned exit does not match the Trade Episode")

        entry_quantity, entry_notional = _fill_totals(entry_events)
        exit_quantity, exit_notional = _fill_totals(exit_events)
        if entry_quantity != exit_quantity or facts.quantity != entry_quantity:
            raise ValueError("attribution quantity does not match all fills")
        if _decimal(facts.actual_entry, "actual_entry") * entry_quantity != entry_notional:
            raise ValueError("actual entry does not match all entry fills")
        if _decimal(facts.actual_exit, "actual_exit") * exit_quantity != exit_notional:
            raise ValueError("actual exit does not match all exit fills")

        cost = costs[0]
        if cost.payload.get("currency") != normalized_currency:
            raise ValueError("attribution currency does not match reconciled costs")
        if _decimal(cost.payload.get("fees"), "reconciled fees") != _decimal(
            facts.fees, "fees"
        ):
            raise ValueError("fees do not match reconciled costs")

        existing_attributions = tuple(
            event for event in events if event.event_type == "OutcomeAttributed"
        )
        if existing_attributions and not any(
            event.idempotency_key == command_id for event in existing_attributions
        ):
            raise ValueError("Trade Episode already has an outcome attribution")

        attribution = OutcomeAttributor.attribute(facts)
        event = self._journal.append(
            EventAppend(
                stream_id=stream_id,
                event_type="OutcomeAttributed",
                payload={
                    "episode_id": facts.episode_id,
                    "currency": normalized_currency,
                    "plan_pnl": str(attribution.plan_pnl),
                    "entry_execution_impact": str(
                        attribution.entry_execution_impact
                    ),
                    "exit_execution_impact": str(attribution.exit_execution_impact),
                    "cost_impact": str(attribution.cost_impact),
                    "realized_net_pnl": str(attribution.realized_net_pnl),
                    "process_outcome": attribution.process_outcome,
                    "evidence_refs": list(evidence_refs),
                    "reconciles": attribution.reconciles,
                },
                idempotency_key=command_id,
                expected_version=len(events),
                occurred_at=occurred_at,
                correlation_id=facts.episode_id,
                causation_id=evidence_refs[-1],
            )
        )
        return RecordedAttribution(attribution=attribution, event=event)


def _decimal(value: Decimal, name: str) -> Decimal:
    try:
        converted = Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{name} must be a finite decimal") from None
    if not converted.is_finite():
        raise ValueError(f"{name} must be a finite decimal")
    return converted


def _money(value: Decimal) -> Decimal:
    return value.quantize(_PAISE, rounding=ROUND_HALF_EVEN)


def _fill_totals(events: tuple[JournalEvent, ...]) -> tuple[int, Decimal]:
    quantity = 0
    notional = Decimal("0")
    for event in events:
        fill_quantity = int(event.payload["quantity"])
        fill_price = _decimal(event.payload["price"], "fill price")
        quantity += fill_quantity
        notional += fill_price * fill_quantity
    return quantity, notional
