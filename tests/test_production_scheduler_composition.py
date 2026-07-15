import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from sensei.automation import GovernedSchedulerApplication
from sensei.operations import OperationalJournal
from sensei.runtime import RuntimeSecretStore, VerifiedSurveillanceSource


NOW = datetime(2026, 7, 16, 9, 25, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def test_scheduler_uses_real_supervisor_composition_when_no_plan_signals(tmp_path):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    secrets_path = tmp_path / "runtime-secrets.json"
    secrets = RuntimeSecretStore.bootstrap(secrets_path)
    surveillance_path = tmp_path / "surveillance.json"
    VerifiedSurveillanceSource.publish(
        surveillance_path,
        stages={"INFY": 0},
        session=date(2026, 7, 16),
        observed_at=NOW,
        issuer_id="market-surveillance",
        secret=secrets["market-surveillance"],
    )
    prices_path = tmp_path / "prices"
    prices_path.mkdir()
    index = pd.date_range(end="2026-07-15", periods=220, freq="B")
    pd.DataFrame(
        {
            "open": [1500.0] * len(index),
            "high": [1510.0] * len(index),
            "low": [1490.0] * len(index),
            "close": [1500.0] * len(index),
            "volume": [100_000.0] * len(index),
        },
        index=index,
    ).to_parquet(prices_path / "INFY.parquet")
    risk_path = tmp_path / "risk.yaml"
    risk_path.write_text(
        """capital: 50000
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
""",
        encoding="utf-8",
    )
    playbook_path = tmp_path / "playbook.json"
    playbook_path.write_text('{"strategies": []}', encoding="utf-8")
    config_path = tmp_path / "scheduler.json"
    config_path.write_text(
        json.dumps(
            {
                "execution_backend": "governed_paper",
                "runtime_secrets_path": str(secrets_path),
                "surveillance_path": str(surveillance_path),
                "risk_path": str(risk_path),
                "playbook_path": str(playbook_path),
                "prices_path": str(prices_path),
                "provenance_path": str(tmp_path / "provenance"),
                "legacy_positions_path": str(tmp_path / "missing-positions.json"),
            }
        ),
        encoding="utf-8",
    )

    result = GovernedSchedulerApplication.open(
        journal_path, config_path=config_path
    ).run_once(NOW)

    assert len(result.task_results) == 1
    assert result.task_results[0].outcome.reason_codes == ("NO_CANONICAL_SIGNAL",)
    event_types = [event.event_type for event in OperationalJournal(journal_path).read_all()]
    assert "DeskSupervisorCompleted" in event_types
    assert "PaperGatewayCommandExecuted" not in event_types
