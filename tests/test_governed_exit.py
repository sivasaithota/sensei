from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd
import pytest

from sensei.kernel import CancelEntryCommand, EntryCommand, GatewayReceipt
from sensei.learning.episodes import (
    EpisodeCommand,
    EpisodeEventType,
    TradeEpisodeJournal,
)
from sensei.operations import OperationalJournal
from sensei.runtime.governed_exit import (
    GovernedExitProcessor,
    PaperEpisodeBrokerBridge,
)


NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


def _open_episode(journal, suffix="one", instrument="INFY", *, protect=True):
    episodes = TradeEpisodeJournal(journal)
    intent_id = "intent:" + (
        "d" * 64 if suffix == "one" else "a" * 63 + str(len(suffix) % 10)
    )
    episode_id = f"EP-{suffix}"
    episodes.start(
        episode_id=episode_id,
        strategy_lineage_id=f"lineage-{suffix}",
        plan_version_id="sha256:" + "a" * 64,
        decision_trace_id="trace:one",
        market_snapshot_id="snapshot:" + "b" * 64,
        account_snapshot_id="snapshot:" + "c" * 64,
        intent_id=intent_id,
        instrument_id=instrument,
        timeframe="1d",
        planned_entry_price_paise=10_000,
        planned_exit_price_paise=11_000,
        signal_time=NOW - timedelta(days=2),
        command_id=f"start-{suffix}",
    )
    commands = (
        (EpisodeEventType.APPROVAL_RECORDED, {"approved": True}),
        (
            EpisodeEventType.INTENT_ACCEPTED,
            {"intent_id": intent_id},
        ),
        (
            EpisodeEventType.ORDER_SUBMITTED,
            {"order_id": "paper-entry-one", "quantity": 2},
        ),
        (
            EpisodeEventType.ENTRY_FILL_RECORDED,
            {"fill_id": "entry-fill-one", "quantity": 2, "price": "100.00"},
        ),
        (
            EpisodeEventType.PROTECTION_VERIFIED,
            {"protected_quantity": 2, "stop_price": "95.00"},
        ),
    )[: 5 if protect else 4]
    for index, (event_type, payload) in enumerate(commands):
        episodes.record(EpisodeCommand(
            episode_id=episode_id,
            event_type=event_type,
            payload=payload,
            occurred_at=NOW - timedelta(days=1, seconds=10 - index),
            command_id=f"open-{suffix}-{index}",
        ))


def _accepted_episode(journal, suffix):
    episodes = TradeEpisodeJournal(journal)
    intent_id = f"intent:{suffix}"
    episode_id = f"EP-{suffix}"
    episodes.start(
        episode_id=episode_id,
        strategy_lineage_id=f"lineage-{suffix}",
        plan_version_id="sha256:" + "a" * 64,
        decision_trace_id=f"trace:{suffix}",
        market_snapshot_id="snapshot:" + "b" * 64,
        account_snapshot_id="snapshot:" + "c" * 64,
        intent_id=intent_id,
        instrument_id="INFY",
        timeframe="1d",
        planned_entry_price_paise=10_000,
        planned_exit_price_paise=11_000,
        signal_time=NOW - timedelta(minutes=2),
        command_id=f"start-{suffix}",
    )
    for index, (event_type, payload) in enumerate((
        (EpisodeEventType.APPROVAL_RECORDED, {"approved": True}),
        (EpisodeEventType.INTENT_ACCEPTED, {"intent_id": intent_id}),
    )):
        episodes.record(EpisodeCommand(
            episode_id=episode_id,
            event_type=event_type,
            payload=payload,
            occurred_at=NOW - timedelta(minutes=1, seconds=1 - index),
            command_id=f"accept-{suffix}-{index}",
        ))
    return episodes, episode_id, intent_id


