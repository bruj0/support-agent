"""Tests for `domain/shared/retrieval.py`.

These tests are the red+green pair for `RetrievedChunk.from_chunk`
(post WP01 review v1 Issue 8) and the similarity clamp in the
shared location.
"""
from __future__ import annotations

from support_bot.domain.ingestion.entities import Chunk
from support_bot.domain.shared.retrieval import RetrievedChunk


def _make_chunk() -> Chunk:
    return Chunk.from_text("hello", source_url="https://example.com", ordinal=0)


class TestRetrievedChunkFromChunk:
    """`from_chunk` builds a RetrievedChunk from a Chunk + similarity."""

    def test_copies_chunk_id_text_source_url(self) -> None:
        chunk = _make_chunk()
        retrieved = RetrievedChunk.from_chunk(chunk, similarity=0.75)
        assert retrieved.chunk_id == chunk.chunk_id
        assert retrieved.text == chunk.text
        assert retrieved.source_url == chunk.source_url
        assert retrieved.similarity == 0.75

    def test_clamps_out_of_range_similarity(self) -> None:
        chunk = _make_chunk()
        # Validator must clamp on construction even when built
        # via the from_chunk factory.
        above = RetrievedChunk.from_chunk(chunk, similarity=1.5)
        assert above.similarity == 1.0
        below = RetrievedChunk.from_chunk(chunk, similarity=-0.5)
        assert below.similarity == 0.0


class TestRetrievedChunkValidator:
    """`similarity` clamps on direct construction too."""

    def test_clamps_negative_similarity_to_zero(self) -> None:
        rc = RetrievedChunk(
            chunk_id="a" * 40,
            text="x",
            source_url="u",
            similarity=-0.3,
        )
        assert rc.similarity == 0.0

    def test_clamps_similarity_above_one(self) -> None:
        rc = RetrievedChunk(
            chunk_id="a" * 40,
            text="x",
            source_url="u",
            similarity=2.0,
        )
        assert rc.similarity == 1.0
