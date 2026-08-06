import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sensei.automation import SchedulerApplicationConfig
from sensei.governance.lifecycle import LifecycleStage
from sensei.operations import OperationalJournal
from sensei.runtime.production_replay import (
    complete_market_sessions,
    ProductionHistoricalDeskReplay,
    publish_replay_ingestion,
    preregister_replay_plans,
    publish_replay_surveillance,
    ReplayArtifactSandbox,
    ReplayCurrentSessionBarUnavailable,
    ReplayFrameCache,
    ReplayProductionPaperSession,
    _project_session_result,
)
from sensei.runtime import RuntimeSecretStore, VerifiedSurveillanceSource
from sensei.strategy import StrategyPlanCatalog


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_replay_frame_cache_reads_each_price_artifact_once(tmp_path):
    import pandas as pd

    path = tmp_path / "TEST.parquet"
    expected = pd.DataFrame(
        {"close": [100.0, 101.0]},
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
    )
    expected.to_parquet(path)
    reads = 0

    def load(candidate):
        nonlocal reads
        reads += 1
        return pd.read_parquet(candidate)

    cache = ReplayFrameCache(loader=load)

    first = cache.load(path)
    second = cache.load(path)

    assert first is second
    assert reads == 1


def test_replay_regime_excludes_symbol_without_current_session_bar():
    import pandas as pd

    index = pd.date_range("2025-01-01", periods=200, freq="B")
    usable = pd.DataFrame({
        "close": range(100, 300),
    }, index=index)

    class ReplayFixture(ReplayProductionPaperSession):
        def __init__(self):
            pass

        @staticmethod
        def _instruments():
            return ("NSE:MISSING", "NSE:USABLE")

        @staticmethod
        def _bars(instrument):
            if instrument == "NSE:MISSING":
                raise ReplayCurrentSessionBarUnavailable(
                    "CURRENT_SESSION_BAR_MISSING:MISSING:2025-10-07"
                )
            return usable

    regime = ReplayFixture()._regime()

    assert regime.n_symbols == 1


def _strategy_files(tmp_path):
    playbook = tmp_path / "playbook.json"
    rules = tmp_path / "rules.json"
    playbook.write_text(json.dumps({
        "version": "2025-01-01",
        "thresholds": {},
        "strategies": [{
            "name": "accepted",
            "adopted": True,
            "out_of_sample": {
                "trades": 100,
                "expectancy_pct": 1.0,
                "hit_rate": 0.5,
            },
        }],
    }))
    rules.write_text(json.dumps([{
        "name": "accepted",
        "source": "book",
        "principle": "trend",
        "conditions": [{
            "left": "close",
            "op": ">",
            "right": "sma_20",
            "factor": 1.0,
        }],
        "stop_pct": 5.0,
        "target_pct": 10.0,
        "max_hold_days": 20,
    }]))
    return playbook, rules


def test_replay_governance_starts_clean_and_preregisters_paper_plans(tmp_path):
    playbook, rules = _strategy_files(tmp_path)
    journal = OperationalJournal(tmp_path / "replay.sqlite3")
    config = SchedulerApplicationConfig(
        playbook_path=playbook,
        provenance_path=tmp_path / "provenance",
        execution_backend="governed_paper",
    )

    plan_ids = preregister_replay_plans(
        journal=journal,
        config=config,
        rules_path=rules,
        artifact_root=tmp_path / "artifacts",
        occurred_at=NOW,
    )

    assert len(plan_ids) == 1
    catalog = StrategyPlanCatalog(journal)
    assert [record.plan_id for record in catalog.list()] == list(plan_ids)
    assert not any(
        event.event_type in {
            "EpisodeStarted",
            "PaperGatewayCommandExecuted",
            "LearningObservationRecorded",
        }
        for event in journal.read_all()
    )
    from sensei.automation import GovernedSchedulerApplication

    app = GovernedSchedulerApplication(journal=journal, config=config)
    assert [
        record.plan_id
        for record in catalog.plans_at_stage(app.lifecycle, LifecycleStage.PAPER)
    ] == list(plan_ids)


