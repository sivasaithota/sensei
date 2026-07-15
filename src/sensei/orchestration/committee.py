"""Durable per-trade L1-L4 committee gate for governed paper admission."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sensei.agents.thesis import ApprovalRecord, Direction
from sensei.operations.journal import EventAppend, JournalEvent, OperationalJournal
from sensei.portfolio_risk import TradeIntent

from .verdicts import CommitteeVerdictAuthority, EXPECTED_COMMITTEE

_CLAIM_ID = re.compile(r"claim:[0-9a-f]{64}\Z")
@dataclass(frozen=True)
class CommitteeApproval:
    approval_id: str
    event_id: str
    thesis_id: str
    intent_id: str
    lineage_id: str
    plan_version_id: str
    decision_trace_id: str
    verdict_evidence_event_ids: tuple[str, ...]


class TradeCommitteeGate:
    """Bind the existing specialized-agent verdicts to one exact trade intent."""

    def __init__(
        self,
        journal: OperationalJournal,
        verdict_authority: CommitteeVerdictAuthority,
    ) -> None:
        self._journal = journal
        self._verdict_authority = verdict_authority

    def is_bound_to_journal(self, journal: OperationalJournal) -> bool:
        """Return whether the gate and its verdict evidence share a journal."""

        return (
            self._journal is journal
            and type(self._verdict_authority) is CommitteeVerdictAuthority
            and CommitteeVerdictAuthority.is_bound_to_journal(
                self._verdict_authority,
                journal,
            )
        )

    def record(
        self,
        approval: ApprovalRecord,
        *,
        intent: TradeIntent,
        lineage_id: str,
        allowed_claim_ids: frozenset[str],
        maximum_holding_sessions: int,
        signal_observed_at: datetime,
        occurred_at: datetime,
        command_id: str,
        verdict_evidence_event_ids: tuple[str, ...],
    ) -> CommitteeApproval:
        if not isinstance(approval, ApprovalRecord):
            raise TypeError("approval must be an ApprovalRecord")
        if not lineage_id.strip() or not command_id.strip():
            raise ValueError("lineage_id and command_id are required")
        _aware(signal_observed_at, "signal_observed_at")
        _aware(occurred_at, "occurred_at")
        if type(maximum_holding_sessions) is not int or maximum_holding_sessions <= 0:
            raise ValueError("maximum_holding_sessions must be positive")
        if not allowed_claim_ids or any(
            _CLAIM_ID.fullmatch(claim_id) is None for claim_id in allowed_claim_ids
        ):
            raise ValueError("allowed claims must be content-addressed")
        self._validate_approval(
            approval,
            intent=intent,
            allowed_claim_ids=allowed_claim_ids,
            maximum_holding_sessions=maximum_holding_sessions,
            signal_observed_at=signal_observed_at,
            occurred_at=occurred_at,
        )
        self._validate_evidence(
            approval,
            verdict_evidence_event_ids=verdict_evidence_event_ids,
            occurred_at=occurred_at,
        )

        thesis_payload = approval.thesis.model_dump(mode="json")
        verdict_payloads = [verdict.model_dump(mode="json") for verdict in approval.verdicts]
        identity = {
            "lineage_id": lineage_id,
            "intent": intent.to_payload(),
            "thesis": thesis_payload,
            "verdicts": verdict_payloads,
            "allowed_claim_ids": sorted(allowed_claim_ids),
            "maximum_holding_sessions": maximum_holding_sessions,
            "signal_observed_at": signal_observed_at.isoformat(),
            "verdict_evidence_event_ids": list(verdict_evidence_event_ids),
        }
        approval_id = "approval:" + _digest(identity)
        payload = {
            "schema_version": "1.0",
            "approval_id": approval_id,
            **identity,
            "verdict_levels": [level for level, _ in EXPECTED_COMMITTEE],
            "authority": "TRADE_ADMISSION_ONLY",
        }
        stream = _stream(intent.intent_id)
        existing = self._journal.read_stream(stream)
        if existing:
            result = _approval_from_event(existing)
            if result.approval_id != approval_id:
                raise ValueError("trade intent already has a different committee decision")
            return result
        event = self._journal.append(
            EventAppend(
                stream_id=stream,
                event_type="TradeCommitteeApproved",
                payload=payload,
                idempotency_key="committee:" + hashlib.sha256(
                    command_id.encode("utf-8")
                ).hexdigest(),
                expected_version=0,
                occurred_at=occurred_at,
                correlation_id=intent.intent_id,
            )
        )
        return _approval_from_event((event,))

    def _validate_evidence(
        self,
        approval: ApprovalRecord,
        *,
        verdict_evidence_event_ids: tuple[str, ...],
        occurred_at: datetime,
    ) -> None:
        if (
            not isinstance(verdict_evidence_event_ids, tuple)
            or len(verdict_evidence_event_ids) != len(EXPECTED_COMMITTEE)
            or len(set(verdict_evidence_event_ids)) != len(EXPECTED_COMMITTEE)
        ):
            raise ValueError("trade requires authenticated L1-L4 evidence")
        for verdict, event_id in zip(
            approval.verdicts, verdict_evidence_event_ids, strict=True
        ):
            if not self._verdict_authority.verify(
                event_id,
                thesis=approval.thesis,
                verdict=verdict,
                no_later_than=occurred_at,
            ):
                raise ValueError("trade requires authenticated L1-L4 evidence")

    @staticmethod
    def _validate_approval(
        approval: ApprovalRecord,
        *,
        intent: TradeIntent,
        allowed_claim_ids: frozenset[str],
        maximum_holding_sessions: int,
        signal_observed_at: datetime,
        occurred_at: datetime,
    ) -> None:
        actual_committee = tuple(
            (verdict.level, verdict.agent) for verdict in approval.verdicts
        )
        if (
            actual_committee != EXPECTED_COMMITTEE
            or not approval.approved
            or any(not verdict.approved for verdict in approval.verdicts)
        ):
            raise ValueError("trade requires exactly four approved L1-L4 verdicts")
        thesis = approval.thesis
        _aware(thesis.created_at, "thesis.created_at")
        if not signal_observed_at <= thesis.created_at <= occurred_at:
            raise ValueError("thesis time must follow the signal and precede approval")
        previous = thesis.created_at
        for verdict in approval.verdicts:
            _aware(verdict.checked_at, f"{verdict.level}.checked_at")
            if not previous <= verdict.checked_at <= occurred_at:
                raise ValueError("committee verdict times must be ordered and not future")
            if not verdict.reasoning.strip():
                raise ValueError("committee verdict reasoning must not be blank")
            previous = verdict.checked_at

        if thesis.direction is not Direction.BUY or intent.side != "BUY":
            raise ValueError("committee and intent must both be long BUY")
        if thesis.symbol != intent.instrument_id:
            raise ValueError("thesis instrument does not match the trade intent")
        if thesis.quantity != intent.quantity:
            raise ValueError("thesis quantity does not match derived intent quantity")
        entry = _money(intent.limit_price_paise)
        if not _decimal(thesis.entry_zone_low) <= entry <= _decimal(
            thesis.entry_zone_high
        ):
            raise ValueError("intent entry lies outside the approved thesis zone")
        if _decimal(thesis.stop_loss) != _money(intent.stop_price_paise):
            raise ValueError("thesis stop does not match the trade intent")
        if not thesis.targets or _decimal(thesis.targets[0]) != _money(
            intent.target_price_paise
        ):
            raise ValueError("thesis target does not match the trade intent")
        if thesis.time_horizon_days != maximum_holding_sessions:
            raise ValueError("thesis horizon does not match the exact plan")
        evidence = tuple(thesis.evidence)
        if (
            not evidence
            or len(set(evidence)) != len(evidence)
            or any(_CLAIM_ID.fullmatch(claim_id) is None for claim_id in evidence)
            or not set(evidence) <= allowed_claim_ids
        ):
            raise ValueError("thesis evidence must use the plan's provenance claims")
        if not any(
            citation.strategy == intent.strategy_plan_id
            for citation in thesis.playbook_citations
        ):
            raise ValueError("thesis must cite the exact strategy plan version")
        for citation in thesis.playbook_citations:
            if not all(
                math.isfinite(value)
                for value in (
                    citation.oos_expectancy_pct,
                    citation.oos_hit_rate,
                )
            ) or citation.oos_trades <= 0:
                raise ValueError("playbook citation statistics must be finite and positive")


def _approval_from_event(events: tuple[JournalEvent, ...]) -> CommitteeApproval:
    if len(events) != 1 or events[0].event_type != "TradeCommitteeApproved":
        raise RuntimeError("trade approval stream is invalid")
    event = events[0]
    payload = event.payload
    if (
        payload.get("schema_version") != "1.0"
        or payload.get("authority") != "TRADE_ADMISSION_ONLY"
    ):
        raise RuntimeError("trade committee approval has invalid authority")
    identity = {
        "lineage_id": payload["lineage_id"],
        "intent": payload["intent"],
        "thesis": payload["thesis"],
        "verdicts": payload["verdicts"],
        "allowed_claim_ids": list(payload["allowed_claim_ids"]),
        "maximum_holding_sessions": payload["maximum_holding_sessions"],
        "signal_observed_at": payload["signal_observed_at"],
        "verdict_evidence_event_ids": list(
            payload["verdict_evidence_event_ids"]
        ),
    }
    approval_id = "approval:" + _digest(identity)
    if payload.get("approval_id") != approval_id:
        raise RuntimeError("trade committee approval content identity is invalid")
    if tuple(payload.get("verdict_levels", ())) != tuple(
        level for level, _ in EXPECTED_COMMITTEE
    ):
        raise RuntimeError("trade committee verdict levels are invalid")
    intent = payload["intent"]
    thesis = payload["thesis"]
    return CommitteeApproval(
        approval_id=approval_id,
        event_id=event.event_id,
        thesis_id=str(thesis["id"]),
        intent_id=str(intent["intent_id"]),
        lineage_id=str(payload["lineage_id"]),
        plan_version_id=str(intent["strategy_plan_id"]),
        decision_trace_id=str(intent["decision_trace_id"]),
        verdict_evidence_event_ids=tuple(payload["verdict_evidence_event_ids"]),
    )


def _decimal(value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("thesis prices must be finite decimals") from None
    if not result.is_finite():
        raise ValueError("thesis prices must be finite decimals")
    return result


def _money(paise: int) -> Decimal:
    return Decimal(paise) / Decimal(100)


def _stream(intent_id: str) -> str:
    return f"trade-approval:{intent_id.removeprefix('intent:')}"


def _digest(value: object) -> str:
    canonical = json.dumps(
        _plain(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _plain(value):
    if isinstance(value, Mapping):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(child) for child in value]
    return value


def _aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
