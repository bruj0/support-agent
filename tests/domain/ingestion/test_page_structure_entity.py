"""TDD contract for ``domain.ingestion.entities.PageStructure``.

Per WP06 T051.

The ``PageStructure`` is the LLM analyzer's output: it lists one
``SemanticChunk`` per logical region of the cleaned page (FAQ Q/A
pair, heading + body, list, paragraph, table). Pydantic validation
is the contract boundary — the LLM may emit slightly malformed
JSON, so the entity must reject all obvious drift.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from support_bot.domain.ingestion.entities import (
    Chunk,
    ContentKind,
    PageStructure,
    SemanticChunk,
)


def _valid_structure() -> PageStructure:
    return PageStructure(
        source_url="https://example.com/help",
        chunks=[
            SemanticChunk(
                kind="faq",
                title="Hoe installeer ik mijn modem?",
                text="Sluit het modem aan op het wandcontact.",
            ),
            SemanticChunk(
                kind="section",
                title="Veelgestelde vragen",
                text="Hier vind je antwoorden op veelgestelde vragen.",
            ),
        ],
        model="gpt-4o-mini",
        generated_at=datetime(2026, 9, 7, tzinfo=UTC),
    )


def test_semantic_chunk_is_frozen() -> None:
    """SemanticChunk is immutable (frozen=True)."""
    sc = SemanticChunk(kind="faq", title="Q?", text="A.")
    with pytest.raises(ValidationError):
        sc.title = "Q!?"  # type: ignore[misc]


def test_semantic_chunk_rejects_empty_title() -> None:
    """``title`` must be non-empty so chunks are self-describing."""
    with pytest.raises(ValidationError):
        SemanticChunk(kind="faq", title="", text="answer")


def test_semantic_chunk_rejects_empty_text() -> None:
    """``text`` must be non-empty."""
    with pytest.raises(ValidationError):
        SemanticChunk(kind="faq", title="Q?", text="")


def test_semantic_chunk_rejects_unknown_kind() -> None:
    """``kind`` is a strict Literal; anything else is rejected."""
    with pytest.raises(ValidationError):
        SemanticChunk(kind="heading", title="Q?", text="A.")  # type: ignore[arg-type]


def test_page_structure_accepts_well_formed_input() -> None:
    """Round-trip a well-formed structure."""
    ps = _valid_structure()
    assert len(ps.chunks) == 2
    assert ps.chunks[0].kind == "faq"
    assert ps.model == "gpt-4o-mini"


def test_page_structure_accepts_empty_chunks() -> None:
    """Empty ``chunks`` is valid — FixedSizeChunker fallback case."""
    ps = PageStructure(
        source_url="https://example.com/empty",
        chunks=[],
        model="gpt-4o-mini",
        generated_at=datetime(2026, 9, 7, tzinfo=UTC),
    )
    assert ps.chunks == []


def test_page_structure_rejects_missing_model() -> None:
    """Missing ``model`` is rejected (audit trail)."""
    with pytest.raises(ValidationError):
        PageStructure(
            source_url="https://example.com",
            chunks=[],
            generated_at=datetime(2026, 9, 7, tzinfo=UTC),
        )  # type: ignore[call-arg]


def test_page_structure_rejects_malformed_chunk() -> None:
    """A nested SemanticChunk that fails validation trips the parent."""
    with pytest.raises(ValidationError):
        PageStructure(
            source_url="https://example.com",
            chunks=[{"kind": "faq", "title": "", "text": "x"}],  # type: ignore[list-item]
            model="gpt-4o-mini",
            generated_at=datetime(2026, 9, 7, tzinfo=UTC),
        )


def test_page_structure_is_frozen() -> None:
    """PageStructure is immutable after construction."""
    ps = _valid_structure()
    with pytest.raises(ValidationError):
        ps.model = "gpt-4o"  # type: ignore[misc]


def test_content_kind_is_exhaustive_literal() -> None:
    """``ContentKind`` covers all five content kinds plus an 'other' bucket."""
    assert set(ContentKind.__args__) == {  # type: ignore[attr-defined]
        "faq",
        "section",
        "list",
        "paragraph",
        "table",
        "other",
    }


def test_chunk_section_remains_optional() -> None:
    """``Chunk.section`` is still optional (pre-existing forward-compat seam)."""
    chunk = Chunk.from_text("hello world", source_url="u", ordinal=0)
    assert chunk.section is None