def test_replay_sandbox_redirects_every_mutable_runtime_artifact(tmp_path):
    production = tmp_path / "production"
    production.mkdir()
    surveillance = production / "surveillance.json"
    surveillance.write_text('{"production":true}')
    positions = production / "positions.json"
    positions.write_text('{"positions":[]}')
    provenance = production / "provenance"
    provenance.mkdir()
    (provenance / "claim.json").write_text('{"production":true}')
    config_path = production / "scheduler.json"
    config_path.write_text(json.dumps({
        "execution_backend": "governed_paper",
        "surveillance_path": str(surveillance),
        "legacy_positions_path": str(positions),
        "provenance_path": str(provenance),
    }))
    before = {
        path: path.read_bytes()
        for path in (surveillance, positions, provenance / "claim.json")
    }

    sandbox = ReplayArtifactSandbox.materialize(
        source_config_path=config_path,
        root=tmp_path / "sandbox",
    )
    replay_config = SchedulerApplicationConfig.from_json(sandbox.config_path)
    replay_config.surveillance_path.write_text('{"sandbox":true}')
    sandbox.earnings_cache_path.write_text('{"sandbox":true}')

    assert replay_config.surveillance_path.is_relative_to(sandbox.root)
    assert replay_config.legacy_positions_path.is_relative_to(sandbox.root)
    assert replay_config.provenance_path.is_relative_to(sandbox.root)
    assert sandbox.journal_path.is_relative_to(sandbox.root)
    assert all(path.read_bytes() == content for path, content in before.items())


def test_replay_sandbox_can_override_capital_without_mutating_production(tmp_path):
    risk = tmp_path / "risk.yaml"
    risk.write_text("capital: 50000\nmax_open_positions: 5\n")
    config = tmp_path / "scheduler.json"
    config.write_text(json.dumps({"risk_path": str(risk)}))

    sandbox = ReplayArtifactSandbox.materialize(
        source_config_path=config, root=tmp_path / "sandbox", capital=300_000,
    )

    replay = SchedulerApplicationConfig.from_json(sandbox.config_path)
    assert replay.risk_path.read_text().startswith("capital: 300000")
    assert risk.read_text().startswith("capital: 50000")


def test_replay_sandbox_rejects_invalid_capital(tmp_path):
    import pytest

    config = tmp_path / "scheduler.json"
    config.write_text("{}")
    for capital in (0, -1, float("nan"), float("inf"), True):
        with pytest.raises(ValueError, match="finite and positive"):
            ReplayArtifactSandbox.materialize(
                source_config_path=config,
                root=tmp_path / f"sandbox-{capital!s}",
                capital=capital,
            )


