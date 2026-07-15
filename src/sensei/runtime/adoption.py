"""Fail-closed reconciliation for paper positions predating the governed gateway."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sensei.kernel import BrokerPosition, BrokerProtection, BrokerSnapshot
from sensei.operations import EventAppend, OperationalJournal
from sensei.portfolio_risk.models import AccountPosition, AccountSnapshot, require_timestamp


class LegacyPositionDrift(RuntimeError):
    """The mutable paper book no longer matches its adopted immutable inventory."""


@dataclass(frozen=True)
class ReconciledLegacyPositionTruth:
    broker_snapshot: BrokerSnapshot
    account_snapshot: AccountSnapshot
    reconciliation_event_id: str


class LegacyPositionAdoptionRegistry:
    """Reconcile the legacy JSON book without inventing historical commands."""

    def __init__(self, journal: OperationalJournal, *, positions_path: Path) -> None:
        self._journal = journal
        self._positions_path = Path(positions_path)

    def reconcile(self, *, mark_prices_paise: dict[str, int], captured_at: datetime,
                  command_id: str) -> ReconciledLegacyPositionTruth:
        require_timestamp(captured_at, "captured_at")
        if not command_id.strip():
            raise ValueError("command_id is required")
        events = self._journal.read_stream("legacy-paper-position-adoption")
        if not events or any(
            event.event_type != "LegacyPaperPositionsAdopted" for event in events
        ):
            raise LegacyPositionDrift("legacy inventory has no valid adoption history")
        adopted_event = events[-1]
        content = self._positions_path.read_bytes()
        content_id = "sha256:" + hashlib.sha256(content).hexdigest()
        if content_id != adopted_event.payload.get("source_sha256"):
            raise LegacyPositionDrift("legacy paper inventory changed after adoption")
        payload = json.loads(content)
        positions = tuple(payload.get("positions", ()))
        if set(mark_prices_paise) != {str(item["symbol"]) for item in positions}:
            raise LegacyPositionDrift("marks must exactly cover adopted positions")

        broker_positions, protections, account_positions = [], [], []
        marked_notional = 0
        for item in positions:
            symbol, quantity = str(item["symbol"]), int(item["quantity"])
            mark = int(mark_prices_paise[symbol])
            stop = round(float(item["stop_loss"]) * 100)
            target = round(float(item["targets"][0]) * 100)
            if mark <= 0 or stop <= 0 or target <= stop:
                raise LegacyPositionDrift(f"invalid price truth for {symbol}")
            notional = quantity * mark
            marked_notional += notional
            broker_positions.append(BrokerPosition(symbol, quantity))
            protections.append(BrokerProtection(symbol, quantity, stop, target))
            account_positions.append(AccountPosition(
                instrument_id=symbol, quantity=quantity, notional_paise=notional,
                risk_to_stop_paise=quantity * max(0, mark - stop),
            ))
        cash_paise = round(float(payload["cash"]) * 100)
        broker = BrokerSnapshot(captured_at=captured_at,
                                positions=tuple(broker_positions),
                                protections=tuple(protections))
        equity = cash_paise + marked_notional
        account = AccountSnapshot(
            available_cash_paise=cash_paise, marked_equity_paise=equity,
            high_water_mark_paise=max(equity, cash_paise + sum(
                int(item["quantity"]) * round(float(item["entry_price"]) * 100)
                for item in positions)),
            day_pnl_paise=0, week_pnl_paise=0,
            positions=tuple(account_positions), included_reservation_ids=(),
            reconciled=True, captured_at=captured_at,
        )
        event_payload = {
            "schema_version": "1.0",
            "authority": "LEGACY_BOOK_RECONCILIATION_ONLY",
            "adoption_event_id": adopted_event.event_id,
            "source_sha256": content_id,
            "broker_snapshot_id": broker.snapshot_id,
            "account_snapshot_id": account.snapshot_id,
            "requires_gateway_command_history": True,
        }
        stream = "legacy-paper-position-reconciliation"
        existing = self._journal.read_stream(stream)
        if existing and existing[-1].payload == event_payload:
            event = existing[-1]
        else:
            event = self._journal.append(EventAppend(
                stream_id=stream, event_type="LegacyPaperPositionsReconciled",
                payload=event_payload,
                idempotency_key="legacy-reconciliation:" + hashlib.sha256(command_id.encode()).hexdigest(),
                expected_version=len(existing), occurred_at=captured_at,
                causation_id=adopted_event.event_id,
            ))
        return ReconciledLegacyPositionTruth(broker, account, event.event_id)


__all__ = ["LegacyPositionAdoptionRegistry", "LegacyPositionDrift",
           "ReconciledLegacyPositionTruth"]
