"""In-memory `FakeRetriever` for unit and contract tests.

Returns a configurable list of `RetrievedChunk`s. The
`fail_next` flag drives the next call into a
`VectorStoreUnavailable` raise (M6); `raise_empty` drives the
next call into an `EmptyRetrieval` raise (the guard node's
informational exception).
"""
from __future__ import annotations

from support_bot.domain.shared.errors import EmptyRetrieval, VectorStoreUnavailable
from support_bot.domain.shared.retrieval import RetrievedChunk


class FakeRetriever:
    """Canned `Retriever` returning a configurable list.

    Attributes:
        retrieved_chunks: What `retrieve` returns. Configure
            before calling.
        raise_empty: When `True`, the next `retrieve` raises
            `EmptyRetrieval`. Auto-resets after one raise.
        fail_next: When `True`, the next `retrieve` raises
            `VectorStoreUnavailable`. Auto-resets after one
            raise.
        calls: List of `(question, k)` pairs that have been
            retrieved (read-only introspection).
    """

    def __init__(
        self,
        retrieved_chunks: list[RetrievedChunk] | None = None,
        *,
        fail_next: bool = False,
        raise_empty: bool = False,
    ) -> None:
        self.retrieved_chunks: list[RetrievedChunk] = list(retrieved_chunks or [])
        self.fail_next: bool = fail_next
        self.raise_empty: bool = raise_empty
        self.calls: list[tuple[str, int]] = []

    def retrieve(self, question: str, k: int = 4) -> list[RetrievedChunk]:
        self.calls.append((question, k))
        if self.fail_next:
            self.fail_next = False
            raise VectorStoreUnavailable("FakeRetriever injected failure")
        if self.raise_empty:
            self.raise_empty = False
            raise EmptyRetrieval()
        return list(self.retrieved_chunks)[:k]


__all__ = ["FakeRetriever"]