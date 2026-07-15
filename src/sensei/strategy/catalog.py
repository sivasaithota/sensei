"""Immutable, journal-backed catalog of exact canonical Strategy Plans."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from sensei.governance.lifecycle import LifecycleStage, StrategyLifecycle
from sensei.operations import (
    EventAppend,
    JournalEvent,
    JournalIntegrityError,
    OperationalJournal,
)

from .models import StrategyPlan

_PLAN_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_EVENT_TYPE = "StrategyPlanRegistered"
_PAYLOAD_KEYS = frozenset(
    {
        "schema_version",
        "authority",
        "can_authorize_lifecycle",
        "can_authorize_trading",
        "plan_id",
        "lineage_id",
        "source_rule_name",
        "plan",
    }
)


@dataclass(frozen=True)
class StrategyPlanRecord:
    plan_id: str
    lineage_id: str
    source_rule_name: str
    plan: StrategyPlan
    registered_at: datetime
    event_id: str


class StrategyPlanCatalog:
    """Register and reconstruct exact plans through one durable interface."""

    def __init__(self, journal: OperationalJournal) -> None:
        self._journal = journal

    def is_bound_to_journal(self, journal: OperationalJournal) -> bool:
        return self._journal is journal

    def register(
        self,
        *,
        lineage_id: str,
        plan: StrategyPlan,
        source_rule_name: str,
        occurred_at: datetime,
        command_id: str,
    ) -> StrategyPlanRecord:
        if not isinstance(plan, StrategyPlan):
            raise TypeError("plan must be a StrategyPlan")
        lineage_id = _required_text(lineage_id, "lineage_id")
        source_rule_name = _required_text(source_rule_name, "source_rule_name")
        command_id = _required_text(command_id, "command_id")
        _aware(occurred_at)

        existing = self.get(plan.plan_id)
        if existing is not None:
            exact = (
                existing.lineage_id == lineage_id
                and existing.source_rule_name == source_rule_name
                and existing.plan.model_dump(mode="json")
                == plan.model_dump(mode="json")
            )
            if not exact:
                raise JournalIntegrityError(
                    "immutable plan registration conflicts with retained metadata"
                )
            return existing

        payload = {
            "schema_version": "1.0",
            "authority": "REGISTRATION_ONLY",
            "can_authorize_lifecycle": False,
            "can_authorize_trading": False,
            "plan_id": plan.plan_id,
            "lineage_id": lineage_id,
            "source_rule_name": source_rule_name,
            "plan": plan.model_dump(mode="json"),
        }
        event = self._journal.append(
            EventAppend(
                stream_id=_plan_stream(plan.plan_id),
                event_type=_EVENT_TYPE,
                payload=payload,
                idempotency_key="strategy-plan:" + _digest(command_id),
                expected_version=0,
                occurred_at=occurred_at,
                correlation_id=plan.plan_id,
            )
        )
        return _record_from_event(event)

    def get(self, plan_id: str) -> StrategyPlanRecord | None:
        _validate_plan_id(plan_id)
        records = tuple(
            record for record in self.list() if record.plan_id == plan_id
        )
        if len(records) > 1:
            raise JournalIntegrityError("duplicate canonical plan registration")
        return records[0] if records else None

    def list(self) -> tuple[StrategyPlanRecord, ...]:
        verification = self._journal.verify()
        if not verification.ok:
            raise JournalIntegrityError(
                "strategy plan catalog journal integrity verification failed"
            )
        return tuple(
            _record_from_event(event)
            for event in self._journal.read_all()
            if event.event_type == _EVENT_TYPE
        )

    def plans_at_stage(
        self,
        lifecycle: StrategyLifecycle,
        stage: LifecycleStage,
    ) -> tuple[StrategyPlanRecord, ...]:
        if not isinstance(lifecycle, StrategyLifecycle):
            raise TypeError("lifecycle must be a StrategyLifecycle")
        if not isinstance(stage, LifecycleStage):
            raise TypeError("stage must be a LifecycleStage")
        if not lifecycle.is_bound_to_journal(self._journal):
            raise ValueError("plan catalog and lifecycle must share one journal")

        eligible: list[StrategyPlanRecord] = []
        for record in self.list():
            view = lifecycle.view(record.lineage_id)
            try:
                current = view.stage_for(record.plan_id)
            except KeyError:
                continue
            if current is stage:
                eligible.append(record)
        return tuple(eligible)


def _record_from_event(event: JournalEvent) -> StrategyPlanRecord:
    if event.event_type != _EVENT_TYPE:
        raise JournalIntegrityError("journal event is not a strategy plan registration")
    payload = event.payload
    if frozenset(payload) != _PAYLOAD_KEYS:
        raise JournalIntegrityError("strategy plan registration payload is invalid")
    if (
        payload.get("schema_version") != "1.0"
        or payload.get("authority") != "REGISTRATION_ONLY"
        or payload.get("can_authorize_lifecycle") is not False
        or payload.get("can_authorize_trading") is not False
    ):
        raise JournalIntegrityError("strategy plan registration authority is invalid")
    try:
        plan = StrategyPlan.model_validate_json(
            json.dumps(_plain(payload["plan"]), sort_keys=True, allow_nan=False)
        )
        plan_id = str(payload["plan_id"])
        lineage_id = _required_text(str(payload["lineage_id"]), "lineage_id")
        source_rule_name = _required_text(
            str(payload["source_rule_name"]), "source_rule_name"
        )
        _validate_plan_id(plan_id)
    except (KeyError, TypeError, ValueError) as exc:
        raise JournalIntegrityError("strategy plan registration content is invalid") from exc
    if (
        plan.plan_id != plan_id
        or event.stream_id != _plan_stream(plan_id)
        or event.correlation_id != plan_id
        or event.stream_sequence != 1
    ):
        raise JournalIntegrityError("strategy plan registration identity is invalid")
    return StrategyPlanRecord(
        plan_id=plan_id,
        lineage_id=lineage_id,
        source_rule_name=source_rule_name,
        plan=plan,
        registered_at=event.occurred_at,
        event_id=event.event_id,
    )


def _plan_stream(plan_id: str) -> str:
    _validate_plan_id(plan_id)
    return "strategy-plan:" + plan_id.removeprefix("sha256:")


def _validate_plan_id(plan_id: str) -> None:
    if not isinstance(plan_id, str) or _PLAN_ID.fullmatch(plan_id) is None:
        raise ValueError("plan_id must be a lowercase SHA-256 content identity")


def _required_text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must not be blank")
    return value.strip()


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("occurred_at must be timezone-aware")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(child) for child in value]
    return value
