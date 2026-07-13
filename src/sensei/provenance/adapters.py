"""Bounded local adapters for documents, articles, and video transcripts."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from lxml import html

from .models import (
    AdaptedSource,
    LocatorKind,
    SourceKind,
    SourceMetadata,
    SourceSegment,
    segment_id_for,
)

_DEFAULT_MAX_BYTES = 20_000_000
_MAX_TRANSCRIPT_SEGMENTS = 200_000


class PlainTextAdapter:
    adapter_id = "plain-text:v1"

    def __init__(self, *, max_bytes: int = _DEFAULT_MAX_BYTES) -> None:
        self._max_bytes = _positive_limit(max_bytes)

    def adapt(self, path: Path, metadata: SourceMetadata) -> AdaptedSource:
        if metadata.source_kind is not SourceKind.TEXT_DOCUMENT:
            raise ValueError("PlainTextAdapter requires TEXT_DOCUMENT metadata")
        raw = _read_regular_file(Path(path), self._max_bytes)
        text = _decode_utf8(raw)
        if not text.strip():
            raise ValueError("text document has no research content")
        segment = _segment(LocatorKind.CHARACTERS, 0, len(text), text)
        return AdaptedSource(metadata, self.adapter_id, raw, (segment,))


class HtmlArticleAdapter:
    adapter_id = "html-article:v1"

    def __init__(self, *, max_bytes: int = _DEFAULT_MAX_BYTES) -> None:
        self._max_bytes = _positive_limit(max_bytes)

    def adapt(self, path: Path, metadata: SourceMetadata) -> AdaptedSource:
        if metadata.source_kind is not SourceKind.HTML_ARTICLE:
            raise ValueError("HtmlArticleAdapter requires HTML_ARTICLE metadata")
        raw = _read_regular_file(Path(path), self._max_bytes)
        try:
            document = html.fromstring(raw)
        except (ValueError, TypeError) as exc:
            raise ValueError("article is not parseable HTML") from exc
        for unwanted in document.xpath("//script|//style|//noscript|//template"):
            unwanted.drop_tree()
        text = " ".join(document.text_content().split())
        if not text:
            raise ValueError("HTML article has no research content")
        segment = _segment(LocatorKind.CHARACTERS, 0, len(text), text)
        return AdaptedSource(metadata, self.adapter_id, raw, (segment,))


class TimestampedTranscriptAdapter:
    adapter_id = "timestamped-transcript-json:v1"

    def __init__(self, *, max_bytes: int = _DEFAULT_MAX_BYTES) -> None:
        self._max_bytes = _positive_limit(max_bytes)

    def adapt(self, path: Path, metadata: SourceMetadata) -> AdaptedSource:
        if metadata.source_kind is not SourceKind.TIMED_TRANSCRIPT:
            raise ValueError(
                "TimestampedTranscriptAdapter requires TIMED_TRANSCRIPT metadata"
            )
        raw = _read_regular_file(Path(path), self._max_bytes)
        try:
            records = json.loads(raw, object_pairs_hook=_unique_object)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("transcript must be valid UTF-8 JSON") from exc
        if not isinstance(records, list) or not records:
            raise ValueError("transcript must be a non-empty segment array")
        if len(records) > _MAX_TRANSCRIPT_SEGMENTS:
            raise ValueError("transcript exceeds the segment safety limit")

        segments: list[SourceSegment] = []
        previous_end = 0
        for index, record in enumerate(records):
            if not isinstance(record, dict) or set(record) != {
                "start_ms",
                "end_ms",
                "text",
            }:
                raise ValueError(f"transcript segment {index} has invalid shape")
            start = record["start_ms"]
            end = record["end_ms"]
            text = record["text"]
            if type(start) is not int or type(end) is not int:
                raise ValueError("transcript timecodes must be integer milliseconds")
            if start < previous_end:
                raise ValueError("transcript segments must be ordered and non-overlapping")
            if end <= start:
                raise ValueError("transcript segment end must follow start")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("transcript segment text must not be blank")
            normalized = " ".join(text.split())
            segments.append(
                _segment(LocatorKind.TIMECODE_MS, start, end, normalized)
            )
            previous_end = end
        return AdaptedSource(metadata, self.adapter_id, raw, tuple(segments))


def _segment(
    locator_kind: LocatorKind, start: int, end: int, text: str
) -> SourceSegment:
    return SourceSegment(
        segment_id=segment_id_for(locator_kind, start, end, text),
        locator_kind=locator_kind,
        start=start,
        end=end,
        text=text,
    )


def _read_regular_file(path: Path, max_bytes: int) -> bytes:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
    except OSError as exc:
        raise ValueError(f"cannot open source artifact: {path.name}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("source artifacts must be regular files")
        if before.st_size <= 0 or before.st_size > max_bytes:
            raise ValueError("source artifact violates the byte limit")
        content = bytearray()
        while len(content) < before.st_size:
            chunk = os.read(
                descriptor,
                min(1_048_576, before.st_size - len(content)),
            )
            if not chunk:
                break
            content.extend(chunk)
        after = os.fstat(descriptor)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        )
        if len(content) != before.st_size or identity_before != identity_after:
            raise ValueError("source artifact changed while it was read")
        return bytes(content)
    finally:
        os.close(descriptor)


def _decode_utf8(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("text source must be valid UTF-8") from exc


def _positive_limit(value: int) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("max_bytes must be a positive integer")
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate transcript key {key!r}")
        result[key] = value
    return result