def test_stop_exit_closes_attributes_reviews_and_teaches_coach(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    _open_episode(journal)
    dispatched = []

    def exit_position(intent_id, **kwargs):
        dispatched.append((intent_id, kwargs))
        return GatewayReceipt(
            command_id="command:" + "e" * 64,
            accepted=True,
            broker_reference="paper-exit-one",
            cumulative_fill_quantity=2,
            average_fill_price_paise=9_400,
        )

    bars = pd.DataFrame(
        {
            "open": [96.0],
            "high": [97.0],
            "low": [94.0],
            "close": [95.0],
            "volume": [1_000_000],
        },
        index=pd.to_datetime(["2026-07-25"]),
    )
    result = GovernedExitProcessor(
        journal=journal,
        exit_position=exit_position,
        resize_protection=lambda *_args, **_kwargs: None,
        bars=lambda _instrument: bars,
        maximum_holding_sessions=lambda _plan: 25,
        trading_sessions_between=lambda _start, _end: 2,
        market_regime=lambda _now: "mixed",
    ).run(now=NOW)

    assert result.closed_episode_ids == ("EP-one",)
    assert dispatched[0][1]["reason_code"] == "STOP"
    events = journal.read_stream("episode:EP-one")
    assert [
        event.event_type for event in events[-5:]
    ] == [
        "ExitFillRecorded",
        "EpisodeClosed",
        "CostsReconciled",
        "OutcomeAttributed",
        "ReviewRecorded",
    ]
    outcome = next(
        event for event in events if event.event_type == "OutcomeAttributed"
    )
    assert Decimal(outcome.payload["realized_net_pnl"]) == Decimal("-12.00")
    assert any(
        event.event_type == "LearningObservationRecorded"
        and event.correlation_id == "EP-one"
        for event in journal.read_all()
    )

    replay = GovernedExitProcessor(
        journal=journal,
        exit_position=exit_position,
        resize_protection=lambda *_args, **_kwargs: None,
        bars=lambda _instrument: bars,
        maximum_holding_sessions=lambda _plan: 25,
        trading_sessions_between=lambda _start, _end: 2,
        market_regime=lambda _now: "mixed",
    ).run(now=NOW + timedelta(minutes=1))
    assert replay.closed_episode_ids == ()
    assert len(dispatched) == 1


def test_partial_exit_retries_only_remaining_quantity_and_learns_once(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    _open_episode(journal)
    requested = []

    def exit_position(intent_id, **kwargs):
        requested.append(kwargs["quantity"])
        quantity = 1
        suffix = len(requested)
        return GatewayReceipt(
            command_id="command:" + str(suffix) * 64,
            accepted=True,
            broker_reference=f"paper-exit-{suffix}",
            cumulative_fill_quantity=quantity,
            average_fill_price_paise=9_400,
        )

    bars = pd.DataFrame(
        {
            "open": [94.0], "high": [97.0], "low": [93.0],
            "close": [95.0], "volume": [1_000_000],
        },
        index=pd.to_datetime(["2026-07-25"]),
    )
    processor = GovernedExitProcessor(
        journal=journal,
        exit_position=exit_position,
        resize_protection=lambda *_args, **_kwargs: GatewayReceipt(
            command_id="command:" + "f" * 64,
            accepted=True,
            broker_reference="protection-resized",
        ),
        bars=lambda _instrument: bars,
        maximum_holding_sessions=lambda _plan: 25,
        trading_sessions_between=lambda _start, _end: 2,
        market_regime=lambda _now: "mixed",
    )

    first = processor.run(now=NOW)
    second = processor.run(now=NOW + timedelta(minutes=1))
    third = processor.run(now=NOW + timedelta(minutes=2))

    assert first.open_episode_ids == ("EP-one",)
    assert second.closed_episode_ids == ("EP-one",)
    assert third.closed_episode_ids == ()
    assert requested == [2, 1]
    assert sum(
        event.event_type == "LearningObservationRecorded"
        for event in journal.read_all()
    ) == 1


@pytest.mark.parametrize(
    ("bar", "maximum_holding_sessions", "expected_reason"),
    [
        (
            {"open": 100.0, "high": 111.0, "low": 99.0, "close": 109.0},
            25,
            "TARGET",
        ),
        (
            {"open": 100.0, "high": 105.0, "low": 99.0, "close": 101.0},
            1,
            "TIME",
        ),
        # Conservative same-bar ambiguity: protection wins over target.
        (
            {"open": 100.0, "high": 111.0, "low": 94.0, "close": 105.0},
            25,
            "STOP",
        ),
        (
            {"open": 120.0, "high": 125.0, "low": 90.0, "close": 100.0},
            25,
            "TARGET",
        ),
    ],
)
def test_exit_policy_covers_target_time_and_ambiguous_bars(
    tmp_path, bar, maximum_holding_sessions, expected_reason
):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    _open_episode(journal)
    reasons = []

    def exit_position(_intent_id, **kwargs):
        reasons.append(kwargs["reason_code"])
        return GatewayReceipt(
            command_id="command:" + "f" * 64,
            accepted=True,
            broker_reference="paper-exit-policy",
            cumulative_fill_quantity=2,
            average_fill_price_paise=kwargs["reference_price_paise"],
        )

    frame = pd.DataFrame(
        [{**bar, "volume": 1_000_000}],
        index=pd.to_datetime(["2026-07-25"]),
    )
    GovernedExitProcessor(
        journal=journal,
        exit_position=exit_position,
        resize_protection=lambda *_args, **_kwargs: None,
        bars=lambda _instrument: frame,
        maximum_holding_sessions=lambda _plan: maximum_holding_sessions,
        trading_sessions_between=lambda _start, _end: 2,
        market_regime=lambda _now: "mixed",
    ).run(now=NOW)

    assert reasons == [expected_reason]


@pytest.mark.parametrize(
    "crash_step",
    [
        "exit_fill",
        "episode_closed",
        "costs_reconciled",
        "outcome_attributed",
        "review_recorded",
    ],
)
def test_settlement_resumes_after_every_durable_boundary(
    tmp_path, crash_step
):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    _open_episode(journal)
    crashed = False

    def checkpoint(step, _episode_id):
        nonlocal crashed
        if step == crash_step and not crashed:
            crashed = True
            raise RuntimeError("simulated process crash")

    def exit_position(_intent_id, **kwargs):
        return GatewayReceipt(
            command_id="command:" + "9" * 64,
            accepted=True,
            broker_reference="paper-exit-restart",
            cumulative_fill_quantity=2,
            average_fill_price_paise=9_400,
        )

    frame = pd.DataFrame(
        [{
            "open": 94.0, "high": 97.0, "low": 93.0,
            "close": 95.0, "volume": 1_000_000,
        }],
        index=pd.to_datetime(["2026-07-25"]),
    )
    kwargs = {
        "journal": journal,
        "exit_position": exit_position,
        "resize_protection": lambda *_args, **_kwargs: None,
        "bars": lambda _instrument: frame,
        "maximum_holding_sessions": lambda _plan: 25,
        "trading_sessions_between": lambda _start, _end: 2,
        "market_regime": lambda _now: "mixed",
    }
    first = GovernedExitProcessor(
        **kwargs, checkpoint=checkpoint
    ).run(now=NOW)
    second = GovernedExitProcessor(**kwargs).run(
        now=NOW + timedelta(minutes=1)
    )

    assert first.halted_episode_ids == ("EP-one",)
    assert second.closed_episode_ids == ("EP-one",)
    assert sum(
        event.event_type == "LearningObservationRecorded"
        for event in journal.read_all()
    ) == 1


def test_one_malformed_episode_does_not_block_other_protective_exits(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    _open_episode(journal, protect=False)
    _open_episode(journal, suffix="two", instrument="TCS")
    exited = []

    def exit_position(intent_id, **kwargs):
        exited.append(intent_id)
        return GatewayReceipt(
            command_id="command:" + "8" * 64,
            accepted=True,
            broker_reference="paper-exit-isolated",
            cumulative_fill_quantity=2,
            average_fill_price_paise=9_400,
        )

    frame = pd.DataFrame(
        [{
            "open": 94.0, "high": 97.0, "low": 93.0,
            "close": 95.0, "volume": 1_000_000,
        }],
        index=pd.to_datetime(["2026-07-25"]),
    )
    result = GovernedExitProcessor(
        journal=journal,
        exit_position=exit_position,
        resize_protection=lambda *_args, **_kwargs: None,
        bars=lambda _instrument: frame,
        maximum_holding_sessions=lambda _plan: 25,
        trading_sessions_between=lambda _start, _end: 2,
        market_regime=lambda _now: "mixed",
    ).run(now=NOW)

    assert result.halted_episode_ids == ("EP-one",)
    assert result.closed_episode_ids == ("EP-two",)
    assert len(exited) == 1


def test_rejected_entry_becomes_terminal_without_learning(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    episodes, episode_id, intent_id = _accepted_episode(journal, "rejected")
    entry = EntryCommand(intent_id, "INFY", 2, 10_000)
    bridge = PaperEpisodeBrokerBridge(journal, clock=lambda: NOW)

    bridge(entry, GatewayReceipt(
        command_id=entry.command_id,
        accepted=False,
        broker_reference="rejected-by-paper-broker",
    ))

    episode = episodes.get(episode_id)
    assert episode.status.value == "CANCELLED"
    assert episode.open_quantity == 0
    assert not any(
        event.event_type == "LearningObservationRecorded"
        for event in journal.read_all()
    )


def test_zero_fill_cancel_terminates_but_partial_fill_cancel_stays_open(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    episodes, zero_id, zero_intent = _accepted_episode(journal, "zero")
    _, partial_id, partial_intent = _accepted_episode(journal, "partial")
    bridge = PaperEpisodeBrokerBridge(journal, clock=lambda: NOW)

    zero_entry = EntryCommand(zero_intent, "INFY", 2, 10_000)
    bridge(zero_entry, GatewayReceipt(
        command_id=zero_entry.command_id,
        accepted=True,
        broker_reference="working-zero",
    ))
    zero_cancel = CancelEntryCommand(
        zero_intent, "INFY", zero_entry.command_id, 2
    )
    bridge(zero_cancel, GatewayReceipt(
        command_id=zero_cancel.command_id,
        accepted=True,
        broker_reference="cancel-zero",
    ))

    partial_entry = EntryCommand(partial_intent, "INFY", 2, 10_000)
    bridge(partial_entry, GatewayReceipt(
        command_id=partial_entry.command_id,
        accepted=True,
        broker_reference="partial-fill",
        cumulative_fill_quantity=1,
        average_fill_price_paise=10_000,
    ))
    partial_cancel = CancelEntryCommand(
        partial_intent, "INFY", partial_entry.command_id, 1
    )
    bridge(partial_cancel, GatewayReceipt(
        command_id=partial_cancel.command_id,
        accepted=True,
        broker_reference="cancel-remainder",
    ))

    assert episodes.get(zero_id).status.value == "CANCELLED"
    assert episodes.get(partial_id).status.value == "OPEN"
    assert episodes.get(partial_id).open_quantity == 1


def test_partial_exit_halts_when_remaining_protection_is_rejected(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    _open_episode(journal)
    frame = pd.DataFrame(
        [{
            "open": 94.0, "high": 97.0, "low": 93.0,
            "close": 95.0, "volume": 1_000_000,
        }],
        index=pd.to_datetime(["2026-07-25"]),
    )

    result = GovernedExitProcessor(
        journal=journal,
        exit_position=lambda _intent, **_kwargs: GatewayReceipt(
            command_id="command:" + "7" * 64,
            accepted=True,
            broker_reference="partial-exit",
            cumulative_fill_quantity=1,
            average_fill_price_paise=9_400,
        ),
        resize_protection=lambda *_args, **_kwargs: GatewayReceipt(
            command_id="command:" + "6" * 64,
            accepted=False,
            broker_reference="resize-rejected",
        ),
        bars=lambda _instrument: frame,
        maximum_holding_sessions=lambda _plan: 25,
        trading_sessions_between=lambda _start, _end: 2,
        market_regime=lambda _now: "mixed",
    ).run(now=NOW)

    assert result.halted_episode_ids == ("EP-one",)
    assert TradeEpisodeJournal(journal).get("EP-one").open_quantity == 1
