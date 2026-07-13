"""Bounded source provenance without RAG or execution authority."""

from .adapters import (
    HtmlArticleAdapter,
    PlainTextAdapter,
    TimestampedTranscriptAdapter,
)
from .corpus import ProvenanceCorpus
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
)

__all__ = [
    "AdaptedSource",
    "ClaimProposal",
    "HtmlArticleAdapter",
    "LocatorKind",
    "PlainTextAdapter",
    "ProvenanceCorpus",
    "SourceArtifact",
    "SourceCitation",
    "SourceClaim",
    "SourceKind",
    "SourceMetadata",
    "SourceSegment",
    "TimestampedTranscriptAdapter",
]
