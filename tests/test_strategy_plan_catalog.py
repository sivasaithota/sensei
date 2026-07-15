from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sensei.governance.lifecycle import (
    Authority,
    AuthorityRole,
    EvidenceKind,
    EvidenceRef,
    LifecycleStage,
    StrategyLifecycle,
    TransitionRequest,
)
from sensei.operations import JournalIntegrityError, OperationalJournal
from sensei.backtest.rulespec import Condition, RuleSpec
from sensei.strategy import StrategyPlanCatalog, convert_rule_spec

from tests.test_strategy_plan import hammer_follow_through_plan
from tests.test_strategy_rule_conversion import policy_for

NOW = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)


def test_catalog_persists_and_reloads_the_full_immutable_plan(tmp_path):
    path = tmp_path / "operations.sqlite3"
    spec = RuleSpec(
        name="catalog_v2_fixture",
        source="Research fixture",
        principle="Close above a scaled moving average.",
        conditions=(Condition(left="close", op=">", right="sma_20", factor=1.01),),
        stop_pct=5.0,
        target_pct=10.0,
        max_hold_days=10,
    )
    plan = convert_rule_spec(spec, policy=policy_for(spec))
    catalog = StrategyPlanCatalog(OperationalJournal(path))

    registered = catalog.register(
        lineage_id="catalog-v2-lineage",
        plan=plan,
        source_rule_name=spec.name,
        occurred_at=NOW,
        command_id="register-catalog-v2",
    )
    rebuilt = StrategyPlanCatalog(OperationalJournal(path))

    assert rebuilt.get(plan.plan_id) == registered
    assert rebuilt.list() == (registered,)
    assert registered.plan == plan


def test_catalog_registration_is_content_idempotent_but_not_mutable(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    catalog = StrategyPlanCatalog(journal)
    plan = hammer_follow_through_plan()
    original = catalog.register(
        lineage_id="hammer-follow-through",
        plan=plan,
        source_rule_name="sadekar_hammer_confirmation",
        occurred_at=NOW,
        command_id="register-hammer-v1",
    )

    repeated = catalog.register(
        lineage_id="hammer-follow-through",
        plan=plan,
        source_rule_name="sadekar_hammer_confirmation",
        occurred_at=NOW,
        command_id="register-hammer-v1-retry",
    )
    assert repeated == original

    with pytest.raises(JournalIntegrityError, match="immutable plan registration"):
        catalog.register(
            lineage_id="other-lineage",
            plan=plan,
            source_rule_name="renamed-source-rule",
            occurred_at=NOW,
            command_id="mutate-hammer-registration",
        )


def test_catalog_selects_only_plans_at_the_requested_lifecycle_stage(tmp_path):
    journal = OperationalJournal(tmp_path / "operations.sqlite3")
    catalog = StrategyPlanCatalog(journal)
    paper_plan = hammer_follow_through_plan()
    proposed_plan = paper_plan.model_copy(
        update={
            "exits": paper_plan.exits.model_copy(
                update={
                    "max_hold_sessions": paper_plan.exits.max_hold_sessions.model_copy(
                        update={"value": 21}
                    )
                }
            )
        }
    )
    for lineage, plan, command in (
        ("paper-lineage", paper_plan, "register-paper-plan"),
        ("proposed-lineage", proposed_plan, "register-proposed-plan"),
    ):
        catalog.register(
            lineage_id=lineage,
            plan=plan,
            source_rule_name=lineage,
            occurred_at=NOW,
            command_id=command,
        )

    proposer = Authority("scheduler-proposer", AuthorityRole.PROPOSER)
    governor = Authority("scheduler-governor", AuthorityRole.GOVERNOR)
    lifecycle = StrategyLifecycle(
        journal,
        evidence_verifier=lambda _request: True,
        trusted_actor_roles={
            proposer.actor_id: frozenset({AuthorityRole.PROPOSER}),
            governor.actor_id: frozenset({AuthorityRole.GOVERNOR}),
        },
    )
    revision = 0
    stages = (
        (LifecycleStage.PROPOSED, proposer, ()),
        (
            LifecycleStage.EXAMINED,
            governor,
            (EvidenceRef(EvidenceKind.EXAMINATION_DOSSIER, "evidence:exam"),),
        ),
        (
            LifecycleStage.SHADOW,
            governor,
            (
                EvidenceRef(EvidenceKind.SHADOW_READINESS, "evidence:ready"),
                EvidenceRef(EvidenceKind.CONFORMANCE_DOSSIER, "evidence:conformance"),
                EvidenceRef(EvidenceKind.LOCKED_CONFIRMATION, "evidence:confirm"),
            ),
        ),
        (
            LifecycleStage.PAPER,
            governor,
            (EvidenceRef(EvidenceKind.SHADOW_TRIAL, "evidence:shadow"),),
        ),
    )
    for stage, actor, evidence in stages:
        lifecycle.transition(
            TransitionRequest(
                lineage_id="paper-lineage",
                plan_version_id=paper_plan.plan_id,
                target_stage=stage,
                evidence_refs=evidence,
                authority=actor,
                expected_revision=revision,
                command_id=f"paper-{stage.value}",
                occurred_at=NOW,
            )
        )
        revision += 1
    lifecycle.transition(
        TransitionRequest(
            lineage_id="proposed-lineage",
            plan_version_id=proposed_plan.plan_id,
            target_stage=LifecycleStage.PROPOSED,
            evidence_refs=(),
            authority=proposer,
            expected_revision=0,
            command_id="proposed-plan-proposal",
            occurred_at=NOW,
        )
    )

    paper = catalog.plans_at_stage(lifecycle, LifecycleStage.PAPER)

    assert tuple(record.plan_id for record in paper) == (paper_plan.plan_id,)
