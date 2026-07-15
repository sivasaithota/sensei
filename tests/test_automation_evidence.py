from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sensei.automation.evidence import (
    ArtifactIntegrityError,
    ImmutableJsonArtifactStore,
    PlanStaticEvidenceProducer,
    StageEvidencePublisher,
)
from sensei.governance.evidence import (
    DossierOutcome,
    StageDossierRegistry,
)
from sensei.governance.lifecycle import EvidenceKind
from sensei.operations.journal import OperationalJournal
from sensei.strategy import (
    ApplicabilityPolicy,
    AttributedValue,
    ComparisonOperator,
    EntryCondition,
    EntryPolicy,
    ExitPolicy,
    FieldAttribution,
    FieldAuthority,
    ObservableField,
    SizingPolicy,
    StrategyPlan,
    TemporalReference,
    TimingPolicy,
)


NOW = datetime(2026, 7, 16, 8, 0, tzinfo=timezone.utc)
CLAIM_A = "claim:" + "a" * 64
CLAIM_B = "claim:" + "b" * 64
ISSUER = "governance-evidence-issuer"
PRODUCERS = {
    EvidenceKind.CONFORMANCE_DOSSIER: "strategy-conformance-producer",
    EvidenceKind.SHADOW_READINESS: "shadow-readiness-producer",
}


def _attribution(
    authority: FieldAuthority,
    *,
    claims: tuple[str, ...] = (),
    rationale: str | None = None,
) -> FieldAttribution:
    return FieldAttribution(
        authority=authority,
        claim_ids=claims,
        rationale=rationale,
    )


def _research(reason: str = "Research protocol choice") -> FieldAttribution:
    return _attribution(FieldAuthority.RESEARCH_ASSUMPTION, rationale=reason)


def _safety(reason: str) -> FieldAttribution:
    return _attribution(FieldAuthority.SAFETY_OVERRIDE, rationale=reason)


def _value(raw, attribution: FieldAttribution | None = None):
    return AttributedValue(value=raw, attribution=attribution or _research())


def _plan(*, claims: tuple[str, ...] = (CLAIM_A,)) -> StrategyPlan:
    strategy_attribution = (
        _attribution(FieldAuthority.SOURCE_CLAIM, claims=claims)
        if claims
        else _research("No source provenance supplied")
    )
    return StrategyPlan(
        name="static evidence fixture",
        strategy_family=_value("fixture", strategy_attribution),
        entry=EntryPolicy(
            conditions=(
                EntryCondition(
                    condition_id="close-above-prior-close",
                    left=TemporalReference(
                        field=ObservableField.CLOSE,
                        sessions_ago=0,
                    ),
                    operator=ComparisonOperator.GT,
                    right=TemporalReference(
                        field=ObservableField.CLOSE,
                        sessions_ago=1,
                    ),
                    attribution=strategy_attribution,
                ),
            )
        ),
        exits=ExitPolicy(
            stop_loss_pct=_value(5.0, _safety("Bound downside")),
            take_profit_pct=_value(10.0),
            max_hold_sessions=_value(20),
        ),
        timing=TimingPolicy(
            decision_point=_value("session_close"),
            entry_point=_value("next_session_open"),
        ),
        sizing=SizingPolicy(
            risk_budget_fraction=_value(0.005, _safety("Risk limit")),
            max_position_fraction=_value(0.10, _safety("Concentration limit")),
        ),
        applicability=ApplicabilityPolicy(
            min_price=_value(10.0, _safety("Exclude invalid low prices")),
            max_price=_value(10_000.0),
            min_average_volume=_value(100_000.0, _safety("Liquidity floor")),
            average_volume_lookback_sessions=_value(20),
        ),
    )


def _publisher(
    journal: OperationalJournal,
    artifact_dir,
) -> StageEvidencePublisher:
    registry = StageDossierRegistry(
        journal,
        trusted_issuer_ids=frozenset({ISSUER}),
        trusted_producers_by_kind={
            kind: frozenset({producer_id})
            for kind, producer_id in PRODUCERS.items()
        },
    )
    return StageEvidencePublisher(
        journal,
        registry,
        ImmutableJsonArtifactStore(artifact_dir),
        issuer_id=ISSUER,
        producer_ids_by_kind=PRODUCERS,
    )


