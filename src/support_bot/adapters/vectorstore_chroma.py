"""Chroma ``VectorStore`` and ``Retriever`` adapter.

Per WP03 T026.

Both classes wrap every public method in
``tracer.start_as_current_span("adapter.<port>.<method>")``
with the AGENTS.md 6.4 mandatory span attributes. The
``request_id`` is read from the active OTel span attribute that
the application layer (or composition root) sets before the
call — the adapter itself never imports ``opentelemetry``
directly at import time (only at call time, lazily), so the
SDK surface stays contained.

Design choices
--------------

Chroma is chosen for its HTTP-server model that decouples
storage from the API process, matching the Docker / k8s
deployment topology. The HTTP client is preferred over
``PersistentClient`` for any non-local dev so the cluster
storage survives API restarts.

The ``client_factory`` indirection lets tests substitute a
``chromadb.EphemeralClient``-backed stand-in and let production
wire a real ``chromadb.HttpClient``. This keeps the production
code path testable without monkeypatching ``chromadb``.
"""
from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from typing import Any, Protocol

import structlog

from support_bot.domain.ingestion.entities import Chunk
from support_bot.domain.shared.errors import VectorStoreUnavailable
from support_bot.domain.shared.retrieval import RetrievedChunk

_log = structlog.get_logger(__name__)


class _ClientLike(Protocol):
    """Structural interface for the Chroma client."""

    def get_or_create_collection(self, name: str) -> Any:  # pragma: no cover
        """Return (or create) the collection named ``name``."""
        ...


def _clamp01(value: float) -> float:
    """Clamp ``value`` into ``[0.0, 1.0]``."""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _chunk_text_hash(text: str) -> str:
    """First 16 hex chars of ``sha256(text)`` for span attributes."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _source_url_hash(url: str) -> str:
    """First 16 hex chars of ``sha256(url)`` for span attributes."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


