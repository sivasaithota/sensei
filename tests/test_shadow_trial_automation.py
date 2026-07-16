from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from sensei.automation.shadow import (
    CanonicalShadowRunner,
    ShadowTrialLedger,
    ShadowTrialPolicy,
)
from sensei.governance.lifecycle import (
    Authority,
    AuthorityRole,
    LifecycleStage,
    StrategyLifecycle,
    TransitionRequest,
)
from sensei.operations import OperationalJournal
from sensei.strategy import StrategyPlanCatalog
from tests.test_strategy_plan import hammer_bars, hammer_follow_through_plan


def _shadow_system(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    plan = hammer_follow_through_plan()
    catalog = StrategyPlanCatalog(journal)
    record = catalog.register(
        lineage_id="hammer-lineage",
        plan=plan,
        source_rule_name="hammer",
        occurred_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        command_id="register-shadow-plan",
    )
    proposer = Authority("proposer", AuthorityRole.PROPOSER)
    governor = Authority("governor", AuthorityRole.GOVERNOR)
    lifecycle = StrategyLifecycle(
        journal,
        evidence_verifier=lambda _request: True,
        trusted_actor_roles={
            proposer.actor_id: frozenset({proposer.role}),
            governor.actor_id: frozenset({governor.role}),
        },
    )
    revision = 0
    for stage, authority, evidence in (
        (LifecycleStage.PROPOSED, proposer, ()),
        (LifecycleStage.EXAMINED, governor, ("examination_dossier",)),
        (
            LifecycleStage.SHADOW,
            governor,
            (
                "shadow_readiness",
                "conformance_dossier",
                "locked_confirmation",
            ),
        ),
    ):
        from sensei.governance.lifecycle import EvidenceKind, EvidenceRef

        lifecycle.transition(
            TransitionRequest(
                lineage_id=record.lineage_id,
                plan_version_id=record.plan_id,
                target_stage=stage,
                evidence_refs=tuple(
                    EvidenceRef(EvidenceKind(item), f"fixture:{item}")
                    for item in evidence
                ),
                authority=authority,
                expected_revision=revision,
                command_id=f"to-{stage.value}",
                occurred_at=datetime(2025, 1, 2 + revision, tzinfo=timezone.utc),
            )
        )
        revision += 1
    return journal, record, lifecycle


def test_shadow_runner_rejects_historical_backfill(tmp_path):
    journal, record, lifecycle = _shadow_system(tmp_path)
    runner = CanonicalShadowRunner(
        lifecycle=lifecycle,
        ledger=ShadowTrialLedger(journal),
    )
    bars = hammer_bars()

    with pytest.raises(ValueError, match="forward sessions"):
        runner.run_session(
            record=record,
            expected_instrument_ids=("NSE:TEST",),
            bars_by_instrument={"NSE:TEST": bars},
            evaluation_session=datetime(2025, 1, 3).date(),
            market_snapshot_id="sha256:" + "a" * 64,
            observed_at=datetime(2025, 1, 3, 18, 0, tzinfo=timezone.utc),
            command_id="backfill",
        )


def test_shadow_trial_counts_forward_sessions_signals_and_replays(tmp_path):
    journal, record, lifecycle = _shadow_system(tmp_path)
    ledger = ShadowTrialLedger(journal)
    runner = CanonicalShadowRunner(lifecycle=lifecycle, ledger=ledger)
    first = hammer_bars()
    second_index = first.index[-1] + pd.offsets.BDay()
    second = pd.concat(
        [
            first,
            pd.DataFrame(
                {
                    "open": [106.0],
                    "high": [108.0],
                    "low": [105.0],
                    "close": [107.0],
                    "volume": [1_000_000.0],
                },
                index=pd.DatetimeIndex([second_index]),
            ),
        ]
    )
    observed = datetime(2025, 1, 20, 12, 0, tzinfo=timezone.utc)

    first_record = runner.run_session(
        record=record,
        expected_instrument_ids=("NSE:TEST",),
        bars_by_instrument={"NSE:TEST": first},
        evaluation_session=first.index[-1].date(),
        market_snapshot_id="sha256:" + "b" * 64,
        observed_at=observed,
        command_id="shadow-day-1",
    )
    replay = runner.run_session(
        record=record,
        expected_instrument_ids=("NSE:TEST",),
        bars_by_instrument={"NSE:TEST": first},
        evaluation_session=first.index[-1].date(),
        market_snapshot_id="sha256:" + "b" * 64,
        observed_at=observed + timedelta(minutes=5),
        command_id="shadow-day-1-retry",
    )
    runner.run_session(
        record=record,
        expected_instrument_ids=("NSE:TEST",),
        bars_by_instrument={"NSE:TEST": second},
        evaluation_session=second.index[-1].date(),
        market_snapshot_id="sha256:" + "c" * 64,
        observed_at=observed + timedelta(days=1),
        command_id="shadow-day-2",
    )

    result = ledger.assess(
        lineage_id=record.lineage_id,
        plan_id=record.plan_id,
        policy=ShadowTrialPolicy(
            minimum_sessions=2,
            minimum_signals=1,
            minimum_signal_instruments=1,
            minimum_data_completeness=1.0,
        ),
        no_later_than=observed + timedelta(days=2),
    )

    assert replay == first_record
    assert result.passed is True
    assert result.sessions == 2
    assert result.signals >= 1
    assert result.signal_instruments == 1
    assert result.data_completeness == 1.0
    assert result.error_count == 0
    assert len(result.supporting_event_ids) == 2


def test_missing_expected_market_data_keeps_shadow_trial_unready(tmp_path):
    journal, record, lifecycle = _shadow_system(tmp_path)
    ledger = ShadowTrialLedger(journal)
    runner = CanonicalShadowRunner(lifecycle=lifecycle, ledger=ledger)
    bars = hammer_bars()
    observed = datetime(2025, 1, 20, 12, 0, tzinfo=timezone.utc)

    runner.run_session(
        record=record,
        expected_instrument_ids=("NSE:MISSING", "NSE:TEST"),
        bars_by_instrument={"NSE:TEST": bars},
        evaluation_session=bars.index[-1].date(),
        market_snapshot_id="sha256:" + "d" * 64,
        observed_at=observed,
        command_id="shadow-with-gap",
    )
    result = ledger.assess(
        lineage_id=record.lineage_id,
        plan_id=record.plan_id,
        policy=ShadowTrialPolicy(
            minimum_sessions=1,
            minimum_signals=1,
            minimum_signal_instruments=1,
            minimum_data_completeness=0.99,
        ),
        no_later_than=observed,
    )

    assert result.passed is False
    assert result.data_completeness == 0.5
    assert result.error_count == 1
    assert "SHADOW_DATA_INCOMPLETE" in result.reason_codes
    assert "SHADOW_EVALUATION_ERRORS" in result.reason_codes


def test_default_shadow_policy_is_an_operational_gate_for_paper():
    policy = ShadowTrialPolicy()

    assert policy.minimum_sessions == 5
    assert policy.minimum_signals == 0
    assert policy.minimum_signal_instruments == 0
    assert policy.minimum_data_completeness == 0.99
    assert policy.require_zero_errors is True
