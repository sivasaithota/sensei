import json
import stat
from datetime import date, datetime, timedelta, timezone

import pytest

from sensei.runtime.activation import (
    RuntimeSecretStore,
    RuntimeTrustError,
    NseSurveillanceRefresher,
    VerifiedSurveillanceSource,
)
from sensei.kernel import RecordingPaperGateway
from sensei.operations import OperationalJournal
from sensei.portfolio_risk import AccountPosition, AccountSnapshot
from sensei.runtime import PaperAccountProjector


UTC = timezone.utc
NOW = datetime(2026, 7, 16, 3, 30, tzinfo=UTC)


def test_runtime_secret_store_bootstraps_private_complete_material(tmp_path):
    path = tmp_path / "runtime-secrets.json"

    created = RuntimeSecretStore.bootstrap(path)
    loaded = RuntimeSecretStore.load(path)

    assert created == loaded
    assert set(loaded) == set(RuntimeSecretStore.REQUIRED_ISSUERS)
    assert all(len(secret) >= 32 for secret in loaded.values())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_runtime_secret_store_rejects_group_readable_material(tmp_path):
    path = tmp_path / "runtime-secrets.json"
    RuntimeSecretStore.bootstrap(path)
    path.chmod(0o640)

    with pytest.raises(RuntimeTrustError, match="0600"):
        RuntimeSecretStore.load(path)


def test_runtime_secret_store_rejects_symlink(tmp_path):
    actual = tmp_path / "actual.json"
    RuntimeSecretStore.bootstrap(actual)
    link = tmp_path / "runtime-secrets.json"
    link.symlink_to(actual)

    with pytest.raises(RuntimeTrustError, match="regular owner file"):
        RuntimeSecretStore.load(link)


def test_surveillance_source_requires_fresh_signed_exact_session(tmp_path):
    secret_path = tmp_path / "runtime-secrets.json"
    secrets = RuntimeSecretStore.bootstrap(secret_path)
    snapshot_path = tmp_path / "surveillance.json"
    VerifiedSurveillanceSource.publish(
        snapshot_path,
        stages={"INFY": 0, "TCS": 2},
        session=date(2026, 7, 16),
        observed_at=NOW,
        issuer_id="market-surveillance",
        secret=secrets["market-surveillance"],
    )
    source = VerifiedSurveillanceSource(
        snapshot_path,
        issuer_id="market-surveillance",
        secret=secrets["market-surveillance"],
        maximum_age=timedelta(minutes=15),
        clock=lambda: NOW + timedelta(minutes=5),
    )

    assert source("INFY", date(2026, 7, 16)) == 0
    assert source("TCS", date(2026, 7, 15)) is None

    payload = json.loads(snapshot_path.read_text())
    payload["stages"]["INFY"] = 1
    snapshot_path.write_text(json.dumps(payload))
    with pytest.raises(RuntimeTrustError, match="signature"):
        source("INFY", date(2026, 7, 16))


def test_surveillance_source_rejects_stale_snapshot(tmp_path):
    secret_path = tmp_path / "runtime-secrets.json"
    secrets = RuntimeSecretStore.bootstrap(secret_path)
    snapshot_path = tmp_path / "surveillance.json"
    VerifiedSurveillanceSource.publish(
        snapshot_path,
        stages={"INFY": 0},
        session=date(2026, 7, 16),
        observed_at=NOW,
        issuer_id="market-surveillance",
        secret=secrets["market-surveillance"],
    )

    source = VerifiedSurveillanceSource(
        snapshot_path,
        issuer_id="market-surveillance",
        secret=secrets["market-surveillance"],
        maximum_age=timedelta(minutes=15),
        clock=lambda: NOW + timedelta(minutes=16),
    )
    assert source("INFY", date(2026, 7, 16)) is None


def test_account_projection_includes_reconciled_pre_cutover_exposure(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    gateway = RecordingPaperGateway(journal)
    baseline = AccountSnapshot(
        available_cash_paise=8_000_000,
        marked_equity_paise=10_000_000,
        high_water_mark_paise=10_500_000,
        day_pnl_paise=-10_000,
        week_pnl_paise=25_000,
        positions=(AccountPosition("INFY", 10, 2_000_000, 100_000),),
        included_reservation_ids=(),
        reconciled=True,
        captured_at=NOW,
    )
    projector = PaperAccountProjector(
        gateway,
        starting_capital_paise=10_000_000,
        high_water_mark_paise=10_000_000,
        baseline_snapshot_source=lambda captured_at, marks: baseline,
    )

    projected = projector.project(captured_at=NOW, mark_prices_paise={"INFY": 200_000})

    assert projected.positions == baseline.positions
    assert projected.available_cash_paise == 8_000_000
    assert projected.marked_equity_paise == 10_000_000
    assert projected.high_water_mark_paise == 10_500_000


def test_nse_regulatory_indicator_refreshes_signed_daily_surveillance(tmp_path):
    secrets = RuntimeSecretStore.bootstrap(tmp_path / "runtime-secrets.json")
    destination = tmp_path / "surveillance.json"
    csv_bytes = (
        b"101,INFY,N,A,EQ,100,100,100,100,100\n"
        b"102,RISKY,N,A,EQ,3,100,100,2,100\n"
    )
    requested = []
    refresher = NseSurveillanceRefresher(
        destination=destination,
        issuer_id="market-surveillance",
        secret=secrets["market-surveillance"],
        fetch=lambda url: requested.append(url) or csv_bytes,
    )

    stages = refresher.refresh(session=date(2026, 7, 16), observed_at=NOW)

    assert stages == {"INFY": 0, "RISKY": 3}
    assert requested == [
        "https://nsearchives.nseindia.com/content/equities/REG_IND160726.csv"
    ]
    source = VerifiedSurveillanceSource(
        destination,
        issuer_id="market-surveillance",
        secret=secrets["market-surveillance"],
        maximum_age=timedelta(minutes=15),
        clock=lambda: NOW,
    )
    assert source("INFY", date(2026, 7, 16)) == 0
    assert source("RISKY", date(2026, 7, 16)) == 3
