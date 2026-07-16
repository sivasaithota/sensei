import json
from datetime import datetime, timedelta, timezone

from sensei.automation.scheduling import (
    SchedulerTaskKind,
    ScheduledTask,
    scheduled_task_id,
)
from sensei.automation.shadow import ShadowTrialPolicy
from sensei.automation.shadow_session import (
    AdoptedOosEvidenceCatalog,
    DailyCanonicalShadowSession,
)
from sensei.governance.evidence import StageDossierRegistry
from sensei.governance.lifecycle import EvidenceKind
from sensei.strategy import StrategyPlanCatalog
from tests.test_shadow_trial_automation import _shadow_system
from tests.test_strategy_plan import hammer_bars


def _playbook(
    tmp_path,
    *,
    name="strategy-a",
    adopted=True,
    trades=40,
    expectancy=0.5,
    hit_rate=0.4,
):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "playbook.json"
    path.write_text(
        json.dumps(
            {
                "version": "2026-07-16",
                "universe_size": 50,
                "thresholds": {
                    "min_trades_oos": 30,
                    "min_expectancy_pct": 0.3,
                    "min_hit_rate": 0.35,
                },
                "strategies": [
                    {
                        "name": name,
                        "adopted": adopted,
                        "out_of_sample": {
                            "trades": trades,
                            "expectancy_pct": expectancy,
                            "hit_rate": hit_rate,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_adopted_oos_catalog_returns_threshold_bound_evidence(tmp_path):
    evidence = AdoptedOosEvidenceCatalog(_playbook(tmp_path)).for_strategy(
        "strategy-a"
    )

    assert evidence is not None
    assert evidence["playbook_version"] == "2026-07-16"
    assert evidence["strategy_name"] == "strategy-a"
    assert evidence["out_of_sample"]["trades"] == 40
    assert evidence["thresholds"]["min_trades_oos"] == 30
    assert evidence["thresholds_satisfied"] is True


def test_adopted_oos_catalog_fails_closed_on_unadopted_or_weak_result(tmp_path):
    unadopted = AdoptedOosEvidenceCatalog(
        _playbook(tmp_path / "unadopted", adopted=False)
    )
    weak = AdoptedOosEvidenceCatalog(
        _playbook(tmp_path / "weak", trades=29)
    )

    assert unadopted.for_strategy("strategy-a") is None
    assert weak.for_strategy("strategy-a") is None
    assert weak.for_strategy("missing") is None


def test_adopted_oos_catalog_rejects_self_weakened_playbook_thresholds(tmp_path):
    path = _playbook(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["thresholds"]["min_trades_oos"] = 1
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert AdoptedOosEvidenceCatalog(path).for_strategy("strategy-a") is None


def test_paper_dossier_binds_historical_oos_and_forward_shadow(
    tmp_path, monkeypatch
):
    journal, record, lifecycle = _shadow_system(tmp_path)
    issuer = "governance-issuer"
    producer = "shadow-trial-producer"
    dossiers = StageDossierRegistry(
        journal,
        trusted_issuer_ids=frozenset({issuer}),
        trusted_producers_by_kind={
            EvidenceKind.SHADOW_TRIAL: frozenset({producer})
        },
    )
    bars = hammer_bars()
    session_date = bars.index[-1].date()
    now = datetime.combine(
        session_date,
        datetime.min.time(),
        tzinfo=timezone.utc,
    ) + timedelta(hours=18)
    monkeypatch.setattr(
        "sensei.automation.shadow_session.available_symbols",
        lambda: ("NSE:TEST",),
    )
    monkeypatch.setattr(
        "sensei.automation.shadow_session.load_prices", lambda _symbol: bars
    )
    artifacts = tmp_path / "artifacts"
    policy_version = "test-policy"
    task = ScheduledTask(
        task_id=scheduled_task_id(
            kind=SchedulerTaskKind.END_OF_DAY_SESSION,
            trading_date=session_date,
            policy_version=policy_version,
        ),
        kind=SchedulerTaskKind.END_OF_DAY_SESSION,
        trading_date=session_date,
        due_at=now,
        expires_at=now + timedelta(hours=1),
        policy_version=policy_version,
    )

    session = DailyCanonicalShadowSession(
        journal=journal,
        catalog=StrategyPlanCatalog(journal),
        lifecycle=lifecycle,
        dossiers=dossiers,
        issuer_id=issuer,
        shadow_trial_producer_id=producer,
        artifact_root=artifacts,
        policy=ShadowTrialPolicy(minimum_sessions=1),
        playbook_path=_playbook(tmp_path / "playbook", name="hammer"),
    )
    outcome = session(task, now)

    assert "paper-ready evidence=1" in outcome.detail
    artifact = next(
        json.loads(path.read_text(encoding="utf-8"))
        for path in artifacts.glob("*.json")
        if json.loads(path.read_text(encoding="utf-8"))["evidence_kind"]
        == "shadow_trial"
    )
    evidence = artifact["evidence"]
    assert evidence["assessment_type"] == "accelerated_paper_readiness"
    assert evidence["sessions"] == 1
    assert evidence["historical_oos"]["thresholds_satisfied"] is True
    assert evidence["historical_oos"]["strategy_name"] == record.source_rule_name
    events = journal.read_all()
    policy_event = next(
        event for event in events if event.event_type == "ShadowTrialPolicyRegistered"
    )
    observation_event = next(
        event for event in events if event.event_type == "ShadowSessionObserved"
    )
    assert policy_event.global_sequence < observation_event.global_sequence
    assert policy_event.payload["forward_operational_policy"]["minimum_sessions"] == 1
    assert policy_event.payload["historical_oos"]["playbook_content_id"].startswith(
        "sha256:"
    )
