"""Durable, paper-only trading kernel.

Intent acceptance is append-only and side-effect free. Broker calls happen
only after a typed command is durably prepared (the outbox boundary), and a
completed command is never resent after restart.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Lock

from sensei.operations.authority import HmacFactSigner, HmacFactVerifier
from sensei.operations.journal import EventAppend, JournalEvent, OperationalJournal
from sensei.portfolio_risk import (
    AccountSnapshot,
    PortfolioRisk,
    SafetyAction,
    SafetyControl,
    SafetyResetAuthority,
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
from .admission import KernelAdmissionAuthority
from .broker_authority import BrokerSnapshotAuthority
from .gateway import GatewayReceipt, PaperGateway
from .reconciliation import BrokerSnapshot, ReconciliationReport

_STREAM = "kernel:paper"
ENTRY_DISPATCH_AUTHORIZATION_FACT_TYPE = "SupervisorEntryDispatchAuthorized"
_ENTRY_AUTHORIZATION_BINDING_FACT_TYPE = "SupervisorEntryDispatchRuntimeBinding"
_INTENT_ID = re.compile(r"intent:[0-9a-f]{64}\Z")
_DESK_REQUEST_ID = re.compile(r"desk-request:[0-9a-f]{64}\Z")


class EntryAuthorizationInvalid(RuntimeError):
    """The final entry capability failed Kernel validation."""

    reason_code = "ENTRY_AUTHORIZATION_INVALID"


@dataclass
class _KernelState:
    intents: dict[str, TradeIntent] = field(default_factory=dict)
    intent_order: list[str] = field(default_factory=list)
    commands: dict[str, BrokerCommand] = field(default_factory=dict)
    command_order: list[str] = field(default_factory=list)
    completed: set[str] = field(default_factory=set)
    receipts: dict[str, GatewayReceipt] = field(default_factory=dict)
    completion_event_ids: dict[str, str] = field(default_factory=dict)
    fills: dict[str, tuple[int, int]] = field(default_factory=dict)
    quarantined_intents: set[str] = field(default_factory=set)
    consumed_entry_authorizations: dict[str, str] = field(default_factory=dict)

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


@dataclass(frozen=True)
class EntryDispatchAuthorization:
    """Fresh, authenticated facts authorizing one exact entry dispatch."""

    account_snapshot: AccountSnapshot
    authorized_at: datetime
    evidence_event_id: str
    intent_id: str
    cycle_request_id: str
    issuer_id: str
    signature: str

    def __post_init__(self) -> None:
        if not isinstance(self.account_snapshot, AccountSnapshot):
            raise TypeError("entry authorization requires an AccountSnapshot")
        require_timestamp(self.authorized_at, "authorized_at")
        if (
            not isinstance(self.evidence_event_id, str)
            or not self.evidence_event_id.startswith("event:")
        ):
            raise ValueError("entry authorization evidence_event_id is required")
        if not isinstance(self.intent_id, str) or _INTENT_ID.fullmatch(
            self.intent_id
        ) is None:
            raise ValueError("entry authorization intent_id is invalid")
        if not isinstance(
            self.cycle_request_id, str
        ) or _DESK_REQUEST_ID.fullmatch(self.cycle_request_id) is None:
            raise ValueError("entry authorization cycle_request_id is invalid")
        if not isinstance(self.issuer_id, str) or not self.issuer_id.strip():
            raise ValueError("entry authorization issuer_id is required")
        if not isinstance(self.signature, str) or not self.signature.strip():
            raise ValueError("entry authorization signature is required")

    def signed_fact(self) -> dict[str, object]:
        """Return the canonical fact authenticated by the Supervisor."""

        return entry_dispatch_authorization_fact(
            intent_id=self.intent_id,
            cycle_request_id=self.cycle_request_id,
            account_snapshot_id=self.account_snapshot.snapshot_id,
            authorized_at=self.authorized_at,
            evidence_event_id=self.evidence_event_id,
        )


def entry_dispatch_authorization_fact(
    *,
    intent_id: str,
    cycle_request_id: str,
    account_snapshot_id: str,
    authorized_at: datetime,
    evidence_event_id: str,
) -> dict[str, object]:
    """Build the stable fact used for the one-shot entry capability."""

    require_timestamp(authorized_at, "authorized_at")
    return {
        "intent_id": intent_id,
        "cycle_request_id": cycle_request_id,
        "account_snapshot_id": account_snapshot_id,
        "authorized_at": authorized_at.isoformat(),
        "evidence_event_id": evidence_event_id,
    }


class TradingKernel:
    def __init__(
        self,
        journal: OperationalJournal,
        portfolio_risk: PortfolioRisk,
        safety: SafetyControl,
        gateway: PaperGateway,
        *,
        admission_authority: KernelAdmissionAuthority,
        broker_snapshot_authority: BrokerSnapshotAuthority | None = None,
        safety_reset_authority: SafetyResetAuthority | None = None,
        reconciliation_signer: HmacFactSigner | None = None,
        entry_authorization_verifier: HmacFactVerifier | None = None,
        expected_supervisor_issuer_id: str | None = None,
        maximum_broker_snapshot_age: timedelta = timedelta(minutes=2),
        after_command_completed: Callable[
            [BrokerCommand, GatewayReceipt], None
        ]
        | None = None,
    ) -> None:
        if maximum_broker_snapshot_age <= timedelta(0):
            raise ValueError("maximum_broker_snapshot_age must be positive")
        self._journal = journal
        self._risk = portfolio_risk
        self._safety = safety
        self._gateway = gateway
        self._admission_authority = admission_authority
        self._broker_snapshot_authority = broker_snapshot_authority
        self._safety_reset_authority = safety_reset_authority
        self._reconciliation_signer = reconciliation_signer
        if (entry_authorization_verifier is None) != (
            expected_supervisor_issuer_id is None
        ):
            raise ValueError(
                "entry authorization verifier and issuer must be configured together"
            )
        self._entry_authorization_verifier = entry_authorization_verifier
        self._expected_supervisor_issuer_id = expected_supervisor_issuer_id
        self._maximum_broker_snapshot_age = maximum_broker_snapshot_age
        self._after_command_completed = after_command_completed
        self._entry_authorization_lock = Lock()

    def accepts_entry_authorization_signer(
        self, signer: HmacFactSigner
    ) -> bool:
        """Prove that this kernel trusts the exact Supervisor signer."""

        verifier = getattr(self, "_entry_authorization_verifier", None)
        issuer_id = getattr(self, "_expected_supervisor_issuer_id", None)
        if (
            type(signer) is not HmacFactSigner
            or type(verifier) is not HmacFactVerifier
            or issuer_id != signer.issuer_id
        ):
            return False
        fact = {"purpose": "paper-runtime-binding", "schema_version": 1}
        return verifier.verify(
            issuer_id=issuer_id,
            fact_type=_ENTRY_AUTHORIZATION_BINDING_FACT_TYPE,
            fact=fact,
            signature=signer.sign(
                _ENTRY_AUTHORIZATION_BINDING_FACT_TYPE,
                fact,
            ),
        )

    def is_bound_to_paper_runtime(
        self,
        *,
        journal: OperationalJournal,
        gateway: PaperGateway,
        safety: SafetyControl,
    ) -> bool:
        """Return whether this kernel owns the exact paper runtime objects."""

        return (
            self._gateway is gateway
            and self.is_bound_to_runtime(journal=journal, safety=safety)
        )

    def is_bound_to_runtime(
        self,
        *,
        journal: OperationalJournal,
        safety: SafetyControl,
    ) -> bool:
        """Check the kernel's durable dependencies and exact safety latch."""

        return self._safety is safety and self.is_bound_to_journal(journal)

    def is_bound_to_journal(self, journal: OperationalJournal) -> bool:
        """Check that every journal-backed kernel dependency is co-located."""

        risk = getattr(self, "_risk", None)
        admission = getattr(self, "_admission_authority", None)
        safety = getattr(self, "_safety", None)
        return (
            self._journal is journal
            and type(risk) is PortfolioRisk
            and PortfolioRisk.is_bound_to_journal(risk, journal)
            and type(admission) is KernelAdmissionAuthority
            and KernelAdmissionAuthority.is_bound_to_journal(admission, journal)
            and type(safety) is SafetyControl
            and self._reconciliation_runtime_is_bound(journal, safety)
        )

    def _reconciliation_runtime_is_bound(
        self,
        journal: OperationalJournal,
        safety: SafetyControl,
    ) -> bool:
        broker_authority = getattr(self, "_broker_snapshot_authority", None)
        reset_authority = getattr(self, "_safety_reset_authority", None)
        signer = getattr(self, "_reconciliation_signer", None)
        components = (broker_authority, reset_authority, signer)
        if all(component is None for component in components):
            return SafetyControl.is_bound_to_runtime(
                safety,
                journal=journal,
                reset_authority=None,
            )
        if any(component is None for component in components):
            return False
        return (
            type(broker_authority) is BrokerSnapshotAuthority
            and BrokerSnapshotAuthority.is_bound_to_journal(
                broker_authority,
                journal,
            )
            and type(reset_authority) is SafetyResetAuthority
            and type(signer) is HmacFactSigner
            and SafetyResetAuthority.is_bound_to_reconciliation_runtime(
                reset_authority,
                journal=journal,
                signer=signer,
            )
            and SafetyControl.is_bound_to_runtime(
                safety,
                journal=journal,
                reset_authority=reset_authority,
            )
        )

    def accept(
        self,
        intent: TradeIntent,
        *,
        admission_event_id: str,
        occurred_at: datetime,
    ) -> TradeIntent:
        require_timestamp(occurred_at, "occurred_at")
        if not self._admission_authority.verify(
            admission_event_id,
            intent=intent,
            no_later_than=occurred_at,
        ):
            raise ValueError("intent requires authenticated paper admission")
        state = self._state()
        existing = state.intents.get(intent.intent_id)
        if existing is not None:
            if existing != intent:
                raise ValueError("intent identity conflicts with durable content")
            return existing
        self._append(
            event_type="TradeIntentAccepted",
            payload={
                "intent": intent.to_payload(),
                "admission_event_id": admission_event_id,
            },
            idempotency_key=(
                f"kernel-accept:{intent.intent_id.removeprefix('intent:')}"
            ),
            occurred_at=occurred_at,
            correlation_id=intent.intent_id,
        )
        return intent

    def quarantine_intent(
        self,
        intent_id: str,
        *,
        reason_codes: tuple[str, ...],
        evidence_event_id: str,
        occurred_at: datetime,
    ) -> JournalEvent:
        """Make an accepted, unprepared intent permanently ineligible."""

        require_timestamp(occurred_at, "occurred_at")
        if not isinstance(intent_id, str) or not intent_id.strip():
            raise ValueError("intent_id is required")
        reasons = tuple(reason_codes)
        if (
            not reasons
            or any(
                not isinstance(reason, str) or not reason.strip()
                for reason in reasons
            )
            or len(reasons) != len(set(reasons))
        ):
            raise ValueError("quarantine requires unique reason codes")
        if not isinstance(evidence_event_id, str) or not evidence_event_id.strip():
            raise ValueError("quarantine evidence_event_id is required")
        state = self._state()
        if intent_id not in state.intents:
            raise ValueError(f"unknown intent {intent_id!r}")
        if state.entry_for(intent_id) is not None:
            raise RuntimeError("an intent with an entry command cannot be quarantined")
        suffix = intent_id.removeprefix("intent:")
        try:
            return self._append(
                event_type="TradeIntentQuarantined",
                payload={
                    "intent_id": intent_id,
                    "reason_codes": reasons,
                    "evidence_event_id": evidence_event_id,
                },
                idempotency_key=f"kernel-quarantine-intent:{suffix}",
                occurred_at=occurred_at,
                correlation_id=intent_id,
                causation_id=evidence_event_id,
            )
        except Exception:
            self._latch_once(
                reason="DISPATCH_QUARANTINE_FAILED",
                detail=f"failed to quarantine {intent_id}",
                now=occurred_at,
                identity=intent_id,
            )
            raise

    def has_prepared_entry(self, intent_id: str) -> bool:
        """Return whether an entry command is already a durable commitment."""

        if not isinstance(intent_id, str) or not intent_id.strip():
            raise ValueError("intent_id is required")
        state = self._state()
        if intent_id not in state.intents:
            raise ValueError(f"unknown intent {intent_id!r}")
        return state.entry_for(intent_id) is not None

    def cancel_entry(self, intent_id: str, *, occurred_at: datetime) -> None:
        require_timestamp(occurred_at, "occurred_at")
        state = self._state()
        intent = state.intents.get(intent_id)
        if intent is None:
            raise ValueError(f"unknown intent {intent_id!r}")
        entry = state.entry_for(intent_id)
        if entry is None or entry.command_id not in state.completed:
            return
        durable_fill = state.receipts[entry.command_id].cumulative_fill_quantity
        filled, _ = state.fills.get(intent_id, (durable_fill, 0))
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
        """Record a broker fill update and install protection before returning."""
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

    def run_once(
        self,
        account_snapshot: AccountSnapshot,
        *,
        now: datetime,
        intent_id: str | None = None,
        authorize_entry: (
            Callable[[TradeIntent], EntryDispatchAuthorization] | None
        ) = None,
    ) -> None:
        require_timestamp(now, "now")
        if intent_id is not None and (
            not isinstance(intent_id, str) or not intent_id.strip()
        ):
            raise ValueError("intent_id must be nonblank text")
        self.enforce(now=now)

        state = self._state()
        if intent_id is not None:
            if intent_id not in state.intents:
                raise ValueError(f"unknown intent {intent_id!r}")
            if intent_id in state.quarantined_intents:
                raise RuntimeError("quarantined intent cannot be dispatched")
            selected_intents = (intent_id,)
        else:
            # Recovery is deliberately protective-only. An accepted intent may
            # have been left behind by a crash before the Supervisor callback;
            # only an explicitly scoped request may ever advance it to entry.
            return
        for selected_intent_id in selected_intents:
            state = self._state()
            if (
                selected_intent_id in state.cancelled_intents
                or selected_intent_id in state.quarantined_intents
            ):
                continue
            intent = state.intents[selected_intent_id]
            entry = state.entry_for(selected_intent_id)
            dispatch_snapshot = account_snapshot
            dispatch_time = now
            if entry is None or entry.command_id not in state.completed:
                if authorize_entry is None:
                    raise EntryAuthorizationInvalid(
                        "pending entry dispatch requires fresh authorization"
                    )
                authorization = authorize_entry(intent)
                if type(authorization) is not EntryDispatchAuthorization:
                    raise EntryAuthorizationInvalid(
                        "entry authorizer must return an exact "
                        "EntryDispatchAuthorization"
                    )
                if (
                    authorization.account_snapshot.snapshot_id
                    != intent.account_snapshot_id
                ):
                    raise EntryAuthorizationInvalid(
                        "entry authorization account does not match intent"
                    )
                if authorization.authorized_at < now:
                    raise EntryAuthorizationInvalid(
                        "entry authorization cannot predate kernel recovery"
                    )
                with self._entry_authorization_lock:
                    self._verify_entry_authorization(
                        intent,
                        authorization,
                    )
                    self._consume_entry_authorization(
                        intent,
                        authorization,
                    )
                dispatch_snapshot = authorization.account_snapshot
                dispatch_time = authorization.authorized_at
            if entry is None:
                self._safety.assert_allowed(SafetyAction.ENTRY)
                self._risk.reserve(intent, dispatch_snapshot, dispatch_time)
                entry = self._entry_command(intent)
                self._prepare(entry, dispatch_time)
            state = self._state()
            if entry.command_id not in state.completed:
                receipt = self._dispatch(entry, dispatch_time)
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
                        selected_intent_id,
                        cumulative_quantity=receipt.cumulative_fill_quantity,
                        average_price_paise=receipt.average_fill_price_paise,
                        occurred_at=dispatch_time,
                    )
            # A partial fill must be protected before the loop can dispatch the
            # next accepted intent.
            self._protect_gap(selected_intent_id, dispatch_time)

    def _verify_entry_authorization(
        self,
        intent: TradeIntent,
        authorization: EntryDispatchAuthorization,
    ) -> None:
        verifier = getattr(self, "_entry_authorization_verifier", None)
        expected_issuer = getattr(
            self, "_expected_supervisor_issuer_id", None
        )
        if (
            type(verifier) is not HmacFactVerifier
            or authorization.issuer_id != expected_issuer
            or authorization.intent_id != intent.intent_id
            or not verifier.verify(
                issuer_id=authorization.issuer_id,
                fact_type=ENTRY_DISPATCH_AUTHORIZATION_FACT_TYPE,
                fact=authorization.signed_fact(),
                signature=authorization.signature,
            )
        ):
            raise EntryAuthorizationInvalid(
                "Supervisor entry capability is not authentic"
            )
        if not self._journal.verify().ok:
            raise EntryAuthorizationInvalid(
                "Supervisor truth evidence journal is invalid"
            )
        event = next(
            (
                candidate
                for candidate in self._journal.read_all()
                if candidate.event_id == authorization.evidence_event_id
            ),
            None,
        )
        if event is None:
            raise EntryAuthorizationInvalid(
                "Supervisor truth evidence is not in this journal"
            )
        payload = event.payload
        authorized_request_ids = payload.get("authorized_cycle_request_ids")
        cycle_request_id = payload.get("cycle_request_id")
        if (
            event.event_type != "DeskSupervisorTruthCaptured"
            or not event.stream_id.startswith("desk-supervisor:")
            or event.correlation_id != payload.get("session_id")
            or not str(payload.get("phase", "")).startswith("PRE_DISPATCH:")
            or payload.get("checked_at")
            != authorization.authorized_at.isoformat()
            or event.occurred_at != authorization.authorized_at
            or payload.get("account_snapshot_id")
            != authorization.account_snapshot.snapshot_id
            or payload.get("authorized_intent_id") != intent.intent_id
            or payload.get("reason_codes") != ()
            or not isinstance(cycle_request_id, str)
            or not cycle_request_id.startswith("desk-request:")
            or not isinstance(authorized_request_ids, tuple)
            or cycle_request_id not in authorized_request_ids
            or cycle_request_id != authorization.cycle_request_id
            or authorization.account_snapshot.snapshot_id
            != intent.account_snapshot_id
            or authorization.evidence_event_id
            in self._state().consumed_entry_authorizations
        ):
            raise EntryAuthorizationInvalid(
                "Supervisor truth evidence does not authorize entry"
            )

    def _consume_entry_authorization(
        self,
        intent: TradeIntent,
        authorization: EntryDispatchAuthorization,
    ) -> None:
        """Durably consume a capability before reserving or preparing entry."""

        suffix = authorization.evidence_event_id.removeprefix("event:")
        self._append(
            event_type="SupervisorEntryAuthorizationConsumed",
            payload={
                "evidence_event_id": authorization.evidence_event_id,
                "intent_id": intent.intent_id,
                "cycle_request_id": authorization.cycle_request_id,
                "issuer_id": authorization.issuer_id,
                "signature": authorization.signature,
            },
            idempotency_key=f"kernel-entry-authorization:{suffix}",
            occurred_at=authorization.authorized_at,
            correlation_id=intent.intent_id,
            causation_id=authorization.evidence_event_id,
        )

    def enforce(self, *, now: datetime) -> None:
        """Enforce protection and cancellation without admitting a new entry."""
        require_timestamp(now, "now")
        protection_errors: list[Exception] = []
        protection_errors.extend(self._recover_gateway_receipts(now))
        protection_errors.extend(self._recover_completed_entry_fills(now))
        # Existing exposure gaps always outrank cancellation. Each gap is
        # attempted independently so one failed protection cannot hide another.
        protection_errors.extend(self._protect_all_gaps(now))
        try:
            self._sync_risk_fills(now)
        except Exception as exc:
            protection_errors.append(exc)

        cancellation_errors = self._recover_completed_cancellations(now)
        cancellation_errors.extend(self._dispatch_pending_cancels(now))
        if self._safety.state().latched:
            cancellation_errors.extend(
                self._cancel_all_working_remainders(now)
            )
        if protection_errors:
            raise protection_errors[0]
        if cancellation_errors:
            raise cancellation_errors[0]

    def reconcile(
        self,
        snapshot: BrokerSnapshot,
        *,
        snapshot_event_id: str,
        now: datetime,
    ) -> ReconciliationReport:
        require_timestamp(now, "now")
        if (
            self._broker_snapshot_authority is None
            or self._safety_reset_authority is None
            or self._reconciliation_signer is None
            or not self._broker_snapshot_authority.verify(
                snapshot_event_id,
                snapshot=snapshot,
                no_later_than=now,
            )
        ):
            raise ValueError("reconciliation requires an authenticated broker snapshot")
        snapshot_age = now - snapshot.captured_at
        if (
            snapshot_age < timedelta(0)
            or snapshot_age > self._maximum_broker_snapshot_age
        ):
            raise ValueError("broker snapshot is stale or future-dated")
        state = self._state()
        known_by_instrument: dict[str, int] = {}
        for intent_id, (quantity, _) in state.fills.items():
            instrument = state.intents[intent_id].instrument_id
            known_by_instrument[instrument] = (
                known_by_instrument.get(instrument, 0) + quantity
            )
        issues: list[str] = []
        protected: dict[str, int] = {}
        for broker_protection in snapshot.protections:
            command = state.commands.get(
                broker_protection.client_command_id or ""
            )
            if not isinstance(command, ProtectionCommand):
                issues.append(
                    f"unknown broker protection for "
                    f"{broker_protection.instrument_id}"
                )
                continue
            if (
                command.instrument_id != broker_protection.instrument_id
                or command.quantity != broker_protection.quantity
            ):
                issues.append(
                    f"broker protection mismatch for "
                    f"{broker_protection.instrument_id}"
                )
                continue
            if (
                command.stop_price_paise != broker_protection.stop_price_paise
                or command.target_price_paise
                != broker_protection.target_price_paise
            ):
                issues.append(
                    f"protective level mismatch for "
                    f"{broker_protection.instrument_id}"
                )
                continue
            protected[broker_protection.instrument_id] = (
                broker_protection.quantity
            )
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
                continue
            if isinstance(command, ProtectionCommand) and (
                command.stop_price_paise != working_order.stop_price_paise
                or command.target_price_paise != working_order.target_price_paise
            ):
                issues.append(
                    f"working protective level mismatch "
                    f"{working_order.broker_order_id}"
                )

        identity = self._snapshot_digest(snapshot, issues)
        if issues:
            kernel_event = self._append(
                event_type="QuarantineRaised",
                payload={
                    "snapshot_id": snapshot.snapshot_id,
                    "broker_snapshot_event_id": snapshot_event_id,
                    "issues": issues,
                },
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
            kernel_event = self._append(
                event_type="ReconciliationClean",
                payload={
                    "snapshot_id": snapshot.snapshot_id,
                    "broker_snapshot_event_id": snapshot_event_id,
                    "issues": (),
                },
                idempotency_key=f"kernel-reconciled:{identity}",
                occurred_at=now,
            )
        evidence = self._safety_reset_authority.attest_reconciliation(
            kernel_event_id=kernel_event.event_id,
            broker_snapshot_event_id=snapshot_event_id,
            snapshot_id=snapshot.snapshot_id,
            clean=not issues,
            issues=tuple(issues),
            signer=self._reconciliation_signer,
            occurred_at=now,
            command_id=f"kernel-reconciliation:{identity}",
        )
        return ReconciliationReport(
            snapshot_id=snapshot.snapshot_id,
            clean=not issues,
            issues=tuple(issues),
            observed_at=now,
            broker_snapshot_event_id=snapshot_event_id,
            kernel_event_id=kernel_event.event_id,
            evidence_event_id=evidence.event_id,
        )

    def _protect_all_gaps(self, now: datetime) -> list[Exception]:
        state = self._state()
        errors: list[Exception] = []
        for intent_id in state.intent_order:
            try:
                self._protect_gap(intent_id, now)
            except Exception as exc:
                errors.append(exc)
        return errors

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

    def _dispatch_pending_cancels(self, now: datetime) -> list[Exception]:
        state = self._state()
        errors: list[Exception] = []
        for command_id in state.command_order:
            command = state.commands[command_id]
            if command_id in state.completed or not isinstance(
                command, CancelEntryCommand
            ):
                continue
            try:
                self._dispatch(command, now)
                self._release_after_cancel(command, now)
            except Exception as exc:
                errors.append(exc)
        return errors

    def _recover_completed_cancellations(
        self, now: datetime
    ) -> list[Exception]:
        state = self._state()
        errors: list[Exception] = []
        for command_id in state.command_order:
            command = state.commands[command_id]
            if command_id not in state.completed or not isinstance(
                command, CancelEntryCommand
            ):
                continue
            try:
                self._release_after_cancel(command, now)
            except Exception as exc:
                errors.append(exc)
        return errors

    def _cancel_all_working_remainders(self, now: datetime) -> list[Exception]:
        state = self._state()
        errors: list[Exception] = []
        for command_id in state.command_order:
            command = state.commands[command_id]
            if not isinstance(command, EntryCommand):
                continue
            if command_id not in state.completed:
                continue
            filled, _ = state.fills.get(command.intent_id, (0, 0))
            try:
                self._cancel_unfilled_remainder(
                    state.intents[command.intent_id], filled, now
                )
            except Exception as exc:
                errors.append(exc)
        return errors

    def _cancel_unfilled_remainder(
        self, intent: TradeIntent, filled_quantity: int, now: datetime
    ) -> JournalEvent:
        remaining = intent.quantity - filled_quantity
        if remaining <= 0:
            return
        state = self._state()
        entry = state.entry_for(intent.intent_id)
        if entry is None or entry.command_id not in state.completed:
            return
        existing = [
            command
            for command in state.commands.values()
            if isinstance(command, CancelEntryCommand)
            and command.intent_id == intent.intent_id
        ]
        command = (
            existing[-1]
            if existing
            else CancelEntryCommand(
                intent_id=intent.intent_id,
                instrument_id=intent.instrument_id,
                entry_command_id=entry.command_id,
                remaining_quantity=remaining,
            )
        )
        if not existing:
            self._prepare(command, now)
        if command.command_id not in self._state().completed:
            self._dispatch(command, now)
        self._release_after_cancel(command, now)

    def _release_after_cancel(
        self, command: CancelEntryCommand, now: datetime
    ) -> JournalEvent:
        reservation_id = (
            f"reservation:{command.intent_id.removeprefix('intent:')}"
        )
        if any(
            item.reservation_id == reservation_id
            for item in self._risk.reservations()
        ):
            state = self._state()
            terminal_event_id = state.completion_event_ids.get(command.command_id)
            if terminal_event_id is None:
                raise RuntimeError(
                    "completed cancellation lacks durable event identity"
                )
            self._risk.release(
                reservation_id,
                terminal_evidence_event_id=terminal_event_id,
                occurred_at=now,
            )

    def _recover_completed_entry_fills(self, now: datetime) -> list[Exception]:
        state = self._state()
        errors: list[Exception] = []
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
                errors.append(
                    RuntimeError("durable entry fill receipt omitted average price")
                )
                continue
            try:
                self.observe_fill(
                    command.intent_id,
                    cumulative_quantity=durable_quantity,
                    average_price_paise=receipt.average_fill_price_paise,
                    occurred_at=now,
                )
            except Exception as exc:
                errors.append(exc)
        return errors

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
        self._record_completion(command, receipt, now)
        if self._after_command_completed is not None:
            self._after_command_completed(command, receipt)
        return receipt

    def _record_completion(
        self,
        command: BrokerCommand,
        receipt: GatewayReceipt,
        now: datetime,
    ) -> None:
        if (
            type(receipt) is not GatewayReceipt
            or receipt.command_id != command.command_id
            or not receipt.accepted
        ):
            self._latch_once(
                reason="BROKER_COMMAND_REJECTED",
                detail=f"invalid or rejected receipt for {command.command_id}",
                now=now,
                identity=command.command_id,
            )
            raise RuntimeError("paper gateway did not accept broker command")
        try:
            self._append(
                event_type="BrokerCommandCompleted",
                payload={"receipt": receipt.to_payload()},
                idempotency_key=(
                    "kernel-complete:"
                    + command.command_id.removeprefix("command:")
                ),
                occurred_at=now,
                correlation_id=command.intent_id,
                causation_id=command.command_id,
            )
        except Exception as exc:
            try:
                self._latch_once(
                    reason="BROKER_RECEIPT_PERSISTENCE_FAILED",
                    detail=(
                        f"{command.command_id}: {type(exc).__name__}: {exc}"
                    ),
                    now=now,
                    identity=f"receipt-persistence:{command.command_id}",
                )
            except Exception:
                pass
            raise

    def _recover_gateway_receipts(self, now: datetime) -> list[Exception]:
        """Resolve prepared commands via lookup; recovery never resends them."""

        state = self._state()
        errors: list[Exception] = []
        for command_id in state.command_order:
            if command_id in state.completed:
                continue
            command = state.commands[command_id]
            try:
                receipt = self._gateway.receipt_for(command_id)
            except Exception as exc:
                try:
                    self._latch_once(
                        reason="BROKER_RECEIPT_LOOKUP_FAILED",
                        detail=(
                            f"{command_id}: {type(exc).__name__}: {exc}"
                        ),
                        now=now,
                        identity=f"receipt-lookup:{command_id}",
                    )
                except Exception:
                    pass
                errors.append(exc)
                continue
            if receipt is not None:
                try:
                    self._record_completion(command, receipt, now)
                except Exception as exc:
                    errors.append(exc)
        return errors

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
    ) -> JournalEvent:
        events = self._journal.read_stream(_STREAM)
        return self._journal.append(
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
            elif event.event_type == "TradeIntentQuarantined":
                state.quarantined_intents.add(str(event.payload["intent_id"]))
            elif event.event_type == "SupervisorEntryAuthorizationConsumed":
                state.consumed_entry_authorizations[
                    str(event.payload["evidence_event_id"])
                ] = str(event.payload["intent_id"])
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
                state.completion_event_ids[receipt.command_id] = event.event_id
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
                    [
                        item.instrument_id,
                        item.quantity,
                        item.stop_price_paise,
                        item.target_price_paise,
                        item.client_command_id,
                    ]
                    for item in snapshot.protections
                ],
                "working_orders": [
                    [
                        item.broker_order_id,
                        item.client_command_id,
                        item.instrument_id,
                        item.kind,
                        item.quantity,
                        item.stop_price_paise,
                        item.target_price_paise,
                    ]
                    for item in snapshot.working_orders
                ],
                "issues": issues,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()
