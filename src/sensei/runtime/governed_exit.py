"""Automatic settlement of governed paper Trade Episodes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import pandas as pd

from sensei.kernel import (
    BrokerCommand,
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


@dataclass(frozen=True)
class GovernedExitResult:
    closed_episode_ids: tuple[str, ...]
    open_episode_ids: tuple[str, ...]


class GovernedExitProcessor:
    """Apply deterministic stop/target/time exits and close the learning loop."""

    def __init__(
        self,
        *,
        journal: OperationalJournal,
        exit_position: Callable[..., GatewayReceipt],
        bars: Callable[[str], pd.DataFrame],
        maximum_holding_sessions: Callable[[str], int],
        market_regime: Callable[[datetime], str],
    ) -> None:
        self._journal = journal
        self._episodes = TradeEpisodeJournal(journal)
        self._exit_position = exit_position
        self._bars = bars
        self._maximum_holding_sessions = maximum_holding_sessions
        self._market_regime = market_regime

    def run(self, *, now: datetime) -> GovernedExitResult:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        closed: list[str] = []
        still_open: list[str] = []
        for episode in self._open_episodes():
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
            self._settle(
                episode,
                receipt=receipt,
                reason=reason,
                now=now,
            )
            refreshed = self._episodes.get(episode.episode_id)
            if refreshed.status is EpisodeStatus.CLOSED:
                closed.append(episode.episode_id)
            else:
                still_open.append(episode.episode_id)
        return GovernedExitResult(tuple(closed), tuple(still_open))

    def _open_episodes(self) -> tuple[TradeEpisode, ...]:
        ids = {
            event.stream_id.removeprefix("episode:")
            for event in self._journal.read_all()
            if event.event_type == "EpisodeStarted"
            and event.stream_id.startswith("episode:")
        }
        return tuple(
            episode
            for episode_id in sorted(ids)
            if (episode := self._episodes.get(episode_id)).status
            is EpisodeStatus.OPEN
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
        if session_open <= stop or session_low <= stop:
            return "STOP", min(session_open, stop)
        if session_high >= target:
            return "TARGET", target
        holding_sessions = len(
            pd.bdate_range(
                episode.signal_time.date(),
                now.date(),
                inclusive="right",
            )
        )
        if holding_sessions >= self._maximum_holding_sessions(
            episode.plan_version_id
        ):
            return "TIME", session_close
        return None

    def _settle(
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
        exit_event = self._episodes.record(EpisodeCommand(
            episode_id=episode.episode_id,
            event_type=EpisodeEventType.EXIT_FILL_RECORDED,
            payload={
                "quantity": quantity,
                "price": str(Decimal(price_paise) / 100),
                "fill_id": receipt.broker_reference,
                "broker_command_id": receipt.command_id,
                "fees_paise": _fee_paise(receipt),
            },
            occurred_at=now,
            command_id=f"exit-fill:{suffix}",
        ))
        current = self._episodes.get(episode.episode_id)
        if current.open_quantity:
            return
        close_event = self._episodes.record(EpisodeCommand(
            episode_id=episode.episode_id,
            event_type=EpisodeEventType.EPISODE_CLOSED,
            payload={"reason": reason},
            occurred_at=now,
            command_id=f"episode-close:{suffix}",
        ))
        episode_events = self._journal.read_stream(
            f"episode:{episode.episode_id}"
        )
        exit_events = [
            event for event in episode_events
            if event.event_type == "ExitFillRecorded"
        ]
        fee_paise = sum(
            int(event.payload.get("fees_paise", 0)) for event in exit_events
        )
        cost_event = self._episodes.record(EpisodeCommand(
            episode_id=episode.episode_id,
            event_type=EpisodeEventType.COSTS_RECONCILED,
            payload={
                "reconciliation_id": f"costs:{suffix}",
                "fees": str(Decimal(fee_paise) / 100),
                "currency": "INR",
                "source_ref": receipt.broker_reference,
            },
            occurred_at=now,
            command_id=f"episode-costs:{suffix}",
        ))
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
        attribution = OutcomeAttributionService(self._journal).record(
            AttributionInput(
                episode_id=episode.episode_id,
                quantity=entry_quantity,
                planned_entry=Decimal(episode.planned_entry_price_paise) / 100,
                planned_exit=Decimal(episode.planned_exit_price_paise) / 100,
                actual_entry=entry_notional / entry_quantity,
                actual_exit=exit_notional / exit_quantity,
                fees=Decimal(fee_paise) / 100,
                reasoning_quality_passed=True,
            ),
            evidence_refs=tuple(
                event.event_id
                for event in (*entry_events, *exit_events, cost_event)
            ),
            currency="INR",
            occurred_at=now,
            command_id=f"outcome:{suffix}",
        )
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
                    if attribution.attribution.realized_net_pnl >= 0
                    else f"{reason.lower()}_loss"
                ),
                "close_event_id": close_event.event_id,
            },
            occurred_at=now,
            command_id=f"review:{suffix}",
        ))
        OutcomeLearner(self._journal).record_pending_reviews(
            no_later_than=now,
            command_id=f"exit-learning:{suffix}",
        )


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
        if not isinstance(command, (EntryCommand, ProtectionCommand)):
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