def test_replay_surveillance_is_signed_date_bound_and_final_preflight(tmp_path):
    secrets_path = tmp_path / "runtime-secrets.json"
    secrets = RuntimeSecretStore.bootstrap(secrets_path)
    config = SchedulerApplicationConfig(
        runtime_secrets_path=secrets_path,
        surveillance_path=tmp_path / "surveillance.json",
        execution_backend="governed_paper",
    )
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    entry_at = datetime(
        2026, 1, 5, 9, 21, tzinfo=ZoneInfo("Asia/Kolkata")
    )

    task = publish_replay_surveillance(
        journal=journal,
        config=config,
        symbols=("INFY", "TCS"),
        entry_at=entry_at,
    )

    verifier = VerifiedSurveillanceSource(
        config.surveillance_path,
        issuer_id="historical-replay-surveillance",
        secret=__import__("hashlib").sha256(
            b"sensei-historical-replay-surveillance-v1"
        ).digest(),
        maximum_age=timedelta(days=1),
        clock=lambda: entry_at,
    )
    assert verifier("INFY", entry_at.date()) == 0
    assert task.trading_date == entry_at.date()
    assert task.policy_version.endswith(":surveillance-0850")
    event = journal.read_stream(
        f"historical-replay-surveillance:{task.task_id}"
    )[0]
    assert event.payload["authority"] == "SIMULATION_ONLY"
    from sensei.automation.scheduling import (
        SchedulerTaskKind,
        SwingSessionPolicy,
    )
    from sensei.automation.surveillance import require_surveillance_preflight

    entry_task = next(
        value for value in SwingSessionPolicy().due_tasks(entry_at).tasks
        if value.kind is SchedulerTaskKind.ENTRY_SESSION
    )
    require_surveillance_preflight(
        journal_path=tmp_path / "operations.sqlite3",
        snapshot_path=config.surveillance_path,
        entry_task=entry_task,
        allowed_source_report_types=frozenset({
            "COUNTERFACTUAL_NEUTRAL_SURVEILLANCE"
        }),
        allow_simulation_authority=True,
    )
    import pytest
    from sensei.runtime import SurveillanceSourceUnavailable

    with pytest.raises(SurveillanceSourceUnavailable):
        require_surveillance_preflight(
            journal_path=tmp_path / "operations.sqlite3",
            snapshot_path=config.surveillance_path,
            entry_task=entry_task,
            allowed_source_report_types=frozenset({
                "COUNTERFACTUAL_NEUTRAL_SURVEILLANCE"
            }),
        )


def test_session_calendar_requires_declared_universe_completeness(tmp_path):
    prices = tmp_path / "prices"
    prices.mkdir()
    import pandas as pd

    for symbol, dates in {
        "A": ["2026-01-01", "2026-01-02", "2026-01-05"],
        "B": ["2026-01-01", "2026-01-02", "2026-01-05"],
        "C": ["2026-01-01", "2026-01-05"],
    }.items():
        pd.DataFrame(
            {"close": [100.0] * len(dates)},
            index=pd.to_datetime(dates),
        ).to_parquet(prices / f"{symbol}.parquet")

    sessions = complete_market_sessions(
        prices_path=prices,
        required_sessions=2,
        minimum_completeness=1.0,
    )

    assert sessions == (date(2026, 1, 1), date(2026, 1, 5))


def test_replay_ingestion_records_exact_point_in_time_universe(tmp_path):
    prices = tmp_path / "prices"
    prices.mkdir()
    import pandas as pd

    pd.DataFrame(
        {"close": [100.0]}, index=pd.to_datetime(["2026-01-02"])
    ).to_parquet(prices / "A.parquet")
    pd.DataFrame(
        {"close": [100.0]}, index=pd.to_datetime(["2026-01-01"])
    ).to_parquet(prices / "STALE.parquet")
    journal = OperationalJournal(tmp_path / "operations.sqlite3")

    event = publish_replay_ingestion(
        journal=journal,
        prices_path=prices,
        source_session=date(2026, 1, 2),
        target_session=date(2026, 7, 27),
        occurred_at=datetime(
            2026, 7, 27, 8, 20, tzinfo=ZoneInfo("Asia/Kolkata")
        ),
    )

    assert event.payload["eligible_symbols"] == ("A",)
    assert event.payload["failed_symbols"] == ("STALE",)
    assert event.payload["completeness"] == 0.5
    assert event.payload["authority"] == "SIMULATION_ONLY"


