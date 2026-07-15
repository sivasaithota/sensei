"""Fail-closed ownership of one bounded, governed paper Desk session."""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from tempfile import gettempdir
from threading import Lock
from typing import BinaryIO, Protocol

from sensei.kernel import (
    ENTRY_DISPATCH_AUTHORIZATION_FACT_TYPE,
    BrokerPosition,
    BrokerProtection,
    BrokerSnapshot,
    BrokerSnapshotAuthority,
    BrokerWorkingOrder,
    ReconciliationReport,
    RecordingPaperGateway,
    TradingKernel,
    entry_dispatch_authorization_fact,
)
from sensei.operations.authority import HmacFactSigner
from sensei.operations.health import HealthState, OperationalHealth, OperationsMonitor
from sensei.operations.journal import (
    EventAppend,
    JournalEvent,
    OperationalJournal,
)
from sensei.orchestration import (
    DeskCycleRequest,
    DeskCycleResult,
    DeskCycleStatus,
    DeskRuntime,
    DispatchAuthorization,
    DispatchAuthorizationRejected,
    GovernedPaperCoordinator,
    PaperTrader,
    desk_cycle_request_id,
)
from sensei.portfolio_risk import (
    AccountPosition,
    AccountSnapshot,
    AccountSnapshotAuthority,
    ReconciliationHealth,
    SafetyControl,
    SafetyResetAuthority,
    TradeIntent,
)
from sensei.portfolio_risk.safety import SafetyState

_SESSION_STREAM = re.compile(r"desk-supervisor:([0-9a-f]{64})\Z")
_EVENT_ID = re.compile(r"event:[0-9a-f]{64}\Z")
_ACCOUNT_SNAPSHOT_ID = re.compile(r"snapshot:[0-9a-f]{64}\Z")
_BROKER_SNAPSHOT_ID = re.compile(r"broker-snapshot:[0-9a-f]{64}\Z")
_DESK_REQUEST_ID = re.compile(r"desk-request:[0-9a-f]{64}\Z")
_INTENT_ID = re.compile(r"intent:[0-9a-f]{64}\Z")
_TRUTH_PHASE = re.compile(
    r"(?:INITIAL|PRE_DISPATCH:[1-9][0-9]*|POST_CYCLE:[1-9][0-9]*)\Z"
)
_CONTROL_STREAM = "desk-supervisor:control"
_TERMINAL_TYPES = {
    "DeskSupervisorCompleted",
    "DeskSupervisorFailed",
    "DeskSupervisorHalted",
}


class SupervisorConfigurationError(RuntimeError):
    """The configured desk cannot satisfy the paper-only safety policy."""


class SupervisorStartupError(RuntimeError):
    """The intended governed session cannot be started safely."""

    def __init__(self, *reason_codes: str) -> None:
        self.reason_codes = tuple(reason_codes)
        super().__init__("; ".join(self.reason_codes))


class SupervisorState(StrEnum):
    COMPLETED = "COMPLETED"
    HALTED = "HALTED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class SupervisorSessionRequest:
    now: datetime
    command_id: str

    def __post_init__(self) -> None:
        _require_aware(self.now, "session time")
        if not self.command_id.strip():
            raise ValueError("session command_id is required")


@dataclass(frozen=True)
class SupervisorShutdownRequest:
    now: datetime
    command_id: str
    reason: str

    def __post_init__(self) -> None:
        _require_aware(self.now, "shutdown time")
        if not self.command_id.strip():
            raise ValueError("shutdown command_id is required")
        if not self.reason.strip():
            raise ValueError("shutdown reason is required")


@dataclass(frozen=True)
class SupervisorShutdown:
    event_id: str
    stopped_at: datetime
    reason: str


class CycleSource(Protocol):
    def pending(self, *, now: datetime) -> tuple[object, ...]: ...


class SessionTruthSource(Protocol):
    def capture(self, *, now: datetime, command_id: str) -> SessionTruth: ...


