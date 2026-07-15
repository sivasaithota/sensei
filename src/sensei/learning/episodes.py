"""Trade Episode commands and projections over the shared event journal."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

from sensei.operations.journal import EventAppend, JournalEvent, OperationalJournal


class EpisodeInvariantError(ValueError):
    """A command would make an episode's history internally inconsistent."""


class EpisodeNotFound(LookupError):
    """No episode exists for the supplied identity."""


class EpisodeEventType(str, Enum):
    APPROVAL_RECORDED = "ApprovalRecorded"
    INTENT_ACCEPTED = "IntentAccepted"
    ORDER_SUBMITTED = "OrderSubmitted"
    ENTRY_FILL_RECORDED = "EntryFillRecorded"
    PROTECTION_VERIFIED = "ProtectionVerified"
    EXIT_FILL_RECORDED = "ExitFillRecorded"
    COSTS_RECONCILED = "CostsReconciled"
    RECONCILIATION_RECORDED = "ReconciliationRecorded"
    REVIEW_RECORDED = "ReviewRecorded"
    EPISODE_CLOSED = "EpisodeClosed"


class EpisodeStatus(str, Enum):
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    WORKING = "WORKING"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class EpisodeCommand:
    episode_id: str
    event_type: EpisodeEventType
    payload: Mapping[str, Any]
    occurred_at: datetime
    command_id: str

    def __post_init__(self) -> None:
        _require_identity("episode_id", self.episode_id)
        _require_identity("command_id", self.command_id)
        _require_aware(self.occurred_at)


@dataclass(frozen=True)
class TradeEpisode:
    episode_id: str
    strategy_lineage_id: str
    plan_version_id: str
    decision_trace_id: str
    market_snapshot_id: str
    account_snapshot_id: str
    intent_id: str
    instrument_id: str
    timeframe: str
    planned_entry_price_paise: int
    planned_exit_price_paise: int
    signal_time: datetime
    status: EpisodeStatus
    open_quantity: int
    protected_quantity: int
    approved: bool | None
    costs_reconciled: bool
    event_ids: tuple[str, ...]
    linked_event_ids: tuple[str, ...]


