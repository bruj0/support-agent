"""TDD red tests for ``adapters.vectorstore_chroma.ChromaVectorStore`` and ``ChromaRetriever``.

Per WP03 T026.

The adapter wraps ``chromadb.HttpClient`` (lazy construction),
translates connection failures into ``VectorStoreUnavailable``,
and exposes ``upsert`` / ``query`` / ``delete_by_source`` /
``count``. ``ChromaRetriever`` implements the ``Retriever``
port (from ``domain/answering/ports``) by delegating to the
``ChromaVectorStore`` and an injected ``Embedder``.
"""
from __future__ import annotations

from typing import Any

import pytest

from support_bot.adapters.vectorstore_chroma import (
    ChromaRetriever,
    ChromaVectorStore,
)
from support_bot.domain.ingestion.entities import Chunk
from support_bot.domain.shared.errors import VectorStoreUnavailable


def _build_chunks(texts: list[str], source_url: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    for i, t in enumerate(texts):
        base = Chunk.from_text(text=t, source_url=source_url, ordinal=i)
        chunks.append(
            base.model_copy(update={"embedding": [0.0] * 4})
        )
    return chunks


@pytest.fixture
def store() -> ChromaVectorStore:
    """A ``ChromaVectorStore`` wired to an in-memory ephemeral client."""
    return ChromaVectorStore(
        collection_name=f"test_collection_{id(object())}",
        client_factory=_EphemeralClient,
    )


def test_upsert_then_count_returns_chunk_count(store: ChromaVectorStore) -> None:
    """After upserting 3 chunks, ``count`` returns 3."""
    chunks = _build_chunks(["a", "b", "c"], "https://example.com/")
    store.upsert(chunks)
    assert store.count() == 3


def test_upsert_then_query_returns_retrieved_chunks(store: ChromaVectorStore) -> None:
    """Querying after upsert returns ``RetrievedChunk`` instances in score order."""
    chunks = _build_chunks(["a", "b", "c"], "https://example.com/")
    store.upsert(chunks)
    results = store.query(embedding=[0.0] * 4, k=3)
    assert len(results) == 3
    assert all(r.chunk_id for r in results)
    assert all(0.0 <= r.similarity <= 1.0 for r in results)


def test_query_with_higher_k_than_count_returns_all(store: ChromaVectorStore) -> None:
    """``query(k=10)`` returns at most the count of stored chunks."""
    chunks = _build_chunks(["only"], "https://example.com/")
    store.upsert(chunks)
    results = store.query(embedding=[0.0] * 4, k=10)
    assert len(results) == 1


def test_delete_by_source_removes_matching_chunks(store: ChromaVectorStore) -> None:
    """``delete_by_source`` removes only the matching ``source_url`` chunks."""
    a = _build_chunks(["a1", "a2"], "https://a.example.com/")
    b = _build_chunks(["b1"], "https://b.example.com/")
    store.upsert(a)
    store.upsert(b)
    deleted = store.delete_by_source("https://a.example.com/")
    assert deleted == 2
    assert store.count() == 1


def test_query_raises_vector_store_unavailable_on_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A connection failure raises ``VectorStoreUnavailable``."""
    store = ChromaVectorStore(
        collection_name="test_conn_fail",
        client_factory=_BrokenClient,
    )
    with pytest.raises(VectorStoreUnavailable):
        store.query(embedding=[0.0] * 4, k=2)


def test_upsert_raises_vector_store_unavailable_on_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An upsert connection failure raises ``VectorStoreUnavailable``."""
    store = ChromaVectorStore(
        collection_name="test_conn_fail",
        client_factory=_BrokenClient,
    )
    with pytest.raises(VectorStoreUnavailable):
        store.upsert(_build_chunks(["x"], "https://example.com/"))


def test_constructor_does_not_open_client() -> None:
    """The HTTP client is opened lazily on the first call."""
    opened = {"count": 0}

    def _factory() -> Any:
        opened["count"] += 1
        return _EphemeralClient()

    store = ChromaVectorStore(
        collection_name="test_lazy",
        client_factory=_factory,
    )
    assert opened["count"] == 0
    store.count()
    assert opened["count"] == 1


def test_retriever_uses_injected_embedder(store: ChromaVectorStore) -> None:
    """``ChromaRetriever`` calls the injected ``Embedder`` to compute the query vector."""
    chunks = _build_chunks(["alpha", "beta"], "https://example.com/")
    store.upsert(chunks)

    captured: list[list[str]] = []

    class _Embedder:
        def embed(self, texts: list[str]) -> list[list[float]]:
            captured.append(list(texts))
            return [[0.0] * 4]

    retriever = ChromaRetriever(vectorstore=store, embedder=_Embedder())
    results = retriever.retrieve(query="any", k=2)
    assert captured == [["any"]]
    assert len(results) == 2


class _EphemeralClient:
    """Minimal Chroma client wrapper backed by an in-memory ``chromadb.EphemeralClient``.

    Implements only the subset of methods the adapter uses:
    ``get_or_create_collection``.
    """

    def __init__(self) -> None:
        import chromadb

        self._client = chromadb.EphemeralClient()

    def get_or_create_collection(self, name: str) -> Any:
        return self._client.get_or_create_collection(name=name)


class _BrokenClient:
    """Client whose every method raises a connection-like error."""

    def get_or_create_collection(self, name: str) -> Any:
        import requests

        raise requests.ConnectionError("connection refused")