class ChromaVectorStore:
    """``VectorStore`` adapter backed by ChromaDB.

    Attributes:
        collection_name: The Chroma collection name. Default
            ``"support_bot"`` per the assignment.
        client_factory: A zero-arg callable returning a
            Chroma client (``HttpClient`` in production,
            ``EphemeralClient`` in tests). Lazy — invoked on
            the first ``upsert`` / ``query`` / ``count`` /
            ``delete_by_source`` call.
        _client: The lazily-built client.
        _collection: The lazily-fetched collection handle.
    """

    def __init__(
        self,
        *,
        host: str = "localhost",
        port: int = 8000,
        collection_name: str = "support_bot",
        tenant: str = "default_tenant",
        database: str = "default_database",
        client_factory: Callable[[], _ClientLike] | None = None,
    ) -> None:
        """Initialise the adapter.

        Args:
            host: Chroma HTTP host (production).
            port: Chroma HTTP port (production).
            collection_name: The Chroma collection name.
            tenant: Chroma tenant id.
            database: Chroma database id.
            client_factory: Optional zero-arg factory that
                returns a Chroma client. Used by tests to
                substitute an in-memory client.
        """
        self.host: str = host
        self.port: int = port
        self.collection_name: str = collection_name
        self.tenant: str = tenant
        self.database: str = database
        self._client_factory: Callable[[], _ClientLike] | None = client_factory
        self._client: _ClientLike | None = None
        self._collection: Any = None

    def _ensure_client(self) -> _ClientLike:
        """Open the Chroma client lazily on first use."""
        if self._client is None:
            if self._client_factory is not None:
                self._client = self._client_factory()
            else:
                import chromadb

                self._client = chromadb.HttpClient(
                    host=self.host,
                    port=self.port,
                    tenant=self.tenant,
                    database=self.database,
                )
        return self._client

    def _ensure_collection(self) -> Any:
        """Open the collection lazily on first use."""
        if self._collection is None:
            self._collection = self._ensure_client().get_or_create_collection(
                name=self.collection_name
            )
        return self._collection

    def upsert(self, chunks: list[Chunk]) -> None:
        """Upsert ``chunks`` into the collection.

        Args:
            chunks: Chunks to persist. Each ``chunk`` must have
                a non-empty ``chunk_id``, ``text``, and
                ``source_url``. The ``embedding`` field is
                required at this point — the ingestion service
                assigns it via the embedder before calling.

        Raises:
            VectorStoreUnavailable: On connection failure or
                any other Chroma-level error.
        """
        from opentelemetry import trace  # lazy: SDK-free at import

        tracer = trace.get_tracer("support_bot.adapter.vectorstore")
        with tracer.start_as_current_span("adapter.vectorstore.upsert") as span:
            source_urls = sorted({c.source_url for c in chunks})
            span.set_attribute("vectorstore.chunk_count", len(chunks))
            span.set_attribute(
                "vectorstore.source_url_hash",
                _source_url_hash(source_urls[0]) if source_urls else "",
            )
            _log.debug(
                "adapter.call.start",
                adapter="ChromaVectorStore",
                operation="upsert",
                chunk_count=len(chunks),
                source_url_hashes=[_source_url_hash(u) for u in source_urls],
            )
            started = time.monotonic()
            try:
                collection = self._ensure_collection()
                collection.upsert(
                    ids=[c.chunk_id for c in chunks],
                    documents=[c.text for c in chunks],
                    embeddings=[list(c.embedding or []) for c in chunks],
                    metadatas=[
                        {
                            "source_url": c.source_url,
                            # Preserve the WP06 HybridChunker section
                            # title as a filterable metadata field so
                            # lexical-recovery queries (e.g. "Hoe kan
                            # ik mijn Ziggo internet instellen?" vs
                            # "Hoe installeer ik Ziggo Internet?")
                            # can rank FAQ headings by similarity.
                            "section": c.section or "",
                            "ordinal": int(c.ordinal),
                        }
                        for c in chunks
                    ],
                )
                elapsed_ms = (time.monotonic() - started) * 1000.0
                _log.info(
                    "adapter.call.ok",
                    adapter="ChromaVectorStore",
                    operation="upsert",
                    chunk_count=len(chunks),
                    latency_ms=elapsed_ms,
                )
            except VectorStoreUnavailable:
                raise
            except Exception as exc:
                elapsed_ms = (time.monotonic() - started) * 1000.0
                span.set_attribute("error.type", type(exc).__name__)
                _log.info(
                    "adapter.call.ok",
                    adapter="ChromaVectorStore",
                    operation="upsert",
                    outcome="error",
                    error_type=type(exc).__name__,
                    latency_ms=elapsed_ms,
                )
                raise VectorStoreUnavailable(str(exc)) from exc

    def delete_by_source(self, source_url: str) -> int:
        """Remove every chunk with the given ``source_url``.

        Args:
            source_url: The source URL to filter on.

        Returns:
            The number of deleted chunks.

        Raises:
            VectorStoreUnavailable: On connection failure.
        """
        from opentelemetry import trace  # lazy: SDK-free at import

        tracer = trace.get_tracer("support_bot.adapter.vectorstore")
        with tracer.start_as_current_span("adapter.vectorstore.delete_by_source") as span:
            url_hash = _source_url_hash(source_url)
            span.set_attribute("vectorstore.source_url_hash", url_hash)
            _log.debug(
                "adapter.call.start",
                adapter="ChromaVectorStore",
                operation="delete_by_source",
                source_url_hash=url_hash,
            )
            started = time.monotonic()
            try:
                collection = self._ensure_collection()
                existing = collection.get(where={"source_url": source_url})
                ids: list[str] = list(existing.get("ids") or [])
                if ids:
                    collection.delete(ids=ids)
                elapsed_ms = (time.monotonic() - started) * 1000.0
                span.set_attribute("vectorstore.deleted_count", len(ids))
                _log.info(
                    "adapter.call.ok",
                    adapter="ChromaVectorStore",
                    operation="delete_by_source",
                    deleted_count=len(ids),
                    source_url_hash=url_hash,
                    latency_ms=elapsed_ms,
                )
                return len(ids)
            except VectorStoreUnavailable:
                raise
            except Exception as exc:
                elapsed_ms = (time.monotonic() - started) * 1000.0
                span.set_attribute("error.type", type(exc).__name__)
                _log.info(
                    "adapter.call.ok",
                    adapter="ChromaVectorStore",
                    operation="delete_by_source",
                    outcome="error",
                    error_type=type(exc).__name__,
                    latency_ms=elapsed_ms,
                )
                raise VectorStoreUnavailable(str(exc)) from exc

    def count(self) -> int:
        """Return the total number of chunks in the collection.

        Raises:
            VectorStoreUnavailable: On connection failure.
        """
        from opentelemetry import trace  # lazy: SDK-free at import

        tracer = trace.get_tracer("support_bot.adapter.vectorstore")
        with tracer.start_as_current_span("adapter.vectorstore.count") as span:
            _log.debug(
                "adapter.call.start",
                adapter="ChromaVectorStore",
                operation="count",
            )
            started = time.monotonic()
            try:
                collection = self._ensure_collection()
                result = collection.count()
                elapsed_ms = (time.monotonic() - started) * 1000.0
                span.set_attribute("vectorstore.count", result)
                _log.info(
                    "adapter.call.ok",
                    adapter="ChromaVectorStore",
                    operation="count",
                    count=result,
                    latency_ms=elapsed_ms,
                )
                return int(result)
            except VectorStoreUnavailable:
                raise
            except Exception as exc:
                elapsed_ms = (time.monotonic() - started) * 1000.0
                span.set_attribute("error.type", type(exc).__name__)
                _log.info(
                    "adapter.call.ok",
                    adapter="ChromaVectorStore",
                    operation="count",
                    outcome="error",
                    error_type=type(exc).__name__,
                    latency_ms=elapsed_ms,
                )
                raise VectorStoreUnavailable(str(exc)) from exc

    def query(
        self, embedding: list[float], k: int = 4
    ) -> list[RetrievedChunk]:
        """Return the top-``k`` ``RetrievedChunk``s.

        Args:
            embedding: The query embedding.
            k: The maximum number of chunks to return.

        Returns:
            A list of ``RetrievedChunk`` ordered by similarity
            (descending). Similarity is computed as
            ``1 - cosine_distance`` and clamped to ``[0, 1]``.

        Raises:
            VectorStoreUnavailable: On connection failure.
        """
        from opentelemetry import trace  # lazy: SDK-free at import

        tracer = trace.get_tracer("support_bot.adapter.vectorstore")
        with tracer.start_as_current_span("adapter.vectorstore.query") as span:
            span.set_attribute("vectorstore.k", k)
            span.set_attribute(
                "vectorstore.embedding_dim", len(embedding)
            )
            _log.debug(
                "adapter.call.start",
                adapter="ChromaVectorStore",
                operation="query",
                k=k,
                embedding_dim=len(embedding),
            )
            started = time.monotonic()
            try:
                collection = self._ensure_collection()
                results = collection.query(
                    query_embeddings=[embedding],
                    n_results=k,
                )
                elapsed_ms = (time.monotonic() - started) * 1000.0

                ids = (results.get("ids") or [[]])[0]
                documents = (results.get("documents") or [[]])[0]
                metadatas = (results.get("metadatas") or [[]])[0]
                distances = (results.get("distances") or [[]])[0]
                out: list[RetrievedChunk] = []
                for cid, doc, meta, dist in zip(
                    ids, documents, metadatas, distances, strict=True
                ):
                    similarity = _clamp01(1.0 - float(dist))
                    source_url = (meta or {}).get("source_url", "")
                    out.append(
                        RetrievedChunk(
                            chunk_id=cid,
                            text=doc,
                            source_url=source_url,
                            similarity=similarity,
                        )
                    )
                span.set_attribute(
                    "vectorstore.candidate_count", len(out)
                )
                _log.info(
                    "adapter.call.ok",
                    adapter="ChromaVectorStore",
                    operation="query",
                    k=k,
                    returned=len(out),
                    latency_ms=elapsed_ms,
                )
                return out
            except VectorStoreUnavailable:
                raise
            except Exception as exc:
                elapsed_ms = (time.monotonic() - started) * 1000.0
                span.set_attribute("error.type", type(exc).__name__)
                _log.info(
                    "adapter.call.ok",
                    adapter="ChromaVectorStore",
                    operation="query",
                    outcome="error",
                    error_type=type(exc).__name__,
                    latency_ms=elapsed_ms,
                )
                raise VectorStoreUnavailable(str(exc)) from exc


class ChromaRetriever:
    """``Retriever`` adapter backed by a ``ChromaVectorStore`` + injected ``Embedder``.

    Implements the ``Retriever`` port from
    ``domain/answering/ports`` by computing the query embedding
    with the injected ``Embedder`` and delegating to the
    ``VectorStore.query``.
    """

    def __init__(
        self,
        *,
        vectorstore: ChromaVectorStore,
        embedder: Any,
    ) -> None:
        """Initialise the retriever.

        Args:
            vectorstore: The ``VectorStore`` adapter that holds
                the indexed chunks.
            embedder: The ``Embedder`` adapter used to embed the
                query string.
        """
        self.vectorstore: ChromaVectorStore = vectorstore
        self.embedder: Any = embedder

    def retrieve(self, query: str, k: int = 4) -> list[RetrievedChunk]:
        """Embed ``query`` and return the top-``k`` chunks."""
        vectors = self.embedder.embed([query])
        if not vectors:
            return []
        return self.vectorstore.query(vectors[0], k=k)


__all__ = ["ChromaVectorStore", "ChromaRetriever"]
