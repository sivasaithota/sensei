"""Deterministic migration of legacy paper assets into governed records."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sensei.backtest.rulespec import RuleSpec
from sensei.automation.evidence import (
    ImmutableJsonArtifactStore,
    PlanStaticEvidenceProducer,
    StageEvidencePublisher,
)
from sensei.governance.evidence import DossierOutcome, StageDossierRegistry
from sensei.governance.lifecycle import EvidenceKind
from sensei.operations import EventAppend, OperationalJournal
from sensei.provenance import (
    ClaimProposal,
    LocatorKind,
    PlainTextAdapter,
    ProvenanceCorpus,
    SourceCitation,
    SourceKind,
    SourceMetadata,
)
from sensei.strategy import (
    ApplicabilityPolicy,
    AttributedValue,
    FieldAttribution,
    FieldAuthority,
    RuleSpecPlanPolicy,
    SizingPolicy,
    StrategyPlanCatalog,
    StrategyPlanRecord,
    TimingPolicy,
    convert_rule_spec,
)


def _research(reason: str) -> FieldAttribution:
    return FieldAttribution(authority=FieldAuthority.RESEARCH_ASSUMPTION, rationale=reason)


def _safety(reason: str) -> FieldAttribution:
    return FieldAttribution(authority=FieldAuthority.SAFETY_OVERRIDE, rationale=reason)


def migration_policy(spec: RuleSpec, *, claim_id: str | None = None) -> RuleSpecPlanPolicy:
    """Return the explicit, conservative policy used for legacy conversion."""

    source = (
        FieldAttribution(authority=FieldAuthority.SOURCE_CLAIM, claim_ids=(claim_id,))
        if claim_id is not None else _research("Legacy rule awaiting provenance migration")
    )
    return RuleSpecPlanPolicy(
        strategy_family=AttributedValue(value=spec.name, attribution=source),
        condition_attributions=tuple(
            source for _ in spec.conditions
        ),
        stop_loss_attribution=_safety("Retain the backtested stop during paper migration"),
        take_profit_attribution=source,
        max_hold_attribution=source,
        timing=TimingPolicy(
            decision_point=AttributedValue(value="session_close", attribution=_research("Daily close decision")),
            entry_point=AttributedValue(value="next_session_open", attribution=_research("No same-close fill")),
        ),
        sizing=SizingPolicy(
            risk_budget_fraction=AttributedValue(value=0.005, attribution=_safety("Half-percent risk cap")),
            max_position_fraction=AttributedValue(value=0.10, attribution=_safety("Ten-percent concentration cap")),
        ),
        applicability=ApplicabilityPolicy(
            min_price=AttributedValue(value=1.0, attribution=_safety("Reject invalid prices")),
            max_price=AttributedValue(value=1_000_000.0, attribution=_research("Broad paper range")),
            min_average_volume=AttributedValue(value=0.0, attribution=_safety("Liquidity remains enforced upstream")),
            average_volume_lookback_sessions=AttributedValue(value=20, attribution=_research("Twenty-session liquidity window")),
        ),
    )


@dataclass(frozen=True)
class StrategyMigrationResult:
    registered: tuple[StrategyPlanRecord, ...]
    skipped_names: tuple[str, ...]


def publish_pre_shadow_evidence(
    journal: OperationalJournal,
    registry: StageDossierRegistry,
    *,
    records: tuple[StrategyPlanRecord, ...],
    playbook_path: Path,
    provenance_root: Path,
    artifact_root: Path,
    issuer_id: str,
    producer_ids_by_kind: dict[EvidenceKind, str],
    occurred_at: datetime,
) -> None:
    """Publish reproducible examination, conformance, readiness and lock facts."""

    playbook_bytes = playbook_path.read_bytes()
    playbook = json.loads(playbook_bytes)
    by_name = {item["name"]: item for item in playbook["strategies"]}
    publisher = StageEvidencePublisher(
        journal,
        registry,
        ImmutableJsonArtifactStore(artifact_root),
        issuer_id=issuer_id,
        producer_ids_by_kind=producer_ids_by_kind,
    )
    corpus = ProvenanceCorpus(journal, provenance_root)
    static = PlanStaticEvidenceProducer(
        publisher,
        claim_resolver=corpus.has_claim,
        supported_engine_contracts=frozenset({"daily-long-only-v1", "daily-long-only-v2"}),
    )
    playbook_sha = "sha256:" + hashlib.sha256(playbook_bytes).hexdigest()
    for record in records:
        result = by_name[record.source_rule_name]
        passed = result.get("adopted") is True
        publisher.publish(
            lineage_id=record.lineage_id,
            plan_version_id=record.plan_id,
            evidence_kind=EvidenceKind.EXAMINATION_DOSSIER,
            outcome=DossierOutcome.PASSED if passed else DossierOutcome.FAILED,
            evidence={
                "check": "retained_walk_forward_playbook",
                "playbook_sha256": playbook_sha,
                "playbook_version": playbook.get("version"),
                "thresholds": playbook.get("thresholds"),
                "out_of_sample": result.get("out_of_sample"),
                "passed": passed,
            },
            occurred_at=occurred_at,
        )
        static.produce_conformance(
            lineage_id=record.lineage_id,
            plan_version_id=record.plan_id,
            candidate=record.plan,
            occurred_at=occurred_at,
        )
        static.produce_shadow_readiness(
            lineage_id=record.lineage_id,
            plan=record.plan,
            occurred_at=occurred_at,
        )
        publisher.publish(
            lineage_id=record.lineage_id,
            plan_version_id=record.plan_id,
            evidence_kind=EvidenceKind.LOCKED_CONFIRMATION,
            outcome=DossierOutcome.PASSED,
            evidence={
                "check": "immutable_plan_locked_before_shadow",
                "plan_id": record.plan_id,
                "catalog_event_id": record.event_id,
                "locked": True,
            },
            occurred_at=occurred_at,
        )


def migrate_adopted_strategies(
    journal: OperationalJournal,
    *,
    playbook_path: Path,
    rules_path: Path,
    artifact_root: Path | None = None,
    occurred_at: datetime,
) -> StrategyMigrationResult:
    """Register only exact rules that passed the retained playbook thresholds."""

    playbook_bytes = playbook_path.read_bytes()
    rules_bytes = rules_path.read_bytes()
    playbook = json.loads(playbook_bytes)
    rules = json.loads(rules_bytes)
    adopted = {item["name"] for item in playbook["strategies"] if item.get("adopted") is True}
    by_name = {item["name"]: RuleSpec.model_validate(item) for item in rules}
    source_digest = hashlib.sha256(playbook_bytes + b"\0" + rules_bytes).hexdigest()
    catalog = StrategyPlanCatalog(journal)
    source_retrieved_at = datetime.fromisoformat(
        str(playbook.get("version", "1970-01-01"))
    ).replace(tzinfo=timezone.utc)
    corpus = ProvenanceCorpus(journal, artifact_root or rules_path.parent / "provenance")
    source = corpus.ingest(
        PlainTextAdapter().adapt(
            rules_path,
            SourceMetadata(
                title="Retained studied trading rules",
                canonical_uri=f"file:{rules_path.resolve()}",
                source_kind=SourceKind.TEXT_DOCUMENT,
                edition=f"sha256:{hashlib.sha256(rules_bytes).hexdigest()}",
                usage_rights="owner-supplied research notes",
                retrieved_at=source_retrieved_at,
            ),
        ),
        occurred_at=occurred_at,
        command_id=f"strategy-migration-source:{source_digest}",
    )
    segment = source.segments[0]
    citation = SourceCitation(
        source_id=source.source_id,
        segment_id=segment.segment_id,
        locator_kind=LocatorKind.CHARACTERS,
        start=segment.start,
        end=segment.end,
        quote_sha256="sha256:" + hashlib.sha256(segment.text.encode()).hexdigest(),
    )
    registered = []
    skipped = []
    for name in sorted(adopted):
        spec = by_name.get(name)
        if spec is None:
            skipped.append(name)
            continue
        claim = corpus.record_claim(
            ClaimProposal(
                statement=f"{spec.name}: {spec.principle}",
                citations=(citation,),
                producer_id="legacy-rule-migrator",
                extraction_method_id="owner-retained-rules:v1",
            ),
            occurred_at=occurred_at,
            command_id=f"strategy-migration-claim:{source_digest}:{name}",
        )
        plan = convert_rule_spec(spec, policy=migration_policy(spec, claim_id=claim.claim_id))
        registered.append(catalog.register(
            lineage_id=f"legacy-playbook:{name}",
            plan=plan,
            source_rule_name=name,
            occurred_at=occurred_at,
            command_id=f"strategy-migration:{source_digest}:{name}",
        ))
    return StrategyMigrationResult(tuple(registered), tuple(skipped))


@dataclass(frozen=True)
class AdoptedLegacyPosition:
    symbol: str
    quantity: int
    entry_price: float
    stop_loss: float
    target: float
    opened: str


def adopt_legacy_positions(
    journal: OperationalJournal,
    *,
    positions_path: Path,
    occurred_at: datetime,
) -> tuple[AdoptedLegacyPosition, ...]:
    """Journal an immutable inventory snapshot without inventing broker fills."""

    content = positions_path.read_bytes()
    payload = json.loads(content)
    adopted = tuple(
        AdoptedLegacyPosition(
            symbol=str(item["symbol"]),
            quantity=int(item["quantity"]),
            entry_price=float(item["entry_price"]),
            stop_loss=float(item["stop_loss"]),
            target=float(item["targets"][0]),
            opened=str(item["opened"]),
        )
        for item in payload.get("positions", ())
    )
    digest = hashlib.sha256(content).hexdigest()
    existing = journal.read_stream("legacy-paper-position-adoption")
    if existing:
        if (
            len(existing) != 1
            or existing[0].event_type != "LegacyPaperPositionsAdopted"
            or existing[0].payload.get("source_sha256") != f"sha256:{digest}"
        ):
            raise RuntimeError(
                "legacy paper inventory changed after its governed adoption"
            )
        return adopted
    journal.append(EventAppend(
        stream_id="legacy-paper-position-adoption",
        event_type="LegacyPaperPositionsAdopted",
        payload={
            "schema_version": "1.0",
            "authority": "OBSERVATION_ONLY",
            "source_sha256": f"sha256:{digest}",
            "cash": payload.get("cash"),
            "positions": [item.__dict__ for item in adopted],
            "requires_broker_reconciliation": True,
        },
        idempotency_key=f"legacy-position-adoption:{digest}",
        expected_version=0,
        occurred_at=occurred_at,
    ))
    return adopted


__all__ = [
    "AdoptedLegacyPosition",
    "StrategyMigrationResult",
    "adopt_legacy_positions",
    "migrate_adopted_strategies",
    "migration_policy",
    "publish_pre_shadow_evidence",
]
