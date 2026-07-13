# Provenance Corpus and bounded source claims

Status: implemented foundation. This module deliberately has no RAG, vector
store, Obsidian, Hermes, autonomous promotion, or execution authority.

## Purpose

Books, owner-supplied documents, saved blog articles, and timestamped video
transcripts are research inputs, not trading instructions. The corpus retains
their exact bytes, extraction version, canonical metadata, usage-rights label,
and precise citable spans. An LLM or human may propose a claim from those spans;
only a content-addressed, citation-verified claim may appear in a canonical
Strategy Plan. The Research Examiner and lifecycle still decide whether a
hypothesis earns any later stage.

## Source adapters

- `PlainTextAdapter` reads bounded UTF-8 text/Markdown exports for book notes and
  documents.
- `HtmlArticleAdapter` retains the HTML bytes, removes executable/non-content
  elements, and produces a stable character-addressable article segment.
- `TimestampedTranscriptAdapter` reads a strict JSON array of ordered,
  non-overlapping `{start_ms, end_ms, text}` records for video/audio material.

All local adapters reject symlinks, non-regular files, files that change during
read, invalid encodings/shapes, empty content, and configured byte/segment-limit
violations. Adding PDF/OCR or remote-download adapters must preserve this same
`AdaptedSource` contract; fetched network content is not implemented here.

## Identities and storage

`SourceMetadata` pins title, canonical URI, source kind, edition, usage rights,
and retrieval time. The Source ID covers that metadata, adapter version, raw
SHA-256, and every extracted segment. Raw bytes and a canonical manifest are
written immutably under content-derived names. The Operational Journal records
their identities and hashes; reads verify the journal, retained bytes, manifest,
segment identities, and event agreement.

A citation pins the exact Source ID, Segment ID, locator type and range, plus a
SHA-256 of the quoted text. Character citations must fit retained text.
Timecode citations must match a retained timestamped segment. A claim is
content-addressed over its normalized statement, citations, producer, extraction
method, and explicit contradiction links. Claims always have
`RESEARCH_ONLY` authority.

## Authority boundary

`FieldAttribution` and governed research hypotheses accept only
content-addressed claim IDs. Governed paper admission additionally resolves the
plan's claim IDs in the durable corpus on every candidate. This is mandatory:
constructing a claim-shaped string, retaining only a URL, or omitting the corpus
cannot satisfy admission. The retained source bytes, deterministic adapter
manifest, precise citation range, quoted-text hash and Claim identity must all
verify. Source content, a claim, an LLM output, or a Scholar result cannot
directly:

- promote a strategy plan;
- bypass preregistration or locked confirmation;
- approve a trade;
- size an order;
- change risk or safety state; or
- call a broker gateway.

Exact duplicate claims naturally converge on one identity. Contradictions are
explicit links rather than silent overwrites. Semantic retrieval, ranking, and
automatic contradiction inference are intentionally outside this foundation.
RAG, Obsidian and Hermes are not dependencies, shadow authorities, or alternate
storage paths for governed admission.
