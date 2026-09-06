"""Automatic settlement of governed paper Trade Episodes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import hashlib

import pandas as pd

from sensei.kernel import (
    BrokerCommand,
    CancelEntryCommand,
    EntryCommand,
    GatewayReceipt,
    ProtectionCommand,
)
from sensei.learning.attribution import (
    AttributionInput,
    OutcomeAttributionService,
)
from sensei.learning.episodes import (
    EpisodeCommand,
    EpisodeEventType,
    EpisodeStatus,
    TradeEpisode,
    TradeEpisodeJournal,
)
from sensei.learning.outcomes import OutcomeLearner
from sensei.operations import OperationalJournal
from sensei.backtest.daily_execution import intraday_exit, opening_exit


@dataclass(frozen=True)
class GovernedExitResult:
    closed_episode_ids: tuple[str, ...]
    open_episode_ids: tuple[str, ...]
    halted_episode_ids: tuple[str, ...] = ()


class GovernedExitProcessor:
    """Apply deterministic stop/target/time exits and close the learning loop."""

    def __init__(
        self,
        *,
        journal: OperationalJournal,
        exit_position: Callable[..., GatewayReceipt],
        resize_protection: Callable[..., GatewayReceipt],
        bars: Callable[[str], pd.DataFrame],
        maximum_holding_sessions: Callable[[str], int],
        trading_sessions_between: Callable[[datetime, datetime], int],
        market_regime: Callable[[datetime], str],
        checkpoint: Callable[[str, str], None] | None = None,
    ) -> None:
        self._journal = journal
        self._episodes = TradeEpisodeJournal(journal)
        self._exit_position = exit_position
        self._resize_protection = resize_protection
        self._bars = bars
        self._maximum_holding_sessions = maximum_holding_sessions
        self._trading_sessions_between = trading_sessions_between
        self._market_regime = market_regime
        self._checkpoint = checkpoint or (lambda _step, _episode_id: None)

    def run(self, *, now: datetime) -> GovernedExitResult:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        closed: list[str] = []
        still_open: list[str] = []
        halted: list[str] = []
        for episode in self._unsettled_episodes():
            try:
                if episode.open_quantity == 0:
                    self._advance_settlement(episode, now=now)
                elif episode.status is EpisodeStatus.OPEN:
                    decision = self._decision(episode, now)
                    if decision is None:
                        still_open.append(episode.episode_id)
                        continue
                    reason, reference_price_paise = decision
                    receipt = self._exit_position(
                        episode.intent_id,
                        quantity=episode.open_quantity,
                        reference_price_paise=reference_price_paise,
                        reason_code=reason,
                        occurred_at=now,
                    )
                    if (
                        not receipt.accepted
                        or receipt.cumulative_fill_quantity <= 0
                        or receipt.average_fill_price_paise is None
                    ):
                        still_open.append(episode.episode_id)
                        continue
                    self._record_exit(
                        episode, receipt=receipt, reason=reason, now=now
                    )
                refreshed = self._episodes.get(episode.episode_id)
                if self._is_learned(episode.episode_id):
                    closed.append(episode.episode_id)
                elif refreshed.open_quantity:
                    still_open.append(episode.episode_id)
            except Exception as exc:
                self._record_halt(episode.episode_id, exc=exc, now=now)
                halted.append(episode.episode_id)
        return GovernedExitResult(
            tuple(closed), tuple(still_open), tuple(halted)
        )

    def _unsettled_episodes(self) -> tuple[TradeEpisode, ...]:
        ids = {
            event.stream_id.removeprefix("episode:")
            for event in self._journal.read_all()
            if event.event_type == "EpisodeStarted"
            and event.stream_id.startswith("episode:")
        }
        return tuple(
            episode
            for episode_id in sorted(ids)
            if (
                episode := self._episodes.get(episode_id)
            ).status in {EpisodeStatus.OPEN, EpisodeStatus.CLOSED}
            and not self._is_learned(episode_id)
        )

    def _is_learned(self, episode_id: str) -> bool:
        return any(
            event.event_type == "LearningObservationRecorded"
            and event.correlation_id == episode_id
            for event in self._journal.read_all()
        )

    def _decision(
        self, episode: TradeEpisode, now: datetime
    ) -> tuple[str, int] | None:
        frame = self._bars(episode.instrument_id)
        if frame.empty:
            return None
        row = frame.iloc[-1]
        events = self._journal.read_stream(f"episode:{episode.episode_id}")
        protection = next(
            event
            for event in reversed(events)
            if event.event_type == "ProtectionVerified"
        )
        stop = round(Decimal(str(protection.payload["stop_price"])) * 100)
        target = episode.planned_exit_price_paise
        session_open = round(float(row["open"]) * 100)
        session_low = round(float(row["low"]) * 100)
        session_high = round(float(row["high"]) * 100)
        session_close = round(float(row["close"]) * 100)
        outcome = opening_exit(session_open, stop, target) or intraday_exit(
            session_low, session_high, stop, target,
        )
        if outcome is not None:
            return ("TARGET" if outcome.reason == "target" else "STOP"), int(outcome.price)
        holding_sessions = self._trading_sessions_between(
            episode.signal_time, now
        )
        if holding_sessions >= self._maximum_holding_sessions(
            episode.plan_version_id
        ):
            return "TIME", session_close
        return None

    def _record_exit(
        self,
        episode: TradeEpisode,
        *,
        receipt: GatewayReceipt,
        reason: str,
        now: datetime,
    ) -> None:
        quantity = receipt.cumulative_fill_quantity
        price_paise = receipt.average_fill_price_paise
        assert price_paise is not None
        suffix = receipt.command_id.removeprefix("command:")
        self._episodes.record(EpisodeCommand(
            episode_id=episode.episode_id,
            event_type=EpisodeEventType.EXIT_FILL_RECORDED,
            payload={
                "quantity": quantity,
                "price": str(Decimal(price_paise) / 100),
                "fill_id": receipt.broker_reference,
                "broker_command_id": receipt.command_id,
                "fees_paise": _fee_paise(receipt),
                "reason": reason,
            },
            occurred_at=now,
            command_id=f"exit-fill:{suffix}",
        ))
        self._checkpoint("exit_fill", episode.episode_id)
        current = self._episodes.get(episode.episode_id)
        if current.open_quantity:
            protection_receipt = self._resize_protection(
                episode.intent_id,
                quantity=current.open_quantity,
                occurred_at=now,
            )
            if (
                not isinstance(protection_receipt, GatewayReceipt)
                or not protection_receipt.accepted
            ):
                raise RuntimeError(
                    "partial exit protection resize was not accepted"
                )
            return
        self._advance_settlement(current, now=now)

    def _advance_settlement(
        self, episode: TradeEpisode, *, now: datetime
    ) -> None:
        events = self._journal.read_stream(f"episode:{episode.episode_id}")
        exit_events = [
            event for event in events
            if event.event_type == "ExitFillRecorded"
        ]
        if not exit_events:
            raise RuntimeError("zero-quantity episode has no exit evidence")
        latest_exit = exit_events[-1]
        reason = str(latest_exit.payload["reason"])
        suffix = episode.episode_id.removeprefix("EP-")
        close_event = next(
            (event for event in events if event.event_type == "EpisodeClosed"),
            None,
        )
        if close_event is None:
            close_event = self._episodes.record(EpisodeCommand(
            episode_id=episode.episode_id,
            event_type=EpisodeEventType.EPISODE_CLOSED,
            payload={"reason": reason},
            occurred_at=now,
            command_id=f"episode-close:{suffix}",
            ))
            self._checkpoint("episode_closed", episode.episode_id)
        fee_paise = sum(
            int(event.payload.get("fees_paise", 0)) for event in exit_events
        )
        events = self._journal.read_stream(f"episode:{episode.episode_id}")
        cost_event = next(
            (event for event in events if event.event_type == "CostsReconciled"),
            None,
        )
        if cost_event is None:
            cost_event = self._episodes.record(EpisodeCommand(
                episode_id=episode.episode_id,
                event_type=EpisodeEventType.COSTS_RECONCILED,
                payload={
                    "reconciliation_id": f"costs:{suffix}",
                    "fees": str(Decimal(fee_paise) / 100),
                    "currency": "INR",
                    "source_ref": str(latest_exit.payload["fill_id"]),
                },
                occurred_at=now,
                command_id=f"episode-costs:{suffix}",
            ))
            self._checkpoint("costs_reconciled", episode.episode_id)
        events = self._journal.read_stream(f"episode:{episode.episode_id}")
        entry_events = [
            event for event in events
            if event.event_type == "EntryFillRecorded"
        ]
        entry_quantity = sum(int(event.payload["quantity"]) for event in entry_events)
        entry_notional = sum(
            Decimal(str(event.payload["price"])) * int(event.payload["quantity"])
            for event in entry_events
        )
        exit_quantity = sum(
            int(event.payload["quantity"]) for event in exit_events
        )
        exit_notional = sum(
            Decimal(str(event.payload["price"])) * int(event.payload["quantity"])
            for event in exit_events
        )
        attribution_event = next(
            (event for event in events if event.event_type == "OutcomeAttributed"),
            None,
        )
        if attribution_event is None:
            attribution = OutcomeAttributionService(self._journal).record(
                AttributionInput(
                episode_id=episode.episode_id,
                quantity=entry_quantity,
                planned_entry=Decimal(episode.planned_entry_price_paise) / 100,
                planned_exit=Decimal(episode.planned_exit_price_paise) / 100,
                actual_entry=entry_notional / entry_quantity,
                actual_exit=exit_notional / exit_quantity,
                fees=Decimal(fee_paise) / 100,
                    reasoning_quality_passed=None,
                ),
                evidence_refs=tuple(
                    event.event_id
                    for event in (*entry_events, *exit_events, cost_event)
                ),
                currency="INR",
                occurred_at=now,
                command_id=f"outcome:{suffix}",
            )
            attribution_event = attribution.event
            self._checkpoint("outcome_attributed", episode.episode_id)
        events = self._journal.read_stream(f"episode:{episode.episode_id}")
        review_event = next(
            (event for event in events if event.event_type == "ReviewRecorded"),
            None,
        )
        if review_event is None:
            outcome_pnl = Decimal(str(
                attribution_event.payload["realized_net_pnl"]
            ))
            self._episodes.record(EpisodeCommand(
                episode_id=episode.episode_id,
                event_type=EpisodeEventType.REVIEW_RECORDED,
                payload={
                "review_id": f"review:{suffix}",
                "assessment": f"deterministic {reason.lower()} exit",
                "authority": "ADVISORY_ONLY",
                "market_regime": self._market_regime(now),
                "failure_type": (
                    "none"
                    if outcome_pnl >= 0
                    else f"{reason.lower()}_loss"
                ),
                "close_event_id": close_event.event_id,
                },
                occurred_at=now,
                command_id=f"review:{suffix}",
            ))
            self._checkpoint("review_recorded", episode.episode_id)
        OutcomeLearner(self._journal).record_pending_reviews(
            no_later_than=now,
            command_id=f"exit-learning:{suffix}",
        )
        self._checkpoint("learning_recorded", episode.episode_id)

    def _record_halt(
        self, episode_id: str, *, exc: Exception, now: datetime
    ) -> None:
        stream = f"governed-exit-halt:{episode_id}:{now.date().isoformat()}"
        existing = self._journal.read_stream(stream)
        if existing:
            return
        from sensei.operations import EventAppend

        self._journal.append(EventAppend(
            stream_id=stream,
            event_type="GovernedExitEpisodeHalted",
            payload={
                "episode_id": episode_id,
                "reason_code": "GOVERNED_EXIT_EPISODE_FAILED",
                "error_type": type(exc).__name__,
            },
            idempotency_key=(
                "governed-exit-halt:"
                + hashlib.sha256(
                    f"{episode_id}:{now.isoformat()}".encode()
                ).hexdigest()
            ),
            expected_version=0,
            occurred_at=now,
            correlation_id=episode_id,
        ))


class PaperEpisodeBrokerBridge:
    """Project durable entry/protection receipts into their Trade Episode."""

    def __init__(
        self,
        journal: OperationalJournal,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._journal = journal
        self._episodes = TradeEpisodeJournal(journal)
        self._clock = clock

    def __call__(
        self, command: BrokerCommand, receipt: GatewayReceipt
    ) -> None:
        if not isinstance(
            command, (EntryCommand, ProtectionCommand, CancelEntryCommand)
        ):
            return
        episode_id = self._episode_id(command.intent_id)
        now = self._clock()
        if isinstance(command, EntryCommand):
            self._record_once(EpisodeCommand(
                episode_id=episode_id,
                event_type=EpisodeEventType.ORDER_SUBMITTED,
                payload={
                    "order_id": receipt.broker_reference,
                    "quantity": command.quantity,
                    "broker_command_id": command.command_id,
                },
                occurred_at=now,
                command_id=f"episode-order:{command.command_id}",
            ))
            if receipt.cumulative_fill_quantity and (
                receipt.average_fill_price_paise is not None
            ):
                self._record_once(EpisodeCommand(
                    episode_id=episode_id,
                    event_type=EpisodeEventType.ENTRY_FILL_RECORDED,
                    payload={
                        "fill_id": receipt.broker_reference,
                        "quantity": receipt.cumulative_fill_quantity,
                        "price": str(
                            Decimal(receipt.average_fill_price_paise) / 100
                        ),
                        "broker_command_id": command.command_id,
                    },
                    occurred_at=now,
                    command_id=f"episode-entry-fill:{command.command_id}",
                ))
            if not receipt.accepted:
                self._terminate_entry(
                    episode_id,
                    broker_command_id=command.command_id,
                    reason="ENTRY_REJECTED",
                    now=now,
                )
        elif isinstance(command, CancelEntryCommand):
            if receipt.accepted:
                self._terminate_entry(
                    episode_id,
                    broker_command_id=command.command_id,
                    reason="ENTRY_REMAINDER_CANCELLED",
                    now=now,
                )
        elif receipt.accepted:
            self._record_once(EpisodeCommand(
                episode_id=episode_id,
                event_type=EpisodeEventType.PROTECTION_VERIFIED,
                payload={
                    "protected_quantity": command.quantity,
                    "stop_price": str(Decimal(command.stop_price_paise) / 100),
                    "target_price": str(
                        Decimal(command.target_price_paise) / 100
                    ),
                    "broker_command_id": command.command_id,
                },
                occurred_at=now,
                command_id=f"episode-protection:{command.command_id}",
            ))

    def _terminate_entry(
        self,
        episode_id: str,
        *,
        broker_command_id: str,
        reason: str,
        now: datetime,
    ) -> None:
        episode = self._episodes.get(episode_id)
        self._record_once(EpisodeCommand(
            episode_id=episode_id,
            event_type=EpisodeEventType.ENTRY_TERMINATED,
            payload={
                "reason": reason,
                "broker_command_id": broker_command_id,
                "open_quantity": episode.open_quantity,
            },
            occurred_at=now,
            command_id=f"episode-entry-terminal:{broker_command_id}",
        ))

    def _episode_id(self, intent_id: str) -> str:
        matches = {
            str(event.payload["episode_id"])
            for event in self._journal.read_all()
            if event.event_type == "EpisodeStarted"
            and event.payload.get("intent_id") == intent_id
        }
        if len(matches) != 1:
            raise RuntimeError(
                "broker command must map to exactly one Trade Episode"
            )
        return matches.pop()

    def _record_once(self, command: EpisodeCommand) -> None:
        if any(
            event.idempotency_key == command.command_id
            for event in self._journal.read_stream(
                f"episode:{command.episode_id}"
            )
        ):
            return
        self._episodes.record(command)


def _fee_paise(receipt: GatewayReceipt) -> int:
    quality = receipt.execution_quality or {}
    charges = quality.get("charges", {})
    if not isinstance(charges, dict):
        try:
            charges = dict(charges)
        except (TypeError, ValueError):
            return 0
    value = charges.get("total_paise", 0)
    return int(value) if not isinstance(value, bool) else 0


__all__ = [
    "GovernedExitProcessor",
    "GovernedExitResult",
    "PaperEpisodeBrokerBridge",
]