class TradeEpisodeJournal:
    """Own episode invariants while delegating durability to OperationalJournal."""

    def __init__(self, journal: OperationalJournal) -> None:
        self._journal = journal

    def is_bound_to_journal(self, journal: OperationalJournal) -> bool:
        """Return whether episode history uses the exact runtime journal."""

        return self._journal is journal

    def start(
        self,
        *,
        episode_id: str,
        strategy_lineage_id: str,
        plan_version_id: str,
        decision_trace_id: str,
        market_snapshot_id: str,
        account_snapshot_id: str,
        intent_id: str,
        instrument_id: str,
        timeframe: str,
        planned_entry_price_paise: int,
        planned_exit_price_paise: int,
        signal_time: datetime,
        command_id: str,
    ) -> JournalEvent:
        for label, value in (
            ("episode_id", episode_id),
            ("strategy_lineage_id", strategy_lineage_id),
            ("plan_version_id", plan_version_id),
            ("decision_trace_id", decision_trace_id),
            ("market_snapshot_id", market_snapshot_id),
            ("account_snapshot_id", account_snapshot_id),
            ("intent_id", intent_id),
            ("instrument_id", instrument_id),
            ("timeframe", timeframe),
            ("command_id", command_id),
        ):
            _require_identity(label, value)
        for label, value in (
            ("planned_entry_price_paise", planned_entry_price_paise),
            ("planned_exit_price_paise", planned_exit_price_paise),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{label} must be a positive integer")
        if planned_exit_price_paise <= planned_entry_price_paise:
            raise ValueError("planned exit must be above planned entry")
        _require_aware(signal_time)
        return self._journal.append(
            EventAppend(
                stream_id=_stream_id(episode_id),
                event_type="EpisodeStarted",
                payload={
                    "episode_id": episode_id,
                    "strategy_lineage_id": strategy_lineage_id,
                    "plan_version_id": plan_version_id,
                    "decision_trace_id": decision_trace_id,
                    "market_snapshot_id": market_snapshot_id,
                    "account_snapshot_id": account_snapshot_id,
                    "intent_id": intent_id,
                    "instrument_id": instrument_id,
                    "timeframe": timeframe,
                    "planned_entry_price_paise": planned_entry_price_paise,
                    "planned_exit_price_paise": planned_exit_price_paise,
                    "signal_time": signal_time.isoformat(),
                },
                idempotency_key=command_id,
                expected_version=0,
                occurred_at=signal_time,
                correlation_id=intent_id,
            )
        )

    def record(self, command: EpisodeCommand) -> JournalEvent:
        events = self._journal.read_stream(_stream_id(command.episode_id))
        if not events:
            raise EpisodeNotFound(command.episode_id)
        episode, state = _project(events)
        repeated = next(
            (
                event
                for event in events
                if event.idempotency_key == command.command_id
            ),
            None,
        )
        if repeated is not None:
            if (
                repeated.event_type != command.event_type.value
                or dict(repeated.payload) != dict(command.payload)
                or repeated.occurred_at != command.occurred_at
            ):
                raise EpisodeInvariantError(
                    "command_id was reused for a different episode event"
                )
            return repeated
        _validate_command(episode, state, command)
        return self._journal.append(
            EventAppend(
                stream_id=_stream_id(command.episode_id),
                event_type=command.event_type.value,
                payload=dict(command.payload),
                idempotency_key=command.command_id,
                expected_version=len(events),
                occurred_at=command.occurred_at,
                correlation_id=episode.intent_id,
                causation_id=events[-1].event_id,
            )
        )

    def get(self, episode_id: str) -> TradeEpisode:
        events = self._journal.read_stream(_stream_id(episode_id))
        if not events:
            raise EpisodeNotFound(episode_id)
        episode, _ = _project(events)
        linked = tuple(
            event.event_id
            for event in self._journal.read_all()
            if event.stream_id != _stream_id(episode_id)
            and event.correlation_id in {episode.episode_id, episode.intent_id}
        )
        return replace(episode, linked_event_ids=linked)


@dataclass
class _ProjectionState:
    status: EpisodeStatus = EpisodeStatus.AWAITING_APPROVAL
    approved: bool | None = None
    intent_accepted: bool = False
    order_submitted: bool = False
    open_quantity: int = 0
    protected_quantity: int = 0
    entry_fill_ids: set[str] | None = None
    exit_fill_ids: set[str] | None = None
    costs_reconciled: bool = False

    def __post_init__(self) -> None:
        self.entry_fill_ids = set() if self.entry_fill_ids is None else self.entry_fill_ids
        self.exit_fill_ids = set() if self.exit_fill_ids is None else self.exit_fill_ids


def _project(events: tuple[JournalEvent, ...]) -> tuple[TradeEpisode, _ProjectionState]:
    first = events[0]
    if first.event_type != "EpisodeStarted":
        raise EpisodeInvariantError("episode stream does not start with EpisodeStarted")
    payload = first.payload
    state = _ProjectionState()
    for event in events[1:]:
        _apply(state, event.event_type, event.payload)
    return (
        TradeEpisode(
            episode_id=str(payload["episode_id"]),
            strategy_lineage_id=str(payload["strategy_lineage_id"]),
            plan_version_id=str(payload["plan_version_id"]),
            decision_trace_id=str(payload["decision_trace_id"]),
            market_snapshot_id=str(payload["market_snapshot_id"]),
            account_snapshot_id=str(payload["account_snapshot_id"]),
            intent_id=str(payload["intent_id"]),
            instrument_id=str(payload["instrument_id"]),
            timeframe=str(payload["timeframe"]),
            planned_entry_price_paise=int(payload["planned_entry_price_paise"]),
            planned_exit_price_paise=int(payload["planned_exit_price_paise"]),
            signal_time=datetime.fromisoformat(str(payload["signal_time"])),
            status=state.status,
            open_quantity=state.open_quantity,
            protected_quantity=state.protected_quantity,
            approved=state.approved,
            costs_reconciled=state.costs_reconciled,
            event_ids=tuple(event.event_id for event in events),
            linked_event_ids=(),
        ),
        state,
    )


def _validate_command(
    episode: TradeEpisode, state: _ProjectionState, command: EpisodeCommand
) -> None:
    if episode.status in (EpisodeStatus.CLOSED, EpisodeStatus.REJECTED):
        if command.event_type not in (
            EpisodeEventType.COSTS_RECONCILED,
            EpisodeEventType.RECONCILIATION_RECORDED,
            EpisodeEventType.REVIEW_RECORDED,
        ):
            raise EpisodeInvariantError("terminal episode cannot accept trading events")
    payload = command.payload
    if command.event_type is EpisodeEventType.APPROVAL_RECORDED:
        if state.approved is not None:
            raise EpisodeInvariantError("approval was already recorded")
        if not isinstance(payload.get("approved"), bool):
            raise EpisodeInvariantError("approval requires an approved boolean")
    elif command.event_type is EpisodeEventType.INTENT_ACCEPTED:
        if state.approved is not True:
            raise EpisodeInvariantError("intent acceptance requires approval")
        if state.intent_accepted:
            raise EpisodeInvariantError("trade intent was already accepted")
        if payload.get("intent_id") != episode.intent_id:
            raise EpisodeInvariantError("accepted intent does not match the episode")
    elif command.event_type is EpisodeEventType.ORDER_SUBMITTED:
        if not state.intent_accepted:
            raise EpisodeInvariantError("an accepted intent is required before an order")
        if state.order_submitted:
            raise EpisodeInvariantError("entry order was already submitted")
        _positive_int(payload, "quantity")
        _require_identity("order_id", payload.get("order_id"))
    elif command.event_type is EpisodeEventType.ENTRY_FILL_RECORDED:
        if not state.order_submitted:
            raise EpisodeInvariantError("entry fill requires a submitted order")
        _positive_int(payload, "quantity")
        _positive_decimal(payload, "price")
        fill_id = _require_identity("fill_id", payload.get("fill_id"))
        if fill_id in state.entry_fill_ids:
            raise EpisodeInvariantError("entry fill was already recorded")
    elif command.event_type is EpisodeEventType.PROTECTION_VERIFIED:
        if state.open_quantity <= 0:
            raise EpisodeInvariantError("protection requires an open position")
        protected = _positive_int(payload, "protected_quantity")
        if protected < state.open_quantity:
            raise EpisodeInvariantError("protection must cover the full open quantity")
        _positive_decimal(payload, "stop_price")
    elif command.event_type is EpisodeEventType.EXIT_FILL_RECORDED:
        quantity = _positive_int(payload, "quantity")
        if state.open_quantity <= 0:
            raise EpisodeInvariantError("exit fill requires an open position")
        if quantity > state.open_quantity:
            raise EpisodeInvariantError("exit quantity exceeds the open position")
        _positive_decimal(payload, "price")
        fill_id = _require_identity("fill_id", payload.get("fill_id"))
        if fill_id in state.exit_fill_ids:
            raise EpisodeInvariantError("exit fill was already recorded")
    elif command.event_type is EpisodeEventType.COSTS_RECONCILED:
        if episode.status is not EpisodeStatus.CLOSED:
            raise EpisodeInvariantError("costs can be reconciled only after close")
        if state.costs_reconciled:
            raise EpisodeInvariantError("costs were already reconciled")
        _require_identity("reconciliation_id", payload.get("reconciliation_id"))
        _nonnegative_decimal(payload, "fees")
        currency = payload.get("currency")
        if (
            not isinstance(currency, str)
            or len(currency) != 3
            or not currency.isalpha()
            or currency != currency.upper()
        ):
            raise EpisodeInvariantError("cost currency must be a three-letter code")
        _require_identity("source_ref", payload.get("source_ref"))
    elif command.event_type is EpisodeEventType.EPISODE_CLOSED:
        if state.open_quantity != 0 or not state.entry_fill_ids:
            raise EpisodeInvariantError("episode can close only after all exposure exits")
        _require_identity("reason", payload.get("reason"))


def _apply(state: _ProjectionState, event_type: str, payload: Mapping[str, Any]) -> None:
    if event_type == EpisodeEventType.APPROVAL_RECORDED.value:
        state.approved = bool(payload["approved"])
        state.status = EpisodeStatus.APPROVED if state.approved else EpisodeStatus.REJECTED
    elif event_type == EpisodeEventType.INTENT_ACCEPTED.value:
        state.intent_accepted = True
    elif event_type == EpisodeEventType.ORDER_SUBMITTED.value:
        state.order_submitted = True
        state.status = EpisodeStatus.WORKING
    elif event_type == EpisodeEventType.ENTRY_FILL_RECORDED.value:
        state.open_quantity += int(payload["quantity"])
        state.entry_fill_ids.add(str(payload["fill_id"]))
        state.status = EpisodeStatus.OPEN
    elif event_type == EpisodeEventType.PROTECTION_VERIFIED.value:
        state.protected_quantity = int(payload["protected_quantity"])
    elif event_type == EpisodeEventType.EXIT_FILL_RECORDED.value:
        quantity = int(payload["quantity"])
        state.open_quantity -= quantity
        state.protected_quantity = min(state.protected_quantity, state.open_quantity)
        state.exit_fill_ids.add(str(payload["fill_id"]))
    elif event_type == EpisodeEventType.COSTS_RECONCILED.value:
        state.costs_reconciled = True
    elif event_type == EpisodeEventType.EPISODE_CLOSED.value:
        state.status = EpisodeStatus.CLOSED


def _stream_id(episode_id: str) -> str:
    _require_identity("episode_id", episode_id)
    return f"episode:{episode_id}"


def _require_identity(label: str, value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 100:
        raise ValueError(f"{label} must be a non-empty identifier")
    if any(character.isspace() for character in value):
        raise ValueError(f"{label} must not contain whitespace")
    return value


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")


def _positive_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EpisodeInvariantError(f"{key} must be a positive integer")
    return value


def _positive_decimal(payload: Mapping[str, Any], key: str) -> Decimal:
    try:
        value = Decimal(str(payload.get(key)))
    except (InvalidOperation, ValueError):
        raise EpisodeInvariantError(f"{key} must be a positive finite decimal") from None
    if not value.is_finite() or value <= 0:
        raise EpisodeInvariantError(f"{key} must be a positive finite decimal")
    return value


def _nonnegative_decimal(payload: Mapping[str, Any], key: str) -> Decimal:
    try:
        value = Decimal(str(payload.get(key)))
    except (InvalidOperation, ValueError, TypeError):
        raise EpisodeInvariantError(f"{key} must be a finite decimal") from None
    if not value.is_finite() or value < 0:
        raise EpisodeInvariantError(f"{key} must be a non-negative decimal")
    return value
