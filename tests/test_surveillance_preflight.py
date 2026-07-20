from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from sensei.automation.scheduling import (
    ScheduledTask,
    SchedulerLedger,
    SchedulerTaskKind,
    SwingSessionPolicy,
    scheduled_task_id,
)
from sensei.automation.surveillance import (
    SurveillancePreflightSession,
    require_surveillance_preflight,
)
from sensei.operations import OperationalJournal
from sensei.runtime import (
    RuntimeSecretStore,
    RuntimeTrustError,
    SurveillanceSourceUnavailable,
    VerifiedSurveillanceSource,
)
from sensei.runtime.production import ProductionPaperSession


IST = ZoneInfo("Asia/Kolkata")
MONDAY = date(2026, 7, 20)
PREFLIGHT_AT = datetime(2026, 7, 20, 8, 45, tzinfo=IST)
ENTRY_AT = datetime(2026, 7, 20, 9, 20, tzinfo=IST)
REGULATORY_CSV = (
    b"ScripCode,Symbol,Nse Exclusive,Status,Series,GSM,"
    b"Long_Term_Additional_Surveillance_Measure (Long Term ASM),"
    b"Unsolicited_SMS,Insolvency_Resolution_Process(IRP),"
    b"Short_Term_Additional_Surveillance_Measure (Short Term ASM)\n"
    b"101,INFY,N,A,EQ,100,100,100,100,100\n"
)


def prepared_task(journal, destination, secret):
    task = SwingSessionPolicy().due_tasks(
        datetime(2026, 7, 20, 8, 31, tzinfo=IST)
    ).tasks[0]
    ledger = SchedulerLedger(journal)
    observed_at = task.due_at + timedelta(minutes=1)
    claim = ledger.claim(task, occurred_at=observed_at)
    SurveillancePreflightSession(
        journal=journal,
        destination=destination,
        issuer_id="market-surveillance",
        secret=secret,
        fetch=lambda _url: REGULATORY_CSV,
        retry_backoff_seconds=0,
    ).prepare(
        trading_date=MONDAY,
        observed_at=observed_at,
        command_id=task.task_id,
    )
    return task, ledger, claim


def test_preflight_retries_transient_nse_failure_and_publishes_entry_snapshot(
    tmp_path,
) -> None:
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    secrets = RuntimeSecretStore.bootstrap(tmp_path / "runtime-secrets.json")
    destination = tmp_path / "surveillance.json"
    attempts = 0

    def fetch(_url: str) -> bytes:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeTrustError("temporary NSE failure")
        return REGULATORY_CSV

    session = SurveillancePreflightSession(
        journal=journal,
        destination=destination,
        issuer_id="market-surveillance",
        secret=secrets["market-surveillance"],
        fetch=fetch,
        maximum_attempts=3,
        retry_backoff_seconds=0,
    )

    outcome = session.prepare(
        trading_date=MONDAY,
        observed_at=PREFLIGHT_AT,
        command_id="preflight:monday",
    )

    assert outcome.ready is True
    assert attempts == 3
    source = VerifiedSurveillanceSource(
        destination,
        issuer_id="market-surveillance",
        secret=secrets["market-surveillance"],
        maximum_age=timedelta(days=4),
        clock=lambda: ENTRY_AT,
    )
    assert source("INFY", MONDAY) == 0
    assert [event.event_type for event in journal.read_all()] == [
        "SurveillancePreflightStarted",
        "SurveillancePreflightCompleted",
    ]
    completed = journal.read_all()[-1]
    assert completed.payload["source_session"] == "2026-07-17"
    assert completed.payload["source_report_type"] == "REG1_IND"
    assert len(completed.payload["source_content_sha256"]) == 64


def test_terminal_source_failure_journals_sanitized_attempt_diagnostics(
    tmp_path,
) -> None:
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    secrets = RuntimeSecretStore.bootstrap(tmp_path / "runtime-secrets.json")

    session = SurveillancePreflightSession(
        journal=journal,
        destination=tmp_path / "surveillance.json",
        issuer_id="market-surveillance",
        secret=secrets["market-surveillance"],
        fetch=lambda _url: (_ for _ in ()).throw(
            RuntimeTrustError("official NSE surveillance download failed")
        ),
        maximum_attempts=1,
        retry_backoff_seconds=0,
    )

    with pytest.raises(SurveillanceSourceUnavailable):
        session.prepare(
            trading_date=MONDAY,
            observed_at=PREFLIGHT_AT,
            command_id="preflight:terminal-failure",
        )

    events = journal.read_all()
    assert [event.event_type for event in events] == [
        "SurveillancePreflightStarted",
        "SurveillancePreflightFailed",
    ]
    attempts = events[-1].payload["attempts"]
    assert len(attempts) == 14
    assert attempts[0] == {
        "source_session": "2026-07-17",
        "report_type": "REG1_IND",
        "attempt": 1,
        "category": "source_unavailable",
    }


def test_prepared_friday_snapshot_is_valid_for_monday_entry(tmp_path) -> None:
    secrets = RuntimeSecretStore.bootstrap(tmp_path / "runtime-secrets.json")
    destination = tmp_path / "surveillance.json"
    friday_evening = datetime(2026, 7, 17, 18, 30, tzinfo=IST)
    VerifiedSurveillanceSource.publish(
        destination,
        stages={"INFY": 0},
        session=MONDAY,
        source_session=date(2026, 7, 17),
        observed_at=friday_evening,
        issuer_id="market-surveillance",
        secret=secrets["market-surveillance"],
    )
    source = VerifiedSurveillanceSource(
        destination,
        issuer_id="market-surveillance",
        secret=secrets["market-surveillance"],
        maximum_age=timedelta(days=4),
        clock=lambda: ENTRY_AT,
    )

    assert source("INFY", MONDAY) == 0


