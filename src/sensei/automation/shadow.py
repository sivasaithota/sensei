"""Forward-only shadow observation and readiness assessment.

Shadow data is accumulated only after the exact plan reaches SHADOW.  The
module evaluates canonical StrategyPlan semantics and records every expected
instrument, including missing/error outcomes, so data gaps cannot disappear
from the readiness denominator.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from sensei.governance.lifecycle import LifecycleStage, StrategyLifecycle
from sensei.operations import (
    EventAppend,
    JournalIntegrityError,
    OperationalJournal,
)
from sensei.strategy import (
    DecisionAction,
    PlanDecisionTrace,
    PlanEvaluationRequest,
    PlanInputError,
    StrategyPlanEngine,
    StrategyPlanRecord,
)


_IST = ZoneInfo("Asia/Kolkata")
_CONTENT_ID = re.compile(r"(?:sha256|snapshot):[0-9a-f]{64}\Z")
_PLAN_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_ERROR_CODE = re.compile(r"[A-Z][A-Z0-9_]{2,95}\Z")
_EVENT_TYPE = "ShadowSessionObserved"


@dataclass(frozen=True)
class ShadowInstrumentEvaluation:
    instrument_id: str
    trace: PlanDecisionTrace | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not self.instrument_id.strip():
            raise ValueError("shadow instrument_id is required")
        if (self.trace is None) == (self.error_code is None):
            raise ValueError("shadow evaluation needs exactly one trace or error")
        if self.trace is not None and not isinstance(self.trace, PlanDecisionTrace):
            raise TypeError("shadow trace must be a PlanDecisionTrace")
        if self.error_code is not None and _ERROR_CODE.fullmatch(
            self.error_code
        ) is None:
            raise ValueError("shadow error_code is invalid")

    def to_payload(self) -> dict[str, object]:
        return {
            "instrument_id": self.instrument_id,
            "trace": (
                self.trace.model_dump(mode="json")
                if self.trace is not None
                else None
            ),
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class ShadowSessionObservation:
    lineage_id: str
    plan_id: str
    evaluation_session: date
    market_snapshot_id: str
    shadow_started_at: datetime
    observed_at: datetime
    evaluations: tuple[ShadowInstrumentEvaluation, ...]

    def __post_init__(self) -> None:
        if not self.lineage_id.strip():
            raise ValueError("shadow lineage_id is required")
        if _PLAN_ID.fullmatch(self.plan_id) is None:
            raise ValueError("shadow plan_id must be content-addressed")
        if type(self.evaluation_session) is not date:
            raise TypeError("evaluation_session must be a date")
        if _CONTENT_ID.fullmatch(self.market_snapshot_id) is None:
            raise ValueError("market_snapshot_id must be content-addressed")
        _aware(self.shadow_started_at, "shadow_started_at")
        _aware(self.observed_at, "observed_at")
        if self.evaluation_session <= self.shadow_started_at.astimezone(_IST).date():
            raise ValueError("shadow evidence must use forward sessions only")
        if self.observed_at.astimezone(_IST).date() < self.evaluation_session:
            raise ValueError("shadow observation cannot precede its session")
        evaluations = tuple(sorted(self.evaluations, key=lambda item: item.instrument_id))
        if not evaluations:
            raise ValueError("shadow session needs expected instruments")
        if len({item.instrument_id for item in evaluations}) != len(evaluations):
            raise ValueError("shadow instruments must be unique")
        for evaluation in evaluations:
            if (
                evaluation.trace is not None
                and evaluation.trace.plan_id != self.plan_id
            ):
                raise ValueError("shadow trace belongs to another plan")
            if (
                evaluation.trace is not None
                and evaluation.trace.instrument_id != evaluation.instrument_id
            ):
                raise ValueError("shadow trace belongs to another instrument")
            if (
                evaluation.trace is not None
                and evaluation.trace.evaluation_session
                != self.evaluation_session.isoformat()
            ):
                raise ValueError("shadow trace belongs to another session")
        object.__setattr__(self, "evaluations", evaluations)

    def semantic_payload(self) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "authority": "SHADOW_OBSERVATION_ONLY",
            "lineage_id": self.lineage_id,
            "plan_id": self.plan_id,
            "evaluation_session": self.evaluation_session.isoformat(),
            "market_snapshot_id": self.market_snapshot_id,
            "shadow_started_at": self.shadow_started_at.astimezone(
                timezone.utc
            ).isoformat(),
            "evaluations": [item.to_payload() for item in self.evaluations],
        }


@dataclass(frozen=True)
class ShadowSessionRecord:
    observation: ShadowSessionObservation
    event_id: str


@dataclass(frozen=True)
class ShadowTrialPolicy:
    minimum_sessions: int = 5
    minimum_signals: int = 0
    minimum_signal_instruments: int = 0
    minimum_data_completeness: float = 0.99
    require_zero_errors: bool = True

    def __post_init__(self) -> None:
        if type(self.minimum_sessions) is not int or self.minimum_sessions < 1:
            raise ValueError("minimum_sessions must be a positive integer")
        for label, value in (
            ("minimum_signals", self.minimum_signals),
            ("minimum_signal_instruments", self.minimum_signal_instruments),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{label} must be a non-negative integer")
        if (
            not math.isfinite(self.minimum_data_completeness)
            or not 0 < self.minimum_data_completeness <= 1
        ):
            raise ValueError("minimum_data_completeness must be in (0, 1]")
        if not isinstance(self.require_zero_errors, bool):
            raise TypeError("require_zero_errors must be a boolean")

    def to_payload(self) -> dict[str, object]:
        return {
            "minimum_sessions": self.minimum_sessions,
            "minimum_signals": self.minimum_signals,
            "minimum_signal_instruments": self.minimum_signal_instruments,
            "minimum_data_completeness": self.minimum_data_completeness,
            "require_zero_errors": self.require_zero_errors,
        }


@dataclass(frozen=True)
class ShadowTrialAssessment:
    lineage_id: str
    plan_id: str
    policy: ShadowTrialPolicy
    assessed_at: datetime
    sessions: int
    expected_evaluations: int
    successful_evaluations: int
    signals: int
    signal_instruments: int
    data_completeness: float
    error_count: int
    conformance_failures: int
    passed: bool
    reason_codes: tuple[str, ...]
    supporting_event_ids: tuple[str, ...]

    def to_artifact(self) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "assessment_type": "canonical_forward_shadow_trial",
            "lineage_id": self.lineage_id,
            "plan_id": self.plan_id,
            "policy": self.policy.to_payload(),
            "assessed_at": self.assessed_at.astimezone(timezone.utc).isoformat(),
            "sessions": self.sessions,
            "expected_evaluations": self.expected_evaluations,
            "successful_evaluations": self.successful_evaluations,
            "signals": self.signals,
            "signal_instruments": self.signal_instruments,
            "data_completeness": self.data_completeness,
            "error_count": self.error_count,
            "conformance_failures": self.conformance_failures,
            "passed": self.passed,
            "reason_codes": list(self.reason_codes),
            "supporting_event_ids": list(self.supporting_event_ids),
        }


class ShadowTrialLedger:
    def __init__(self, journal: OperationalJournal) -> None:
        self._journal = journal

    def is_bound_to_journal(self, journal: OperationalJournal) -> bool:
        return self._journal is journal

    def register_policy(
        self,
        *,
        lineage_id: str,
        plan_id: str,
        policy: ShadowTrialPolicy,
        historical_oos: Mapping[str, object],
        occurred_at: datetime,
        command_id: str,
    ) -> str:
        """Pre-register immutable PAPER-readiness criteria before observations."""

        _aware(occurred_at, "occurred_at")
        if not lineage_id.strip() or _PLAN_ID.fullmatch(plan_id) is None:
            raise ValueError("lineage_id and content-addressed plan_id are required")
        if not isinstance(policy, ShadowTrialPolicy):
            raise TypeError("policy must be a ShadowTrialPolicy")
        if not isinstance(historical_oos, Mapping):
            raise TypeError("historical_oos must be a mapping")
        if not command_id.strip():
            raise ValueError("command_id is required")
        payload = {
            "lineage_id": lineage_id,
            "plan_id": plan_id,
            "paper_only": True,
            "forward_operational_policy": policy.to_payload(),
            "historical_oos": _plain(historical_oos),
        }
        stream = "shadow-trial-policy:" + hashlib.sha256(
            f"{lineage_id}|{plan_id}".encode()
        ).hexdigest()
        existing = self._journal.read_stream(stream)
        if existing:
            if (
                len(existing) != 1
                or existing[0].event_type != "ShadowTrialPolicyRegistered"
                or _canonical(existing[0].payload) != _canonical(payload)
            ):
                raise JournalIntegrityError(
                    "shadow trial policy conflicts with preregistered criteria"
                )
            return existing[0].event_id
        event = self._journal.append(
            EventAppend(
                stream_id=stream,
                event_type="ShadowTrialPolicyRegistered",
                payload=payload,
                idempotency_key="shadow-policy:"
                + hashlib.sha256(command_id.encode()).hexdigest(),
                expected_version=0,
                occurred_at=occurred_at,
                correlation_id=plan_id,
            )
        )
        return event.event_id

    def record_session(
        self,
        observation: ShadowSessionObservation,
        *,
        command_id: str,
    ) -> ShadowSessionRecord:
        if not isinstance(observation, ShadowSessionObservation):
            raise TypeError("observation must be a ShadowSessionObservation")
        if not command_id.strip():
            raise ValueError("command_id is required")
        if not self._journal.verify().ok:
            raise JournalIntegrityError("shadow journal integrity failed")
        stream = _session_stream(
            observation.lineage_id,
            observation.plan_id,
            observation.evaluation_session,
        )
        existing = self._journal.read_stream(stream)
        if existing:
            record = _record_from_events(existing)
            if (
                _canonical(record.observation.semantic_payload())
                != _canonical(observation.semantic_payload())
            ):
                raise JournalIntegrityError(
                    "shadow session identity conflicts with retained evidence"
                )
            return record
        payload = {
            **observation.semantic_payload(),
            "observed_at": observation.observed_at.astimezone(timezone.utc).isoformat(),
        }
        event = self._journal.append(
            EventAppend(
                stream_id=stream,
                event_type=_EVENT_TYPE,
                payload=payload,
                idempotency_key="shadow-session:" + stream.rsplit(":", 1)[-1],
                expected_version=0,
                occurred_at=observation.observed_at,
                correlation_id=observation.plan_id,
            )
        )
        return _record_from_events((event,))

    def sessions(
        self,
        *,
        lineage_id: str,
        plan_id: str,
        no_later_than: datetime,
    ) -> tuple[ShadowSessionRecord, ...]:
        _aware(no_later_than, "no_later_than")
        if not self._journal.verify().ok:
            raise JournalIntegrityError("shadow journal integrity failed")
        records = []
        for event in self._journal.read_all():
            if event.event_type != _EVENT_TYPE or event.occurred_at > no_later_than:
                continue
            record = _record_from_events(
                self._journal.read_stream(event.stream_id)
            )
            if (
                record.observation.lineage_id == lineage_id
                and record.observation.plan_id == plan_id
            ):
                records.append(record)
        return tuple(
            sorted(records, key=lambda item: item.observation.evaluation_session)
        )

    def assess(
        self,
        *,
        lineage_id: str,
        plan_id: str,
        policy: ShadowTrialPolicy,
        no_later_than: datetime,
    ) -> ShadowTrialAssessment:
        if not lineage_id.strip() or _PLAN_ID.fullmatch(plan_id) is None:
            raise ValueError("lineage_id and content-addressed plan_id are required")
        if not isinstance(policy, ShadowTrialPolicy):
            raise TypeError("policy must be a ShadowTrialPolicy")
        records = self.sessions(
            lineage_id=lineage_id,
            plan_id=plan_id,
            no_later_than=no_later_than,
        )
        expected = sum(len(record.observation.evaluations) for record in records)
        successes = 0
        errors = 0
        conformance_failures = 0
        signals = 0
        signal_instruments: set[str] = set()
        for record in records:
            for evaluation in record.observation.evaluations:
                if evaluation.trace is None:
                    errors += 1
                    continue
                successes += 1
                if evaluation.trace.plan_id != plan_id:
                    conformance_failures += 1
                if evaluation.trace.action is DecisionAction.ENTER_LONG:
                    signals += 1
                    signal_instruments.add(evaluation.instrument_id)
        completeness = successes / expected if expected else 0.0
        reasons: list[str] = []
        if len(records) < policy.minimum_sessions:
            reasons.append("SHADOW_SESSIONS_INSUFFICIENT")
        if signals < policy.minimum_signals:
            reasons.append("SHADOW_SIGNALS_INSUFFICIENT")
        if len(signal_instruments) < policy.minimum_signal_instruments:
            reasons.append("SHADOW_SIGNAL_INSTRUMENTS_INSUFFICIENT")
        if completeness < policy.minimum_data_completeness:
            reasons.append("SHADOW_DATA_INCOMPLETE")
        if policy.require_zero_errors and errors:
            reasons.append("SHADOW_EVALUATION_ERRORS")
        if conformance_failures:
            reasons.append("SHADOW_PLAN_CONFORMANCE_FAILED")
        return ShadowTrialAssessment(
            lineage_id=lineage_id,
            plan_id=plan_id,
            policy=policy,
            assessed_at=no_later_than,
            sessions=len(records),
            expected_evaluations=expected,
            successful_evaluations=successes,
            signals=signals,
            signal_instruments=len(signal_instruments),
            data_completeness=round(completeness, 8),
            error_count=errors,
            conformance_failures=conformance_failures,
            passed=not reasons,
            reason_codes=tuple(reasons),
            supporting_event_ids=tuple(record.event_id for record in records),
        )


class CanonicalShadowRunner:
    def __init__(
        self,
        *,
        lifecycle: StrategyLifecycle,
        ledger: ShadowTrialLedger,
        engine: StrategyPlanEngine | None = None,
    ) -> None:
        if not isinstance(lifecycle, StrategyLifecycle):
            raise TypeError("lifecycle must be a StrategyLifecycle")
        if not isinstance(ledger, ShadowTrialLedger):
            raise TypeError("ledger must be a ShadowTrialLedger")
        if not lifecycle.is_bound_to_journal(ledger._journal):
            raise ValueError("shadow lifecycle and ledger must share one journal")
        self._lifecycle = lifecycle
        self._ledger = ledger
        self._engine = engine or StrategyPlanEngine()

    def run_session(
        self,
        *,
        record: StrategyPlanRecord,
        expected_instrument_ids: tuple[str, ...],
        bars_by_instrument: Mapping[str, pd.DataFrame],
        evaluation_session: date,
        market_snapshot_id: str,
        observed_at: datetime,
        command_id: str,
    ) -> ShadowSessionRecord:
        if not isinstance(record, StrategyPlanRecord):
            raise TypeError("record must be a StrategyPlanRecord")
        expected = tuple(sorted(expected_instrument_ids))
        if not expected or len(set(expected)) != len(expected):
            raise ValueError("expected instruments must be nonempty and unique")
        if any(not item.strip() for item in expected):
            raise ValueError("expected instruments must not be blank")
        extras = set(bars_by_instrument) - set(expected)
        if extras:
            raise ValueError("bars contain instruments outside the expected universe")
        view = self._lifecycle.view(record.lineage_id)
        state = next(
            (
                candidate
                for candidate in view.plans
                if candidate.plan_version_id == record.plan_id
            ),
            None,
        )
        if state is None or state.stage is not LifecycleStage.SHADOW:
            raise ValueError("exact plan must be at SHADOW")
        shadow_started_at = state.last_record.occurred_at

        evaluations: list[ShadowInstrumentEvaluation] = []
        for instrument_id in expected:
            bars = bars_by_instrument.get(instrument_id)
            if bars is None:
                evaluations.append(
                    ShadowInstrumentEvaluation(
                        instrument_id=instrument_id,
                        error_code="MARKET_DATA_MISSING",
                    )
                )
                continue
            try:
                trace = self._engine.evaluate(
                    PlanEvaluationRequest(
                        plan=record.plan,
                        instrument_id=instrument_id,
                        bars=bars,
                        evaluation_session=evaluation_session,
                    )
                )
            except Exception as exc:
                code = (
                    "PLAN_INPUT_ERROR"
                    if isinstance(exc, PlanInputError)
                    else "EVALUATION_" + type(exc).__name__.upper()
                )
                if _ERROR_CODE.fullmatch(code) is None:
                    code = "EVALUATION_FAILED"
                evaluations.append(
                    ShadowInstrumentEvaluation(
                        instrument_id=instrument_id,
                        error_code=code,
                    )
                )
            else:
                evaluations.append(
                    ShadowInstrumentEvaluation(
                        instrument_id=instrument_id,
                        trace=trace,
                    )
                )
        observation = ShadowSessionObservation(
            lineage_id=record.lineage_id,
            plan_id=record.plan_id,
            evaluation_session=evaluation_session,
            market_snapshot_id=market_snapshot_id,
            shadow_started_at=shadow_started_at,
            observed_at=observed_at,
            evaluations=tuple(evaluations),
        )
        return self._ledger.record_session(observation, command_id=command_id)


def _record_from_events(events) -> ShadowSessionRecord:
    if len(events) != 1 or events[0].event_type != _EVENT_TYPE:
        raise JournalIntegrityError("shadow session stream is invalid")
    event = events[0]
    payload = event.payload
    expected_keys = {
        "schema_version",
        "authority",
        "lineage_id",
        "plan_id",
        "evaluation_session",
        "market_snapshot_id",
        "shadow_started_at",
        "observed_at",
        "evaluations",
    }
    if set(payload) != expected_keys:
        raise JournalIntegrityError("shadow session payload is invalid")
    try:
        if (
            payload["schema_version"] != "1.0"
            or payload["authority"] != "SHADOW_OBSERVATION_ONLY"
        ):
            raise ValueError
        evaluations = tuple(
            ShadowInstrumentEvaluation(
                instrument_id=str(item["instrument_id"]),
                trace=(
                    PlanDecisionTrace.model_validate_json(
                        json.dumps(_plain(item["trace"]), allow_nan=False)
                    )
                    if item["trace"] is not None
                    else None
                ),
                error_code=(
                    str(item["error_code"])
                    if item["error_code"] is not None
                    else None
                ),
            )
            for item in payload["evaluations"]
        )
        observation = ShadowSessionObservation(
            lineage_id=str(payload["lineage_id"]),
            plan_id=str(payload["plan_id"]),
            evaluation_session=date.fromisoformat(str(payload["evaluation_session"])),
            market_snapshot_id=str(payload["market_snapshot_id"]),
            shadow_started_at=datetime.fromisoformat(str(payload["shadow_started_at"])),
            observed_at=datetime.fromisoformat(str(payload["observed_at"])),
            evaluations=evaluations,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise JournalIntegrityError("shadow session content is invalid") from exc
    if (
        observation.observed_at != event.occurred_at
        or event.stream_id
        != _session_stream(
            observation.lineage_id,
            observation.plan_id,
            observation.evaluation_session,
        )
        or event.correlation_id != observation.plan_id
    ):
        raise JournalIntegrityError("shadow session identity is invalid")
    return ShadowSessionRecord(observation=observation, event_id=event.event_id)


def _session_stream(lineage_id: str, plan_id: str, session: date) -> str:
    material = f"{lineage_id}|{plan_id}|{session.isoformat()}"
    return "shadow-session:" + hashlib.sha256(material.encode()).hexdigest()


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(child) for child in value]
    return value


def _canonical(value: object) -> str:
    return json.dumps(
        _plain(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
