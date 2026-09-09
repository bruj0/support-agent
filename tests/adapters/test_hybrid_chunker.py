"""TDD contract for ``adapters.hybrid_chunker.HybridChunker``.

Per WP06 T055.

The hybrid chunker consumes a ``PageStructure`` produced by the
``PageAnalyzer`` and emits one ``Chunk`` per logical region:

- ``kind == 'faq'`` -> one chunk per item with title prepended.
- other kinds -> one chunk per item; oversized sections are
  split at sentence boundaries.

Contract:
- ``structure`` must NOT be ``None`` (this is the analyzer-required
  variant of the ``Chunker`` port).
- ``structure.source_url`` must match the ``source_url`` argument
  (otherwise raise ``ConfigurationError``).
- Stable ``chunk_id = sha1(source_url + ':' + ordinal)[:40]``
  (AGENTS.md §4.5).
- ``Chunk.section`` is populated for non-FAQ chunks.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from support_bot.adapters.hybrid_chunker import HybridChunker
from support_bot.domain.ingestion.entities import (
    PageStructure,
    SemanticChunk,
)
from support_bot.domain.shared.errors import ConfigurationError


def _ps(
    *, chunks: list[SemanticChunk], source_url: str = "https://example.com/help"
) -> PageStructure:
    return PageStructure(
        source_url=source_url,
        chunks=chunks,
        model="gpt-4o-mini",
        generated_at=datetime(2026, 9, 7, tzinfo=UTC),
    )


def test_rejects_none_structure() -> None:
    """``structure=None`` raises ``ConfigurationError`` (WP06 design)."""
    chunker = HybridChunker()
    with pytest.raises(ConfigurationError):
        chunker.chunk(
            "ignored",
            source_url="https://example.com/help",
            structure=None,
        )


def test_rejects_mismatched_source_url() -> None:
    """A structure whose ``source_url`` differs raises ``ConfigurationError``."""
    chunker = HybridChunker()
    ps = _ps(chunks=[SemanticChunk(kind="faq", title="Q", text="A")])
    with pytest.raises(ConfigurationError):
        chunker.chunk(
            "ignored",
            source_url="https://other.example.com/x",
            structure=ps,
        )


def test_faq_one_chunk_per_pair() -> None:
    """One FAQ pair -> one chunk with the question prepended."""
    chunker = HybridChunker()
    ps = _ps(
        chunks=[
            SemanticChunk(
                kind="faq",
                title="Hoe installeer ik mijn modem?",
                text="Sluit het aan op het wandcontact.",
            )
        ]
    )
    chunks = chunker.chunk("ignored", source_url=ps.source_url, structure=ps)
    assert len(chunks) == 1
    assert "Hoe installeer ik mijn modem?" in chunks[0].text
    assert "Sluit het aan" in chunks[0].text
    # WP06 follow-up: FAQ chunks also carry the title in
    # ``Chunk.section`` so downstream lexical re-rankers /
    # chroma metadata filters can prefer FAQ headings by
    # exact match. The title is already inlined into the body
    # text, so ``section`` is a second copy for filtering.
    assert chunks[0].section == "Hoe installeer ik mijn modem?"


def test_section_one_chunk_with_section_heading() -> None:
    """A non-FAQ chunk populates ``Chunk.section``."""
    chunker = HybridChunker()
    ps = _ps(
        chunks=[
            SemanticChunk(
                kind="section",
                title="Veelgestelde vragen",
                text="Antwoorden op veelgestelde vragen over je abonnement.",
            )
        ]
    )
    chunks = chunker.chunk("ignored", source_url=ps.source_url, structure=ps)
    assert len(chunks) == 1
    assert chunks[0].section == "Veelgestelde vragen"


def test_multiple_faqs_each_get_a_chunk() -> None:
    """N FAQ entries -> N chunks, ordinals monotonic from 0."""
    chunker = HybridChunker()
    ps = _ps(
        chunks=[
            SemanticChunk(kind="faq", title="Q1", text="A1"),
            SemanticChunk(kind="faq", title="Q2", text="A2"),
            SemanticChunk(kind="faq", title="Q3", text="A3"),
        ]
    )
    chunks = chunker.chunk("ignored", source_url=ps.source_url, structure=ps)
    assert len(chunks) == 3
    assert [c.ordinal for c in chunks] == [0, 1, 2]


def test_chunk_ids_are_stable_across_reruns() -> None:
    """Re-running the chunker yields identical chunk_ids (AGENTS.md §4.5)."""
    chunker = HybridChunker()
    ps = _ps(
        chunks=[
            SemanticChunk(kind="faq", title="Q1", text="A1"),
            SemanticChunk(kind="section", title="S1", text="Body1"),
            SemanticChunk(kind="faq", title="Q2", text="A2"),
        ]
    )
    url = str(ps.source_url)
    first = chunker.chunk("ignored", source_url=url, structure=ps)
    second = chunker.chunk("ignored", source_url=url, structure=ps)
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]


def test_empty_structure_returns_no_chunks() -> None:
    """An empty ``PageStructure.chunks`` returns ``[]`` (matches FixedSizeChunker)."""
    chunker = HybridChunker()
    ps = _ps(chunks=[])
    chunks = chunker.chunk("ignored", source_url=ps.source_url, structure=ps)
    assert chunks == []


def test_oversized_section_split_at_sentence_boundary() -> None:
    """A section whose joined text exceeds ``max_chunk_chars`` is split."""
    chunker = HybridChunker(max_chunk_chars=100)
    body = (
        "Eerste zin van de paragraaf. "
        "Tweede zin met extra detail. "
        "Derde zin die het onderwerp afsluit met een langere toelichting "
        "en een vierde die nog wat extra context biedt aan de lezer."
    )
    ps = _ps(chunks=[SemanticChunk(kind="section", title="Big", text=body)])
    chunks = chunker.chunk("ignored", source_url=ps.source_url, structure=ps)
    assert len(chunks) > 1
    # Every emitted chunk still carries the section title.
    for c in chunks:
        assert c.section == "Big"
    # Ordinals are 0-based and contiguous.
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


def test_faq_section_mixed_ordering() -> None:
    """A mix of FAQ + section + list produces one chunk per region, in order."""
    chunker = HybridChunker()
    ps = _ps(
        chunks=[
            SemanticChunk(kind="section", title="Intro", text="Inleiding."),
            SemanticChunk(kind="faq", title="Q1", text="A1"),
            SemanticChunk(kind="list", title="Opts", text="een twee drie"),
            SemanticChunk(kind="faq", title="Q2", text="A2"),
        ]
    )
    chunks = chunker.chunk("ignored", source_url=ps.source_url, structure=ps)
    assert len(chunks) == 4
    assert chunks[0].section == "Intro"
    # FAQ chunks now also carry their title in ``section``
    # (see comment in ``test_faq_one_chunk_per_pair``).
    assert chunks[1].section == "Q1"
    assert chunks[2].section == "Opts"
    assert chunks[3].section == "Q2"  # FAQ (carries title in section)