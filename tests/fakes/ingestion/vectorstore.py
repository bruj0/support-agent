"""In-memory `FakeVectorStore` for unit and contract tests.

Stores chunks in a `dict` keyed by `chunk_id`. Not thread-safe;
not async. The `fail_next` flag drives the next call into a
`VectorStoreUnavailable` raise (M6 foundation).

Post WP01 review v1 Issue 8: `query` returns
`list[RetrievedChunk]` (not `list[Chunk]`). The fake populates
`similarity` with a deterministic score derived from the
chunk_id (an integer in `[0.0, 1.0]` so the test asserts
structural properties, not numeric content). The production
Chroma adapter (WP03) will compute similarity from cosine
distance.
"""
from __future__ import annotations

from support_bot.domain.ingestion.entities import Chunk
from support_bot.domain.shared.errors import VectorStoreUnavailable
from support_bot.domain.shared.retrieval import RetrievedChunk


def _deterministic_similarity(chunk_id: str) -> float:
    """Map a 40-char hex `chunk_id` to a `[0.0, 1.0]` similarity.

    The first 8 hex chars (32 bits) are mapped to `[0, 1]` by
    dividing by `0xFFFFFFFF`. Deterministic so tests can
    assert on specific ids without time-based flakiness.
    """
    prefix = chunk_id[:8]
    n = int(prefix, 16)
    return n / 0xFFFFFFFF


class FakeVectorStore:
    """Canned `VectorStore` backed by a `dict[str, Chunk]`.

    Attributes:
        chunks: The in-memory store.
        upsert_calls: List of batches the fake has been asked to
            upsert (read-only introspection).
        delete_calls: List of source URLs that have been deleted.
        query_calls: List of `(embedding, k)` query pairs.
        fail_next: When `True`, the next call raises
            `VectorStoreUnavailable`.
    """

    def __init__(self, *, fail_next: bool = False) -> None:
        self.chunks: dict[str, Chunk] = {}
        self.upsert_calls: list[list[Chunk]] = []
        self.delete_calls: list[str] = []
        self.query_calls: list[tuple[list[float], int]] = []
        self.fail_next: bool = fail_next

    def upsert(self, chunks: list[Chunk]) -> None:
        self.upsert_calls.append(list(chunks))
        if self.fail_next:
            self.fail_next = False
            raise VectorStoreUnavailable("FakeVectorStore injected failure")
        for chunk in chunks:
            self.chunks[chunk.chunk_id] = chunk

    def delete_by_source(self, source_url: str) -> int:
        self.delete_calls.append(source_url)
        to_delete = [
            cid for cid, c in self.chunks.items() if c.source_url == source_url
        ]
        for cid in to_delete:
            del self.chunks[cid]
        return len(to_delete)

    def count(self) -> int:
        return len(self.chunks)

    def query(self, embedding: list[float], k: int = 4) -> list[RetrievedChunk]:
        self.query_calls.append((list(embedding), k))
        if self.fail_next:
            self.fail_next = False
            raise VectorStoreUnavailable("FakeVectorStore injected failure")
        # Deterministic ordering: chunk_id ascending; cap at k.
        # Embedding is not used by the fake (a real adapter
        # would compute distance and rank). We map similarity
        # deterministically from `chunk_id` so tests assert on
        # known values.
        ordered = sorted(self.chunks.values(), key=lambda c: c.chunk_id)
        sliced = ordered[:k]
        return [
            RetrievedChunk(
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                source_url=chunk.source_url,
                similarity=_deterministic_similarity(chunk.chunk_id),
            )
            for chunk in sliced
        ]


__all__ = ["FakeVectorStore"]
