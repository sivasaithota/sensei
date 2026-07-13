"""Durable, paper-only trading kernel.

Intent acceptance is append-only and side-effect free. Broker calls happen
only after a typed command is durably prepared (the outbox boundary), and a
completed command is never resent after restart.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sensei.operations.journal import EventAppend, OperationalJournal
from sensei.portfolio_risk import (
    AccountSnapshot,
    PortfolioRisk,
    SafetyAction,
    SafetyControl,
    TradeIntent,
)
from sensei.portfolio_risk.models import require_timestamp

from .commands import (
    BrokerCommand,
    CancelEntryCommand,
    CommandKind,
    EntryCommand,
    ProtectionCommand,
    command_from_payload,
)
from .gateway import GatewayReceipt, PaperGateway
from .reconciliation import BrokerSnapshot, ReconciliationReport

_STREAM = "kernel:paper"


@dataclass
class _KernelState:
    intents: dict[str, TradeIntent] = field(default_factory=dict)
    intent_order: list[str] = field(default_factory=list)
    commands: dict[str, BrokerCommand] = field(default_factory=dict)
    command_order: list[str] = field(default_factory=list)
    completed: set[str] = field(default_factory=set)
    receipts: dict[str, GatewayReceipt] = field(default_factory=dict)
    fills: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def cancelled_intents(self) -> set[str]:
        return {
            command.intent_id
            for command in self.commands.values()
            if isinstance(command, CancelEntryCommand)
        }

    def entry_for(self, intent_id: str) -> EntryCommand | None:
        for command in self.commands.values():
            if isinstance(command, EntryCommand) and command.intent_id == intent_id:
                return command
        return None

    def protected_quantity(self, intent_id: str) -> int:
        return max(
            (
                command.quantity
                for command_id, command in self.commands.items()
                if command_id in self.completed
                and isinstance(command, ProtectionCommand)
                and command.intent_id == intent_id
            ),
            default=0,
        )


class TradingKernel:
    def __init__(
        self,
        journal: OperationalJournal,
        portfolio_risk: PortfolioRisk,
        safety: SafetyControl,
        gateway: PaperGateway,
        *,
        after_command_completed: Callable[
            [BrokerCommand, GatewayReceipt], None
        ]
        | None = None,
    ) -> None:
        self._journal = journal
        self._risk = portfolio_risk
        self._safety = safety
        self._gateway = gateway
        self._after_command_completed = after_command_completed

    def accept(self, intent: TradeIntent, *, occurred_at: datetime) -> TradeIntent:
        require_timestamp(occurred_at, "occurred_at")
        state = self._state()
        existing = state.intents.get(intent.intent_id)
        if existing is not None:
            if existing != intent:
                raise ValueError("intent identity conflicts with durable content")
            return existing
        self._append(
            event_type="TradeIntentAccepted",
            payload={"intent": intent.to_payload()},
            idempotency_key=(
                f"kernel-accept:{intent.intent_id.removeprefix('intent:')}"
            ),
            occurred_at=occurred_at,
            correlation_id=intent.intent_id,
        )
        return intent

    def cancel_entry(self, intent_id: str, *, occurred_at: datetime) -> None:
        require_timestamp(occurred_at, "occurred_at")
        state = self._state()
        intent = state.intents.get(intent_id)
        if intent is None:
            raise ValueError(f"unknown intent {intent_id!r}")
        entry = state.entry_for(intent_id) or self._entry_command(intent)
        filled, _ = state.fills.get(intent_id, (0, 0))
        remaining = intent.quantity - filled
        if remaining <= 0:
            return
        command = CancelEntryCommand(
            intent_id=intent_id,
            instrument_id=intent.instrument_id,
            entry_command_id=entry.command_id,
            remaining_quantity=remaining,
        )
        self._prepare(command, occurred_at)

    def observe_fill(
        self,
        intent_id: str,
        *,
        cumulative_quantity: int,
        average_price_paise: int,
        occurred_at: datetime,
    ) -> None:
        """Record a broker fill update; protection is installed by run_once."""
        require_timestamp(occurred_at, "occurred_at")
        state = self._state()
        intent = state.intents.get(intent_id)
        if intent is None:
            raise ValueError(f"unknown intent {intent_id!r}")
        previous_quantity, previous_average = state.fills.get(intent_id, (0, 0))
        if cumulative_quantity < previous_quantity:
            raise ValueError("cumulative fill cannot move backwards")
        if cumulative_quantity > intent.quantity:
            raise ValueError("cumulative fill exceeds intent quantity")
        if cumulative_quantity == previous_quantity:
            if cumulative_quantity and average_price_paise != previous_average:
                raise ValueError("same cumulative fill conflicts with average price")
            return
        self._append(
            event_type="EntryFillObserved",
            payload={
                "intent_id": intent_id,
                "cumulative_quantity": cumulative_quantity,
                "average_price_paise": average_price_paise,
            },
            idempotency_key=(
                "kernel-fill:"
                + hashlib.sha256(
                    f"{intent_id}:{cumulative_quantity}".encode("utf-8")
                ).hexdigest()
            ),
            occurred_at=occurred_at,
            correlation_id=intent_id,
        )
        # The kernel journal is the first durable witness of a fill.  Protection
        # then outranks accounting: if the process dies after this append, the
        # next run sees the gap and retries the idempotent protection command.
        self._protect_gap(intent_id, occurred_at)
        self._apply_fill_to_risk(
            intent,
            cumulative_quantity=cumulative_quantity,
            average_price_paise=average_price_paise,
            occurred_at=occurred_at,
        )

    def run_once(self, account_snapshot: AccountSnapshot, *, now: datetime) -> None:
        require_timestamp(now, "now")

        self._recover_completed_entry_fills(now)
        # Existing exposure gaps always outrank new entries.
        self._protect_all_gaps(now)
        self._sync_risk_fills(now)
        self._dispatch_pending_non_entries(now)

        state = self._state()
        for intent_id in state.intent_order:
            state = self._state()
            if intent_id in state.cancelled_intents:
                continue
            intent = state.intents[intent_id]
            entry = state.entry_for(intent_id)
            if entry is None:
                self._safety.assert_allowed(SafetyAction.ENTRY)
                self._risk.reserve(intent, account_snapshot, now)
                entry = self._entry_command(intent)
                self._prepare(entry, now)
            state = self._state()
            if entry.command_id not in state.completed:
                receipt = self._dispatch(entry, now)
                if receipt.cumulative_fill_quantity:
                    if receipt.average_fill_price_paise is None:
                        self._latch_once(
                            reason="INVALID_BROKER_RECEIPT",
                            detail=f"{entry.command_id} reported fill without price",
                            now=now,
                            identity=entry.command_id,
                        )
                        raise RuntimeError("entry fill receipt omitted average price")
                    self.observe_fill(
                        intent_id,
                        cumulative_quantity=receipt.cumulative_fill_quantity,
                        average_price_paise=receipt.average_fill_price_paise,
                        occurred_at=now,
                    )
            # A partial fill must be protected before the loop can dispatch the
            # next accepted intent.
            self._protect_gap(intent_id, now)

    def reconcile(
        self, snapshot: BrokerSnapshot, *, now: datetime
    ) -> ReconciliationReport:
        require_timestamp(now, "now")
        state = self._state()
        known_by_instrument: dict[str, int] = {}
        for intent_id, (quantity, _) in state.fills.items():
            instrument = state.intents[intent_id].instrument_id
            known_by_instrument[instrument] = (
                known_by_instrument.get(instrument, 0) + quantity
            )
        protected = {
            item.instrument_id: item.quantity for item in snapshot.protections
        }
        issues: list[str] = []
        broker_by_instrument = {
            position.instrument_id: position.quantity
            for position in snapshot.positions
        }
        for position in snapshot.positions:
            known = known_by_instrument.get(position.instrument_id, 0)
            if position.quantity > known:
                issues.append(
                    f"unknown exposure {position.instrument_id}: broker "
                    f"{position.quantity} > kernel {known}"
                )
            protected_quantity = protected.get(position.instrument_id, 0)
            if protected_quantity < position.quantity:
                issues.append(
                    f"unprotected exposure {position.instrument_id}: protected "
                    f"{protected_quantity} < held {position.quantity}"
                )
        for instrument_id, known in known_by_instrument.items():
            broker_quantity = broker_by_instrument.get(instrument_id, 0)
            if broker_quantity < known:
                issues.append(
                    f"position mismatch {instrument_id}: broker "
                    f"{broker_quantity} < kernel {known}"
                )
        for working_order in snapshot.working_orders:
            command_id = working_order.client_command_id
            command = state.commands.get(command_id or "")
            if command is None:
                issues.append(
                    f"unknown broker order {working_order.broker_order_id} for "
                    f"{working_order.instrument_id}"
                )
                continue
            expected_quantity = (
                command.remaining_quantity
                if isinstance(command, CancelEntryCommand)
                else command.quantity
            )
            if (
                command.instrument_id != working_order.instrument_id
                or command.kind.value != working_order.kind
                or expected_quantity != working_order.quantity
            ):
                issues.append(
                    f"broker order mismatch {working_order.broker_order_id} for "
                    f"known command {command.command_id}"
                )

        identity = self._snapshot_digest(snapshot, issues)
        if issues:
            self._append(
                event_type="QuarantineRaised",
                payload={"snapshot_id": snapshot.snapshot_id, "issues": issues},
                idempotency_key=f"kernel-quarantine:{identity}",
                occurred_at=now,
            )
            self._latch_once(
                reason="RECONCILIATION_MISMATCH",
                detail="; ".join(issues),
                now=now,
                identity=identity,
            )
        else:
            self._append(
                event_type="ReconciliationClean",
                payload={"snapshot_id": snapshot.snapshot_id},
                idempotency_key=f"kernel-reconciled:{identity}",
                occurred_at=now,
            )
        return ReconciliationReport(
            snapshot_id=snapshot.snapshot_id,
            clean=not issues,
            issues=tuple(issues),
        )

    def _protect_all_gaps(self, now: datetime) -> None:
        state = self._state()
        for intent_id in state.intent_order:
            self._protect_gap(intent_id, now)

    def _protect_gap(self, intent_id: str, now: datetime) -> None:
        state = self._state()
        filled, _ = state.fills.get(intent_id, (0, 0))
        if filled <= state.protected_quantity(intent_id):
            return
        intent = state.intents[intent_id]
        command = ProtectionCommand(
            intent_id=intent_id,
            instrument_id=intent.instrument_id,
            quantity=filled,
            stop_price_paise=intent.stop_price_paise,
            target_price_paise=intent.target_price_paise,
        )
        self._prepare(command, now)
        state = self._state()
        if command.command_id not in state.completed:
            try:
                self._dispatch(command, now)
            except Exception:
                if command.command_id in self._state().completed:
                    # A fault-injection hook can model death immediately after
                    # the completion append. The durable protection receipt is
                    # authoritative; do not cancel a safely protected remainder.
                    raise
                # The already-filled quantity still needs protection, but the
                # unfilled entry remainder must not be allowed to increase the
                # exposure while protection is unavailable.
                _, average_price = state.fills[intent_id]
                self._apply_fill_to_risk(
                    intent,
                    cumulative_quantity=filled,
                    average_price_paise=average_price,
                    occurred_at=now,
                )
                self._cancel_unfilled_remainder(intent, filled, now)
                raise

    def _dispatch_pending_non_entries(self, now: datetime) -> None:
        state = self._state()
        for command_id in state.command_order:
            command = state.commands[command_id]
            if command_id in state.completed or isinstance(command, EntryCommand):
                continue
            self._dispatch(command, now)
            if isinstance(command, CancelEntryCommand):
                reservation_id = (
                    f"reservation:{command.intent_id.removeprefix('intent:')}"
                )
                if any(
                    item.reservation_id == reservation_id
                    for item in self._risk.reservations()
                ):
                    self._risk.release(reservation_id, occurred_at=now)

    def _cancel_unfilled_remainder(
        self, intent: TradeIntent, filled_quantity: int, now: datetime
    ) -> None:
        remaining = intent.quantity - filled_quantity
        if remaining <= 0:
            return
        state = self._state()
        entry = state.entry_for(intent.intent_id) or self._entry_command(intent)
        command = CancelEntryCommand(
            intent_id=intent.intent_id,
            instrument_id=intent.instrument_id,
            entry_command_id=entry.command_id,
            remaining_quantity=remaining,
        )
        self._prepare(command, now)
        if command.command_id not in self._state().completed:
            self._dispatch(command, now)
        reservation_id = (
            f"reservation:{intent.intent_id.removeprefix('intent:')}"
        )
        if any(
            item.reservation_id == reservation_id
            for item in self._risk.reservations()
        ):
            self._risk.release(reservation_id, occurred_at=now)

    def _recover_completed_entry_fills(self, now: datetime) -> None:
        state = self._state()
        for command_id in state.command_order:
            command = state.commands[command_id]
            receipt = state.receipts.get(command_id)
            if not isinstance(command, EntryCommand) or receipt is None:
                continue
            durable_quantity = receipt.cumulative_fill_quantity
            observed_quantity, _ = state.fills.get(command.intent_id, (0, 0))
            if durable_quantity <= observed_quantity:
                continue
            if receipt.average_fill_price_paise is None:
                self._latch_once(
                    reason="INVALID_BROKER_RECEIPT",
                    detail=f"{command_id} reported fill without price",
                    now=now,
                    identity=command_id,
                )
                raise RuntimeError("durable entry fill receipt omitted average price")
            self.observe_fill(
                command.intent_id,
                cumulative_quantity=durable_quantity,
                average_price_paise=receipt.average_fill_price_paise,
                occurred_at=now,
            )

    def _sync_risk_fills(self, now: datetime) -> None:
        """Bring conservative reservation accounting up to kernel fill truth."""
        state = self._state()
        for intent_id, (quantity, average_price) in state.fills.items():
            self._apply_fill_to_risk(
                state.intents[intent_id],
                cumulative_quantity=quantity,
                average_price_paise=average_price,
                occurred_at=now,
            )

    def _apply_fill_to_risk(
        self,
        intent: TradeIntent,
        *,
        cumulative_quantity: int,
        average_price_paise: int,
        occurred_at: datetime,
    ) -> None:
        reservation_id = (
            f"reservation:{intent.intent_id.removeprefix('intent:')}"
        )
        self._risk.apply_fill(
            reservation_id,
            cumulative_quantity=cumulative_quantity,
            average_price_paise=average_price_paise,
            occurred_at=occurred_at,
        )

    def _dispatch(self, command: BrokerCommand, now: datetime) -> GatewayReceipt:
        action = {
            CommandKind.ENTRY: SafetyAction.ENTRY,
            CommandKind.PROTECTION: SafetyAction.PROTECTION,
            CommandKind.CANCEL_ENTRY: SafetyAction.CANCEL_ENTRY,
        }[command.kind]
        self._safety.assert_allowed(action)
        try:
            receipt = self._gateway.execute(command)
        except Exception as exc:
            self._latch_once(
                reason="BROKER_COMMAND_FAILED",
                detail=f"{command.command_id}: {type(exc).__name__}: {exc}",
                now=now,
                identity=command.command_id,
            )
            raise
        if receipt.command_id != command.command_id or not receipt.accepted:
            self._latch_once(
                reason="BROKER_COMMAND_REJECTED",
                detail=f"invalid or rejected receipt for {command.command_id}",
                now=now,
                identity=command.command_id,
            )
            raise RuntimeError("paper gateway did not accept broker command")
        self._append(
            event_type="BrokerCommandCompleted",
            payload={"receipt": receipt.to_payload()},
            idempotency_key=(
                f"kernel-complete:{command.command_id.removeprefix('command:')}"
            ),
            occurred_at=now,
            correlation_id=command.intent_id,
            causation_id=command.command_id,
        )
        if self._after_command_completed is not None:
            self._after_command_completed(command, receipt)
        return receipt

    def _prepare(self, command: BrokerCommand, occurred_at: datetime) -> None:
        state = self._state()
        existing = state.commands.get(command.command_id)
        if existing is not None:
            if existing != command:
                raise ValueError("command identity conflicts with durable content")
            return
        self._append(
            event_type="BrokerCommandPrepared",
            payload={"command": command.to_payload()},
            idempotency_key=(
                f"kernel-command:{command.command_id.removeprefix('command:')}"
            ),
            occurred_at=occurred_at,
            correlation_id=command.intent_id,
        )

    @staticmethod
    def _entry_command(intent: TradeIntent) -> EntryCommand:
        return EntryCommand(
            intent_id=intent.intent_id,
            instrument_id=intent.instrument_id,
            quantity=intent.quantity,
            limit_price_paise=intent.limit_price_paise,
        )

    def _append(
        self,
        *,
        event_type: str,
        payload: dict[str, object],
        idempotency_key: str,
        occurred_at: datetime,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> None:
        events = self._journal.read_stream(_STREAM)
        self._journal.append(
            EventAppend(
                stream_id=_STREAM,
                event_type=event_type,
                payload=payload,
                idempotency_key=idempotency_key,
                expected_version=len(events),
                occurred_at=occurred_at,
                correlation_id=correlation_id,
                causation_id=causation_id,
            )
        )

    def _state(self) -> _KernelState:
        state = _KernelState()
        for event in self._journal.read_stream(_STREAM):
            if event.event_type == "TradeIntentAccepted":
                intent = TradeIntent.from_payload(event.payload["intent"])
                state.intents[intent.intent_id] = intent
                state.intent_order.append(intent.intent_id)
            elif event.event_type == "BrokerCommandPrepared":
                command = command_from_payload(event.payload["command"])
                state.commands[command.command_id] = command
                state.command_order.append(command.command_id)
            elif event.event_type == "BrokerCommandCompleted":
                payload = event.payload["receipt"]
                average = payload["average_fill_price_paise"]
                receipt = GatewayReceipt(
                    command_id=str(payload["command_id"]),
                    accepted=bool(payload["accepted"]),
                    broker_reference=str(payload["broker_reference"]),
                    cumulative_fill_quantity=int(
                        payload["cumulative_fill_quantity"]
                    ),
                    average_fill_price_paise=(
                        int(average) if average is not None else None
                    ),
                )
                state.completed.add(receipt.command_id)
                state.receipts[receipt.command_id] = receipt
            elif event.event_type == "EntryFillObserved":
                state.fills[str(event.payload["intent_id"])] = (
                    int(event.payload["cumulative_quantity"]),
                    int(event.payload["average_price_paise"]),
                )
        return state

    def _latch_once(
        self, *, reason: str, detail: str, now: datetime, identity: str
    ) -> None:
        if self._safety.state().latched:
            return
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        self._safety.latch(
            reason_code=reason,
            detail=detail,
            occurred_at=now,
            idempotency_key=f"kernel-latch:{digest}",
        )

    @staticmethod
    def _snapshot_digest(snapshot: BrokerSnapshot, issues: list[str]) -> str:
        material = json.dumps(
            {
                "snapshot_id": snapshot.snapshot_id,
                "captured_at": snapshot.captured_at.isoformat(),
                "positions": [
                    [item.instrument_id, item.quantity] for item in snapshot.positions
                ],
                "protections": [
                    [item.instrument_id, item.quantity]
                    for item in snapshot.protections
                ],
                "working_orders": [
                    [
                        item.broker_order_id,
                        item.client_command_id,
                        item.instrument_id,
                        item.kind,
                        item.quantity,
                    ]
                    for item in snapshot.working_orders
                ],
                "issues": issues,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()
