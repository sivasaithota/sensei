"""Honest, restart-safe production of governed lifecycle evidence.

The publisher in this module is the narrow bridge between a full JSON
artifact, its exact ``StageEvidenceProduced`` journal event, and the dossier
that cites that event.  Static plan checks deliberately cover only facts that
can be established without a market experiment.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sensei.governance.evidence import (
    DossierOutcome,
    StageDossier,
    StageDossierIssue,
    StageDossierRegistry,
    StageEvidenceEnvelope,
)
from sensei.governance.lifecycle import EvidenceKind
from sensei.operations.journal import (
    EventAppend,
    JournalConflict,
    JournalEvent,
    JournalIntegrityError,
    OperationalJournal,
)
from sensei.strategy.conformance import assess_strategy_conformance
from sensei.strategy.models import StrategyPlan


_ARTIFACT_CONTENT_ID = re.compile(r"sha256:([0-9a-f]{64})\Z")
_SCHEMA_VERSION = "1.0"
_DEFAULT_MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
_STATIC_EVIDENCE_KINDS = frozenset(
    {
        EvidenceKind.CONFORMANCE_DOSSIER,
        EvidenceKind.SHADOW_READINESS,
    }
)


class ArtifactStoreError(RuntimeError):
    """Base error for immutable JSON artifact persistence."""


class ArtifactIntegrityError(ArtifactStoreError):
    """An artifact path or its bytes do not match its content identity."""


class EvidencePublicationError(RuntimeError):
    """The evidence journal stream conflicts with the requested artifact."""


@dataclass(frozen=True)
class StoredJsonArtifact:
    """A verified content-addressed JSON object."""

    content_id: str
    path: Path
    payload: Mapping[str, object]


class ImmutableJsonArtifactStore:
    """Persist canonical JSON objects with exclusive, atomic file creation."""

    def __init__(
        self,
        artifact_dir: Path,
        *,
        max_artifact_bytes: int = _DEFAULT_MAX_ARTIFACT_BYTES,
    ) -> None:
        self._artifact_dir = Path(artifact_dir)
        if max_artifact_bytes < 1:
            raise ValueError("max_artifact_bytes must be positive")
        self._max_artifact_bytes = max_artifact_bytes

    def record(self, payload: Mapping[str, object]) -> StoredJsonArtifact:
        """Record once or verify and return the exact existing artifact."""

        content = _canonical_artifact_bytes(payload)
        if len(content) > self._max_artifact_bytes:
            raise ValueError("artifact exceeds the configured size limit")
        digest = hashlib.sha256(content).hexdigest()
        content_id = f"sha256:{digest}"
        destination = self._artifact_dir / f"{digest}.json"
        self._write_immutable(destination, content)
        artifact = self.get(content_id)
        if artifact is None:  # pragma: no cover - defensive filesystem guard
            raise ArtifactIntegrityError("new artifact disappeared after persistence")
        return artifact

    def get(self, content_id: str) -> StoredJsonArtifact | None:
        """Load one artifact only after path, hash, and canonical JSON checks."""

        match = _ARTIFACT_CONTENT_ID.fullmatch(content_id)
        if match is None:
            raise ValueError("content_id must be a lowercase sha256 identity")
        path = self._artifact_dir / f"{match.group(1)}.json"
        if not path.exists() and not path.is_symlink():
            return None
        content = self._read_regular_file(path)
        actual_id = f"sha256:{hashlib.sha256(content).hexdigest()}"
        if actual_id != content_id:
            raise ArtifactIntegrityError("artifact hash does not match its content ID")
        payload = _parse_canonical_artifact(content)
        return StoredJsonArtifact(
            content_id=content_id,
            path=path,
            payload=payload,
        )

    def verify(self, content_id: str) -> bool:
        """Return literal verification without weakening ``get`` diagnostics."""

        try:
            return self.get(content_id) is not None
        except (ArtifactStoreError, OSError, ValueError):
            return False

    def _write_immutable(self, destination: Path, content: bytes) -> None:
        self._artifact_dir.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        linked = False
        try:
            with tempfile.NamedTemporaryFile(
                dir=self._artifact_dir,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_path.chmod(0o444)
            try:
                os.link(temporary_path, destination)
                linked = True
            except FileExistsError:
                existing = self._read_regular_file(destination)
                if existing != content:
                    raise ArtifactIntegrityError(
                        "immutable artifact collision or corruption"
                    )
            else:
                directory_fd = os.open(self._artifact_dir, os.O_RDONLY)
                try:
                    try:
                        os.fsync(directory_fd)
                    except Exception:
                        destination.unlink(missing_ok=True)
                        linked = False
                        raise
                finally:
                    os.close(directory_fd)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            if linked and not destination.exists():  # pragma: no cover
                raise ArtifactIntegrityError("artifact link disappeared")

    def _read_regular_file(self, path: Path) -> bytes:
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            raise ArtifactIntegrityError("artifact path disappeared") from None
        if not stat.S_ISREG(metadata.st_mode):
            raise ArtifactIntegrityError("artifact path is not a regular file")
        if metadata.st_size > self._max_artifact_bytes:
            raise ArtifactIntegrityError("artifact exceeds the configured size limit")
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise ArtifactIntegrityError("artifact could not be read") from exc
        if len(content) != metadata.st_size:
            raise ArtifactIntegrityError("artifact changed while it was being read")
        return content


@dataclass(frozen=True)
class PublishedStageEvidence:
    """The exact artifact, support event, and issued dossier for one check."""

    artifact: StoredJsonArtifact
    envelope: StageEvidenceEnvelope
    support_event: JournalEvent
    dossier: StageDossier


class StageEvidencePublisher:
    """Atomically converge evidence publication across process restarts."""

    def __init__(
        self,
        journal: OperationalJournal,
        dossier_registry: StageDossierRegistry,
        artifact_store: ImmutableJsonArtifactStore,
        *,
        issuer_id: str,
        producer_ids_by_kind: Mapping[EvidenceKind, str],
    ) -> None:
        if not dossier_registry.is_bound_to_journal(journal):
            raise ValueError(
                "publisher and dossier registry must use the same operational journal"
            )
        if not isinstance(issuer_id, str) or not issuer_id.strip():
            raise ValueError("issuer_id must name an actor")
        normalized: dict[EvidenceKind, str] = {}
        for kind, producer_id in producer_ids_by_kind.items():
            if not isinstance(kind, EvidenceKind):
                raise ValueError("producer mapping keys must be EvidenceKind values")
            if not isinstance(producer_id, str) or not producer_id.strip():
                raise ValueError("producer IDs must name actors")
            normalized[kind] = producer_id
        if not normalized:
            raise ValueError("at least one evidence producer must be configured")
        if issuer_id in normalized.values():
            raise ValueError(
                "dossier issuer and evidence producers must be independent"
            )
        self._journal = journal
        self._dossier_registry = dossier_registry
        self._artifact_store = artifact_store
        self._issuer_id = issuer_id
        self._producer_ids_by_kind = normalized

    def publish(
        self,
        *,
        lineage_id: str,
        plan_version_id: str,
        evidence_kind: EvidenceKind,
        outcome: DossierOutcome,
        evidence: Mapping[str, object],
        occurred_at: datetime,
    ) -> PublishedStageEvidence:
        """Store, journal, and issue one exact item in restart-safe order."""

        _require_aware(occurred_at)
        try:
            producer_id = self._producer_ids_by_kind[evidence_kind]
        except KeyError:
            raise ValueError(
                f"no producer configured for {evidence_kind.value}"
            ) from None
        artifact_payload: dict[str, object] = {
            "schema_version": _SCHEMA_VERSION,
            "artifact_type": "stage_evidence",
            "lineage_id": lineage_id,
            "plan_version_id": plan_version_id,
            "evidence_kind": evidence_kind.value,
            "producer_id": producer_id,
            "outcome": outcome.value,
            "evidence": dict(evidence),
        }
        artifact = self._artifact_store.record(artifact_payload)
        envelope = StageEvidenceEnvelope(
            lineage_id=lineage_id,
            plan_version_id=plan_version_id,
            evidence_kind=evidence_kind,
            producer_id=producer_id,
            outcome=outcome,
            artifact_content_id=artifact.content_id,
        )
        support_event = self._append_or_reuse_support(envelope, occurred_at)
        if not self._artifact_store.verify(artifact.content_id):
            raise ArtifactIntegrityError(
                "artifact failed verification before dossier issuance"
            )
        dossier = self._dossier_registry.issue(
            StageDossierIssue(
                lineage_id=lineage_id,
                plan_version_id=plan_version_id,
                evidence_kind=evidence_kind,
                supporting_event_ids=(support_event.event_id,),
                issuer_id=self._issuer_id,
                producer_id=producer_id,
                issued_at=support_event.occurred_at,
                outcome=outcome,
            )
        )
        if not self._artifact_store.verify(artifact.content_id):
            raise ArtifactIntegrityError(
                "artifact failed verification after dossier issuance"
            )
        return PublishedStageEvidence(
            artifact=artifact,
            envelope=envelope,
            support_event=support_event,
            dossier=dossier,
        )

    def _append_or_reuse_support(
        self,
        envelope: StageEvidenceEnvelope,
        occurred_at: datetime,
    ) -> JournalEvent:
        payload = envelope.to_payload()
        identity = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        stream_id = f"stage-evidence:{identity}"
        existing = self._journal.read_stream(stream_id)
        if existing:
            return _require_exact_support(existing, stream_id, payload)
        command = EventAppend(
            stream_id=stream_id,
            event_type="StageEvidenceProduced",
            payload=payload,
            idempotency_key=f"produce-evidence:{identity}",
            expected_version=0,
            occurred_at=occurred_at,
            correlation_id=envelope.plan_version_id,
        )
        try:
            return self._journal.append(command)
        except (JournalConflict, JournalIntegrityError):
            raced = self._journal.read_stream(stream_id)
            if not raced:
                raise
            return _require_exact_support(raced, stream_id, payload)


class PlanStaticEvidenceProducer:
    """Publish only deterministic conformance and shadow-readiness checks."""

    def __init__(
        self,
        publisher: StageEvidencePublisher,
        *,
        claim_resolver: Callable[[str], bool],
        supported_engine_contracts: frozenset[str],
    ) -> None:
        if not callable(claim_resolver):
            raise TypeError("claim_resolver must be callable")
        contracts = frozenset(supported_engine_contracts)
        if not contracts or any(
            not isinstance(contract, str) or not contract.strip()
            for contract in contracts
        ):
            raise ValueError("supported_engine_contracts must contain named contracts")
        self._publisher = publisher
        self._claim_resolver = claim_resolver
        self._supported_engine_contracts = contracts

    @property
    def evidence_kinds(self) -> frozenset[EvidenceKind]:
        return _STATIC_EVIDENCE_KINDS

    def produce_conformance(
        self,
        *,
        lineage_id: str,
        plan_version_id: str,
        candidate: object,
        occurred_at: datetime,
    ) -> PublishedStageEvidence:
        """Assess the candidate through the canonical conformance boundary."""

        assessment = assess_strategy_conformance(candidate)
        issues = list(assessment.issues)
        conformant = (
            assessment.conformant
            and assessment.plan_id is not None
            and assessment.plan_id == plan_version_id
        )
        if assessment.conformant and assessment.plan_id != plan_version_id:
            issues.append("plan_version_identity_mismatch")
        evidence: dict[str, object] = {
            "check": "canonical_strategy_plan_conformance",
            "candidate_contract": (
                "StrategyPlan"
                if isinstance(candidate, StrategyPlan)
                else "noncanonical"
            ),
            "expected_plan_version_id": plan_version_id,
            "assessed_plan_id": assessment.plan_id,
            "conformant": conformant,
            "issues": issues,
        }
        return self._publisher.publish(
            lineage_id=lineage_id,
            plan_version_id=plan_version_id,
            evidence_kind=EvidenceKind.CONFORMANCE_DOSSIER,
            outcome=(
                DossierOutcome.PASSED if conformant else DossierOutcome.FAILED
            ),
            evidence=evidence,
            occurred_at=occurred_at,
        )

    def produce_shadow_readiness(
        self,
        *,
        lineage_id: str,
        plan: StrategyPlan,
        occurred_at: datetime,
    ) -> PublishedStageEvidence:
        """Verify exact source claims and engine support; fail closed on doubt."""

        if not isinstance(plan, StrategyPlan):
            raise TypeError("plan must be a canonical StrategyPlan")
        claim_ids = plan.source_claim_ids
        resolved_ids: list[str] = []
        unresolved_ids: list[str] = []
        resolution_error_ids: list[str] = []
        for claim_id in claim_ids:
            try:
                resolved = self._claim_resolver(claim_id)
            except Exception:
                resolved = False
                resolution_error_ids.append(claim_id)
            if resolved is True:
                resolved_ids.append(claim_id)
            else:
                unresolved_ids.append(claim_id)

        contract_supported = plan.engine_contract in self._supported_engine_contracts
        issues: list[str] = []
        if not claim_ids:
            issues.append("source_claims_required")
        if unresolved_ids:
            issues.append("unresolved_source_claims")
        if not contract_supported:
            issues.append("unsupported_engine_contract")
        ready = not issues
        evidence: dict[str, object] = {
            "check": "shadow_readiness",
            "plan_id": plan.plan_id,
            "engine_contract": plan.engine_contract,
            "supported_engine_contracts": sorted(self._supported_engine_contracts),
            "engine_contract_supported": contract_supported,
            "source_claim_ids": list(claim_ids),
            "resolved_source_claim_ids": resolved_ids,
            "unresolved_source_claim_ids": unresolved_ids,
            "claim_resolution_error_ids": resolution_error_ids,
            "ready": ready,
            "issues": issues,
        }
        return self._publisher.publish(
            lineage_id=lineage_id,
            plan_version_id=plan.plan_id,
            evidence_kind=EvidenceKind.SHADOW_READINESS,
            outcome=DossierOutcome.PASSED if ready else DossierOutcome.FAILED,
            evidence=evidence,
            occurred_at=occurred_at,
        )


def _require_exact_support(
    events: tuple[JournalEvent, ...],
    stream_id: str,
    payload: Mapping[str, object],
) -> JournalEvent:
    if len(events) != 1:
        raise EvidencePublicationError(
            f"evidence support stream {stream_id!r} has an invalid event count"
        )
    event = events[0]
    if (
        event.stream_sequence != 1
        or event.event_type != "StageEvidenceProduced"
        or dict(event.payload) != dict(payload)
    ):
        raise EvidencePublicationError(
            f"evidence support stream {stream_id!r} conflicts with its content ID"
        )
    return event


def _canonical_artifact_bytes(payload: Mapping[str, object]) -> bytes:
    if not isinstance(payload, Mapping):
        raise TypeError("artifact payload must be a JSON object")
    return (_canonical_json(dict(payload)) + "\n").encode("utf-8")


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _parse_canonical_artifact(content: bytes) -> dict[str, object]:
    try:
        decoded = content.decode("utf-8")
        payload = json.loads(decoded, object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactIntegrityError("artifact is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ArtifactIntegrityError("artifact JSON root must be an object")
    try:
        canonical = _canonical_artifact_bytes(payload)
    except (TypeError, ValueError) as exc:
        raise ArtifactIntegrityError("artifact JSON is not canonicalizable") from exc
    if canonical != content:
        raise ArtifactIntegrityError("artifact bytes are not canonical JSON")
    return payload


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ArtifactIntegrityError(f"duplicate artifact JSON key {key!r}")
        result[key] = value
    return result


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("occurred_at must be timezone-aware")


__all__ = [
    "ArtifactIntegrityError",
    "ArtifactStoreError",
    "EvidencePublicationError",
    "ImmutableJsonArtifactStore",
    "PlanStaticEvidenceProducer",
    "PublishedStageEvidence",
    "StageEvidencePublisher",
    "StoredJsonArtifact",
]
