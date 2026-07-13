"""Content-addressed source, citation, and claim contracts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SOURCE_ID = re.compile(r"source:[0-9a-f]{64}\Z")
_CLAIM_ID = re.compile(r"claim:[0-9a-f]{64}\Z")
_SEGMENT_ID = re.compile(r"segment:[0-9a-f]{64}\Z")


class SourceKind(StrEnum):
    TEXT_DOCUMENT = "TEXT_DOCUMENT"
    HTML_ARTICLE = "HTML_ARTICLE"
    TIMED_TRANSCRIPT = "TIMED_TRANSCRIPT"


class LocatorKind(StrEnum):
    CHARACTERS = "CHARACTERS"
    TIMECODE_MS = "TIMECODE_MS"


@dataclass(frozen=True)
class SourceMetadata:
    title: str
    canonical_uri: str
    source_kind: SourceKind
    edition: str
    usage_rights: str
    retrieved_at: datetime

    def __post_init__(self) -> None:
        for label, value in (
            ("title", self.title),
            ("canonical_uri", self.canonical_uri),
            ("edition", self.edition),
            ("usage_rights", self.usage_rights),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label} must not be blank")
        if not isinstance(self.source_kind, SourceKind):
            raise ValueError("source_kind must be a SourceKind")
        _aware(self.retrieved_at, "retrieved_at")

    def to_payload(self) -> dict[str, str]:
        return {
            "title": self.title.strip(),
            "canonical_uri": self.canonical_uri.strip(),
            "source_kind": self.source_kind.value,
            "edition": self.edition.strip(),
            "usage_rights": self.usage_rights.strip(),
            "retrieved_at": self.retrieved_at.astimezone(timezone.utc).isoformat(),
        }


@dataclass(frozen=True)
class SourceSegment:
    segment_id: str
    locator_kind: LocatorKind
    start: int
    end: int
    text: str

    def __post_init__(self) -> None:
        if _SEGMENT_ID.fullmatch(self.segment_id) is None:
            raise ValueError("segment_id must be content-addressed")
        if not isinstance(self.locator_kind, LocatorKind):
            raise ValueError("locator_kind must be a LocatorKind")
        if type(self.start) is not int or type(self.end) is not int:
            raise TypeError("segment locators must be integers")
        if self.start < 0 or self.end <= self.start:
            raise ValueError("segment locator range must be positive and ordered")
        if not self.text.strip():
            raise ValueError("segment text must not be blank")
        if self.segment_id != segment_id_for(
            self.locator_kind, self.start, self.end, self.text
        ):
            raise ValueError("segment_id does not match segment content")

    def to_payload(self) -> dict[str, str | int]:
        return {
            "segment_id": self.segment_id,
            "locator_kind": self.locator_kind.value,
            "start": self.start,
            "end": self.end,
            "text": self.text,
        }


@dataclass(frozen=True)
class AdaptedSource:
    metadata: SourceMetadata
    adapter_id: str
    raw_content: bytes
    segments: tuple[SourceSegment, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "segments", tuple(self.segments))
        if not self.adapter_id.strip():
            raise ValueError("adapter_id must not be blank")
        if not self.raw_content:
            raise ValueError("raw source content must not be empty")
        if not self.segments:
            raise ValueError("an adapted source needs at least one segment")
        ids = [segment.segment_id for segment in self.segments]
        if len(ids) != len(set(ids)):
            raise ValueError("source segment IDs must be unique")


@dataclass(frozen=True)
class SourceArtifact:
    source_id: str
    metadata: SourceMetadata
    adapter_id: str
    raw_sha256: str
    segments: tuple[SourceSegment, ...]
    raw_path: Path
    manifest_path: Path
    event_id: str

    def __post_init__(self) -> None:
        if _SOURCE_ID.fullmatch(self.source_id) is None:
            raise ValueError("source_id must be content-addressed")
        if _SHA256.fullmatch(self.raw_sha256) is None:
            raise ValueError("raw_sha256 must be content-addressed")


@dataclass(frozen=True)
class SourceCitation:
    source_id: str
    segment_id: str
    locator_kind: LocatorKind
    start: int
    end: int
    quote_sha256: str

    def __post_init__(self) -> None:
        if _SOURCE_ID.fullmatch(self.source_id) is None:
            raise ValueError("citation source_id must be content-addressed")
        if _SEGMENT_ID.fullmatch(self.segment_id) is None:
            raise ValueError("citation segment_id must be content-addressed")
        if not isinstance(self.locator_kind, LocatorKind):
            raise ValueError("citation locator_kind must be a LocatorKind")
        if type(self.start) is not int or type(self.end) is not int:
            raise TypeError("citation locators must be integers")
        if self.start < 0 or self.end <= self.start:
            raise ValueError("citation locator range must be positive and ordered")
        if _SHA256.fullmatch(self.quote_sha256) is None:
            raise ValueError("citation quote_sha256 must be content-addressed")

    def to_payload(self) -> dict[str, str | int]:
        return {
            "source_id": self.source_id,
            "segment_id": self.segment_id,
            "locator_kind": self.locator_kind.value,
            "start": self.start,
            "end": self.end,
            "quote_sha256": self.quote_sha256,
        }


@dataclass(frozen=True)
class ClaimProposal:
    statement: str
    citations: tuple[SourceCitation, ...]
    producer_id: str
    extraction_method_id: str
    contradicts_claim_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "citations", tuple(self.citations))
        object.__setattr__(
            self, "contradicts_claim_ids", tuple(sorted(self.contradicts_claim_ids))
        )
        for label, value in (
            ("statement", self.statement),
            ("producer_id", self.producer_id),
            ("extraction_method_id", self.extraction_method_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label} must not be blank")
        if not self.citations:
            raise ValueError("a claim requires at least one precise citation")
        if len(set(self.citations)) != len(self.citations):
            raise ValueError("claim citations must be unique")
        if len(set(self.contradicts_claim_ids)) != len(self.contradicts_claim_ids):
            raise ValueError("contradiction claim IDs must be unique")
        if any(
            _CLAIM_ID.fullmatch(claim_id) is None
            for claim_id in self.contradicts_claim_ids
        ):
            raise ValueError("contradictions must reference content-addressed claims")

    def identity_payload(self) -> dict[str, object]:
        return {
            "statement": " ".join(self.statement.split()),
            "citations": [citation.to_payload() for citation in self.citations],
            "producer_id": self.producer_id.strip(),
            "extraction_method_id": self.extraction_method_id.strip(),
            "contradicts_claim_ids": list(self.contradicts_claim_ids),
        }


@dataclass(frozen=True)
class SourceClaim:
    claim_id: str
    statement: str
    citations: tuple[SourceCitation, ...]
    producer_id: str
    extraction_method_id: str
    contradicts_claim_ids: tuple[str, ...]
    event_id: str
    authority: str = "RESEARCH_ONLY"

    def __post_init__(self) -> None:
        if _CLAIM_ID.fullmatch(self.claim_id) is None:
            raise ValueError("claim_id must be content-addressed")
        if self.authority != "RESEARCH_ONLY":
            raise ValueError("source claims have research-only authority")


def segment_id_for(
    locator_kind: LocatorKind, start: int, end: int, text: str
) -> str:
    return "segment:" + _digest(
        {
            "locator_kind": locator_kind.value,
            "start": start,
            "end": end,
            "text": text,
        }
    )


def source_id_for(payload: object) -> str:
    return "source:" + _digest(payload)


def claim_id_for(payload: object) -> str:
    return "claim:" + _digest(payload)


def sha256_id(content: bytes | str) -> str:
    encoded = content.encode("utf-8") if isinstance(content, str) else content
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _digest(payload: object) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