def test_entry_path_never_calls_nse_when_prepared_snapshot_is_missing(
    tmp_path, monkeypatch
) -> None:
    secrets_path = tmp_path / "runtime-secrets.json"
    RuntimeSecretStore.bootstrap(secrets_path)
    prices = tmp_path / "prices"
    prices.mkdir()
    pd.DataFrame(
        {"close": [100.0]},
        index=pd.DatetimeIndex(["2026-07-17"]),
    ).to_parquet(prices / "INFY.parquet")
    network_calls = []
    monkeypatch.setattr(
        "sensei.runtime.activation.httpx.get",
        lambda *args, **kwargs: network_calls.append((args, kwargs)),
    )
    config = SimpleNamespace(
        runtime_secrets_path=secrets_path,
        surveillance_path=tmp_path / "missing-surveillance.json",
    )
    task = ScheduledTask(
        task_id=scheduled_task_id(
            kind=SchedulerTaskKind.ENTRY_SESSION,
            trading_date=MONDAY,
            policy_version="test-v1",
        ),
        kind=SchedulerTaskKind.ENTRY_SESSION,
        trading_date=MONDAY,
        due_at=ENTRY_AT,
        expires_at=ENTRY_AT + timedelta(minutes=15),
        policy_version="test-v1",
    )
    session = ProductionPaperSession(
        journal_path=tmp_path / "operations.sqlite3",
        scheduler_config=config,
        prices_path=prices,
    )

    with pytest.raises(SurveillanceSourceUnavailable):
        session(task, ENTRY_AT)

    assert network_calls == []


def test_entry_rejects_snapshot_when_preflight_task_never_completed(tmp_path) -> None:
    journal_path = tmp_path / "operations.sqlite3"
    journal = OperationalJournal(journal_path)
    secrets = RuntimeSecretStore.bootstrap(tmp_path / "runtime-secrets.json")
    destination = tmp_path / "surveillance.json"
    task, _ledger, _claim = prepared_task(
        journal, destination, secrets["market-surveillance"]
    )
    entry_task = ScheduledTask(
        task_id=scheduled_task_id(
            kind=SchedulerTaskKind.ENTRY_SESSION,
            trading_date=MONDAY,
            policy_version="india-swing-paper-v1",
        ),
        kind=SchedulerTaskKind.ENTRY_SESSION,
        trading_date=MONDAY,
        due_at=ENTRY_AT,
        expires_at=ENTRY_AT + timedelta(minutes=15),
        policy_version="india-swing-paper-v1",
    )

    with pytest.raises(SurveillanceSourceUnavailable, match="completed matching"):
        require_surveillance_preflight(
            journal_path=journal_path,
            snapshot_path=destination,
            entry_task=entry_task,
        )


def test_entry_rejects_valid_file_without_any_preflight_journal_evidence(
    tmp_path,
) -> None:
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    secrets = RuntimeSecretStore.bootstrap(tmp_path / "runtime-secrets.json")
    destination = tmp_path / "surveillance.json"
    VerifiedSurveillanceSource.publish(
        destination,
        stages={"INFY": 0},
        session=MONDAY,
        source_session=date(2026, 7, 17),
        observed_at=PREFLIGHT_AT,
        issuer_id="market-surveillance",
        secret=secrets["market-surveillance"],
    )
    entry_task = ScheduledTask(
        task_id=scheduled_task_id(
            kind=SchedulerTaskKind.ENTRY_SESSION,
            trading_date=MONDAY,
            policy_version="india-swing-paper-v1",
        ),
        kind=SchedulerTaskKind.ENTRY_SESSION,
        trading_date=MONDAY,
        due_at=ENTRY_AT,
        expires_at=ENTRY_AT + timedelta(minutes=15),
        policy_version="india-swing-paper-v1",
    )

    with pytest.raises(SurveillanceSourceUnavailable, match="completed matching"):
        require_surveillance_preflight(
            journal_path=journal_path,
            snapshot_path=destination,
            entry_task=entry_task,
        )


def test_entry_accepts_digest_bound_snapshot_after_scheduler_completion(tmp_path) -> None:
    journal_path = tmp_path / "operations.sqlite3"
    journal = OperationalJournal(journal_path)
    secrets = RuntimeSecretStore.bootstrap(tmp_path / "runtime-secrets.json")
    destination = tmp_path / "surveillance.json"
    task, ledger, claim = prepared_task(
        journal, destination, secrets["market-surveillance"]
    )
    ledger.complete(
        task.task_id,
        claimant_id=claim.record.claimant_id,
        occurred_at=PREFLIGHT_AT + timedelta(seconds=1),
        detail="surveillance ready",
        reason_codes=("SURVEILLANCE_PREFLIGHT_READY",),
    )
    entry_task = ScheduledTask(
        task_id=scheduled_task_id(
            kind=SchedulerTaskKind.ENTRY_SESSION,
            trading_date=MONDAY,
            policy_version="india-swing-paper-v1",
        ),
        kind=SchedulerTaskKind.ENTRY_SESSION,
        trading_date=MONDAY,
        due_at=ENTRY_AT,
        expires_at=ENTRY_AT + timedelta(minutes=15),
        policy_version="india-swing-paper-v1",
    )

    evidence = require_surveillance_preflight(
        journal_path=journal_path,
        snapshot_path=destination,
        entry_task=entry_task,
    )

    assert evidence.task_id == task.task_id
    assert evidence.source_session == date(2026, 7, 17)
    assert evidence.source_report_type == "REG1_IND"
    assert len(evidence.source_content_sha256) == 64
