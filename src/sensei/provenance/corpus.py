"""Immutable provenance corpus with precise citation verification."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from sensei.operations.journal import EventAppend, OperationalJournal

from .adapters import _read_regular_file
from .models import (
    AdaptedSource,
    ClaimProposal,
    LocatorKind,
    SourceArtifact,
    SourceCitation,
    SourceClaim,
    SourceKind,
    SourceMetadata,
    SourceSegment,
    claim_id_for,
    sha256_id,
    source_id_for,
)

_SOURCE_ID = re.compile(r"source:[0-9a-f]{64}\Z")
_CLAIM_ID = re.compile(r"claim:[0-9a-f]{64}\Z")
_MANIFEST_LIMIT = 100_000_000


class ProvenanceCorpus:
    """Retain sources and claims without retrieval or execution authority."""

    def __init__(self, journal: OperationalJournal, artifact_root: Path) -> None:
        self._journal = journal
        self._root = Path(artifact_root)
        self._raw_root = self._root / "raw"
        self._manifest_root = self._root / "manifests"

    def is_bound_to_journal(self, journal: OperationalJournal) -> bool:
        """Return whether provenance records use the exact runtime journal."""

        return self._journal is journal

    def ingest(
        self,
        adapted: AdaptedSource,
        *,
        occurred_at: datetime,
        command_id: str,
    ) -> SourceArtifact:
        _aware(occurred_at)
        if not command_id.strip():
            raise ValueError("command_id must not be blank")
        raw_sha256 = sha256_id(adapted.raw_content)
        identity = _source_identity(adapted, raw_sha256)
        source_id = source_id_for(identity)
        raw_path = self._raw_root / f"{raw_sha256.removeprefix('sha256:')}.bin"
        manifest_path = self._manifest_root / f"{source_id.removeprefix('source:')}.json"
        manifest = {
            "schema_version": "1.0",
            "source_id": source_id,
            **identity,
        }
        manifest_bytes = (_canonical(manifest) + "\n").encode("utf-8")
        _write_immutable(raw_path, adapted.raw_content)
        _write_immutable(manifest_path, manifest_bytes)

        stream = _source_stream(source_id)
        existing = self._journal.read_stream(stream)
        if existing:
            artifact = self.get_source(source_id)
            if artifact is None:
                raise RuntimeError("source stream exists without a valid artifact")
            return artifact
        event = self._journal.append(
            EventAppend(
                stream_id=stream,
                event_type="SourceArtifactIngested",
                payload={
                    "source_id": source_id,
                    "raw_sha256": raw_sha256,
                    "manifest_sha256": sha256_id(manifest_bytes),
                    "metadata": adapted.metadata.to_payload(),
                    "adapter_id": adapted.adapter_id,
                    "segment_count": len(adapted.segments),
                    "authority": "RESEARCH_ONLY",
                },
                idempotency_key=_command_key("source", command_id),
                expected_version=0,
                occurred_at=occurred_at,
                correlation_id=source_id,
            )
        )
        return SourceArtifact(
            source_id=source_id,
            metadata=adapted.metadata,
            adapter_id=adapted.adapter_id,
            raw_sha256=raw_sha256,
            segments=adapted.segments,
            raw_path=raw_path,
            manifest_path=manifest_path,
            event_id=event.event_id,
        )

    def get_source(self, source_id: str) -> SourceArtifact | None:
        if _SOURCE_ID.fullmatch(source_id) is None:
            raise ValueError("source_id must be content-addressed")
        verification = self._journal.verify()
        if not verification.ok:
            raise RuntimeError("provenance journal integrity verification failed")
        events = self._journal.read_stream(_source_stream(source_id))
        if not events:
            return None
        if len(events) != 1 or events[0].event_type != "SourceArtifactIngested":
            raise RuntimeError("source provenance stream is invalid")
        event = events[0]
        raw_sha256 = str(event.payload["raw_sha256"])
        raw_path = self._raw_root / f"{raw_sha256.removeprefix('sha256:')}.bin"
        manifest_path = self._manifest_root / f"{source_id.removeprefix('source:')}.json"
        raw = _read_regular_file(raw_path, _MANIFEST_LIMIT)
        manifest_bytes = _read_regular_file(manifest_path, _MANIFEST_LIMIT)
        if sha256_id(raw) != raw_sha256:
            raise RuntimeError("retained source bytes failed hash verification")
        if sha256_id(manifest_bytes) != event.payload["manifest_sha256"]:
            raise RuntimeError("source manifest failed hash verification")
        try:
            manifest = json.loads(manifest_bytes, object_pairs_hook=_unique_object)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError("source manifest is not valid JSON") from exc
        artifact = _artifact_from_manifest(
            manifest,
            raw_path=raw_path,
            manifest_path=manifest_path,
            event_id=event.event_id,
        )
        if artifact.source_id != source_id or artifact.raw_sha256 != raw_sha256:
            raise RuntimeError("source event and retained manifest disagree")
        if event.payload["metadata"] != artifact.metadata.to_payload():
            raise RuntimeError("source metadata does not match its journal event")
        if event.payload["adapter_id"] != artifact.adapter_id:
            raise RuntimeError("source adapter does not match its journal event")
        if int(event.payload["segment_count"]) != len(artifact.segments):
            raise RuntimeError("source segment count does not match its journal event")
        if event.payload.get("authority") != "RESEARCH_ONLY":
            raise RuntimeError("source artifact has invalid authority")
        return artifact

    def record_claim(
        self,
        proposal: ClaimProposal,
        *,
        occurred_at: datetime,
        command_id: str,
    ) -> SourceClaim:
        _aware(occurred_at)
        if not command_id.strip():
            raise ValueError("command_id must not be blank")
        citation_sources = tuple(
            self._validate_citation(citation) for citation in proposal.citations
        )
        for claim_id in proposal.contradicts_claim_ids:
            if not self.has_claim(claim_id):
                raise ValueError(f"contradicted claim does not exist: {claim_id}")

        identity = proposal.identity_payload()
        claim_id = claim_id_for(identity)
        if claim_id in proposal.contradicts_claim_ids:
            raise ValueError("a claim cannot contradict itself")
        stream = _claim_stream(claim_id)
        existing = self._journal.read_stream(stream)
        if existing:
            return self._claim_from_event(existing, expected_claim_id=claim_id)
        event = self._journal.append(
            EventAppend(
                stream_id=stream,
                event_type="SourceClaimRecorded",
                payload={
                    "schema_version": "1.0",
                    "claim_id": claim_id,
                    **identity,
                    "authority": "RESEARCH_ONLY",
                },
                idempotency_key=_command_key("claim", command_id),
                expected_version=0,
                occurred_at=occurred_at,
                correlation_id=claim_id,
                causation_id=citation_sources[0].event_id,
            )
        )
        return self._claim_from_event((event,), expected_claim_id=claim_id)

    def has_claim(self, claim_id: str) -> bool:
        if _CLAIM_ID.fullmatch(claim_id) is None:
            return False
        if not self._journal.verify().ok:
            return False
        events = self._journal.read_stream(_claim_stream(claim_id))
        if not events:
            return False
        try:
            self._claim_from_event(events, expected_claim_id=claim_id)
        except Exception:
            return False
        return True

    def _claim_from_event(
        self, events, *, expected_claim_id: str
    ) -> SourceClaim:
        if len(events) != 1 or events[0].event_type != "SourceClaimRecorded":
            raise RuntimeError("source claim stream is invalid")
        event = events[0]
        payload = event.payload
        citations = tuple(
            SourceCitation(
                source_id=str(item["source_id"]),
                segment_id=str(item["segment_id"]),
                locator_kind=LocatorKind(str(item["locator_kind"])),
                start=int(item["start"]),
                end=int(item["end"]),
                quote_sha256=str(item["quote_sha256"]),
            )
            for item in payload["citations"]
        )
        proposal = ClaimProposal(
            statement=str(payload["statement"]),
            citations=citations,
            producer_id=str(payload["producer_id"]),
            extraction_method_id=str(payload["extraction_method_id"]),
            contradicts_claim_ids=tuple(
                str(item) for item in payload["contradicts_claim_ids"]
            ),
        )
        calculated = claim_id_for(proposal.identity_payload())
        if (
            payload.get("schema_version") != "1.0"
            or payload.get("authority") != "RESEARCH_ONLY"
            or payload.get("claim_id") != expected_claim_id
            or calculated != expected_claim_id
        ):
            raise RuntimeError("source claim content identity is invalid")
        for citation in citations:
            self._validate_citation(citation)
        return SourceClaim(
            claim_id=expected_claim_id,
            statement=" ".join(proposal.statement.split()),
            citations=citations,
            producer_id=proposal.producer_id,
            extraction_method_id=proposal.extraction_method_id,
            contradicts_claim_ids=proposal.contradicts_claim_ids,
            event_id=event.event_id,
        )

    def _validate_citation(self, citation: SourceCitation) -> SourceArtifact:
        source = self.get_source(citation.source_id)
        if source is None:
            raise ValueError("citation source does not exist")
        segment = next(
            (
                candidate
                for candidate in source.segments
                if candidate.segment_id == citation.segment_id
            ),
            None,
        )
        if segment is None:
            raise ValueError("citation segment does not exist in the source")
        if segment.locator_kind is not citation.locator_kind:
            raise ValueError("citation locator kind does not match the source")
        if citation.locator_kind is LocatorKind.CHARACTERS:
            if citation.end > len(segment.text):
                raise ValueError("citation character range exceeds the source")
            excerpt = segment.text[citation.start : citation.end]
        else:
            if citation.start != segment.start or citation.end != segment.end:
                raise ValueError("timecode citations must match a retained segment")
            excerpt = segment.text
        if sha256_id(excerpt) != citation.quote_sha256:
            raise ValueError("citation quote hash does not match retained source text")
        return source


def _source_identity(adapted: AdaptedSource, raw_sha256: str) -> dict[str, object]:
    return {
        "metadata": adapted.metadata.to_payload(),
        "adapter_id": adapted.adapter_id,
        "raw_sha256": raw_sha256,
        "segments": [segment.to_payload() for segment in adapted.segments],
    }


def _artifact_from_manifest(
    manifest: object,
    *,
    raw_path: Path,
    manifest_path: Path,
    event_id: str,
) -> SourceArtifact:
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "1.0":
        raise RuntimeError("unsupported source manifest")
    metadata_payload = manifest["metadata"]
    metadata = SourceMetadata(
        title=str(metadata_payload["title"]),
        canonical_uri=str(metadata_payload["canonical_uri"]),
        source_kind=SourceKind(str(metadata_payload["source_kind"])),
        edition=str(metadata_payload["edition"]),
        usage_rights=str(metadata_payload["usage_rights"]),
        retrieved_at=datetime.fromisoformat(str(metadata_payload["retrieved_at"])),
    )
    segments = tuple(
        SourceSegment(
            segment_id=str(item["segment_id"]),
            locator_kind=LocatorKind(str(item["locator_kind"])),
            start=int(item["start"]),
            end=int(item["end"]),
            text=str(item["text"]),
        )
        for item in manifest["segments"]
    )
    identity = {
        "metadata": metadata.to_payload(),
        "adapter_id": str(manifest["adapter_id"]),
        "raw_sha256": str(manifest["raw_sha256"]),
        "segments": [segment.to_payload() for segment in segments],
    }
    source_id = source_id_for(identity)
    if source_id != manifest.get("source_id"):
        raise RuntimeError("source manifest content identity is invalid")
    return SourceArtifact(
        source_id=source_id,
        metadata=metadata,
        adapter_id=str(manifest["adapter_id"]),
        raw_sha256=str(manifest["raw_sha256"]),
        segments=segments,
        raw_path=raw_path,
        manifest_path=manifest_path,
        event_id=event_id,
    )


def _write_immutable(destination: Path, content: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.chmod(0o444)
        try:
            os.link(temporary_path, destination)
        except FileExistsError:
            existing = _read_regular_file(destination, max(len(content), 1))
            if existing != content:
                raise RuntimeError(f"immutable provenance collision: {destination}")
        else:
            directory_fd = os.open(destination.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _source_stream(source_id: str) -> str:
    return f"provenance-source:{source_id.removeprefix('source:')}"


def _claim_stream(claim_id: str) -> str:
    return f"provenance-claim:{claim_id.removeprefix('claim:')}"


def _command_key(namespace: str, command_id: str) -> str:
    return f"provenance-{namespace}:{sha256_id(command_id).removeprefix('sha256:')}"


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("occurred_at must be timezone-aware")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeError(f"duplicate source manifest key {key!r}")
        result[key] = value
    return result
