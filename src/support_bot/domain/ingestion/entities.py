"""Ingestion-domain entities.

These are the business nouns of the content pipeline:

- `SourcePage` — a fetched HTML page, identified by URL.
- `CleanedPage` — the result of stripping boilerplate from a
  `SourcePage`.
- `Chunk` — a piece of cleaned text with a stable id, ready for
  embedding and persistence.
- `SemanticChunk` — one logical unit of a cleaned page (FAQ Q/A
  pair, heading + body, list, paragraph, table) emitted by the
  ``PageAnalyzer`` adapter (WP06).
- `PageStructure` — the analyzer's structured output: a list of
  ``SemanticChunk`` entries plus the model name and timestamp for
  audit (WP06).

All entities are Pydantic v2 `BaseModel` subclasses configured as
immutable (`frozen=True`). Embeddings are optional on `Chunk` so the
domain does not couple to a specific embedding backend; the
`Embedder` port assigns the vector before persistence.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


def _utcnow() -> datetime:
    """Return a timezone-aware UTC `datetime` for entity defaults."""
    return datetime.now(tz=UTC)


class SourcePage(BaseModel):
    """A fetched HTML page identified by URL.

    Attributes:
        url: The source URL (validated as `HttpUrl`).
        raw_html: The full HTML body returned by the scraper.
        fetched_at: When the page was fetched (timezone-aware UTC).
    """

    model_config = ConfigDict(frozen=True)

    url: HttpUrl
    raw_html: str = Field(min_length=1)
    fetched_at: datetime = Field(default_factory=_utcnow)


class CleanedPage(BaseModel):
    """The result of stripping boilerplate from a `SourcePage`.

    Attributes:
        url: The source URL.
        text: The cleaned, plain-text content.
        removed_boilerplate_count: How many boilerplate elements the
            cleaner dropped. Recorded so the ingestion Job can
            emit a structured log line describing what was stripped.
    """

    model_config = ConfigDict(frozen=True)

    url: HttpUrl | None = None
    text: str = Field(min_length=0)
    removed_boilerplate_count: int = Field(ge=0, default=0)


def _stable_chunk_id(source_url: str, ordinal: int) -> str:
    """Compute a stable `chunk_id` from `(source_url, ordinal)`.

    The id is the first 40 hex characters of the SHA-1 of
    `"<source_url>:<ordinal>"`. The truncated form keeps ids
    short while preserving the collision-free property for the
    corpus sizes in scope (≤ 10,000 chunks per spec NFR-001).
    """
    digest = hashlib.sha1(f"{source_url}:{ordinal}".encode()).hexdigest()
    return digest[:40]


class Chunk(BaseModel):
    """A piece of cleaned text ready for embedding.

    The `chunk_id` is computed deterministically from
    `(source_url, ordinal)` via `Chunk.from_text`, so two runs of
    the ingestion Job against the same source URL produce identical
    ids (the idempotency guarantee from spec FR-012 acceptance
    scenario 2 and WP03's TDD targets).

    Attributes:
        chunk_id: 40-character hex id (first 40 chars of SHA-1).
        source_url: Parent source URL.
        ordinal: Position of this chunk within the source page.
        text: The chunk's text content.
        embedding: The embedding vector; `None` until the
            `Embedder` adapter assigns it.
        section: Optional section heading (future use; not yet
            populated by the WP03 cleaner).
    """

    model_config = ConfigDict(frozen=True)

    chunk_id: str = Field(min_length=40, max_length=40)
    source_url: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    text: str = Field(min_length=1)
    embedding: list[float] | None = None
    section: str | None = None

    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        source_url: str,
        ordinal: int,
    ) -> Chunk:
        """Construct a `Chunk` from raw text.

        Computes the stable `chunk_id = sha1(source_url +
        ":" + ordinal)[:40]`. Use this factory when producing
        chunks from the cleaner output; assign `embedding`
        afterwards via `Chunk.model_copy(update={"embedding":
        [...]})`.
        """
        return cls(
            chunk_id=_stable_chunk_id(source_url, ordinal),
            source_url=source_url,
            ordinal=ordinal,
            text=text,
        )


ContentKind = Literal["faq", "section", "list", "paragraph", "table", "other"]


class SemanticChunk(BaseModel):
    """One logical region of a cleaned page, emitted by the analyzer.

    Attributes:
        kind: The discriminator for the region type. ``faq`` is the
            primary unit the ``HybridChunker`` keys off (one
            ``Chunk`` per FAQ pair); ``section``, ``list``,
            ``paragraph``, ``table`` cover the remaining
            structured units; ``other`` is the catch-all.
        title: The heading or question text for this region.
            Must be non-empty so each chunk carries a
            self-describing anchor.
        text: The body or answer for this region. Must be
            non-empty.
        anchor: Optional in-page anchor id when the source
            HTML exposes one (e.g. ``<h2 id="...">``).
    """

    model_config = ConfigDict(frozen=True)

    kind: ContentKind
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)
    anchor: str | None = None


class PageStructure(BaseModel):
    """The LLM-driven ``PageAnalyzer`` output.

    Attributes:
        source_url: The URL the structure was extracted from. Must
            match the page passed to ``HybridChunker.chunk``; a
            mismatch raises ``ConfigurationError`` (the orchestrator
            validates this — see the ``HybridChunker`` adapter).
        chunks: One ``SemanticChunk`` per logical region of the
            cleaned page. May be empty (the analyzer returns an
            empty structure when the page has no detectable
            structure).
        model: The LLM model used to produce the structure.
            Recorded for audit (operators must be able to
            attribute the resulting chunks to a specific model
            version).
        generated_at: When the structure was produced
            (timezone-aware UTC).
    """

    model_config = ConfigDict(frozen=True)

    source_url: HttpUrl
    chunks: list[SemanticChunk] = Field(default_factory=list)
    model: str = Field(min_length=1)
    generated_at: datetime = Field(default_factory=_utcnow)


__all__ = [
    "Chunk",
    "CleanedPage",
    "ContentKind",
    "PageStructure",
    "SemanticChunk",
    "SourcePage",
]