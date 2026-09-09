"""TDD red tests for ``adapters.chunker.FixedSizeChunker``.

Per WP03 T023.

The chunker slides a window of ``chunk_size`` characters with
``overlap`` characters of overlap and emits one ``Chunk`` per
window via ``Chunk.from_text``. Chunk ids must be stable across
runs for the same ``(source_url, ordinal)``.
"""
from __future__ import annotations

import pytest

from support_bot.adapters.chunker import FixedSizeChunker
from support_bot.domain.ingestion.entities import Chunk

URL = "https://example.com/help"


def test_chunk_default_size_overlap() -> None:
    """Default chunk_size=500, overlap=50."""
    chunker = FixedSizeChunker()
    assert chunker.chunk_size == 500
    assert chunker.overlap == 50


def test_chunk_returns_chunks_for_short_text() -> None:
    """A short text returns one chunk."""
    chunker = FixedSizeChunker(chunk_size=100, overlap=10)
    chunks = chunker.chunk("hello world", source_url=URL)
    assert len(chunks) == 1
    assert chunks[0].text == "hello world"
    assert chunks[0].source_url == URL
    assert chunks[0].ordinal == 0


def test_chunk_ordinals_are_monotonic() -> None:
    """Chunk ordinals are monotonic starting at 0."""
    text = "x" * 250
    chunker = FixedSizeChunker(chunk_size=100, overlap=10)
    chunks = chunker.chunk(text, source_url=URL)
    ordinals = [c.ordinal for c in chunks]
    assert ordinals == list(range(len(chunks)))


def test_chunk_size_is_respected() -> None:
    """Each chunk is at most ``chunk_size`` characters (last chunk may be smaller)."""
    text = "abcdefghij" * 30  # 300 chars
    chunker = FixedSizeChunker(chunk_size=100, overlap=20)
    chunks = chunker.chunk(text, source_url=URL)
    for chunk in chunks[:-1]:
        assert len(chunk.text) <= 100


def test_chunk_overlap_produces_expected_count() -> None:
    """Two chunks with overlap=10 produce the right number of chunks."""
    text = "x" * 100
    chunker = FixedSizeChunker(chunk_size=50, overlap=10)
    chunks = chunker.chunk(text, source_url=URL)
    # Window starts at 0, 40, 80 — three chunks.
    assert len(chunks) == 3


def test_chunk_ids_are_stable_for_same_input() -> None:
    """Chunk ids are deterministic for ``(source_url, ordinal)``."""
    text = "y" * 250
    chunker = FixedSizeChunker(chunk_size=100, overlap=10)
    first = chunker.chunk(text, source_url=URL)
    second = chunker.chunk(text, source_url=URL)
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]


def test_chunk_ids_differ_across_source_urls() -> None:
    """Chunk ids differ across source URLs even when text and ordinal are equal."""
    text = "y" * 250
    chunker = FixedSizeChunker(chunk_size=100, overlap=10)
    a = chunker.chunk(text, source_url="https://a.example/")
    b = chunker.chunk(text, source_url="https://b.example/")
    assert a[0].chunk_id != b[0].chunk_id


def test_chunk_custom_chunk_size() -> None:
    """Custom chunk_size is respected."""
    text = "z" * 1000
    chunker = FixedSizeChunker(chunk_size=200, overlap=20)
    chunks = chunker.chunk(text, source_url=URL)
    # 200 / (200 - 20) = ~5.5 windows
    assert len(chunks) >= 5


def test_chunk_returns_empty_list_for_empty_text() -> None:
    """Empty text returns an empty list."""
    chunker = FixedSizeChunker(chunk_size=100, overlap=10)
    assert chunker.chunk("", source_url=URL) == []


def test_chunk_returns_chunk_instances() -> None:
    """Each returned element is a `Chunk` instance."""
    chunker = FixedSizeChunker(chunk_size=50, overlap=5)
    chunks = chunker.chunk("hello", source_url=URL)
    assert all(isinstance(c, Chunk) for c in chunks)


def test_chunk_constructor_rejects_invalid_overlap() -> None:
    """Overlap must be smaller than chunk_size."""
    with pytest.raises(ValueError):
        FixedSizeChunker(chunk_size=50, overlap=50)
    with pytest.raises(ValueError):
        FixedSizeChunker(chunk_size=50, overlap=100)
