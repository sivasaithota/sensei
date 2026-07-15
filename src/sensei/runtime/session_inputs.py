"""Authenticated, bounded inputs for one governed paper Desk session."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from sensei.kernel import (
    BrokerSnapshot,
    BrokerSnapshotAuthority,
    RecordingPaperGateway,
)
from sensei.operations import (
    ComponentState,
    HmacFactSigner,
    OperationalJournal,
    OperationsControlPlane,
)
from sensei.operations.health import (
    HealthAssessmentInput,
    OperationalHealth,
    OperationsMonitor,
)
from sensei.operations.supervisor import SessionTruth
from sensei.orchestration import DeskCycleRequest, desk_cycle_request_id
from sensei.portfolio_risk import (
    AccountSnapshot,
    AccountSnapshotAuthority,
    SafetyControl,
    SafetyState,
)
from sensei.portfolio_risk.models import require_timestamp

from .account import PaperAccountProjector


class PaperSessionTruthError(RuntimeError):
    """The current runtime facts cannot safely authorize prepared work."""


@dataclass(frozen=True)
class ComponentCheckResult:
    """One component's actual check result; no health state is inferred."""

    state: ComponentState
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.state, ComponentState):
            raise TypeError("component check state must be a ComponentState")
        if not isinstance(self.detail, str) or not self.detail.strip():
            raise ValueError("component check detail must not be blank")


class MarkPriceSource(Protocol):
    def __call__(
        self,
        *,
        instrument_ids: tuple[str, ...],
        now: datetime,
    ) -> Mapping[str, int]: ...


class ComponentCheck(Protocol):
    def __call__(self, *, now: datetime) -> ComponentCheckResult: ...


class PaperCycleBuilder(Protocol):
    def __call__(
        self,
        *,
        account_snapshot: AccountSnapshot,
        operational_health: OperationalHealth,
        now: datetime,
        command_id: str,
    ) -> DeskCycleRequest | None: ...


@dataclass(frozen=True)
class PreparedPaperSession:
    truth: SessionTruth
    request: DeskCycleRequest | None
    request_id: str | None
    prepared_at: datetime


@dataclass(frozen=True)
class _ObservedInputs:
    broker_snapshot: BrokerSnapshot
    mark_prices_paise: tuple[tuple[str, int], ...]
    component_results: tuple[tuple[str, ComponentCheckResult], ...]
    safety_state: SafetyState


@dataclass(frozen=True)
class _AuthenticatedInputs:
    account_snapshot: AccountSnapshot
    account_snapshot_event_id: str
    operational_health: OperationalHealth
    broker_snapshot: BrokerSnapshot
    broker_snapshot_event_id: str


@dataclass
class _PreparedState:
    truth: SessionTruth
    request: DeskCycleRequest | None
    request_id: str | None
    observed: _ObservedInputs
    pinned_at: datetime
    cycle_builder: PaperCycleBuilder
    pending_issued: bool = False


