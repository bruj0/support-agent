"""In-memory `FakeChunker` for unit and contract tests.

Returns chunks with predictable ids and ordinals so the
`FakeVectorStore` round-trip tests can assert structural
properties.
"""
from __future__ import annotations

from support_bot.domain.ingestion.entities import Chunk


class FakeChunker:
    """Canned `Chunker` that splits on whitespace.

    The split is intentionally trivial — WP03's real
    `FixedSizeChunker` is the production implementation under
    test. This fake exists only so application tests in WP02
    can wire a `Chunker` without depending on real chunking
    logic.

    Attributes:
        fail_next: When `True`, the next call raises
            `NotImplementedError` (kept loose because the chunker
            port does not declare a typed exception — the
            domain's PreEmbedValidator is what rejects garbage,
            see WP03).
    """

    def __init__(self, *, fail_next: bool = False) -> None:
        self.fail_next: bool = fail_next
        self.calls: list[tuple[str, str, int, int]] = []

    def chunk(
        self,
        text: str,
        *,
        source_url: str,
        chunk_size: int = 500,
        overlap: int = 50,
        structure: object | None = None,
    ) -> list[Chunk]:
        if self.fail_next:
            self.fail_next = False
            raise NotImplementedError("FakeChunker injected failure")
        self.calls.append((text, source_url, chunk_size, overlap))
        words = text.split()
        # One chunk per word; trivially small, but stable ids.
        return [
            Chunk.from_text(word, source_url=source_url, ordinal=i)
            for i, word in enumerate(words)
        ]


__all__ = ["FakeChunker"]