def test_halted_entry_task_can_never_be_certified_by_reason_spelling(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    result = _project_session_result(
        session=date(2026, 1, 2),
        events=(),
        entry={"task_results": [{
            "task": {"kind": "ENTRY_SESSION"},
            "outcome": {
                "state": "HALTED",
                "reason_codes": ["NO_AUTHORIZED_PLANS"],
                "detail": "halted",
            },
        }]},
        eod={"task_results": [{
            "task": {"kind": "END_OF_DAY_SESSION"},
            "outcome": {
                "state": "COMPLETED",
                "reason_codes": [],
                "detail": "done",
            },
        }]},
        entry_kind="ENTRY_SESSION",
        eod_kind="END_OF_DAY_SESSION",
        journal=journal,
    )

    assert result.completed is False
    assert any("ENTRY_SESSION:HALTED" in value for value in result.blockers)


def test_production_replay_admits_one_candidate_per_strategy_lineage(
    tmp_path, monkeypatch,
):
    import math
    import pandas as pd

    playbook, rules = _strategy_files(tmp_path)
    prices = tmp_path / "prices"
    prices.mkdir()
    index = pd.date_range("2025-01-01", periods=260, freq="B")
    instruments = tuple(
        (f"TEST{offset}", offset * 0.8)
        for offset in range(10)
    )
    for symbol, phase in instruments:
        closes = [
            100.0 + offset * 0.2 + math.sin(offset / 4 + phase) * 2
            for offset in range(len(index))
        ]
        pd.DataFrame({
            "open": closes,
            "high": [value * 1.01 for value in closes],
            "low": [value * 0.99 for value in closes],
            "close": closes,
            "volume": [1_000_000] * len(index),
        }, index=index).to_parquet(prices / f"{symbol}.parquet")
    secrets = tmp_path / "runtime-secrets.json"
    RuntimeSecretStore.bootstrap(secrets)
    risk = tmp_path / "risk.yaml"
    risk.write_text("""capital: 100000
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
    config_path = tmp_path / "scheduler.json"
    config_path.write_text(json.dumps({
        "execution_backend": "governed_paper",
        "runtime_secrets_path": str(secrets),
        "risk_path": str(risk),
        "playbook_path": str(playbook),
        "prices_path": str(prices),
        "provenance_path": str(tmp_path / "production-provenance"),
        "surveillance_path": str(tmp_path / "production-surveillance.json"),
        "legacy_positions_path": str(tmp_path / "positions.json"),
    }))
    sessions = complete_market_sessions(
        prices_path=prices,
        required_sessions=260,
        minimum_completeness=1.0,
    )[-2:]
    workspace = tmp_path / "replay"
    regime_calls = 0
    original_regime = ReplayProductionPaperSession._regime

    def counted_regime(session):
        nonlocal regime_calls
        regime_calls += 1
        return original_regime(session)

    monkeypatch.setattr(
        ReplayProductionPaperSession, "_regime", counted_regime
    )

    report = ProductionHistoricalDeskReplay(
        source_config_path=config_path,
        rules_path=rules,
        source_sessions=sessions,
        workspace=workspace,
        production_fingerprints=lambda: {},
    ).run()

    events = OperationalJournal.open_read_only(
        workspace / "operations.sqlite3"
    ).read_all()
    entries = [
        event.payload["command"]["instrument_id"]
        for event in events
        if event.event_type == "PaperGatewayCommandExecuted"
        and event.payload["command"]["kind"] == "ENTRY"
    ]
    initial_truth = [
        event.payload
        for event in events
        if event.event_type == "DeskSupervisorTruthCaptured"
        and event.payload["phase"] == "INITIAL"
    ]
    ranking = next(
        event.payload for event in events
        if event.event_type == "SignalRankingRecorded"
    )
    assert report.completed_sessions == 1
    assert report.sessions[0].completed is True
    assert report.sessions[0].coherent_agent_cycle is True
    assert len(entries) == 1
    assert set(entries) <= {symbol for symbol, _ in instruments}
    assert len(initial_truth) == 2
    assert len({
        truth["account_snapshot_id"] for truth in initial_truth
    }) == 2
    assert len({
        truth["broker_snapshot_id"] for truth in initial_truth
    }) == 2
    assert sum(
        event.event_type == "RiskFillApplied" for event in events
    ) == 1
    assert ranking["signal_candidate_count"] > 3
    assert regime_calls == 1
