"""Tests for the ingestion-domain entities."""
from __future__ import annotations

from datetime import UTC

import pytest
from pydantic import ValidationError

from support_bot.domain.ingestion.entities import (
    Chunk,
    CleanedPage,
    SourcePage,
    _stable_chunk_id,
)


class TestSourcePage:
    """`SourcePage` is an immutable Pydantic record."""

    def test_construction_sets_fetched_at_to_utc(self) -> None:
        page = SourcePage(
            url="https://example.com/internet",  # type: ignore[arg-type]
            raw_html="<html></html>",
        )
        assert page.fetched_at.tzinfo is not None
        assert page.fetched_at.tzinfo.utcoffset(page.fetched_at) == UTC.utcoffset(
            page.fetched_at
        )

    def test_frozen_instance_raises_on_mutation(self) -> None:
        page = SourcePage(
            url="https://example.com/internet",  # type: ignore[arg-type]
            raw_html="<html></html>",
        )
        with pytest.raises(ValidationError):
            page.raw_html = "tampered"

    def test_invalid_url_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SourcePage(url="not-a-url", raw_html="<html></html>")  # type: ignore[arg-type]

    def test_empty_raw_html_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SourcePage(
                url="https://example.com/internet",  # type: ignore[arg-type]
                raw_html="",
            )


class TestCleanedPage:
    """`CleanedPage` records the cleaner output + boilerplate count."""

    def test_default_boilerplate_count_is_zero(self) -> None:
        page = CleanedPage(
            url="https://example.com/internet",  # type: ignore[arg-type]
            text="hello",
        )
        assert page.removed_boilerplate_count == 0

    def test_negative_boilerplate_count_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CleanedPage(
                url="https://example.com/internet",  # type: ignore[arg-type]
                text="hello",
                removed_boilerplate_count=-1,
            )


class TestChunk:
    """`Chunk` carries a stable id computed from `(source_url,
    ordinal)`."""

    def test_stable_chunk_id_is_40_chars(self) -> None:
        cid = _stable_chunk_id("https://example.com", 0)
        assert len(cid) == 40
        assert all(c in "0123456789abcdef" for c in cid)

    def test_from_text_computes_stable_id(self) -> None:
        chunk = Chunk.from_text(
            "hello",
            source_url="https://example.com",
            ordinal=0,
        )
        assert chunk.chunk_id == _stable_chunk_id(
            "https://example.com", 0
        )
        assert chunk.ordinal == 0
        assert chunk.embedding is None

    def test_same_inputs_produce_same_id(self) -> None:
        a = Chunk.from_text("x", source_url="u", ordinal=3)
        b = Chunk.from_text("y", source_url="u", ordinal=3)
        # Different text but same id (id is keyed by
        # (source_url, ordinal), not text content) — this is the
        # idempotency guarantee from spec FR-012.
        assert a.chunk_id == b.chunk_id

    def test_chunk_is_frozen(self) -> None:
        chunk = Chunk.from_text("hello", source_url="u", ordinal=0)
        with pytest.raises(ValidationError):
            chunk.text = "tampered"  # type: ignore[misc]

    def test_embedding_assignment_via_model_copy(self) -> None:
        chunk = Chunk.from_text("hi", source_url="u", ordinal=0)
        with_emb = chunk.model_copy(update={"embedding": [0.1, 0.2]})
        assert with_emb.embedding == [0.1, 0.2]
        # Original is unchanged (frozen).
        assert chunk.embedding is None

    def test_invalid_chunk_id_length_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Chunk(
                chunk_id="tooshort",
                source_url="u",
                ordinal=0,
                text="x",
            )