@dataclass(frozen=True)
class SessionTruth:
    """Authenticated session facts plus the exact work identities they permit."""

    account_snapshot: AccountSnapshot
    account_snapshot_event_id: str
    operational_health: OperationalHealth
    broker_snapshot: BrokerSnapshot
    broker_snapshot_event_id: str
    authorized_cycle_request_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.account_snapshot, AccountSnapshot):
            raise TypeError("session truth requires an AccountSnapshot")
        if not isinstance(self.operational_health, OperationalHealth):
            raise TypeError("session truth requires OperationalHealth")
        if not isinstance(self.broker_snapshot, BrokerSnapshot):
            raise TypeError("session truth requires a BrokerSnapshot")
        for label, value in (
            ("account_snapshot_event_id", self.account_snapshot_event_id),
            ("broker_snapshot_event_id", self.broker_snapshot_event_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label} is required")
        request_ids = tuple(self.authorized_cycle_request_ids)
        if any(
            not isinstance(value, str) or not value.startswith("desk-request:")
            for value in request_ids
        ):
            raise ValueError(
                "authorized_cycle_request_ids must contain Desk request identities"
            )
        if len(request_ids) != len(set(request_ids)):
            raise ValueError("authorized cycle request identities must be unique")
        object.__setattr__(
            self,
            "authorized_cycle_request_ids",
            tuple(sorted(request_ids)),
        )


@dataclass(frozen=True)
class SupervisorComposition:
    kernel: TradingKernel
    cycle_source: CycleSource
    desk: DeskRuntime
    truth_source: SessionTruthSource
    account_verifier: AccountSnapshotAuthority
    health_verifier: OperationsMonitor
    safety: SafetyControl
    maximum_account_age: timedelta
    maximum_health_age: timedelta
    maximum_request_skew: timedelta
    dispatch_signer: HmacFactSigner

    def __post_init__(self) -> None:
        for label, value in (
            ("maximum_account_age", self.maximum_account_age),
            ("maximum_health_age", self.maximum_health_age),
            ("maximum_request_skew", self.maximum_request_skew),
        ):
            if value <= timedelta(0):
                raise ValueError(f"{label} must be positive")


@dataclass(frozen=True)
class SupervisorResult:
    state: SupervisorState
    cycles: tuple[DeskCycleResult, ...]
    reason_codes: tuple[str, ...] = ()
    new_entries_allowed: bool = False
    protective_actions_allowed: bool = True
    reconciliation: ReconciliationReport | None = None


class SupervisorSessionFailed(RuntimeError):
    """A supervised session recorded a fail-closed terminal result."""

    def __init__(self, result: SupervisorResult) -> None:
        self.result = result
        super().__init__("; ".join(result.reason_codes) or "SESSION_FAILED")


@dataclass(frozen=True)
class _SessionRecord:
    stream: str
    command_hash: str
    session_id: str
    requested_at: datetime
    terminal: JournalEvent | None
    result: SupervisorResult | None


@dataclass(frozen=True)
class _TruthManifest:
    event: JournalEvent
    phase: str
    checked_at: datetime
    account_snapshot_id: str
    account_snapshot_event_id: str
    health_event_id: str
    broker_snapshot_id: str
    broker_snapshot_event_id: str
    reconciliation_evidence_event_id: str
    authorized_cycle_request_ids: tuple[str, ...]
    cycle_request_id: str | None
    authorized_intent_id: str | None
    reason_codes: tuple[str, ...]


class GovernedDeskSupervisor:
    """Own one paper runtime, its recovery prefix and its terminal evidence."""

    @classmethod
    def paper_only(
        cls,
        *,
        journal_path: Path,
        gateway: object,
        compose: Callable[
            [OperationalJournal, RecordingPaperGateway], SupervisorComposition
        ],
        clock: Callable[[], datetime] | None = None,
    ) -> GovernedDeskSupervisor:
        return cls._open_paper_runtime(
            journal_path=journal_path,
            gateway=gateway,
            compose=compose,
            clock=clock,
            allow_test_doubles=False,
        )

    @classmethod
    def _paper_only_for_tests(
        cls,
        *,
        journal_path: Path,
        gateway: object,
        compose: Callable[
            [OperationalJournal, RecordingPaperGateway], SupervisorComposition
        ],
        clock: Callable[[], datetime] | None = None,
    ) -> GovernedDeskSupervisor:
        """Open the real lifecycle around explicit test doubles.

        Production code must use :meth:`paper_only`, whose side-effecting path
        rejects subclasses. This seam exists only so failure-path tests can use
        deterministic Kernel and Desk harnesses.
        """

        return cls._open_paper_runtime(
            journal_path=journal_path,
            gateway=gateway,
            compose=compose,
            clock=clock,
            allow_test_doubles=True,
        )

    @classmethod
    def _open_paper_runtime(
        cls,
        *,
        journal_path: Path,
        gateway: object,
        compose: Callable[
            [OperationalJournal, RecordingPaperGateway], SupervisorComposition
        ],
        clock: Callable[[], datetime] | None,
        allow_test_doubles: bool,
    ) -> GovernedDeskSupervisor:
        if type(gateway) is not RecordingPaperGateway:
            raise SupervisorConfigurationError(
                "paper supervision requires the exact RecordingPaperGateway type"
            )
        requested_path = Path(journal_path)
        if not requested_path.is_file():
            raise SupervisorStartupError("JOURNAL_MISSING")
        try:
            path = requested_path.resolve(strict=True)
        except FileNotFoundError:
            raise SupervisorStartupError("JOURNAL_MISSING") from None
        lease = _acquire_lease(path)
        try:
            journal = OperationalJournal(path)
            _verify_journal(journal)
            composition = compose(journal, gateway)
            if not isinstance(composition, SupervisorComposition):
                raise SupervisorConfigurationError(
                    "paper composition must return SupervisorComposition"
                )
            _assert_paper_runtime(
                journal,
                gateway,
                composition,
                allow_test_doubles=allow_test_doubles,
            )
            return cls(
                journal,
                gateway,
                composition,
                lease,
                clock=clock,
                allow_test_doubles=allow_test_doubles,
            )
        except BaseException:
            _release_lease(lease)
            raise

    def __init__(
        self,
        journal: OperationalJournal,
        gateway: RecordingPaperGateway,
        composition: SupervisorComposition,
        lease: BinaryIO,
        *,
        clock: Callable[[], datetime] | None,
        allow_test_doubles: bool,
    ) -> None:
        self._journal = journal
        self._gateway = gateway
        self._composition = composition
        self._lease: BinaryIO | None = lease
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._allow_test_doubles = allow_test_doubles
        self._lifecycle_lock = Lock()

    def close(self) -> None:
        with self._lifecycle_lock:
            self._close_lease()

    def _close_lease(self) -> None:
        lease, self._lease = self._lease, None
        if lease is not None:
            _release_lease(lease)

    def __enter__(self) -> GovernedDeskSupervisor:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()

    def run_session(self, request: SupervisorSessionRequest) -> SupervisorResult:
        if not self._lifecycle_lock.acquire(blocking=False):
            raise SupervisorStartupError("SUPERVISOR_BUSY")
        try:
            return self._run_session(request)
        finally:
            self._lifecycle_lock.release()

    def _run_session(self, request: SupervisorSessionRequest) -> SupervisorResult:
        self._require_open()
        _verify_journal(self._journal)
        self._assert_runtime()

        command_hash = _digest(request.command_id)
        stream = f"desk-supervisor:{command_hash}"
        session_id = f"desk-session:{command_hash}"
        try:
            records = _session_records(
                self._journal.read_all(),
                validate_manifest=(
                    None
                    if self._allow_test_doubles
                    else self._validate_truth_manifest_evidence
                ),
            )
        except SupervisorStartupError:
            self._recover_before_replay_rejection()
            raise
        current = next(
            (record for record in records if record.stream == stream),
            None,
        )
        incomplete = tuple(record for record in records if record.result is None)
        if current is not None:
            if current.requested_at != request.now:
                raise SupervisorStartupError("SESSION_REQUEST_CONFLICT")
            if incomplete:
                self._quarantine_incomplete_sessions(
                    incomplete,
                    failure_record=(current if current.result is None else None),
                )
                if current.result is None:
                    return SupervisorResult(
                        state=SupervisorState.HALTED,
                        cycles=(),
                        reason_codes=("INCOMPLETE_SESSION",),
                    )
            if current.result is not None:
                if current.result.state is not SupervisorState.COMPLETED:
                    self._recover_terminal_state()
                if current.result.state is SupervisorState.FAILED:
                    self._close_lease()
                    raise SupervisorSessionFailed(current.result)
                return current.result

        session_now = self._trusted_now()
        self._require_request_time(request.now, session_now)
        self._append_start(
            stream,
            command_hash=command_hash,
            session_id=session_id,
            requested_at=request.now,
            occurred_at=session_now,
        )
        if incomplete:
            return self._quarantine_prior_sessions(
                incomplete,
                current_stream=stream,
                current_hash=command_hash,
                current_session_id=session_id,
                now=session_now,
            )
        return self._run_new_session(
            request,
            stream=stream,
            command_hash=command_hash,
            session_id=session_id,
            session_now=session_now,
        )

    def shutdown(self, request: SupervisorShutdownRequest) -> SupervisorShutdown:
        if not self._lifecycle_lock.acquire(blocking=False):
            raise SupervisorStartupError("SUPERVISOR_BUSY")
        try:
            return self._shutdown(request)
        finally:
            self._lifecycle_lock.release()

    def _shutdown(self, request: SupervisorShutdownRequest) -> SupervisorShutdown:
        self._require_open()
        try:
            _verify_journal(self._journal)
            self._assert_runtime()
            events = self._journal.read_stream(_CONTROL_STREAM)
            _validate_control_stream(events)
            idempotency_key = "desk-supervisor-shutdown:" + _digest(
                request.command_id
            )
            existing = next(
                (
                    event
                    for event in events
                    if event.idempotency_key == idempotency_key
                ),
                None,
            )
            if existing is not None:
                return _shutdown_from_event(existing, expected=request)
            stopped_at = self._trusted_now()
            self._require_request_time(request.now, stopped_at)
            event = self._journal.append(
                EventAppend(
                    stream_id=_CONTROL_STREAM,
                    event_type="DeskSupervisorStopped",
                    payload={
                        "mode": "paper",
                        "reason": request.reason.strip(),
                        "requested_at": request.now.isoformat(),
                    },
                    idempotency_key=idempotency_key,
                    expected_version=len(events),
                    occurred_at=stopped_at,
                )
            )
            return _shutdown_from_event(event, expected=request)
        finally:
            self._close_lease()

    def _quarantine_incomplete_sessions(
        self,
        records: tuple[_SessionRecord, ...],
        *,
        failure_record: _SessionRecord | None,
        now: datetime | None = None,
    ) -> None:
        recovery_time = now or self._trusted_now()
        try:
            self._composition.kernel.enforce(now=recovery_time)
        except Exception as exc:
            if failure_record is not None:
                self._record_failure_and_raise(
                    failure_record.stream,
                    command_hash=failure_record.command_hash,
                    session_id=failure_record.session_id,
                    phase="RECOVERY",
                    cycles=(),
                    reconciliation=None,
                    occurred_at=recovery_time,
                    error=exc,
                )
            self._close_lease()
            raise SupervisorStartupError("RECOVERY_FAILED") from exc
        for record in records:
            quarantined = SupervisorResult(
                state=SupervisorState.HALTED,
                cycles=(),
                reason_codes=("INCOMPLETE_SESSION",),
            )
            self._record_terminal(
                record.stream,
                command_hash=record.command_hash,
                session_id=record.session_id,
                result=quarantined,
                occurred_at=recovery_time,
            )

    def _quarantine_prior_sessions(
        self,
        records: tuple[_SessionRecord, ...],
        *,
        current_stream: str,
        current_hash: str,
        current_session_id: str,
        now: datetime,
    ) -> SupervisorResult:
        current = _session_record(self._journal.read_stream(current_stream))
        self._quarantine_incomplete_sessions(
            records,
            failure_record=current,
            now=now,
        )
        halted = SupervisorResult(
            state=SupervisorState.HALTED,
            cycles=(),
            reason_codes=("INCOMPLETE_PRIOR_SESSION",),
        )
        return self._record_terminal(
            current_stream,
            command_hash=current_hash,
            session_id=current_session_id,
            result=halted,
            occurred_at=now,
        )

    def _run_new_session(
        self,
        request: SupervisorSessionRequest,
        *,
        stream: str,
        command_hash: str,
        session_id: str,
        session_now: datetime,
    ) -> SupervisorResult:
        phase = "RECOVERY"
        phase_now = session_now
        cycles: list[DeskCycleResult] = []
        reconciliation: ReconciliationReport | None = None
        try:
            self._composition.kernel.enforce(now=phase_now)
            phase = "TRUTH"
            phase_now = self._trusted_now()
            truth = self._composition.truth_source.capture(
                now=phase_now,
                command_id=f"{request.command_id}:truth",
            )
            if not isinstance(truth, SessionTruth):
                raise TypeError("truth source must return SessionTruth")

            phase = "RECONCILIATION"
            phase_now = self._trusted_now()
            reconciliation = self._composition.kernel.reconcile(
                truth.broker_snapshot,
                snapshot_event_id=truth.broker_snapshot_event_id,
                now=phase_now,
            )
            if not isinstance(reconciliation, ReconciliationReport):
                raise TypeError("kernel must return ReconciliationReport")

            phase = "HEALTH"
            phase_now = self._trusted_now()
            halt_reasons = self._truth_halt_reasons(
                truth,
                reconciliation,
                now=phase_now,
            )
            self._record_truth_manifest(
                stream,
                command_hash=command_hash,
                session_id=session_id,
                phase="INITIAL",
                truth=truth,
                reconciliation=reconciliation,
                checked_at=phase_now,
                reason_codes=halt_reasons,
                cycle_request_id=None,
                authorized_intent_id=None,
            )
            if halt_reasons:
                return self._record_halt(
                    stream,
                    command_hash=command_hash,
                    session_id=session_id,
                    cycles=(),
                    reason_codes=halt_reasons,
                    reconciliation=reconciliation,
                    occurred_at=phase_now,
                )

            phase = "POLL"
            phase_now = self._trusted_now()
            halt_reasons = self._truth_halt_reasons(
                truth,
                reconciliation,
                now=phase_now,
            )
            if halt_reasons:
                return self._record_halt(
                    stream,
                    command_hash=command_hash,
                    session_id=session_id,
                    cycles=(),
                    reason_codes=halt_reasons,
                    reconciliation=reconciliation,
                    occurred_at=phase_now,
                )
            pending = self._composition.cycle_source.pending(now=phase_now)
            if not isinstance(pending, tuple):
                raise TypeError("cycle source must return a tuple")
            phase_now = self._trusted_now()
            halt_reasons = self._truth_halt_reasons(
                truth,
                reconciliation,
                now=phase_now,
            )
            if halt_reasons:
                return self._record_halt(
                    stream,
                    command_hash=command_hash,
                    session_id=session_id,
                    cycles=(),
                    reason_codes=halt_reasons,
                    reconciliation=reconciliation,
                    occurred_at=phase_now,
                )
            cycle_truth_reasons = _cycle_truth_reasons(pending, truth)
            if cycle_truth_reasons:
                return self._record_halt(
                    stream,
                    command_hash=command_hash,
                    session_id=session_id,
                    cycles=(),
                    reason_codes=cycle_truth_reasons,
                    reconciliation=reconciliation,
                    occurred_at=phase_now,
                )

            phase = "CYCLE"
            for cycle_index, cycle in enumerate(pending, start=1):
                phase = "CYCLE"
                phase_now = self._trusted_now()
                self._assert_runtime()
                cycle_reasons = _cycle_truth_reasons((cycle,), truth)
                cycle_reasons += self._truth_halt_reasons(
                    truth,
                    reconciliation,
                    now=phase_now,
                )
                cycle_reasons += _cycle_time_reasons(
                    cycle,
                    now=phase_now,
                    maximum_skew=self._composition.maximum_request_skew,
                )
                cycle_reasons = tuple(dict.fromkeys(cycle_reasons))
                if cycle_reasons:
                    return self._record_halt(
                        stream,
                        command_hash=command_hash,
                        session_id=session_id,
                        cycles=tuple(cycles),
                        reason_codes=cycle_reasons,
                        reconciliation=reconciliation,
                        occurred_at=phase_now,
                    )
                try:
                    entry_gate_invoked = False

                    def authorize_dispatch(candidate, intent):
                        nonlocal phase, phase_now, truth, reconciliation
                        nonlocal entry_gate_invoked
                        phase = "PRE_DISPATCH"
                        (
                            authorization,
                            truth,
                            reconciliation,
                        ) = self._capture_dispatch_authorization(
                            request,
                            candidate,
                            intent,
                            stream=stream,
                            command_hash=command_hash,
                            session_id=session_id,
                            cycle_index=cycle_index,
                        )
                        entry_gate_invoked = True
                        phase_now = authorization.observed_at
                        return authorization

                    result = self._composition.desk.run_cycle(
                        cycle,
                        authorize_dispatch=authorize_dispatch,
                    )
                except DispatchAuthorizationRejected as exc:
                    return self._record_halt(
                        stream,
                        command_hash=command_hash,
                        session_id=session_id,
                        cycles=tuple(cycles),
                        reason_codes=exc.reason_codes,
                        reconciliation=reconciliation,
                        occurred_at=exc.observed_at,
                    )
                if not isinstance(result, DeskCycleResult):
                    raise TypeError("desk must return DeskCycleResult")
                if (
                    result.status is DeskCycleStatus.PAPER_DISPATCHED
                    and not entry_gate_invoked
                ):
                    start_event = self._journal.read_stream(stream)[0]
                    evidence = {
                        event.event_id: event
                        for event in self._journal.read_all()
                    }
                    if _prior_completed_desk_cycle(
                        evidence,
                        result,
                        before=start_event,
                    ) is None:
                        raise RuntimeError(
                            "paper-dispatched cycle lacks prior terminal proof"
                        )
                cycles.append(result)

                phase = "POST_CYCLE_TRUTH"
                phase_now = self._trusted_now()
                truth = self._composition.truth_source.capture(
                    now=phase_now,
                    command_id=(
                        f"{request.command_id}:truth:after:{cycle_index}"
                    ),
                )
                if not isinstance(truth, SessionTruth):
                    raise TypeError("truth source must return SessionTruth")

                phase = "POST_CYCLE_RECONCILIATION"
                phase_now = self._trusted_now()
                reconciliation = self._composition.kernel.reconcile(
                    truth.broker_snapshot,
                    snapshot_event_id=truth.broker_snapshot_event_id,
                    now=phase_now,
                )
                if not isinstance(reconciliation, ReconciliationReport):
                    raise TypeError("kernel must return ReconciliationReport")

                phase = "POST_CYCLE_HEALTH"
                phase_now = self._trusted_now()
                post_cycle_reasons = self._truth_halt_reasons(
                    truth,
                    reconciliation,
                    now=phase_now,
                )
                self._record_truth_manifest(
                    stream,
                    command_hash=command_hash,
                    session_id=session_id,
                    phase=f"POST_CYCLE:{cycle_index}",
                    truth=truth,
                    reconciliation=reconciliation,
                    checked_at=phase_now,
                    reason_codes=post_cycle_reasons,
                    cycle_request_id=None,
                    authorized_intent_id=None,
                )
                if post_cycle_reasons:
                    return self._record_halt(
                        stream,
                        command_hash=command_hash,
                        session_id=session_id,
                        cycles=tuple(cycles),
                        reason_codes=post_cycle_reasons,
                        reconciliation=reconciliation,
                        occurred_at=phase_now,
                    )

            phase_now = self._trusted_now()
            final_reasons = self._truth_halt_reasons(
                truth,
                reconciliation,
                now=phase_now,
            )
            if final_reasons:
                return self._record_halt(
                    stream,
                    command_hash=command_hash,
                    session_id=session_id,
                    cycles=tuple(cycles),
                    reason_codes=final_reasons,
                    reconciliation=reconciliation,
                    occurred_at=phase_now,
                )
            completed = SupervisorResult(
                state=SupervisorState.COMPLETED,
                cycles=tuple(cycles),
                new_entries_allowed=True,
                protective_actions_allowed=True,
                reconciliation=reconciliation,
            )
            return self._record_terminal(
                stream,
                command_hash=command_hash,
                session_id=session_id,
                result=completed,
                occurred_at=phase_now,
            )
        except Exception as exc:
            return self._record_failure_and_raise(
                stream,
                command_hash=command_hash,
                session_id=session_id,
                phase=phase,
                cycles=tuple(cycles),
                reconciliation=reconciliation,
                occurred_at=phase_now,
                error=exc,
            )

    def _capture_dispatch_authorization(
        self,
        request: SupervisorSessionRequest,
        cycle: DeskCycleRequest,
        intent: object,
        *,
        stream: str,
        command_hash: str,
        session_id: str,
        cycle_index: int,
    ) -> tuple[
        DispatchAuthorization,
        SessionTruth,
        ReconciliationReport,
    ]:
        if isinstance(intent, TradeIntent):
            intent_id = intent.intent_id
        elif self._allow_test_doubles and _INTENT_ID.fullmatch(
            str(getattr(intent, "intent_id", ""))
        ):
            intent_id = str(intent.intent_id)
        else:
            raise TypeError("dispatch authorization requires a TradeIntent")
        capture_time = self._trusted_now()
        truth = self._composition.truth_source.capture(
            now=capture_time,
            command_id=(
                f"{request.command_id}:truth:before-dispatch:{cycle_index}"
            ),
        )
        if not isinstance(truth, SessionTruth):
            raise TypeError("truth source must return SessionTruth")
        reconciliation_time = self._trusted_now()
        reconciliation = self._composition.kernel.reconcile(
            truth.broker_snapshot,
            snapshot_event_id=truth.broker_snapshot_event_id,
            now=reconciliation_time,
        )
        if not isinstance(reconciliation, ReconciliationReport):
            raise TypeError("kernel must return ReconciliationReport")
        checked_at = self._trusted_now()
        self._assert_runtime()
        reasons = _cycle_truth_reasons((cycle,), truth)
        reasons += self._truth_halt_reasons(
            truth,
            reconciliation,
            now=checked_at,
        )
        reasons += _cycle_time_reasons(
            cycle,
            now=checked_at,
            maximum_skew=self._composition.maximum_request_skew,
        )
        reasons = tuple(dict.fromkeys(reasons))
        evidence_event_id = self._record_truth_manifest(
            stream,
            command_hash=command_hash,
            session_id=session_id,
            phase=f"PRE_DISPATCH:{cycle_index}",
            truth=truth,
            reconciliation=reconciliation,
            checked_at=checked_at,
            reason_codes=reasons,
            cycle_request_id=desk_cycle_request_id(cycle),
            authorized_intent_id=intent_id,
        )
        cycle_request_id = desk_cycle_request_id(cycle)
        fact = entry_dispatch_authorization_fact(
            intent_id=intent_id,
            cycle_request_id=cycle_request_id,
            account_snapshot_id=truth.account_snapshot.snapshot_id,
            authorized_at=checked_at,
            evidence_event_id=evidence_event_id,
        )
        signer = self._composition.dispatch_signer
        return (
            DispatchAuthorization(
                observed_at=checked_at,
                evidence_event_id=evidence_event_id,
                intent_id=intent_id,
                cycle_request_id=cycle_request_id,
                issuer_id=signer.issuer_id,
                signature=signer.sign(
                    ENTRY_DISPATCH_AUTHORIZATION_FACT_TYPE,
                    fact,
                ),
                reason_codes=reasons,
            ),
            truth,
            reconciliation,
        )

    def _record_halt(
        self,
        stream: str,
        *,
        command_hash: str,
        session_id: str,
        cycles: tuple[DeskCycleResult, ...],
        reason_codes: tuple[str, ...],
        reconciliation: ReconciliationReport,
        occurred_at: datetime,
    ) -> SupervisorResult:
        enforcement_time = occurred_at
        try:
            enforcement_time = max(occurred_at, self._trusted_now())
            self._composition.kernel.enforce(now=enforcement_time)
        except Exception as exc:
            return self._record_failure_and_raise(
                stream,
                command_hash=command_hash,
                session_id=session_id,
                phase="HALT_ENFORCEMENT",
                cycles=cycles,
                reconciliation=reconciliation,
                occurred_at=enforcement_time,
                error=exc,
            )
        result = SupervisorResult(
            state=SupervisorState.HALTED,
            cycles=cycles,
            reason_codes=reason_codes,
            new_entries_allowed=False,
            protective_actions_allowed=True,
            reconciliation=reconciliation,
        )
        return self._record_terminal(
            stream,
            command_hash=command_hash,
            session_id=session_id,
            result=result,
            occurred_at=enforcement_time,
        )

    def _record_failure_and_raise(
        self,
        stream: str,
        *,
        command_hash: str,
        session_id: str,
        phase: str,
        cycles: tuple[DeskCycleResult, ...],
        reconciliation: ReconciliationReport | None,
        occurred_at: datetime,
        error: Exception,
    ) -> SupervisorResult:
        terminal_time = occurred_at
        reasons = [f"{phase}_FAILED"]
        try:
            terminal_time = max(occurred_at, self._trusted_now())
        except Exception:
            reasons.append("TERMINAL_CLOCK_FAILED")
        try:
            self._composition.kernel.enforce(now=terminal_time)
        except Exception:
            reasons.append("TERMINAL_ENFORCEMENT_FAILED")
        result = SupervisorResult(
            state=SupervisorState.FAILED,
            cycles=cycles,
            reason_codes=tuple(dict.fromkeys(reasons)),
            new_entries_allowed=False,
            protective_actions_allowed=True,
            reconciliation=reconciliation,
        )
        try:
            self._record_terminal(
                stream,
                command_hash=command_hash,
                session_id=session_id,
                result=result,
                occurred_at=terminal_time,
                error=error,
            )
        finally:
            self._close_lease()
        raise SupervisorSessionFailed(result) from error

    def _recover_terminal_state(self) -> None:
        try:
            recovery_time = self._trusted_now()
            self._composition.kernel.enforce(now=recovery_time)
        except Exception as exc:
            self._close_lease()
            raise SupervisorStartupError("TERMINAL_RECOVERY_FAILED") from exc

    def _recover_before_replay_rejection(self) -> None:
        try:
            recovery_time = self._trusted_now()
            self._composition.kernel.enforce(now=recovery_time)
        except Exception as exc:
            self._close_lease()
            raise SupervisorStartupError("RECOVERY_FAILED") from exc

    def _record_truth_manifest(
        self,
        stream: str,
        *,
        command_hash: str,
        session_id: str,
        phase: str,
        truth: SessionTruth,
        reconciliation: ReconciliationReport,
        checked_at: datetime,
        reason_codes: tuple[str, ...],
        cycle_request_id: str | None,
        authorized_intent_id: str | None,
    ) -> str:
        event = self._journal.append(
            EventAppend(
                stream_id=stream,
                event_type="DeskSupervisorTruthCaptured",
                payload={
                    "session_id": session_id,
                    "phase": phase,
                    "checked_at": checked_at.isoformat(),
                    "account_snapshot_id": truth.account_snapshot.snapshot_id,
                    "account_snapshot_event_id": (
                        truth.account_snapshot_event_id
                    ),
                    "health_event_id": truth.operational_health.event_id,
                    "broker_snapshot_id": truth.broker_snapshot.snapshot_id,
                    "broker_snapshot_event_id": truth.broker_snapshot_event_id,
                    "reconciliation_evidence_event_id": (
                        reconciliation.evidence_event_id
                    ),
                    "authorized_cycle_request_ids": (
                        truth.authorized_cycle_request_ids
                    ),
                    "cycle_request_id": cycle_request_id,
                    "authorized_intent_id": authorized_intent_id,
                    "reason_codes": reason_codes,
                },
                idempotency_key=(
                    "desk-supervisor-truth:"
                    + _digest(f"{command_hash}:{phase}")
                ),
                expected_version=len(self._journal.read_stream(stream)),
                occurred_at=checked_at,
                correlation_id=session_id,
            )
        )
        return event.event_id

    def _record_terminal(
        self,
        stream: str,
        *,
        command_hash: str,
        session_id: str,
        result: SupervisorResult,
        occurred_at: datetime,
        error: Exception | None = None,
    ) -> SupervisorResult:
        event_type, suffix = {
            SupervisorState.COMPLETED: ("DeskSupervisorCompleted", "complete"),
            SupervisorState.HALTED: ("DeskSupervisorHalted", "halted"),
            SupervisorState.FAILED: ("DeskSupervisorFailed", "failed"),
        }[result.state]
        payload: dict[str, object] = {
            "session_id": session_id,
            "state": result.state.value,
            "reason_codes": list(result.reason_codes),
            "cycles": [_cycle_payload(cycle) for cycle in result.cycles],
            "new_entries_allowed": result.new_entries_allowed,
            "protective_actions_allowed": result.protective_actions_allowed,
            "reconciliation": (
                _reconciliation_payload(result.reconciliation)
                if result.reconciliation is not None
                else None
            ),
        }
        if result.state is SupervisorState.FAILED:
            if error is None:
                raise ValueError("failed terminal requires its triggering error")
            payload["error_type"] = type(error).__name__
            payload["detail"] = str(error)
        self._journal.append(
            EventAppend(
                stream_id=stream,
                event_type=event_type,
                payload=payload,
                idempotency_key=f"desk-supervisor:{command_hash}:{suffix}",
                expected_version=len(self._journal.read_stream(stream)),
                occurred_at=occurred_at,
                correlation_id=session_id,
            )
        )
        return result

    def _append_start(
        self,
        stream: str,
        *,
        command_hash: str,
        session_id: str,
        requested_at: datetime,
        occurred_at: datetime,
    ) -> None:
        self._journal.append(
            EventAppend(
                stream_id=stream,
                event_type="DeskSupervisorStarted",
                payload={
                    "session_id": session_id,
                    "mode": "paper",
                    "requested_at": requested_at.isoformat(),
                },
                idempotency_key=f"desk-supervisor:{command_hash}:start",
                expected_version=len(self._journal.read_stream(stream)),
                occurred_at=occurred_at,
                correlation_id=session_id,
            )
        )

    def _verify_account(self, truth: SessionTruth, *, now: datetime) -> bool:
        valid = self._composition.account_verifier.verify(
            truth.account_snapshot_event_id,
            snapshot=truth.account_snapshot,
            no_later_than=now,
        )
        if not isinstance(valid, bool):
            raise TypeError("account verifier must return a boolean")
        return valid

    def _truth_halt_reasons(
        self,
        truth: SessionTruth,
        reconciliation: ReconciliationReport,
        *,
        now: datetime,
    ) -> tuple[str, ...]:
        return _halt_reasons(
            truth,
            reconciliation=reconciliation,
            account_valid=self._verify_account(truth, now=now),
            health_valid=self._verify_health(truth, now=now),
            safety=self._safety_state(),
            now=now,
            maximum_account_age=self._composition.maximum_account_age,
            maximum_health_age=self._composition.maximum_health_age,
        )

    def _verify_health(self, truth: SessionTruth, *, now: datetime) -> bool:
        valid = self._composition.health_verifier.verify(
            truth.operational_health,
            no_later_than=now,
        )
        if not isinstance(valid, bool):
            raise TypeError("health verifier must return a boolean")
        return valid

    def _safety_state(self) -> SafetyState:
        state = self._composition.safety.state()
        if not isinstance(state, SafetyState):
            raise TypeError("safety view must return SafetyState")
        return state

    def _validate_truth_manifest_evidence(
        self,
        manifest: _TruthManifest,
        evidence: Mapping[str, JournalEvent],
    ) -> None:
        try:
            account_event = _prior_evidence(
                evidence,
                manifest.account_snapshot_event_id,
                manifest.event,
                "AccountSnapshotAuthenticated",
            )
            account_snapshot = _account_snapshot_from_event(account_event)
            if (
                account_snapshot.snapshot_id != manifest.account_snapshot_id
                or not self._composition.account_verifier.verify(
                    account_event.event_id,
                    snapshot=account_snapshot,
                    no_later_than=manifest.checked_at,
                )
            ):
                raise ValueError

            health_event = _prior_evidence(
                evidence,
                manifest.health_event_id,
                manifest.event,
                "OperationalHealthAssessed",
            )
            health = _operational_health_from_event(health_event)
            if not self._composition.health_verifier.verify(
                health,
                no_later_than=manifest.checked_at,
            ):
                raise ValueError

            broker_event = _prior_evidence(
                evidence,
                manifest.broker_snapshot_event_id,
                manifest.event,
                "BrokerSnapshotAuthenticated",
            )
            broker_snapshot = _broker_snapshot_from_event(broker_event)
            broker_authority = getattr(
                self._composition.kernel,
                "_broker_snapshot_authority",
                None,
            )
            if (
                type(broker_authority) is not BrokerSnapshotAuthority
                or broker_snapshot.snapshot_id != manifest.broker_snapshot_id
                or not broker_authority.verify(
                    broker_event.event_id,
                    snapshot=broker_snapshot,
                    no_later_than=manifest.checked_at,
                )
            ):
                raise ValueError

            reconciliation_event = _prior_evidence(
                evidence,
                manifest.reconciliation_evidence_event_id,
                manifest.event,
                "ReconciliationOutcomeAttested",
            )
            reconciliation = _reconciliation_health_from_event(
                reconciliation_event
            )
            reset_authority = getattr(
                self._composition.kernel,
                "_safety_reset_authority",
                None,
            )
            if (
                type(reset_authority) is not SafetyResetAuthority
                or reconciliation.snapshot_id != manifest.broker_snapshot_id
                or reconciliation.broker_snapshot_event_id
                != manifest.broker_snapshot_event_id
                or not reset_authority.verify_reconciliation(
                    reconciliation,
                    no_later_than=manifest.checked_at,
                )
            ):
                raise ValueError
        except (AttributeError, KeyError, TypeError, ValueError):
            raise SupervisorStartupError("SESSION_TRUTH_EVIDENCE_INVALID") from None

    def _require_open(self) -> None:
        if self._lease is None:
            raise SupervisorStartupError("SUPERVISOR_CLOSED")

    def _assert_runtime(self) -> None:
        _assert_paper_runtime(
            self._journal,
            self._gateway,
            self._composition,
            allow_test_doubles=self._allow_test_doubles,
        )

    def _trusted_now(self) -> datetime:
        try:
            value = self._clock()
            _require_aware(value, "trusted clock")
        except Exception:
            raise SupervisorStartupError("TRUSTED_CLOCK_INVALID") from None
        return value

    def _require_request_time(
        self,
        requested_at: datetime,
        observed_at: datetime,
    ) -> None:
        if abs(observed_at - requested_at) > self._composition.maximum_request_skew:
            raise SupervisorStartupError("SESSION_TIME_SKEW")


def _assert_paper_runtime(
    journal: OperationalJournal,
    gateway: RecordingPaperGateway,
    composition: SupervisorComposition,
    *,
    allow_test_doubles: bool,
) -> None:
    if not allow_test_doubles and type(composition) is not SupervisorComposition:
        raise SupervisorConfigurationError(
            "paper composition must use the exact SupervisorComposition type"
        )
    if type(gateway) is not RecordingPaperGateway:
        raise SupervisorConfigurationError(
            "supervisor gateway changed from the exact paper type"
        )
    if type(composition.dispatch_signer) is not HmacFactSigner:
        raise SupervisorConfigurationError(
            "paper supervision requires an exact dispatch signer"
        )
    required_kernel_type = (
        isinstance(composition.kernel, TradingKernel)
        if allow_test_doubles
        else type(composition.kernel) is TradingKernel
    )
    if not required_kernel_type:
        raise SupervisorConfigurationError(
            "paper composition kernel must be TradingKernel"
        )
    kernel_bound = (
        getattr(composition.kernel, "_journal", None) is journal
        and getattr(composition.kernel, "_gateway", None) is gateway
        and getattr(composition.kernel, "_safety", None) is composition.safety
        if allow_test_doubles
        else TradingKernel.is_bound_to_paper_runtime(
            composition.kernel,
            journal=journal,
            gateway=gateway,
            safety=composition.safety,
        )
    )
    if not kernel_bound:
        raise SupervisorConfigurationError(
            "kernel is not bound to the exact paper runtime"
        )
    if not allow_test_doubles and not (
        TradingKernel.accepts_entry_authorization_signer(
            composition.kernel,
            composition.dispatch_signer,
        )
    ):
        raise SupervisorConfigurationError(
            "kernel does not trust the configured dispatch signer"
        )
    if not allow_test_doubles and (
        type(getattr(composition.kernel, "_broker_snapshot_authority", None))
        is not BrokerSnapshotAuthority
        or type(getattr(composition.kernel, "_safety_reset_authority", None))
        is not SafetyResetAuthority
        or getattr(composition.kernel, "_reconciliation_signer", None) is None
    ):
        raise SupervisorConfigurationError(
            "paper supervision requires authenticated reconciliation"
        )
    required_desk_type = (
        isinstance(composition.desk, DeskRuntime)
        if allow_test_doubles
        else type(composition.desk) is DeskRuntime
    )
    if not required_desk_type:
        raise SupervisorConfigurationError(
            "paper composition desk must be DeskRuntime"
        )
    trader = getattr(composition.desk, "trader", None)
    coordinator = getattr(trader, "_coordinator", None)
    desk_bound = (
        getattr(composition.desk, "_journal", None) is journal
        and isinstance(trader, PaperTrader)
        and getattr(trader, "_kernel", None) is composition.kernel
        and getattr(coordinator, "_journal", None) is journal
        and getattr(coordinator, "_kernel", None) is composition.kernel
        and getattr(coordinator, "_safety", None) is composition.safety
        and getattr(coordinator, "_operations_monitor", None)
        is composition.health_verifier
        if allow_test_doubles
        else DeskRuntime.is_bound_to_governed_paper_runtime(
            composition.desk,
            journal=journal,
            kernel=composition.kernel,
            safety=composition.safety,
            operations_monitor=composition.health_verifier,
        )
    )
    if not desk_bound:
        raise SupervisorConfigurationError(
            "desk is not bound to the exact paper runtime"
        )
    _assert_truth_and_safety_bindings(
        journal,
        composition,
        allow_test_doubles=allow_test_doubles,
    )


def _assert_truth_and_safety_bindings(
    journal: OperationalJournal,
    composition: SupervisorComposition,
    *,
    allow_test_doubles: bool,
) -> None:
    type_checks = (
        (
            composition.account_verifier,
            AccountSnapshotAuthority,
            "account verifier",
        ),
        (composition.health_verifier, OperationsMonitor, "health verifier"),
        (composition.safety, SafetyControl, "safety control"),
    )
    for value, expected_type, label in type_checks:
        valid_type = (
            isinstance(value, expected_type)
            if allow_test_doubles
            else type(value) is expected_type
        )
        if not valid_type:
            raise SupervisorConfigurationError(
                f"paper composition {label} has an invalid concrete type"
            )
    account_bound = (
        getattr(composition.account_verifier, "_journal", None) is journal
        if allow_test_doubles
        else AccountSnapshotAuthority.is_bound_to_journal(
            composition.account_verifier,
            journal,
        )
    )
    if not account_bound:
        raise SupervisorConfigurationError(
            "account verifier is not bound to the exact runtime journal"
        )
    health_bound = (
        getattr(composition.health_verifier, "_journal", None) is journal
        if allow_test_doubles
        else OperationsMonitor.is_bound_to_journal(
            composition.health_verifier,
            journal,
        )
    )
    if not health_bound:
        raise SupervisorConfigurationError(
            "health verifier is not bound to the exact runtime journal"
        )
    if not allow_test_doubles and (
        getattr(composition.health_verifier, "_safety_reset_authority", None)
        is not getattr(composition.kernel, "_safety_reset_authority", None)
    ):
        raise SupervisorConfigurationError(
            "health and Kernel do not share the safety reset authority"
        )
    safety_bound = (
        getattr(composition.safety, "_journal", None) is journal
        if allow_test_doubles
        else SafetyControl.is_bound_to_journal(composition.safety, journal)
    )
    if not safety_bound:
        raise SupervisorConfigurationError(
            "safety control is not bound to the exact runtime journal"
        )
    trader = composition.desk.trader
    if not allow_test_doubles and (
        type(trader) is not PaperTrader
        or type(trader._coordinator) is not GovernedPaperCoordinator
    ):
        raise SupervisorConfigurationError(
            "paper execution chain must use exact Trader and Coordinator types"
        )


def _verify_journal(journal: OperationalJournal) -> None:
    if not journal.verify().ok:
        raise SupervisorStartupError("JOURNAL_INTEGRITY_FAILED")


def _session_records(
    events: Sequence[JournalEvent],
    *,
    validate_manifest: (
        Callable[[_TruthManifest, Mapping[str, JournalEvent]], None] | None
    ) = None,
) -> tuple[_SessionRecord, ...]:
    grouped: dict[str, list[JournalEvent]] = {}
    evidence = {event.event_id: event for event in events}
    if len(evidence) != len(events):
        raise SupervisorStartupError("JOURNAL_EVENT_ID_CONFLICT")
    for event in events:
        if event.stream_id == _CONTROL_STREAM:
            continue
        if event.stream_id.startswith("desk-supervisor:"):
            if _SESSION_STREAM.fullmatch(event.stream_id) is None:
                raise SupervisorStartupError("SESSION_STREAM_INVALID")
            grouped.setdefault(event.stream_id, []).append(event)
    return tuple(
        _session_record(
            tuple(stream_events),
            evidence=evidence,
            validate_manifest=validate_manifest,
        )
        for _, stream_events in sorted(grouped.items())
    )


def _session_record(
    events: Sequence[JournalEvent],
    *,
    evidence: Mapping[str, JournalEvent] | None = None,
    validate_manifest: (
        Callable[[_TruthManifest, Mapping[str, JournalEvent]], None] | None
    ) = None,
) -> _SessionRecord:
    if not events:
        raise SupervisorStartupError("SESSION_STREAM_INVALID")
    start = events[0]
    match = _SESSION_STREAM.fullmatch(start.stream_id)
    if match is None:
        raise SupervisorStartupError("SESSION_STREAM_INVALID")
    command_hash = match.group(1)
    session_id = f"desk-session:{command_hash}"
    try:
        if (
            start.event_type != "DeskSupervisorStarted"
            or start.schema_version != 1
            or start.correlation_id != session_id
            or set(start.payload) != {"session_id", "mode", "requested_at"}
            or start.payload["session_id"] != session_id
            or start.payload["mode"] != "paper"
        ):
            raise ValueError
        requested_at = _parse_aware_text(start.payload["requested_at"])
    except (KeyError, TypeError, ValueError):
        raise SupervisorStartupError("SESSION_START_INVALID") from None
    if any(event.stream_id != start.stream_id for event in events):
        raise SupervisorStartupError("SESSION_STREAM_INVALID")
    terminal = events[-1] if events[-1].event_type in _TERMINAL_TYPES else None
    result = (
        _result_from_terminal(terminal, session_id=session_id)
        if terminal is not None
        else None
    )
    manifest_events = events[1:-1] if terminal is not None else events[1:]
    manifests = tuple(
        _truth_phase_from_event(
            event,
            command_hash=command_hash,
            session_id=session_id,
        )
        for event in manifest_events
    )
    phases = tuple(manifest.phase for manifest in manifests)
    if len(phases) != len(set(phases)):
        raise SupervisorStartupError("SESSION_TRUTH_INVALID")
    if validate_manifest is not None:
        if evidence is None:
            raise SupervisorStartupError("SESSION_TRUTH_EVIDENCE_INVALID")
        for manifest in manifests:
            validate_manifest(manifest, evidence)
    if result is not None and result.state is SupervisorState.COMPLETED:
        expected_phases: list[str] = ["INITIAL"]
        for index, cycle in enumerate(result.cycles, start=1):
            pre_dispatch_phase = f"PRE_DISPATCH:{index}"
            if cycle.status is DeskCycleStatus.PAPER_DISPATCHED:
                if pre_dispatch_phase in phases:
                    expected_phases.append(pre_dispatch_phase)
                elif (
                    evidence is None
                    or _prior_completed_desk_cycle(
                        evidence,
                        cycle,
                        before=start,
                    )
                    is None
                ):
                    raise SupervisorStartupError("SESSION_TRUTH_INVALID")
            expected_phases.append(f"POST_CYCLE:{index}")
        if tuple(expected_phases) != phases or any(
            manifest.reason_codes for manifest in manifests
        ):
            raise SupervisorStartupError("SESSION_TRUTH_INVALID")
    _validate_terminal_manifest_link(
        terminal=terminal,
        result=result,
        manifests=manifests,
        evidence=evidence if validate_manifest is not None else None,
    )
    if terminal is not None and manifest_events and (
        terminal.global_sequence <= manifest_events[-1].global_sequence
        or terminal.occurred_at < manifest_events[-1].occurred_at
    ):
        raise SupervisorStartupError("SESSION_TERMINAL_INVALID")
    return _SessionRecord(
        stream=start.stream_id,
        command_hash=command_hash,
        session_id=session_id,
        requested_at=requested_at,
        terminal=terminal,
        result=result,
    )


def _truth_phase_from_event(
    event: JournalEvent,
    *,
    command_hash: str,
    session_id: str,
) -> _TruthManifest:
    keys = {
        "session_id",
        "phase",
        "checked_at",
        "account_snapshot_id",
        "account_snapshot_event_id",
        "health_event_id",
        "broker_snapshot_id",
        "broker_snapshot_event_id",
        "reconciliation_evidence_event_id",
        "authorized_cycle_request_ids",
        "cycle_request_id",
        "authorized_intent_id",
        "reason_codes",
    }
    try:
        payload = event.payload
        if (
            event.event_type != "DeskSupervisorTruthCaptured"
            or event.schema_version != 1
            or event.correlation_id != session_id
            or set(payload) != keys
            or payload["session_id"] != session_id
        ):
            raise ValueError
        phase = _required_text(payload["phase"])
        if _TRUTH_PHASE.fullmatch(phase) is None:
            raise ValueError
        if event.idempotency_key != (
            "desk-supervisor-truth:"
            + _digest(f"{command_hash}:{phase}")
        ):
            raise ValueError
        checked_at = _parse_aware_text(payload["checked_at"])
        if checked_at != event.occurred_at:
            raise ValueError
        account_snapshot_id = _required_text(payload["account_snapshot_id"])
        broker_snapshot_id = _required_text(payload["broker_snapshot_id"])
        if _ACCOUNT_SNAPSHOT_ID.fullmatch(account_snapshot_id) is None:
            raise ValueError
        if _BROKER_SNAPSHOT_ID.fullmatch(broker_snapshot_id) is None:
            raise ValueError
        evidence_ids: dict[str, str] = {}
        for key in (
            "account_snapshot_event_id",
            "health_event_id",
            "broker_snapshot_event_id",
            "reconciliation_evidence_event_id",
        ):
            evidence_id = _required_text(payload[key])
            if _EVENT_ID.fullmatch(evidence_id) is None:
                raise ValueError
            evidence_ids[key] = evidence_id
        authorized = _text_tuple(payload["authorized_cycle_request_ids"])
        if (
            tuple(sorted(authorized)) != authorized
            or len(authorized) != len(set(authorized))
            or any(_DESK_REQUEST_ID.fullmatch(value) is None for value in authorized)
        ):
            raise ValueError
        cycle_request_id = _optional_text(payload["cycle_request_id"])
        authorized_intent_id = _optional_text(
            payload["authorized_intent_id"]
        )
        if phase.startswith("PRE_DISPATCH:"):
            if (
                cycle_request_id is None
                or cycle_request_id not in authorized
                or _DESK_REQUEST_ID.fullmatch(cycle_request_id) is None
                or authorized_intent_id is None
                or _INTENT_ID.fullmatch(authorized_intent_id) is None
            ):
                raise ValueError
        elif cycle_request_id is not None or authorized_intent_id is not None:
            raise ValueError
        reason_codes = _text_tuple(payload["reason_codes"])
        if len(reason_codes) != len(set(reason_codes)):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise SupervisorStartupError("SESSION_TRUTH_INVALID") from None
    return _TruthManifest(
        event=event,
        phase=phase,
        checked_at=checked_at,
        account_snapshot_id=account_snapshot_id,
        account_snapshot_event_id=evidence_ids["account_snapshot_event_id"],
        health_event_id=evidence_ids["health_event_id"],
        broker_snapshot_id=broker_snapshot_id,
        broker_snapshot_event_id=evidence_ids["broker_snapshot_event_id"],
        reconciliation_evidence_event_id=evidence_ids[
            "reconciliation_evidence_event_id"
        ],
        authorized_cycle_request_ids=authorized,
        cycle_request_id=cycle_request_id,
        authorized_intent_id=authorized_intent_id,
        reason_codes=reason_codes,
    )


def _validate_terminal_manifest_link(
    *,
    terminal: JournalEvent | None,
    result: SupervisorResult | None,
    manifests: tuple[_TruthManifest, ...],
    evidence: Mapping[str, JournalEvent] | None,
) -> None:
    if not _manifest_phase_sequence_is_valid(manifests):
        raise SupervisorStartupError("SESSION_TRUTH_INVALID")
    if terminal is None or result is None:
        return
    reconciliation = result.reconciliation
    incomplete_halt = result.state is SupervisorState.HALTED and set(
        result.reason_codes
    ).issubset({"INCOMPLETE_SESSION", "INCOMPLETE_PRIOR_SESSION"})
    if result.state is SupervisorState.COMPLETED and (
        not manifests
        or reconciliation is None
        or not reconciliation.clean
        or reconciliation.issues
    ):
        raise SupervisorStartupError("SESSION_TERMINAL_INVALID")
    if (
        result.state is SupervisorState.HALTED
        and not incomplete_halt
        and (not manifests or reconciliation is None)
    ):
        raise SupervisorStartupError("SESSION_TERMINAL_INVALID")
    if (
        result.state is not SupervisorState.FAILED
        and manifests
        and reconciliation is not None
    ):
        final = manifests[-1]
        if (
            final.broker_snapshot_id != reconciliation.snapshot_id
            or final.broker_snapshot_event_id
            != reconciliation.broker_snapshot_event_id
            or final.reconciliation_evidence_event_id
            != reconciliation.evidence_event_id
        ):
            raise SupervisorStartupError("SESSION_TERMINAL_INVALID")
        if evidence is not None:
            try:
                attested = _reconciliation_health_from_event(
                    evidence[final.reconciliation_evidence_event_id]
                )
            except (KeyError, TypeError, ValueError):
                raise SupervisorStartupError(
                    "SESSION_TERMINAL_INVALID"
                ) from None
            if (
                reconciliation.snapshot_id != attested.snapshot_id
                or reconciliation.clean is not attested.clean
                or reconciliation.issues != attested.issues
                or reconciliation.observed_at != attested.observed_at
                or reconciliation.broker_snapshot_event_id
                != attested.broker_snapshot_event_id
                or reconciliation.kernel_event_id != attested.kernel_event_id
                or reconciliation.evidence_event_id != attested.event_id
            ):
                raise SupervisorStartupError("SESSION_TERMINAL_INVALID")


def _prior_completed_desk_cycle(
    evidence: Mapping[str, JournalEvent],
    cycle: DeskCycleResult,
    *,
    before: JournalEvent,
) -> JournalEvent | None:
    """Resolve exact prior Desk terminal evidence for a replayed cycle."""

    stream = "desk-cycle:" + cycle.cycle_id.removeprefix("cycle:")
    terminals = tuple(
        event
        for event in evidence.values()
        if event.stream_id == stream
        and event.event_type == "DeskCycleCompleted"
        and event.global_sequence < before.global_sequence
        and event.occurred_at <= before.occurred_at
    )
    if len(terminals) != 1:
        return None
    terminal = terminals[0]
    payload = terminal.payload
    try:
        role_event_ids = _text_tuple(payload["role_event_ids"])
        if (
            terminal.schema_version != 1
            or terminal.correlation_id != cycle.cycle_id
            or payload["cycle_id"] != cycle.cycle_id
            or payload["status"] != cycle.status.value
            or payload["reason"] != cycle.reason
            or payload["trace_id"] != cycle.trace_id
            or _optional_text(payload["thesis_id"]) != cycle.thesis_id
            or _optional_text(payload["intent_id"]) != cycle.intent_id
            or role_event_ids != cycle.role_event_ids
        ):
            return None
        roles = tuple(evidence[event_id] for event_id in role_event_ids)
        if any(
            role.stream_id != stream
            or role.event_type not in {"DeskRoleCompleted", "DeskRoleSkipped"}
            or role.global_sequence >= terminal.global_sequence
            for role in roles
        ):
            return None
        trader = next(
            (
                role
                for role in roles
                if role.event_type == "DeskRoleCompleted"
                and role.payload.get("role") == "trader"
            ),
            None,
        )
        details = trader.payload.get("details") if trader is not None else None
        episode_id = (
            _optional_text(details.get("episode_id"))
            if isinstance(details, Mapping)
            else None
        )
        if episode_id != cycle.episode_id:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return terminal


def _manifest_phase_sequence_is_valid(
    manifests: tuple[_TruthManifest, ...],
) -> bool:
    if not manifests:
        return True
    if manifests[0].phase != "INITIAL":
        return False
    next_cycle = 1
    waiting_for_post = False
    for manifest in manifests[1:]:
        pre = f"PRE_DISPATCH:{next_cycle}"
        post = f"POST_CYCLE:{next_cycle}"
        if not waiting_for_post and manifest.phase == pre:
            waiting_for_post = True
            continue
        if manifest.phase != post:
            return False
        waiting_for_post = False
        next_cycle += 1
    return True


def _prior_evidence(
    evidence: Mapping[str, JournalEvent],
    event_id: str,
    manifest: JournalEvent,
    expected_type: str,
) -> JournalEvent:
    if _EVENT_ID.fullmatch(event_id) is None:
        raise ValueError
    event = evidence.get(event_id)
    if (
        event is None
        or event.event_type != expected_type
        or event.global_sequence >= manifest.global_sequence
        or event.occurred_at > manifest.occurred_at
    ):
        raise ValueError
    return event


def _account_snapshot_from_event(event: JournalEvent) -> AccountSnapshot:
    fact = _strict_mapping(event.payload["fact"])
    if set(fact) != {"snapshot", "observed_at"}:
        raise ValueError
    snapshot_payload = _strict_mapping(fact["snapshot"])
    if set(snapshot_payload) != {
        "available_cash_paise",
        "marked_equity_paise",
        "high_water_mark_paise",
        "day_pnl_paise",
        "week_pnl_paise",
        "positions",
        "included_reservation_ids",
        "reconciled",
        "captured_at",
        "snapshot_id",
    }:
        raise ValueError
    positions = tuple(
        _account_position_from_payload(value)
        for value in _strict_sequence(snapshot_payload["positions"])
    )
    snapshot = AccountSnapshot(
        available_cash_paise=_strict_int(
            snapshot_payload["available_cash_paise"]
        ),
        marked_equity_paise=_strict_int(snapshot_payload["marked_equity_paise"]),
        high_water_mark_paise=_strict_int(
            snapshot_payload["high_water_mark_paise"]
        ),
        day_pnl_paise=_strict_int(snapshot_payload["day_pnl_paise"]),
        week_pnl_paise=_strict_int(snapshot_payload["week_pnl_paise"]),
        positions=positions,
        included_reservation_ids=_text_tuple(
            snapshot_payload["included_reservation_ids"]
        ),
        reconciled=_required_bool(snapshot_payload["reconciled"]),
        captured_at=_parse_aware_text(snapshot_payload["captured_at"]),
    )
    if snapshot_payload["snapshot_id"] != snapshot.snapshot_id:
        raise ValueError
    return snapshot


def _account_position_from_payload(value: object) -> AccountPosition:
    payload = _strict_mapping(value)
    if set(payload) != {
        "instrument_id",
        "quantity",
        "notional_paise",
        "risk_to_stop_paise",
    }:
        raise ValueError
    return AccountPosition(
        instrument_id=_required_text(payload["instrument_id"]),
        quantity=_strict_int(payload["quantity"]),
        notional_paise=_strict_int(payload["notional_paise"]),
        risk_to_stop_paise=_strict_int(payload["risk_to_stop_paise"]),
    )


def _broker_snapshot_from_event(event: JournalEvent) -> BrokerSnapshot:
    fact = _strict_mapping(event.payload["fact"])
    if set(fact) != {"snapshot", "observed_at"}:
        raise ValueError
    payload = _strict_mapping(fact["snapshot"])
    if set(payload) != {
        "captured_at",
        "positions",
        "protections",
        "working_orders",
        "snapshot_id",
    }:
        raise ValueError
    snapshot = BrokerSnapshot(
        captured_at=_parse_aware_text(payload["captured_at"]),
        positions=tuple(
            _broker_position_from_payload(value)
            for value in _strict_sequence(payload["positions"])
        ),
        protections=tuple(
            _broker_protection_from_payload(value)
            for value in _strict_sequence(payload["protections"])
        ),
        working_orders=tuple(
            _broker_working_order_from_payload(value)
            for value in _strict_sequence(payload["working_orders"])
        ),
    )
    if payload["snapshot_id"] != snapshot.snapshot_id:
        raise ValueError
    return snapshot


def _broker_position_from_payload(value: object) -> BrokerPosition:
    payload = _strict_mapping(value)
    if set(payload) != {"instrument_id", "quantity"}:
        raise ValueError
    return BrokerPosition(
        instrument_id=_required_text(payload["instrument_id"]),
        quantity=_strict_int(payload["quantity"]),
    )


def _broker_protection_from_payload(value: object) -> BrokerProtection:
    payload = _strict_mapping(value)
    if set(payload) != {
        "instrument_id",
        "quantity",
        "stop_price_paise",
        "target_price_paise",
        "client_command_id",
    }:
        raise ValueError
    return BrokerProtection(
        instrument_id=_required_text(payload["instrument_id"]),
        quantity=_strict_int(payload["quantity"]),
        stop_price_paise=_strict_int(payload["stop_price_paise"]),
        target_price_paise=_strict_int(payload["target_price_paise"]),
        client_command_id=_optional_text(payload["client_command_id"]),
    )


def _broker_working_order_from_payload(value: object) -> BrokerWorkingOrder:
    payload = _strict_mapping(value)
    if set(payload) != {
        "broker_order_id",
        "client_command_id",
        "instrument_id",
        "kind",
        "quantity",
        "stop_price_paise",
        "target_price_paise",
    }:
        raise ValueError
    stop = payload["stop_price_paise"]
    target = payload["target_price_paise"]
    return BrokerWorkingOrder(
        broker_order_id=_required_text(payload["broker_order_id"]),
        client_command_id=_optional_text(payload["client_command_id"]),
        instrument_id=_required_text(payload["instrument_id"]),
        kind=_required_text(payload["kind"]),
        quantity=_strict_int(payload["quantity"]),
        stop_price_paise=None if stop is None else _strict_int(stop),
        target_price_paise=None if target is None else _strict_int(target),
    )


def _operational_health_from_event(event: JournalEvent) -> OperationalHealth:
    fact = _strict_mapping(event.payload["fact"])
    if set(fact) != {
        "state",
        "reason_codes",
        "new_entries_allowed",
        "protective_actions_allowed",
        "assessed_at",
        "readiness",
    }:
        raise ValueError
    readiness = _strict_mapping(fact["readiness"])
    if set(readiness) != {
        "event_id",
        "ready",
        "assessed_at",
        "reason_codes",
        "evidence_event_ids",
    }:
        raise ValueError
    _required_bool(readiness["ready"])
    _parse_aware_text(readiness["assessed_at"])
    _text_tuple(readiness["reason_codes"])
    return OperationalHealth(
        state=HealthState(_required_text(fact["state"])),
        assessed_at=_parse_aware_text(fact["assessed_at"]),
        reason_codes=_text_tuple(fact["reason_codes"]),
        new_entries_allowed=_required_bool(fact["new_entries_allowed"]),
        protective_actions_allowed=_required_bool(
            fact["protective_actions_allowed"]
        ),
        readiness_event_id=_required_text(readiness["event_id"]),
        readiness_evidence_event_ids=_text_tuple(
            readiness["evidence_event_ids"]
        ),
        event_id=event.event_id,
    )


def _reconciliation_health_from_event(
    event: JournalEvent,
) -> ReconciliationHealth:
    payload = _strict_mapping(event.payload)
    if set(payload) != {
        "schema_version",
        "authority",
        "issuer_id",
        "fact",
        "signature",
    }:
        raise ValueError
    fact = _strict_mapping(payload["fact"])
    if set(fact) != {
        "kernel_event_id",
        "broker_snapshot_event_id",
        "snapshot_id",
        "clean",
        "issues",
        "observed_at",
    }:
        raise ValueError
    return ReconciliationHealth(
        event_id=event.event_id,
        kernel_event_id=_required_event_id(fact["kernel_event_id"]),
        broker_snapshot_event_id=_required_event_id(
            fact["broker_snapshot_event_id"]
        ),
        snapshot_id=_required_text(fact["snapshot_id"]),
        clean=_required_bool(fact["clean"]),
        issues=_text_tuple(fact["issues"]),
        observed_at=_parse_aware_text(fact["observed_at"]),
        issuer_id=_required_text(payload["issuer_id"]),
    )


def _result_from_terminal(
    terminal: JournalEvent,
    *,
    session_id: str,
) -> SupervisorResult:
    base_keys = {
        "session_id",
        "state",
        "reason_codes",
        "cycles",
        "new_entries_allowed",
        "protective_actions_allowed",
        "reconciliation",
    }
    try:
        if (
            terminal.event_type not in _TERMINAL_TYPES
            or terminal.schema_version != 1
            or terminal.correlation_id != session_id
        ):
            raise ValueError
        expected_keys = (
            base_keys | {"error_type", "detail"}
            if terminal.event_type == "DeskSupervisorFailed"
            else base_keys
        )
        payload = terminal.payload
        if set(payload) != expected_keys or payload["session_id"] != session_id:
            raise ValueError
        expected_state = {
            "DeskSupervisorCompleted": SupervisorState.COMPLETED,
            "DeskSupervisorHalted": SupervisorState.HALTED,
            "DeskSupervisorFailed": SupervisorState.FAILED,
        }[terminal.event_type]
        state = SupervisorState(_required_text(payload["state"]))
        if state is not expected_state:
            raise ValueError
        reason_codes = _text_tuple(payload["reason_codes"])
        cycles_payload = _required_list(payload["cycles"])
        cycles = tuple(_cycle_from_payload(value) for value in cycles_payload)
        new_entries_allowed = _required_bool(payload["new_entries_allowed"])
        protective_actions_allowed = _required_bool(
            payload["protective_actions_allowed"]
        )
        reconciliation_payload = payload["reconciliation"]
        reconciliation = (
            None
            if reconciliation_payload is None
            else _reconciliation_from_payload(reconciliation_payload)
        )
        if not protective_actions_allowed:
            raise ValueError
        if reconciliation is not None and reconciliation.clean != (
            not reconciliation.issues
        ):
            raise ValueError
        if state is SupervisorState.COMPLETED:
            if (
                reason_codes
                or not new_entries_allowed
                or reconciliation is None
                or not reconciliation.clean
            ):
                raise ValueError
        elif not reason_codes or new_entries_allowed:
            raise ValueError
        if state is SupervisorState.FAILED:
            _required_text(payload["error_type"])
            if not isinstance(payload["detail"], str):
                raise TypeError
    except (KeyError, TypeError, ValueError):
        raise SupervisorStartupError("SESSION_TERMINAL_INVALID") from None
    return SupervisorResult(
        state=state,
        cycles=cycles,
        reason_codes=reason_codes,
        new_entries_allowed=new_entries_allowed,
        protective_actions_allowed=protective_actions_allowed,
        reconciliation=reconciliation,
    )


def _cycle_payload(cycle: DeskCycleResult) -> dict[str, object]:
    if not isinstance(cycle, DeskCycleResult):
        raise TypeError("desk must return DeskCycleResult")
    return {
        "cycle_id": cycle.cycle_id,
        "status": cycle.status.value,
        "reason": cycle.reason,
        "trace_id": cycle.trace_id,
        "thesis_id": cycle.thesis_id,
        "intent_id": cycle.intent_id,
        "episode_id": cycle.episode_id,
        "role_event_ids": list(cycle.role_event_ids),
    }


def _cycle_from_payload(payload: object) -> DeskCycleResult:
    keys = {
        "cycle_id",
        "status",
        "reason",
        "trace_id",
        "thesis_id",
        "intent_id",
        "episode_id",
        "role_event_ids",
    }
    if not isinstance(payload, Mapping) or set(payload) != keys:
        raise TypeError
    return DeskCycleResult(
        cycle_id=_required_text(payload["cycle_id"]),
        status=DeskCycleStatus(_required_text(payload["status"])),
        reason=_required_text(payload["reason"]),
        trace_id=_required_text(payload["trace_id"]),
        thesis_id=_optional_text(payload["thesis_id"]),
        intent_id=_optional_text(payload["intent_id"]),
        episode_id=_optional_text(payload["episode_id"]),
        role_event_ids=_text_tuple(payload["role_event_ids"]),
    )


def _reconciliation_payload(report: ReconciliationReport) -> dict[str, object]:
    return {
        "snapshot_id": report.snapshot_id,
        "clean": report.clean,
        "issues": list(report.issues),
        "observed_at": report.observed_at.isoformat(),
        "broker_snapshot_event_id": report.broker_snapshot_event_id,
        "kernel_event_id": report.kernel_event_id,
        "evidence_event_id": report.evidence_event_id,
    }


def _reconciliation_from_payload(payload: object) -> ReconciliationReport:
    keys = {
        "snapshot_id",
        "clean",
        "issues",
        "observed_at",
        "broker_snapshot_event_id",
        "kernel_event_id",
        "evidence_event_id",
    }
    if not isinstance(payload, Mapping) or set(payload) != keys:
        raise TypeError
    return ReconciliationReport(
        snapshot_id=_required_text(payload["snapshot_id"]),
        clean=_required_bool(payload["clean"]),
        issues=_text_tuple(payload["issues"]),
        observed_at=_parse_aware_text(payload["observed_at"]),
        broker_snapshot_event_id=_required_text(
            payload["broker_snapshot_event_id"]
        ),
        kernel_event_id=_required_text(payload["kernel_event_id"]),
        evidence_event_id=_required_text(payload["evidence_event_id"]),
    )


def _halt_reasons(
    truth: SessionTruth,
    *,
    reconciliation: ReconciliationReport,
    account_valid: bool,
    health_valid: bool,
    safety: SafetyState,
    now: datetime,
    maximum_account_age: timedelta,
    maximum_health_age: timedelta,
) -> tuple[str, ...]:
    reasons: list[str] = []
    account = truth.account_snapshot
    if not account.has_valid_identity():
        reasons.append("ACCOUNT_SNAPSHOT_IDENTITY_INVALID")
    if not account_valid:
        reasons.append("ACCOUNT_EVIDENCE_INVALID")
    if not account.reconciled:
        reasons.append("ACCOUNT_SNAPSHOT_UNRECONCILED")
    account_age = now - account.captured_at
    if account_age < timedelta(0):
        reasons.append("ACCOUNT_SNAPSHOT_FUTURE")
    elif account_age > maximum_account_age:
        reasons.append("ACCOUNT_SNAPSHOT_STALE")
    health_age = now - truth.operational_health.assessed_at
    if health_age < timedelta(0):
        reasons.append("OPERATIONAL_HEALTH_FUTURE")
    elif health_age > maximum_health_age:
        reasons.append("OPERATIONAL_HEALTH_STALE")
    if not reconciliation.clean:
        reasons.append("RECONCILIATION_MISMATCH")
    if not health_valid:
        reasons.append("HEALTH_EVIDENCE_INVALID")
    elif not truth.operational_health.new_entries_allowed:
        reasons.extend(
            truth.operational_health.reason_codes or ("OPERATIONS_NOT_READY",)
        )
    if safety.latched:
        reasons.append("SAFETY_LATCHED")
        reasons.extend(reason.reason_code for reason in safety.reasons)
    return tuple(dict.fromkeys(reasons))


def _cycle_truth_reasons(
    pending: tuple[object, ...],
    truth: SessionTruth,
) -> tuple[str, ...]:
    reasons: list[str] = []
    authorized = set(truth.authorized_cycle_request_ids)
    observed: set[str] = set()
    for cycle in pending:
        if not isinstance(cycle, DeskCycleRequest):
            reasons.append("CYCLE_REQUEST_INVALID")
            continue
        direct_mismatch = False
        if cycle.account_snapshot != truth.account_snapshot:
            reasons.append("CYCLE_ACCOUNT_TRUTH_MISMATCH")
            direct_mismatch = True
        if cycle.operational_health != truth.operational_health:
            reasons.append("CYCLE_HEALTH_TRUTH_MISMATCH")
            direct_mismatch = True
        if direct_mismatch:
            continue
        request_id = desk_cycle_request_id(cycle)
        if request_id in observed:
            reasons.append("CYCLE_REQUEST_DUPLICATE")
        observed.add(request_id)
        if request_id not in authorized:
            reasons.append("CYCLE_REQUEST_TRUTH_MISMATCH")
    return tuple(dict.fromkeys(reasons))


def _cycle_time_reasons(
    cycle: object,
    *,
    now: datetime,
    maximum_skew: timedelta,
) -> tuple[str, ...]:
    if not isinstance(cycle, DeskCycleRequest):
        return ("CYCLE_REQUEST_INVALID",)
    if abs(now - cycle.now) > maximum_skew:
        return ("CYCLE_TIME_SKEW",)
    return ()


def _validate_control_stream(events: Sequence[JournalEvent]) -> None:
    seen: set[str] = set()
    for event in events:
        if event.idempotency_key in seen:
            raise SupervisorStartupError("SHUTDOWN_EVENT_INVALID")
        seen.add(event.idempotency_key)
        _shutdown_from_event(event)


def _shutdown_from_event(
    event: JournalEvent,
    *,
    expected: SupervisorShutdownRequest | None = None,
) -> SupervisorShutdown:
    try:
        if (
            event.stream_id != _CONTROL_STREAM
            or event.event_type != "DeskSupervisorStopped"
            or event.schema_version != 1
            or event.correlation_id is not None
            or not event.idempotency_key.startswith("desk-supervisor-shutdown:")
            or set(event.payload) != {"mode", "reason", "requested_at"}
            or event.payload["mode"] != "paper"
        ):
            raise ValueError
        reason = _required_text(event.payload["reason"])
        requested_at = _parse_aware_text(event.payload["requested_at"])
        if expected is not None and (
            event.idempotency_key
            != "desk-supervisor-shutdown:" + _digest(expected.command_id)
            or reason != expected.reason.strip()
            or requested_at != expected.now
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise SupervisorStartupError("SHUTDOWN_EVENT_INVALID") from None
    return SupervisorShutdown(
        event_id=event.event_id,
        stopped_at=event.occurred_at,
        reason=reason,
    )


def _required_list(value: object) -> tuple[object, ...]:
    # OperationalJournal deliberately deep-freezes JSON arrays as tuples.
    if not isinstance(value, tuple):
        raise TypeError
    return value


def _text_tuple(value: object) -> tuple[str, ...]:
    values = _required_list(value)
    return tuple(_required_text(item) for item in values)


def _required_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    return _required_text(value)


def _required_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise TypeError
    return value


def _strict_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError
    return value


def _strict_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) for key in value
    ):
        raise TypeError
    return value