def test_json_artifacts_are_content_addressed_replay_safe_and_tamper_evident(
    tmp_path,
):
    store = ImmutableJsonArtifactStore(tmp_path / "artifacts")
    payload = {"check": "fixture", "measurements": [1, 2, 3], "passed": True}

    first = store.record(payload)
    replay = store.record(payload)

    assert replay.content_id == first.content_id
    assert replay.path == first.path
    assert store.get(first.content_id) == first
    assert first.path.read_bytes().endswith(b"\n")

    first.path.chmod(0o644)
    first.path.write_text('{"tampered":true}\n', encoding="utf-8")

    with pytest.raises(ArtifactIntegrityError, match="hash"):
        store.get(first.content_id)
    with pytest.raises(ArtifactIntegrityError):
        store.record(payload)


def test_publisher_restarts_reuse_exact_artifact_support_and_dossier(tmp_path):
    journal_path = tmp_path / "journal.sqlite3"
    artifact_dir = tmp_path / "artifacts"
    first_journal = OperationalJournal(journal_path)
    first_publisher = _publisher(first_journal, artifact_dir)

    first = first_publisher.publish(
        lineage_id="lineage-1",
        plan_version_id="sha256:" + "1" * 64,
        evidence_kind=EvidenceKind.CONFORMANCE_DOSSIER,
        outcome=DossierOutcome.PASSED,
        evidence={"check": "canonical_plan", "passed": True},
        occurred_at=NOW,
    )

    restarted_journal = OperationalJournal(journal_path)
    restarted_publisher = _publisher(restarted_journal, artifact_dir)
    replay = restarted_publisher.publish(
        lineage_id="lineage-1",
        plan_version_id="sha256:" + "1" * 64,
        evidence_kind=EvidenceKind.CONFORMANCE_DOSSIER,
        outcome=DossierOutcome.PASSED,
        evidence={"check": "canonical_plan", "passed": True},
        occurred_at=NOW + timedelta(days=1),
    )

    assert replay.artifact.content_id == first.artifact.content_id
    assert replay.support_event.event_id == first.support_event.event_id
    assert replay.dossier.dossier_id == first.dossier.dossier_id
    assert replay.dossier.journal_event_id == first.dossier.journal_event_id
    assert replay.artifact.payload == {
        "artifact_type": "stage_evidence",
        "evidence": {"check": "canonical_plan", "passed": True},
        "evidence_kind": EvidenceKind.CONFORMANCE_DOSSIER.value,
        "lineage_id": "lineage-1",
        "outcome": DossierOutcome.PASSED.value,
        "plan_version_id": "sha256:" + "1" * 64,
        "producer_id": PRODUCERS[EvidenceKind.CONFORMANCE_DOSSIER],
        "schema_version": "1.0",
    }
    events = restarted_journal.read_all()
    assert [event.event_type for event in events] == [
        "StageEvidenceProduced",
        "StageDossierIssued",
    ]
    assert events[0].global_sequence < events[1].global_sequence


def test_publisher_requires_one_journal_and_separate_configured_actors(tmp_path):
    journal = OperationalJournal(tmp_path / "one.sqlite3")
    other_journal = OperationalJournal(tmp_path / "two.sqlite3")
    registry = StageDossierRegistry(
        journal,
        trusted_issuer_ids=frozenset({ISSUER}),
        trusted_producers_by_kind={
            EvidenceKind.CONFORMANCE_DOSSIER: frozenset(
                {PRODUCERS[EvidenceKind.CONFORMANCE_DOSSIER]}
            )
        },
    )

    with pytest.raises(ValueError, match="same operational journal"):
        StageEvidencePublisher(
            other_journal,
            registry,
            ImmutableJsonArtifactStore(tmp_path / "artifacts"),
            issuer_id=ISSUER,
            producer_ids_by_kind={
                EvidenceKind.CONFORMANCE_DOSSIER: PRODUCERS[
                    EvidenceKind.CONFORMANCE_DOSSIER
                ]
            },
        )

    with pytest.raises(ValueError, match="independent"):
        StageEvidencePublisher(
            journal,
            registry,
            ImmutableJsonArtifactStore(tmp_path / "artifacts"),
            issuer_id=ISSUER,
            producer_ids_by_kind={EvidenceKind.CONFORMANCE_DOSSIER: ISSUER},
        )


