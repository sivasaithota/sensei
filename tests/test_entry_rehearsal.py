import json
from datetime import date, datetime, timezone

import pandas as pd

from sensei.automation import (
    SchedulerLedger,
    SurveillancePreflightSession,
    SwingSessionPolicy,
)
from sensei.operations import EventAppend, OperationalJournal
from sensei.runtime import RuntimeSecretStore, VerifiedSurveillanceSource
from sensei.runtime.rehearsal import (
    PaperEntryRehearsal,
    RehearsalState,
    classify_rehearsal_outcome,
)


NOW = datetime(2026, 7, 18, 4, 30, tzinfo=timezone.utc)
REGULATORY_CSV = (
    b"ScripCode,Symbol,Nse Exclusive,Status,Series,GSM,"
    b"Long_Term_Additional_Surveillance_Measure (Long Term ASM),"
    b"Unsolicited_SMS,Insolvency_Resolution_Process(IRP),"
    b"Short_Term_Additional_Surveillance_Measure (Short Term ASM)\n"
    b"101,INFY,N,A,EQ,100,100,100,100,100\n"
)


def _production_fixture(tmp_path):
    journal_path = tmp_path / "operations.sqlite3"
    journal = OperationalJournal(journal_path)
    journal.append(EventAppend(
        stream_id="seed", event_type="SeedRecorded", payload={},
        idempotency_key="seed", expected_version=0, occurred_at=NOW,
    ))
    secrets_path = tmp_path / "runtime-secrets.json"
    secrets = RuntimeSecretStore.bootstrap(secrets_path)
    surveillance_path = tmp_path / "surveillance.json"
    preflight_at = datetime(2026, 7, 20, 3, 1, tzinfo=timezone.utc)
    preflight = SwingSessionPolicy().due_tasks(preflight_at).tasks[0]
    ledger = SchedulerLedger(journal)
    claim = ledger.claim(preflight, occurred_at=preflight_at)
    SurveillancePreflightSession(
        journal=journal,
        destination=surveillance_path,
        issuer_id="market-surveillance",
        secret=secrets["market-surveillance"],
        fetch=lambda _url: REGULATORY_CSV,
        retry_backoff_seconds=0,
    ).prepare(
        trading_date=date(2026, 7, 20),
        observed_at=preflight_at,
        command_id=preflight.task_id,
    )
    ledger.complete(
        preflight.task_id,
        claimant_id=claim.record.claimant_id,
        occurred_at=preflight_at.replace(second=1),
        detail="surveillance ready",
        reason_codes=("SURVEILLANCE_PREFLIGHT_READY",),
    )
    prices = tmp_path / "prices"
    prices.mkdir()
    index = pd.date_range(end="2026-07-17", periods=220, freq="B")
    pd.DataFrame({
        "open": [1500.0] * len(index), "high": [1510.0] * len(index),
        "low": [1490.0] * len(index), "close": [1500.0] * len(index),
        "volume": [100_000.0] * len(index),
    }, index=index).to_parquet(prices / "INFY.parquet")
    risk = tmp_path / "risk.yaml"
    risk.write_text("""capital: 50000
max_risk_per_trade_pct: 2.0
max_position_pct: 20.0
max_open_positions: 5
daily_loss_halt_pct: 5.0
weekly_loss_halt_pct: 10.0
max_drawdown_pct: 40.0
stop_loss_mandatory: true
min_avg_daily_turnover_inr: 50000000
leverage: false
banned_surveillance_stages: [2, 3, 4]
allowed_products: [CNC]
""")
    playbook = tmp_path / "playbook.json"
    playbook.write_text('{"strategies": []}')
    config = tmp_path / "scheduler.json"
    config.write_text(json.dumps({
        "execution_backend": "governed_paper",
        "runtime_secrets_path": str(secrets_path),
        "surveillance_path": str(surveillance_path),
        "risk_path": str(risk), "playbook_path": str(playbook),
        "prices_path": str(prices),
        "provenance_path": str(tmp_path / "provenance"),
        "legacy_positions_path": str(tmp_path / "missing-positions.json"),
        "closed_dates": [],
    }))
    return journal_path, config, surveillance_path


def test_rehearsal_runs_production_composition_without_changing_source(tmp_path):
    journal_path, config, surveillance = _production_fixture(tmp_path)
    journal_before = journal_path.read_bytes()
    surveillance_before = surveillance.read_bytes()

    report = PaperEntryRehearsal(
        journal_path=journal_path, config_path=config,
    ).run(as_of=NOW)

    assert report.state is RehearsalState.NO_SIGNAL
    assert report.reason_codes == ("NO_CANONICAL_SIGNAL",)
    assert report.production_events_before == report.production_events_after
    assert report.production_events_before > 0
    assert report.sandbox_events_added > 0
    assert report.production_state_unchanged is True
    assert report.real_order_submitted is False
    assert journal_path.read_bytes() == journal_before
    assert surveillance.read_bytes() == surveillance_before


def test_dispatch_requires_recording_gateway_evidence():
    result = {"task_results": [{"outcome": {
        "reason_codes": ["GOVERNED_PAPER_DISPATCHED"],
        "detail": "paper dispatched",
    }}]}

    blocked = classify_rehearsal_outcome(result, gateway_commands=0)
    would_trade = classify_rehearsal_outcome(result, gateway_commands=1)

    assert blocked[0] is RehearsalState.BLOCKED
    assert blocked[1] == ("REHEARSAL_GATEWAY_EVIDENCE_MISSING",)
    assert would_trade[0] is RehearsalState.WOULD_TRADE


def test_rehearsal_fails_closed_when_configuration_is_missing(tmp_path):
    OperationalJournal(tmp_path / "operations.sqlite3")
    report = PaperEntryRehearsal(
        journal_path=tmp_path / "operations.sqlite3",
        config_path=tmp_path / "missing.json",
    ).run(as_of=NOW)

    assert report.state is RehearsalState.BLOCKED
    assert report.reason_codes == ("REHEARSAL_CONFIGURATION_UNAVAILABLE",)


def test_rehearsal_rejects_non_governed_execution_backend(tmp_path):
    OperationalJournal(tmp_path / "operations.sqlite3")
    config = tmp_path / "scheduler.json"
    config.write_text('{"execution_backend":"legacy_paper"}')

    report = PaperEntryRehearsal(
        journal_path=tmp_path / "operations.sqlite3", config_path=config,
    ).run(as_of=NOW)

    assert report.state is RehearsalState.BLOCKED
    assert report.reason_codes == (
        "REHEARSAL_REQUIRES_GOVERNED_PAPER_BACKEND",
    )
