from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd

from sensei.governance.evidence import (
    DossierOutcome,
    StageDossierIssue,
    StageDossierRegistry,
    StageEvidenceEnvelope,
)
from sensei.governance.lifecycle import EvidenceKind
from sensei.operations import EventAppend, OperationalJournal
import sensei.reporting.prelive as prelive
from sensei.reporting.prelive import PreLiveCertifier


NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


def _capital_evidence(
    journal,
    artifact_root: Path,
    *,
    plan_id: str,
    lineage_id: str = "strategy:test",
    capital_ready: bool,
):
    artifact_root.mkdir(parents=True)
    control_refs = {}
    dataset_manifest_id = None
    dataset_request = {
        "universe": "NIFTY_TEST",
        "history_start": "2026-01-02",
        "as_of": "2026-01-06",
        "frequency": "1d",
    }
    snapshot_id = "sha256:" + "0" * 64
    if capital_ready:
        bars_dir = artifact_root / "bars"
        actions_dir = artifact_root / "actions"
        bars_dir.mkdir(exist_ok=True)
        actions_dir.mkdir(exist_ok=True)
        bars_path = bars_dir / "INE-ONE.parquet"
        index = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"])
        pd.DataFrame(
            {
                "open": [100.0, 101.0, 102.0],
                "high": [102.0, 103.0, 104.0],
                "low": [99.0, 100.0, 101.0],
                "close": [101.0, 102.0, 103.0],
                "volume": [1000, 1100, 1200],
            },
            index=index,
        ).to_parquet(bars_path)
        actions_path = actions_dir / "INE-ONE.csv"
        actions_path.write_text("date,type,factor\n2026-01-05,split,2\n")
        membership_path = artifact_root / "membership.csv"
        membership_path.write_text(
            "universe,instrument_id,symbol,effective_from,effective_to\n"
            "NIFTY_TEST,INE-ONE,ONE,2026-01-01,\n"
        )

        def reference(path: Path, rows: int) -> dict[str, object]:
            return {
                "path": str(path.relative_to(artifact_root)),
                "sha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
                "rows": rows,
            }

        dataset_manifest = {
            "schema_version": 1,
            "catalog_id": "fixture.capital-ready",
            "issuer": "trusted-market-data-issuer",
            "source": {
                "provider": "fixture",
                "dataset": "pit-adjusted",
                "uri": "fixture://pit-adjusted",
                "retrieved_at": "2026-01-06",
                "usage_rights": "test-only",
            },
            "market": {
                "calendar": "XNSE",
                "timezone": "Asia/Kolkata",
                "currency": "INR",
                "frequency": "1d",
            },
            "membership": reference(membership_path, 1),
            "instruments": [
                {
                    "instrument_id": "INE-ONE",
                    "exchange": "NSE",
                    "display_symbol": "ONE",
                    "adjustment_policy": "split_adjusted",
                    "bars": reference(bars_path, 3),
                    "corporate_actions": reference(actions_path, 1),
                }
            ],
        }
        dataset_encoded = json.dumps(
            dataset_manifest, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        dataset_digest = hashlib.sha256(dataset_encoded).hexdigest()
        dataset_manifest_id = f"sha256:{dataset_digest}"
        (artifact_root / f"{dataset_digest}.json").write_bytes(
            dataset_encoded
        )
        snapshot_id = prelive.ManifestMarketDataCatalog(
            manifest_path=artifact_root / f"{dataset_digest}.json",
            trusted_issuers={"trusted-market-data-issuer"},
            trusted_manifest_ids={dataset_manifest_id},
        ).snapshot(prelive.SnapshotRequest(
            universe="NIFTY_TEST",
            history_start=datetime(2026, 1, 2).date(),
            as_of=datetime(2026, 1, 6).date(),
        )).snapshot_id
        portfolio_path = {
            "artifact_type": "capital_portfolio_path",
            "schema_version": "1.0",
            "plan_version_id": plan_id,
            "producer_id": "producer:examination_dossier",
            "verifier_id": "governance-dossier-service",
            "shared_cash": True,
            "sizing_rails": {"max_positions": 2, "max_position_pct": 0.75},
            "cost_model_id": "nse-delivery-v1",
            "initial_cash": 100_000.0,
            "total_costs": 125.0,
            "equity_path": [
                {
                    "session": "2026-01-02",
                    "cash": 59_600.0,
                    "positions": {"trade:one": 40_400.0},
                    "equity": 100_000.0,
                },
                {
                    "session": "2026-01-05",
                    "cash": 29_000.0,
                    "positions": {
                        "trade:one": 40_800.0,
                        "trade:two": 30_600.0,
                    },
                    "equity": 100_400.0,
                },
                {
                    "session": "2026-01-06",
                    "cash": 100_975.0,
                    "positions": {},
                    "equity": 100_975.0,
                },
            ],
            "trades": [
                {
                    "trade_id": "trade:one",
                    "instrument_id": "INE-ONE",
                    "entry_session": "2026-01-02",
                    "exit_session": "2026-01-06",
                    "quantity": 400,
                    "entry_price": 101.0,
                    "exit_price": 103.0,
                    "costs": 50.0,
                },
                {
                    "trade_id": "trade:two",
                    "instrument_id": "INE-ONE",
                    "entry_session": "2026-01-05",
                    "exit_session": "2026-01-06",
                    "quantity": 300,
                    "entry_price": 102.0,
                    "exit_price": 103.0,
                    "costs": 75.0,
                },
            ],
        }
        portfolio_id = _write_json_artifact(artifact_root, portfolio_path)
        holdout_ledger = {
            "artifact_type": "locked_holdout_access_ledger",
            "schema_version": "1.0",
            "plan_version_id": plan_id,
            "holdout_id": "holdout:one-use",
            "access_count": 1,
            "verifier_id": "governance-dossier-service",
        }
        holdout_ledger_id = _write_json_artifact(artifact_root, holdout_ledger)
        corporate_action_id = reference(actions_path, 1)["sha256"]
        for control in prelive._CAPITAL_EVIDENCE_FLAGS:
            protocol = {
                "artifact_type": "capital_control_protocol",
                "schema_version": "1.0",
                "plan_version_id": plan_id,
                "control": control,
                "producer_id": "producer:examination_dossier",
                "registered_at": "2026-01-01T00:00:00+00:00",
                "criteria": _protocol_criteria(control),
            }
            protocol_encoded = json.dumps(
                protocol, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            protocol_digest = hashlib.sha256(protocol_encoded).hexdigest()
            (artifact_root / f"{protocol_digest}.json").write_bytes(
                protocol_encoded
            )
            result_payload = {
                "artifact_type": "capital_control_result",
                "schema_version": "1.0",
                "plan_version_id": plan_id,
                "control": control,
                "outcome": "passed",
                "producer_id": "producer:examination_dossier",
                "verifier_id": "governance-dossier-service",
                "protocol_content_id": f"sha256:{protocol_digest}",
                "dataset_manifest_content_id": f"sha256:{dataset_digest}",
                "dataset_request": dataset_request,
                "evaluated_at": "2026-01-07T00:00:00+00:00",
                "metrics": _control_metrics(
                    control,
                    snapshot_id,
                    portfolio_id=portfolio_id,
                    corporate_action_id=corporate_action_id,
                    holdout_ledger_id=holdout_ledger_id,
                ),
            }
            result_encoded = json.dumps(
                result_payload, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            result_digest = hashlib.sha256(result_encoded).hexdigest()
            (artifact_root / f"{result_digest}.json").write_bytes(
                result_encoded
            )
            _append(
                journal,
                f"capital-protocol:{plan_id[-8:]}:{control}",
                "CapitalProtocolRegistered",
                {
                    "plan_version_id": plan_id,
                    "control": control,
                    "protocol_content_id": f"sha256:{protocol_digest}",
                },
                occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            if control == "locked_holdout_passed":
                _append(
                    journal,
                    f"holdout-access:{plan_id[-8:]}",
                    "LockedHoldoutAccessed",
                    {
                        "plan_version_id": plan_id,
                        "holdout_id": "holdout:one-use",
                        "access_ledger_content_id": holdout_ledger_id,
                    },
                    occurred_at=datetime(2026, 1, 6, tzinfo=timezone.utc),
                )
            _append(
                journal,
                f"capital-result:{plan_id[-8:]}:{control}",
                "CapitalControlEvaluated",
                {
                    "plan_version_id": plan_id,
                    "control": control,
                    "result_content_id": f"sha256:{result_digest}",
                },
                occurred_at=datetime(2026, 1, 7, tzinfo=timezone.utc),
            )
            control_refs[control] = f"sha256:{result_digest}"
    payload = {
        "artifact_type": "stage_evidence",
        "evidence_kind": "examination_dossier",
        "lineage_id": lineage_id,
        "outcome": "passed",
        "plan_version_id": plan_id,
        "producer_id": "producer:examination_dossier",
        "schema_version": "1.0",
        "evidence": {
            "capital_readiness": control_refs,
        },
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    (artifact_root / f"{digest}.json").write_bytes(encoded)
    produced = _append(
        journal,
        f"evidence:{plan_id}",
        "StageEvidenceProduced",
        StageEvidenceEnvelope(
            lineage_id=lineage_id,
            plan_version_id=plan_id,
            evidence_kind=EvidenceKind.EXAMINATION_DOSSIER,
            producer_id="producer:examination_dossier",
            outcome=DossierOutcome.PASSED,
            artifact_content_id=f"sha256:{digest}",
        ).to_payload(),
    )
    registry = StageDossierRegistry(
        journal,
        trusted_issuer_ids=frozenset({"governance-dossier-service"}),
        trusted_producers_by_kind={
            EvidenceKind.EXAMINATION_DOSSIER: frozenset(
                {"producer:examination_dossier"}
            )
        },
    )
    dossier = registry.issue(
        StageDossierIssue(
            lineage_id=lineage_id,
            plan_version_id=plan_id,
            evidence_kind=EvidenceKind.EXAMINATION_DOSSIER,
            supporting_event_ids=(produced.event_id,),
            issuer_id="governance-dossier-service",
            producer_id="producer:examination_dossier",
            issued_at=NOW,
            outcome=DossierOutcome.PASSED,
        )
    )
    _append(
        journal,
        f"lifecycle:{plan_id}:examined",
        "StrategyLifecycleTransitioned",
        {
            "plan_version_id": plan_id,
            "lineage_id": lineage_id,
            "target_stage": "examined",
            "evidence_refs": [
                {
                    "kind": "examination_dossier",
                    "ref_id": dossier.dossier_id,
                }
            ],
        },
    )
    _append(
        journal,
        f"lifecycle:{plan_id}:paper",
        "StrategyLifecycleTransitioned",
        {
            "plan_version_id": plan_id,
            "lineage_id": lineage_id,
            "target_stage": "paper",
            "evidence_refs": [],
        },
    )
    return artifact_root / f"{digest}.json", dataset_manifest_id


def _write_json_artifact(root: Path, payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    (root / f"{digest}.json").write_bytes(encoded)
    return f"sha256:{digest}"


def _protocol_criteria(control: str) -> dict[str, object]:
    if control == "portfolio_level":
        return {"cost_model_id": "nse-delivery-v1", "max_drawdown_limit_pct": 10.0}
    if control == "point_in_time_universe":
        return {"minimum_sessions": 3, "minimum_instruments": 1}
    if control == "corporate_actions_adjusted":
        return {"accepted_adjustment_policies": ["split_adjusted"], "require_action_lineage": True}
    if control == "purged_walk_forward":
        return {"folds": 5, "purge_sessions": 5, "embargo_sessions": 5, "minimum_median_fold_cagr_pct": 1.0}
    if control == "multiple_testing_controlled":
        return {"hypotheses_tested": 10, "method": "holm", "adjusted_alpha": 0.01}
    return {"holdout_id": "holdout:one-use", "threshold": 1.0, "maximum_access_count": 1}


def _control_metrics(
    control: str,
    snapshot_id: str,
    *,
    portfolio_id: str,
    corporate_action_id: str,
    holdout_ledger_id: str,
) -> dict[str, object]:
    if control == "portfolio_level":
        return {
            "portfolio_path_content_id": portfolio_id,
            "shared_cash": True,
            "sizing_rails": True,
            "cost_model_id": "nse-delivery-v1",
            "max_drawdown_pct": 0.0,
            "cagr_pct": ((100_975 / 100_000) ** (365.25 / 4) - 1) * 100,
            "observations": 3,
        }
    if control == "point_in_time_universe":
        return {"snapshot_id": snapshot_id, "eligible_sessions": 3, "instrument_count": 1}
    if control == "corporate_actions_adjusted":
        return {
            "snapshot_id": snapshot_id,
            "adjustment_policies": ["split_adjusted"],
            "corporate_action_artifact_ids": [corporate_action_id],
        }
    if control == "purged_walk_forward":
        return {"folds": 5, "purge_sessions": 5, "embargo_sessions": 5, "median_fold_cagr_pct": 4.0}
    if control == "multiple_testing_controlled":
        return {"hypotheses_tested": 10, "method": "holm", "adjusted_alpha": 0.01, "passed": True}
    return {
        "holdout_id": "holdout:one-use",
        "access_ledger_content_id": holdout_ledger_id,
        "access_count": 1,
        "threshold": 1.0,
        "observed": 1.2,
        "passed": True,
    }


def _append(
    journal, stream, event_type, payload, *, correlation_id=None, occurred_at=NOW
):
    return journal.append(
        EventAppend(
            stream_id=stream,
            event_type=event_type,
            payload=payload,
            idempotency_key=f"{stream}:{event_type}",
            expected_version=len(journal.read_stream(stream)),
            occurred_at=occurred_at,
            correlation_id=correlation_id,
        )
    )


def test_certification_blocks_live_capital_until_exit_learning_is_proven(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    _append(
        journal,
        "lifecycle:plan",
        "StrategyLifecycleTransitioned",
        {"plan_version_id": "sha256:" + "a" * 64, "target_stage": "paper"},
    )

    report = PreLiveCertifier(
        journal_path=tmp_path / "operations.sqlite3",
        strategy_study=lambda: (
            {
                "name": "verified-strategy",
                "adopted": True,
                "out_of_sample": {
                    "trades": 100,
                    "expectancy_pct": 1.0,
                    "hit_rate": 0.45,
                },
            },
        ),
    ).run(generated_at=NOW)

    assert report.ready_for_live_capital is False
    assert "closed_episode_learning_chain" in report.blockers
    exit_check = next(
        check for check in report.checks
        if check.name == "governed_exit_capability"
    )
    assert exit_check.passed is True


def test_canary_review_rejects_legacy_trade_level_strategy_evidence(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    plan_id = "sha256:" + "b" * 64
    artifact_root = tmp_path / "governance-artifacts"
    _capital_evidence(
        journal,
        artifact_root,
        plan_id=plan_id,
        lineage_id="legacy-playbook:trend",
        capital_ready=False,
    )

    report = PreLiveCertifier(
        journal_path=tmp_path / "operations.sqlite3",
        governance_artifact_path=artifact_root,
        strategy_study=lambda: (
            {"name": "trend", "adopted": True, "out_of_sample": {}},
        ),
    ).run(generated_at=NOW)

    check = next(
        item for item in report.checks
        if item.name == "capital_strategy_evidence"
    )
    assert check.passed is False
    assert check.evidence["non_capital_ready_plan_ids"] == [plan_id]
    assert report.eligible_for_live_canary_review is False


def test_canary_review_accepts_hash_verified_capital_strategy_evidence(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    plan_id = "sha256:" + "c" * 64
    artifact_root = tmp_path / "governance-artifacts"
    _, manifest_id = _capital_evidence(
        journal,
        artifact_root,
        plan_id=plan_id,
        capital_ready=True,
    )

    report = PreLiveCertifier(
        journal_path=tmp_path / "operations.sqlite3",
        governance_artifact_path=artifact_root,
        trusted_market_data_manifest_ids=frozenset({manifest_id}),
        trusted_market_data_issuers=frozenset({"trusted-market-data-issuer"}),
        strategy_study=lambda: (
            {"name": "verified", "adopted": True, "out_of_sample": {}},
        ),
    ).run(generated_at=NOW)

    check = next(
        item for item in report.checks
        if item.name == "capital_strategy_evidence"
    )
    assert check.passed is True
    assert check.evidence["capital_ready_plan_ids"] == [plan_id]


def test_canary_review_rejects_self_asserted_market_data_trust(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    plan_id = "sha256:" + "e" * 64
    artifact_root = tmp_path / "governance-artifacts"
    _capital_evidence(
        journal,
        artifact_root,
        plan_id=plan_id,
        capital_ready=True,
    )

    report = PreLiveCertifier(
        journal_path=tmp_path / "operations.sqlite3",
        governance_artifact_path=artifact_root,
        strategy_study=lambda: (
            {"name": "verified", "adopted": True, "out_of_sample": {}},
        ),
    ).run(generated_at=NOW)

    check = next(
        item for item in report.checks
        if item.name == "capital_strategy_evidence"
    )
    assert check.passed is False
    assert check.evidence["failure_reasons_by_plan"][plan_id] == [
        "capital_dataset_not_admissible:corporate_actions_adjusted",
        "capital_dataset_not_admissible:locked_holdout_passed",
        "capital_dataset_not_admissible:multiple_testing_controlled",
        "capital_dataset_not_admissible:point_in_time_universe",
        "capital_dataset_not_admissible:portfolio_level",
        "capital_dataset_not_admissible:purged_walk_forward",
    ]


def test_paper_certification_handles_null_examination_references(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    plan_id = "sha256:" + "f" * 64
    _append(
        journal,
        "lifecycle:malformed",
        "StrategyLifecycleTransitioned",
        {
            "plan_version_id": plan_id,
            "lineage_id": "strategy:malformed",
            "target_stage": "examined",
            "evidence_refs": None,
        },
    )
    _append(
        journal,
        "lifecycle:paper",
        "StrategyLifecycleTransitioned",
        {
            "plan_version_id": plan_id,
            "lineage_id": "strategy:malformed",
            "target_stage": "paper",
            "evidence_refs": [],
        },
    )

    report = PreLiveCertifier(
        journal_path=tmp_path / "operations.sqlite3",
        strategy_study=lambda: (
            {"name": "verified", "adopted": True, "out_of_sample": {}},
        ),
    ).run(generated_at=NOW)

    assert report.ready_for_live_capital is False
    check = next(
        item for item in report.checks
        if item.name == "capital_strategy_evidence"
    )
    assert check.evidence["failure_reasons_by_plan"][plan_id] == [
        "missing_passed_examination_dossier"
    ]


def test_canary_review_rejects_capital_evidence_changed_after_issuance(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    plan_id = "sha256:" + "d" * 64
    artifact_root = tmp_path / "governance-artifacts"
    (examination_artifact, manifest_id) = _capital_evidence(
        journal,
        artifact_root,
        plan_id=plan_id,
        capital_ready=True,
    )
    examination_artifact.write_text("{}", encoding="utf-8")

    report = PreLiveCertifier(
        journal_path=tmp_path / "operations.sqlite3",
        governance_artifact_path=artifact_root,
        trusted_market_data_manifest_ids=frozenset({manifest_id}),
        trusted_market_data_issuers=frozenset({"trusted-market-data-issuer"}),
        strategy_study=lambda: (
            {"name": "verified", "adopted": True, "out_of_sample": {}},
        ),
    ).run(generated_at=NOW)

    check = next(
        item for item in report.checks
        if item.name == "capital_strategy_evidence"
    )
    assert check.passed is False
    assert check.evidence["failure_reasons_by_plan"][plan_id] == [
        "governance_artifact_hash_mismatch"
    ]


def test_certification_requires_one_complete_nine_role_cycle(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    cycle = "cycle:one"
    _append(
        journal,
        "desk-cycle:one",
        "DeskCycleCompleted",
        {"cycle_id": cycle},
        correlation_id=cycle,
    )
    for role in ("orchestrator", "historian", "reporter"):
        _append(
            journal,
            f"role:{role}",
            "DeskRoleCompleted",
            {"role": role},
            correlation_id=cycle,
        )

    report = PreLiveCertifier(
        journal_path=tmp_path / "operations.sqlite3",
        strategy_study=lambda: (
            {"name": "verified-strategy", "adopted": True, "out_of_sample": {}},
        ),
    ).run(generated_at=NOW)

    check = next(
        item for item in report.checks
        if item.name == "nine_agent_production_cycle"
    )
    assert check.passed is False
    assert check.evidence["roles_observed"] == [
        "historian",
        "orchestrator",
        "reporter",
    ]


def test_certification_rejects_a_fresh_strategy_replay_failure(tmp_path):
    OperationalJournal(tmp_path / "operations.sqlite3")

    report = PreLiveCertifier(
        journal_path=tmp_path / "operations.sqlite3",
        strategy_study=lambda: (
            {"name": "good", "adopted": True, "out_of_sample": {}},
            {"name": "bad", "adopted": False, "out_of_sample": {}},
        ),
    ).run(generated_at=NOW)

    check = next(
        item for item in report.checks
        if item.name == "fresh_historical_strategy_replay"
    )
    assert check.passed is False
    assert check.evidence["failed_names"] == ["bad"]


def test_live_entry_and_protection_must_share_one_filled_intent(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    for index, (kind, intent, filled) in enumerate((
        ("ENTRY", "intent:one", 1),
        ("PROTECTION", "intent:two", 0),
    )):
        _append(
            journal,
            f"gateway:{index}",
            "PaperGatewayCommandExecuted",
            {
                "command": {"kind": kind, "intent_id": intent},
                "receipt": {
                    "accepted": True,
                    "cumulative_fill_quantity": filled,
                },
            },
        )

    report = PreLiveCertifier(
        journal_path=tmp_path / "operations.sqlite3",
        strategy_study=lambda: (
            {"name": "verified", "adopted": True, "out_of_sample": {}},
        ),
    ).run(generated_at=NOW)

    check = next(
        item for item in report.checks
        if item.name == "paper_entry_and_protection"
    )
    assert check.passed is False
    assert check.evidence["qualifying_live_intent_ids"] == []


def test_isolated_production_rehearsal_proves_agents_committee_and_protection(
    tmp_path,
):
    journal_path = tmp_path / "operations.sqlite3"
    OperationalJournal(journal_path)
    config = tmp_path / "scheduler.json"
    config.write_text("{}")
    code_root = Path(prelive.__file__).resolve().parents[1]
    code_digest = hashlib.sha256()
    for item in sorted(code_root.rglob("*.py")):
        code_digest.update(str(item.relative_to(code_root)).encode())
        code_digest.update(item.read_bytes())
    rehearsal = tmp_path / "rehearsal.json"
    rehearsal.write_text(json.dumps({
        "as_of": NOW.isoformat(),
        "state": "WOULD_TRADE",
        "production_state_unchanged": True,
        "real_order_submitted": False,
        "diagnostics": {
            "roles_completed": [
                "orchestrator", "historian", "reporter", "crowd-reader",
                "analyst", "committee", "trader", "coach", "secretary",
            ],
            "committee_verdicts": [
                {"level": level} for level in ("L1", "L2", "L3", "L4")
            ],
            "sandbox_gateway_commands": 2,
            "gateway_command_kinds": ["ENTRY", "PROTECTION"],
            "gateway_command_intent_ids": ["intent:one", "intent:one"],
            "evidence_binding": {
                "source_journal_sha256": hashlib.sha256(
                    journal_path.read_bytes()
                ).hexdigest(),
                "scheduler_config_sha256": hashlib.sha256(
                    config.read_bytes()
                ).hexdigest(),
                "source_code_sha256": code_digest.hexdigest(),
                "source_events": 0,
            },
        },
    }))

    report = PreLiveCertifier(
        journal_path=journal_path,
        rehearsal_path=rehearsal,
        config_path=config,
        strategy_study=lambda: (
            {"name": "verified-strategy", "adopted": True, "out_of_sample": {}},
        ),
    ).run(generated_at=NOW)
    by_name = {check.name: check for check in report.checks}

    assert by_name["nine_agent_production_cycle"].passed is True
    assert by_name["l1_l4_committee_evidence"].passed is True
    assert by_name["paper_entry_and_protection"].passed is True
    assert by_name["governed_exit_capability"].passed is True
    assert by_name["closed_episode_learning_chain"].passed is False
    assert report.ready_for_unattended_paper is False
    assert report.ready_for_live_capital is False