def _strict_sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(
        value,
        Sequence,
    ):
        raise TypeError
    return tuple(value)


def _required_event_id(value: object) -> str:
    event_id = _required_text(value)
    if _EVENT_ID.fullmatch(event_id) is None:
        raise ValueError
    return event_id


def _parse_aware_text(value: object) -> datetime:
    text = _required_text(value)
    parsed = datetime.fromisoformat(text)
    _require_aware(parsed, "timestamp")
    return parsed


def _require_aware(value: object, label: str) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{label} must be timezone-aware")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _acquire_lease(journal_path: Path) -> BinaryIO:
    try:
        journal_stat = journal_path.stat()
    except OSError:
        raise SupervisorStartupError("JOURNAL_MISSING") from None
    lease_root = Path(gettempdir()) / f"sensei-supervisor-locks-{os.getuid()}"
    lease_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    lease_path = lease_root / (
        f"{journal_stat.st_dev:x}-{journal_stat.st_ino:x}.lock"
    )
    lease = lease_path.open("a+b")
    try:
        fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lease.close()
        raise SupervisorStartupError("SUPERVISOR_LEASE_UNAVAILABLE") from None
    return lease


def _release_lease(lease: BinaryIO) -> None:
    if lease.closed:
        return
    try:
        fcntl.flock(lease.fileno(), fcntl.LOCK_UN)
    finally:
        lease.close()