def test_static_conformance_uses_canonical_assessment_and_publishes_failures(
    tmp_path,
):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    producer = PlanStaticEvidenceProducer(
        _publisher(journal, tmp_path / "artifacts"),
        claim_resolver=lambda _claim_id: True,
        supported_engine_contracts=frozenset({"daily-long-only-v1"}),
    )
    plan = _plan()

    passed = producer.produce_conformance(
        lineage_id="lineage-pass",
        plan_version_id=plan.plan_id,
        candidate=plan,
        occurred_at=NOW,
    )
    failed = producer.produce_conformance(
        lineage_id="lineage-fail",
        plan_version_id=plan.plan_id,
        candidate=object(),
        occurred_at=NOW,
    )

    assert passed.dossier.outcome is DossierOutcome.PASSED
    assert passed.artifact.payload["evidence"] == {
        "assessed_plan_id": plan.plan_id,
        "candidate_contract": "StrategyPlan",
        "check": "canonical_strategy_plan_conformance",
        "conformant": True,
        "expected_plan_version_id": plan.plan_id,
        "issues": [],
    }
    assert failed.dossier.outcome is DossierOutcome.FAILED
    failed_evidence = failed.artifact.payload["evidence"]
    assert failed_evidence["conformant"] is False
    assert failed_evidence["issues"] == ["canonical_strategy_plan_required"]
    assert failed.artifact.payload["outcome"] == DossierOutcome.FAILED.value


def test_shadow_readiness_resolves_every_exact_claim_and_fails_closed(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    resolved: list[str] = []

    def claim_resolver(claim_id: str) -> bool:
        resolved.append(claim_id)
        if claim_id == CLAIM_B:
            raise RuntimeError("provenance service unavailable")
        return True

    producer = PlanStaticEvidenceProducer(
        _publisher(journal, tmp_path / "artifacts"),
        claim_resolver=claim_resolver,
        supported_engine_contracts=frozenset({"daily-long-only-v1"}),
    )
    plan = _plan(claims=(CLAIM_B, CLAIM_A))

    result = producer.produce_shadow_readiness(
        lineage_id="lineage-claims",
        plan=plan,
        occurred_at=NOW,
    )

    assert resolved == [CLAIM_A, CLAIM_B]
    assert result.dossier.outcome is DossierOutcome.FAILED
    evidence = result.artifact.payload["evidence"]
    assert evidence["source_claim_ids"] == [CLAIM_A, CLAIM_B]
    assert evidence["resolved_source_claim_ids"] == [CLAIM_A]
    assert evidence["unresolved_source_claim_ids"] == [CLAIM_B]
    assert evidence["claim_resolution_error_ids"] == [CLAIM_B]
    assert evidence["issues"] == ["unresolved_source_claims"]
    assert evidence["ready"] is False


@pytest.mark.parametrize(
    ("claims", "supported_contracts", "expected_issues"),
    [
        ((), frozenset({"daily-long-only-v1"}), ["source_claims_required"]),
        (
            (CLAIM_A,),
            frozenset({"daily-long-only-v2"}),
            ["unsupported_engine_contract"],
        ),
    ],
)
def test_shadow_readiness_never_passes_missing_provenance_or_engine_support(
    tmp_path,
    claims,
    supported_contracts,
    expected_issues,
):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    producer = PlanStaticEvidenceProducer(
        _publisher(journal, tmp_path / "artifacts"),
        claim_resolver=lambda _claim_id: True,
        supported_engine_contracts=supported_contracts,
    )

    result = producer.produce_shadow_readiness(
        lineage_id="lineage-not-ready",
        plan=_plan(claims=claims),
        occurred_at=NOW,
    )

    assert result.dossier.outcome is DossierOutcome.FAILED
    assert result.artifact.payload["evidence"]["issues"] == expected_issues


def test_static_producer_can_only_create_its_two_honest_evidence_kinds(tmp_path):
    producer = PlanStaticEvidenceProducer(
        _publisher(
            OperationalJournal(tmp_path / "journal.sqlite3"),
            tmp_path / "artifacts",
        ),
        claim_resolver=lambda _claim_id: True,
        supported_engine_contracts=frozenset({"daily-long-only-v1"}),
    )

    assert producer.evidence_kinds == frozenset(
        {
            EvidenceKind.CONFORMANCE_DOSSIER,
            EvidenceKind.SHADOW_READINESS,
        }
    )
    assert not hasattr(producer, "produce_examination_dossier")
    assert not hasattr(producer, "produce_locked_confirmation")
    assert not hasattr(producer, "produce_shadow_trial")
