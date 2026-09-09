"""Hybrid ``Chunker`` adapter that consumes ``PageStructure``.

Per WP06 T055.

The hybrid chunker turns one ``PageStructure`` into a list of
``Chunk`` objects:

- ``kind == 'faq'`` -> one chunk per item; the question
  (``title``) is prepended to the chunk text so the retrieval
  pipeline matches Q/A pairs as a unit.
- other kinds -> one chunk per item with the heading (``title``)
  recorded as ``Chunk.section`` for downstream debugging.

Oversized sections are split on sentence boundaries (``[.!?]\\s+``)
so no single chunk exceeds ``max_chunk_chars``.

Stable ids
----------

The ``chunk_id = sha1(source_url + ':' + ordinal)[:40]`` invariant
(AGENTS.md §4.5) is preserved by computing ``ordinal`` 0-based
and monotonic across the full chunk list. Re-running the chunker
against the same ``PageStructure`` produces identical ids.

Design rationale
----------------

This chunker is the analyzer-required variant of the ``Chunker``
port; ``FixedSizeChunker`` (WP03) is the fallback that ignores
``structure`` entirely. The ``ConfigurationError`` on
``structure is None`` makes the contract loud: the application
layer must supply a structure, and forgetting to wire the
analyzer is a programming error.
"""
from __future__ import annotations

import hashlib
import re
import time

import structlog

from support_bot.domain.ingestion.entities import (
    Chunk,
    PageStructure,
)
from support_bot.domain.shared.errors import ConfigurationError

_log = structlog.get_logger(__name__)

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def _stable_chunk_id(source_url: str, ordinal: int) -> str:
    """Return the 40-char SHA-1 prefix of ``"<source_url>:<ordinal>"``."""
    digest = hashlib.sha1(f"{source_url}:{ordinal}".encode()).hexdigest()
    return digest[:40]


class HybridChunker:
    """Chunker that consumes a ``PageStructure`` from the analyzer.

    Attributes:
        max_chunk_chars: Per-chunk ceiling. Sections whose joined
            ``title + body`` exceeds this are split on sentence
            boundaries; every resulting chunk still carries the
            section title.
    """

    def __init__(self, *, max_chunk_chars: int = 4_000) -> None:
        """Initialize the chunker.

        Args:
            max_chunk_chars: Per-chunk character cap. Default
                4 000.
        """
        self.max_chunk_chars: int = max_chunk_chars

    def _emit(
        self,
        *,
        text: str,
        source_url: str,
        ordinal: int,
        section: str | None,
    ) -> Chunk:
        """Build a ``Chunk`` with the stable id."""
        return Chunk(
            chunk_id=_stable_chunk_id(source_url, ordinal),
            source_url=source_url,
            ordinal=ordinal,
            text=text,
            section=section,
        )

    def _split_oversized(self, text: str) -> list[str]:
        """Split ``text`` into pieces, each <= ``self.max_chunk_chars``.

        Splits on sentence boundaries (``[.!?]\\s+``); the last
        piece may be shorter than the cap. If a single sentence
        exceeds the cap (very rare for Dutch/English help pages),
        it is emitted as one oversized chunk rather than split
        mid-sentence — that preserves readability for the
        downstream answerer.
        """
        if len(text) <= self.max_chunk_chars:
            return [text]
        sentences = _SENTENCE_BOUNDARY.split(text)
        pieces: list[str] = []
        current = ""
        for sent in sentences:
            candidate = (current + " " + sent).strip() if current else sent
            if len(candidate) <= self.max_chunk_chars:
                current = candidate
            else:
                if current:
                    pieces.append(current)
                # Single sentence longer than the cap -> emit as-is.
                current = sent
        if current:
            pieces.append(current)
        return pieces

    def chunk(
        self,
        text: str,  # noqa: ARG002  — accepted for port compatibility
        *,
        source_url: str,
        chunk_size: int = 500,  # noqa: ARG002  — ignored
        overlap: int = 50,  # noqa: ARG002  — ignored
        structure: PageStructure | None = None,
    ) -> list[Chunk]:
        """Emit one ``Chunk`` per ``SemanticChunk`` in ``structure``.

        Args:
            text: Unused (kept for ``Chunker`` port compatibility;
                the analyzer already produced the structure).
            source_url: The page URL; must match
                ``structure.source_url``.
            chunk_size: Ignored; the analyzer decides chunk size.
            overlap: Ignored.
            structure: The ``PageStructure`` from the analyzer.
                Required.

        Returns:
            A list of ``Chunk`` objects with stable ids and
            monotonic ordinals. Empty when ``structure.chunks``
            is empty.

        Raises:
            ConfigurationError: When ``structure`` is ``None`` or
                its ``source_url`` does not match ``source_url``.
        """
        if structure is None:
            raise ConfigurationError(
                "HybridChunker requires a PageStructure; "
                "use FixedSizeChunker for the no-analyzer path."
            )
        # Normalize source_url: callers may pass either a plain ``str``
        # (from the orchestrator) or an ``HttpUrl`` (from a freshly-built
        # PageStructure). Both must compare equal.
        url_str = str(source_url)
        if str(structure.source_url) != url_str:
            raise ConfigurationError(
                f"PageStructure.source_url={structure.source_url!r} does "
                f"not match the chunker's source_url={source_url!r}"
            )

        started = time.monotonic()
        emitted: list[Chunk] = []
        ordinal = 0
        faq_count = 0
        oversized_count = 0
        for sc in structure.chunks:
            if sc.kind == "faq":
                # FAQ chunks carry the question in the text so the
                # retrieval query matches the Q/A pair as a unit;
                # the title is ALSO recorded in ``Chunk.section`` so
                # downstream lexical re-rankers (or Chroma metadata
                # filters) can prefer FAQ headings by exact match.
                body = f"{sc.title}\n\n{sc.text}"
                pieces = self._split_oversized(body)
                if len(pieces) > 1:
                    oversized_count += 1
                for piece in pieces:
                    emitted.append(
                        self._emit(
                            text=piece,
                            source_url=url_str,
                            ordinal=ordinal,
                            section=sc.title,
                        )
                    )
                    ordinal += 1
                faq_count += len(pieces)
            else:
                body = f"{sc.title}\n\n{sc.text}"
                pieces = self._split_oversized(body)
                if len(pieces) > 1:
                    oversized_count += 1
                for piece in pieces:
                    emitted.append(
                        self._emit(
                            text=piece,
                            source_url=url_str,
                            ordinal=ordinal,
                            section=sc.title,
                        )
                    )
                    ordinal += 1
        _log.info(
            "adapter.call.ok",
            adapter="HybridChunker",
            operation="chunk",
            region_count=len(structure.chunks),
            faq_count=faq_count,
            oversized_count=oversized_count,
            emitted_count=len(emitted),
            latency_ms=(time.monotonic() - started) * 1000,
        )
        return emitted


__all__ = ["HybridChunker"]