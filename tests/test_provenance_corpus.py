from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest

from sensei.operations.journal import OperationalJournal
from sensei.provenance import (
    ClaimProposal,
    HtmlArticleAdapter,
    LocatorKind,
    PlainTextAdapter,
    ProvenanceCorpus,
    SourceCitation,
    SourceKind,
    SourceMetadata,
    TimestampedTranscriptAdapter,
)


NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)


def _metadata(kind: SourceKind, uri: str) -> SourceMetadata:
    return SourceMetadata(
        title="Trading source fixture",
        canonical_uri=uri,
        source_kind=kind,
        edition="fixture-v1",
        usage_rights="owner-supplied research copy",
        retrieved_at=NOW,
    )


def _quote_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_text_and_html_sources_are_immutable_and_content_addressed(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    corpus = ProvenanceCorpus(journal, tmp_path / "corpus")
    text_path = tmp_path / "book-notes.txt"
    text_path.write_text("Wait for confirmation above the pattern high.\n")
    html_path = tmp_path / "article.html"
    html_path.write_text(
        "<html><body><article><h1>Risk</h1><p>Size from the stop.</p>"
        "<script>ignore me</script></article></body></html>"
    )

    text_source = corpus.ingest(
        PlainTextAdapter().adapt(
            text_path,
            _metadata(SourceKind.TEXT_DOCUMENT, "isbn:fixture-book"),
        ),
        occurred_at=NOW,
        command_id="ingest-book",
    )
    repeated = corpus.ingest(
        PlainTextAdapter().adapt(
            text_path,
            _metadata(SourceKind.TEXT_DOCUMENT, "isbn:fixture-book"),
        ),
        occurred_at=NOW,
        command_id="ingest-book-retry",
    )
    article = corpus.ingest(
        HtmlArticleAdapter().adapt(
            html_path,
            _metadata(SourceKind.HTML_ARTICLE, "https://example.test/risk"),
        ),
        occurred_at=NOW,
        command_id="ingest-article",
    )

    assert repeated == text_source
    assert text_source.source_id.startswith("source:")
    assert text_source.raw_sha256.startswith("sha256:")
    assert corpus.get_source(text_source.source_id) == text_source
    assert "Size from the stop." in article.segments[0].text
    assert "ignore me" not in article.segments[0].text
    assert journal.verify().ok is True


def test_timestamped_transcript_preserves_precise_timecode_citations(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    corpus = ProvenanceCorpus(journal, tmp_path / "corpus")
    transcript_path = tmp_path / "video-transcript.json"
    transcript_path.write_text(
        json.dumps(
            [
                {"start_ms": 1_000, "end_ms": 4_000, "text": "Protect capital first."},
                {"start_ms": 4_500, "end_ms": 8_000, "text": "Wait for follow-through."},
            ]
        )
    )
    source = corpus.ingest(
        TimestampedTranscriptAdapter().adapt(
            transcript_path,
            _metadata(SourceKind.TIMED_TRANSCRIPT, "video:https://example.test/v/1"),
        ),
        occurred_at=NOW,
        command_id="ingest-transcript",
    )
    segment = source.segments[1]
    citation = SourceCitation(
        source_id=source.source_id,
        segment_id=segment.segment_id,
        locator_kind=LocatorKind.TIMECODE_MS,
        start=segment.start,
        end=segment.end,
        quote_sha256=_quote_hash(segment.text),
    )

    claim = corpus.record_claim(
        ClaimProposal(
            statement="Require follow-through after the initial pattern.",
            citations=(citation,),
            producer_id="scholar-1",
            extraction_method_id="typed-extraction:v1",
        ),
        occurred_at=NOW,
        command_id="claim-follow-through",
    )

    assert claim.claim_id.startswith("claim:")
    assert claim.authority == "RESEARCH_ONLY"
    assert corpus.has_claim(claim.claim_id) is True


def test_claim_rejects_a_citation_that_does_not_match_retained_source(tmp_path):
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    corpus = ProvenanceCorpus(journal, tmp_path / "corpus")
    source_path = tmp_path / "notes.md"
    source_path.write_text("Stops belong below invalidation.\n")
    source = corpus.ingest(
        PlainTextAdapter().adapt(
            source_path,
            _metadata(SourceKind.TEXT_DOCUMENT, "file:owner-notes"),
        ),
        occurred_at=NOW,
        command_id="ingest-notes",
    )
    segment = source.segments[0]
    citation = SourceCitation(
        source_id=source.source_id,
        segment_id=segment.segment_id,
        locator_kind=LocatorKind.CHARACTERS,
        start=0,
        end=5,
        quote_sha256=_quote_hash("wrong"),
    )

    with pytest.raises(ValueError, match="quote hash"):
        corpus.record_claim(
            ClaimProposal(
                statement="Use structural invalidation.",
                citations=(citation,),
                producer_id="scholar-1",
                extraction_method_id="typed-extraction:v1",
            ),
            occurred_at=NOW,
            command_id="claim-invalid",
        )


def test_strategy_source_attribution_rejects_non_content_addressed_claims():
    from pydantic import ValidationError

    from sensei.strategy import FieldAttribution, FieldAuthority

    with pytest.raises(ValidationError, match="content-addressed"):
        FieldAttribution(
            authority=FieldAuthority.SOURCE_CLAIM,
            claim_ids=("the-model-says-this-came-from-a-book",),
        )