class PaperSessionInputs:
    """Prepare and recheck exact truth for one bounded Supervisor session.

    The Supervisor requires a pending request to contain the same AccountSnapshot
    and OperationalHealth objects returned by its later pre-dispatch capture.
    This adapter therefore pins authenticated objects only while fresh and while
    current broker, mark and component checks remain unchanged.  Any change after
    a request is issued refreshes truth and removes its authorization, causing the
    Supervisor to reject that stale request.
    """

    def __init__(
        self,
        *,
        journal: OperationalJournal,
        gateway: RecordingPaperGateway,
        account_projector: PaperAccountProjector,
        mark_price_source: MarkPriceSource,
        account_authority: AccountSnapshotAuthority,
        account_signer: HmacFactSigner,
        broker_authority: BrokerSnapshotAuthority,
        broker_signer: HmacFactSigner,
        control_plane: OperationsControlPlane,
        operations_monitor: OperationsMonitor,
        safety: SafetyControl,
        required_components: Mapping[str, timedelta],
        component_checks: Mapping[str, ComponentCheck],
        component_signers: Mapping[str, HmacFactSigner],
        maximum_pin_age: timedelta,
    ) -> None:
        exact_types = (
            ("journal", journal, OperationalJournal),
            ("gateway", gateway, RecordingPaperGateway),
            ("account_projector", account_projector, PaperAccountProjector),
            ("account_authority", account_authority, AccountSnapshotAuthority),
            ("account_signer", account_signer, HmacFactSigner),
            ("broker_authority", broker_authority, BrokerSnapshotAuthority),
            ("broker_signer", broker_signer, HmacFactSigner),
            ("control_plane", control_plane, OperationsControlPlane),
            ("operations_monitor", operations_monitor, OperationsMonitor),
            ("safety", safety, SafetyControl),
        )
        for label, value, expected_type in exact_types:
            if type(value) is not expected_type:
                raise TypeError(f"{label} must use the exact {expected_type.__name__}")
        if not gateway.is_bound_to_journal(journal):
            raise ValueError("paper gateway must use the runtime journal durably")
        if not account_projector.is_bound_to_gateway(gateway):
            raise ValueError("account projector must use the runtime gateway")
        if not account_authority.is_bound_to_journal(journal):
            raise ValueError("account authority must use the runtime journal")
        if not broker_authority.is_bound_to_journal(journal):
            raise ValueError("broker authority must use the runtime journal")
        if not control_plane.is_bound_to_journal(journal):
            raise ValueError("control plane must use the runtime journal")
        if not operations_monitor.is_bound_to_journal(journal):
            raise ValueError("operations monitor must use the runtime journal")
        if not safety.is_bound_to_journal(journal):
            raise ValueError("safety control must use the runtime journal")
        if getattr(operations_monitor, "_control_plane", None) is not control_plane:
            raise ValueError("operations monitor must use the runtime control plane")
        if getattr(operations_monitor, "_safety_reset_authority", None) is not getattr(
            safety,
            "_reset_authority",
            None,
        ):
            raise ValueError(
                "operations monitor and safety control must share reset authority"
            )
        if not callable(mark_price_source):
            raise TypeError("mark_price_source must be callable")
        if maximum_pin_age <= timedelta(0):
            raise ValueError("maximum_pin_age must be positive")

        required = dict(required_components)
        checks = dict(component_checks)
        signers = dict(component_signers)
        if (
            not required
            or set(required) != set(checks)
            or set(required) != set(signers)
        ):
            raise ValueError(
                "required components, checks and signers must have identical keys"
            )
        if any(maximum_age <= timedelta(0) for maximum_age in required.values()):
            raise ValueError("required component maximum ages must be positive")
        for component, check in checks.items():
            if not callable(check):
                raise TypeError(f"component check {component!r} must be callable")
            signer = signers[component]
            if type(signer) is not HmacFactSigner or signer.issuer_id != component:
                raise ValueError(
                    f"component signer {component!r} must sign its own heartbeat"
                )

        self._journal = journal
        self._gateway = gateway
        self._account_projector = account_projector
        self._mark_price_source = mark_price_source
        self._account_authority = account_authority
        self._account_signer = account_signer
        self._broker_authority = broker_authority
        self._broker_signer = broker_signer
        self._control_plane = control_plane
        self._operations_monitor = operations_monitor
        self._safety = safety
        self._required_components = required
        self._component_checks = checks
        self._component_signers = signers
        self._maximum_pin_age = maximum_pin_age
        self._prepared: _PreparedState | None = None

    def prepare(
        self,
        *,
        now: datetime,
        command_id: str,
        cycle_builder: PaperCycleBuilder,
    ) -> PreparedPaperSession:
        self._validate_call(now=now, command_id=command_id)
        if self._prepared is not None:
            raise PaperSessionTruthError("a paper session is already prepared")
        if not callable(cycle_builder):
            raise TypeError("cycle_builder must be callable")
        observed = self._observe(now)
        authenticated = self._authenticate(
            observed,
            now=now,
            command_id=command_id,
        )
        request = self._build_request(
            authenticated,
            now=now,
            command_id=command_id,
            cycle_builder=cycle_builder,
        )
        truth, request_id = _session_truth(authenticated, request)
        self._prepared = _PreparedState(
            truth=truth,
            request=request,
            request_id=request_id,
            observed=observed,
            pinned_at=now,
            cycle_builder=cycle_builder,
        )
        return PreparedPaperSession(
            truth=truth,
            request=request,
            request_id=request_id,
            prepared_at=now,
        )

    def capture(self, *, now: datetime, command_id: str) -> SessionTruth:
        self._validate_call(now=now, command_id=command_id)
        prepared = self._require_prepared()
        age = now - prepared.pinned_at
        if age < timedelta(0):
            raise PaperSessionTruthError("capture cannot precede prepared truth")
        observed = self._observe(now)
        if age <= self._maximum_pin_age and _same_observation(
            prepared.observed,
            observed,
        ):
            return prepared.truth

        authenticated = self._authenticate(
            observed,
            now=now,
            command_id=command_id,
        )
        request = None
        if not prepared.pending_issued:
            request = self._build_request(
                authenticated,
                now=now,
                command_id=command_id,
                cycle_builder=prepared.cycle_builder,
            )
        truth, request_id = _session_truth(authenticated, request)
        self._prepared = _PreparedState(
            truth=truth,
            request=request,
            request_id=request_id,
            observed=observed,
            pinned_at=now,
            cycle_builder=prepared.cycle_builder,
            pending_issued=prepared.pending_issued,
        )
        return truth

    def pending(self, *, now: datetime) -> tuple[DeskCycleRequest, ...]:
        require_timestamp(now, "now")
        prepared = self._require_prepared()
        age = now - prepared.pinned_at
        if age < timedelta(0) or age > self._maximum_pin_age:
            raise PaperSessionTruthError(
                "prepared truth must be captured before polling cycles"
            )
        if prepared.pending_issued:
            return ()
        if prepared.request is None:
            return ()
        prepared.pending_issued = True
        return (prepared.request,)

    def _observe(self, now: datetime) -> _ObservedInputs:
        broker_snapshot = self._gateway.broker_snapshot(captured_at=now)
        instrument_ids = tuple(
            position.instrument_id for position in broker_snapshot.positions
        )
        raw_marks = self._mark_price_source(
            instrument_ids=instrument_ids,
            now=now,
        )
        if not isinstance(raw_marks, Mapping):
            raise TypeError("mark price source must return a mapping")
        if set(raw_marks) != set(instrument_ids):
            raise PaperSessionTruthError(
                "mark price source must return exactly the held instruments"
            )
        marks = tuple(sorted((str(key), value) for key, value in raw_marks.items()))

        results: list[tuple[str, ComponentCheckResult]] = []
        for component in sorted(self._required_components):
            result = self._component_checks[component](now=now)
            if type(result) is not ComponentCheckResult:
                raise TypeError(
                    f"component check {component!r} returned an invalid result"
                )
            results.append((component, result))
        return _ObservedInputs(
            broker_snapshot=broker_snapshot,
            mark_prices_paise=marks,
            component_results=tuple(results),
            safety_state=self._safety.state(),
        )

    def _authenticate(
        self,
        observed: _ObservedInputs,
        *,
        now: datetime,
        command_id: str,
    ) -> _AuthenticatedInputs:
        broker_evidence = self._broker_authority.record(
            observed.broker_snapshot,
            signer=self._broker_signer,
            occurred_at=now,
            command_id=f"{command_id}:broker",
        )
        account_snapshot = self._account_projector.project_broker_snapshot(
            observed.broker_snapshot,
            mark_prices_paise=dict(observed.mark_prices_paise),
        )
        account_evidence = self._account_authority.record(
            account_snapshot,
            signer=self._account_signer,
            occurred_at=now,
            command_id=f"{command_id}:account",
        )
        for component, result in observed.component_results:
            self._control_plane.record_heartbeat(
                component=component,
                state=result.state,
                occurred_at=now,
                command_id=f"{command_id}:heartbeat:{component}",
                detail=result.detail,
                signer=self._component_signers[component],
            )
        readiness = self._control_plane.assess_readiness(
            required_components=self._required_components,
            now=now,
            command_id=f"{command_id}:readiness",
        )
        health = self._operations_monitor.assess(
            HealthAssessmentInput(now=now, readiness=readiness),
            command_id=f"{command_id}:health",
        )
        if not self._broker_authority.verify(
            broker_evidence.event_id,
            snapshot=observed.broker_snapshot,
            no_later_than=now,
        ):
            raise PaperSessionTruthError("broker snapshot authentication failed")
        if not self._account_authority.verify(
            account_evidence.event_id,
            snapshot=account_snapshot,
            no_later_than=now,
        ):
            raise PaperSessionTruthError("account snapshot authentication failed")
        if not self._operations_monitor.verify(health, no_later_than=now):
            raise PaperSessionTruthError("operational health authentication failed")
        return _AuthenticatedInputs(
            account_snapshot=account_snapshot,
            account_snapshot_event_id=account_evidence.event_id,
            operational_health=health,
            broker_snapshot=observed.broker_snapshot,
            broker_snapshot_event_id=broker_evidence.event_id,
        )

    @staticmethod
    def _build_request(
        authenticated: _AuthenticatedInputs,
        *,
        now: datetime,
        command_id: str,
        cycle_builder: PaperCycleBuilder,
    ) -> DeskCycleRequest | None:
        if not authenticated.operational_health.new_entries_allowed:
            return None
        request = cycle_builder(
            account_snapshot=authenticated.account_snapshot,
            operational_health=authenticated.operational_health,
            now=now,
            command_id=command_id,
        )
        if request is None:
            return None
        if not isinstance(request, DeskCycleRequest):
            raise TypeError("cycle_builder must return one DeskCycleRequest or None")
        if (
            request.account_snapshot is not authenticated.account_snapshot
            or request.operational_health is not authenticated.operational_health
        ):
            raise PaperSessionTruthError(
                "cycle builder must use the exact authenticated account and health"
            )
        if request.now != now:
            raise PaperSessionTruthError(
                "cycle builder must bind the exact preparation time"
            )
        return request

    @staticmethod
    def _validate_call(*, now: datetime, command_id: str) -> None:
        require_timestamp(now, "now")
        if not isinstance(command_id, str) or not command_id.strip():
            raise ValueError("command_id is required")

    def _require_prepared(self) -> _PreparedState:
        if self._prepared is None:
            raise PaperSessionTruthError("paper session inputs are not prepared")
        return self._prepared


def _session_truth(
    authenticated: _AuthenticatedInputs,
    request: DeskCycleRequest | None,
) -> tuple[SessionTruth, str | None]:
    request_id = desk_cycle_request_id(request) if request is not None else None
    return (
        SessionTruth(
            account_snapshot=authenticated.account_snapshot,
            account_snapshot_event_id=authenticated.account_snapshot_event_id,
            operational_health=authenticated.operational_health,
            broker_snapshot=authenticated.broker_snapshot,
            broker_snapshot_event_id=authenticated.broker_snapshot_event_id,
            authorized_cycle_request_ids=(request_id,) if request_id else (),
        ),
        request_id,
    )


def _same_observation(left: _ObservedInputs, right: _ObservedInputs) -> bool:
    return (
        left.broker_snapshot.positions == right.broker_snapshot.positions
        and left.broker_snapshot.protections == right.broker_snapshot.protections
        and left.broker_snapshot.working_orders
        == right.broker_snapshot.working_orders
        and left.mark_prices_paise == right.mark_prices_paise
        and left.component_results == right.component_results
        and left.safety_state == right.safety_state
    )
