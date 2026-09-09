"""Fixed-size sliding-window ``Chunker`` adapter.

Per WP03 T023.

The chunker slides a window of ``chunk_size`` characters with
``overlap`` characters of overlap across the cleaned text,
emitting one ``Chunk`` per window. Chunk ids are produced via
``Chunk.from_text`` and are therefore stable across runs for
the same ``(source_url, ordinal)`` — a requirement for the
ingestion idempotency guarantee (spec FR-012 acceptance
scenario 2).

Design choices
--------------

We use char-based chunking rather than token-based because:

1. It is simpler — no tokenizer dependency at this layer.
2. It is deterministic — the same text always produces the
   same chunk boundaries.
3. It is language-agnostic — no per-locale tokenizer config.

The 500 / 50 defaults match the technical assignment's example.
Future work (WP04+) can tune these via the composition root
without changing the port contract.
"""
from __future__ import annotations

import time

import structlog

from support_bot.domain.ingestion.entities import Chunk

_log = structlog.get_logger(__name__)


class FixedSizeChunker:
    """``Chunker`` adapter splitting text into fixed-size windows.

    Attributes:
        chunk_size: Window size in characters. Must be > 0.
        overlap: Overlap between consecutive windows in
            characters. Must be strictly smaller than
            ``chunk_size``.
    """

    def __init__(self, *, chunk_size: int = 500, overlap: int = 50) -> None:
        """Initialise the chunker.

        Args:
            chunk_size: Window size in characters.
            overlap: Overlap between consecutive windows in
                characters. Must be strictly smaller than
                ``chunk_size``.
        """
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if overlap < 0 or overlap >= chunk_size:
            raise ValueError(
                f"overlap ({overlap}) must be in [0, chunk_size) (got chunk_size={chunk_size})"
            )
        self.chunk_size: int = chunk_size
        self.overlap: int = overlap

    def chunk(self, text: str, *, source_url: str) -> list[Chunk]:
        """Split ``text`` into ``Chunk`` objects with stable ids.

        Args:
            text: The cleaned plain-text body.
            source_url: The parent source URL, used as part of
                the stable ``chunk_id``.

        Returns:
            A list of ``Chunk`` objects with monotonic ordinals
            starting at 0. An empty input yields an empty list.
        """
        from opentelemetry import trace  # lazy: SDK-free at import

        tracer = trace.get_tracer("support_bot.adapter.chunker")
        with tracer.start_as_current_span("adapter.chunker.chunk") as span:
            text_len = len(text)
            span.set_attribute("chunker.chunk_size", self.chunk_size)
            span.set_attribute("chunker.overlap", self.overlap)
            span.set_attribute("chunker.text_length", text_len)
            _log.debug(
                "adapter.call.start",
                adapter="FixedSizeChunker",
                operation="chunk",
                text_length=text_len,
                chunk_size=self.chunk_size,
                overlap=self.overlap,
            )
            started = time.monotonic()

            if not text:
                elapsed_ms = (time.monotonic() - started) * 1000.0
                _log.info(
                    "adapter.call.ok",
                    adapter="FixedSizeChunker",
                    operation="chunk",
                    chunk_count=0,
                    latency_ms=elapsed_ms,
                )
                return []

            step = self.chunk_size - self.overlap
            chunks: list[Chunk] = []
            for ordinal, start in enumerate(range(0, text_len, step)):
                end = start + self.chunk_size
                window = text[start:end]
                if not window:
                    break
                chunks.append(
                    Chunk.from_text(window, source_url=source_url, ordinal=ordinal)
                )
                if end >= text_len:
                    break

            elapsed_ms = (time.monotonic() - started) * 1000.0
            span.set_attribute("chunker.chunk_count", len(chunks))
            _log.info(
                "adapter.call.ok",
                adapter="FixedSizeChunker",
                operation="chunk",
                chunk_count=len(chunks),
                latency_ms=elapsed_ms,
            )
            return chunks


__all__ = ["FixedSizeChunker"]
