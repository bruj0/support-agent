"""Top-level ingestion orchestrator.

Per WP03 T029 + WP03 spec.

``IngestionService.run(source_url, *, request_id)`` wires the
full ingestion pipeline:

    scraper -> cleaner -> validator -> chunker -> embedder -> vectorstore

It is the application-layer use case for "ingest this URL once,
atomically, observably". The orchestrator opens one OTel span
per step (per AGENTS.md §6.4) and emits DEBUG/INFO
``adapter.call.start`` / ``adapter.call.ok`` log lines with
enough context to reproduce every call deterministically.

Misfits resolved by this service
-------------------------------

- **M1 (unreachable URL)**: scraper raises
  ``SourcePageUnreachable``; we propagate the exception
  without touching the vectorstore (the store's ``upsert`` is
  never called). The lock is released in the ``finally`` block.
- **M2 (empty cleaned text)**: the validator raises
  ``SourcePageGarbage``; same path as M1 — no write, lock
  released.
- **M4 (concurrent run)**: when the lock is already held the
  service returns ``{"status": "skipped", ...}`` and does not
  touch the vectorstore.

Single-ID propagation (AGENTS.md §6.3)
--------------------------------------

The ``request_id`` is:

- threaded as an explicit keyword argument (``run(source_url,
  *, request_id)``) — never re-generated,
- bound to ``structlog.contextvars`` so every log line in the
  run scope inherits it,
- attached to every OTel span as the ``request.id`` attribute
  (the adapters read it from the active span via
  ``trace.get_current_span().get_attribute("request.id")`` —
  we set it on the top-level span so children inherit it),
- embedded in the lock filename so the on-disk artefact,
  logs, and spans share one ID.

Observability (AGENTS.md §6.4, §6.5)
------------------------------------

Top-level span ``ingestion.run`` with ``request.id`` and
``source.url``. Each step opens a child span
(``ingestion.fetch`` / ``ingestion.clean`` / etc.) with the
mandatory AGENTS.md attributes (``embedder.input_count``,
``embedder.dimensions``, ``vectorstore.chunk_count``, etc.).
DEBUG ``adapter.call.start`` lines carry the minimum count /
size inputs to reproduce the call deterministically;
``adapter.call.ok`` lines carry ``latency_ms`` and result
counts. No raw page text is ever logged.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Protocol

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

# Local Protocols — these match the structural shape of the
# ports in ``domain/ingestion/ports.py``. We avoid importing
# the domain Protocols directly to keep the application layer
# free of unnecessary imports (the protocols are runtime
# checkable but a duck-typed Protocol here is enough).


class _Scraper(Protocol):
    """Structural ``PageScraper`` port."""

    def fetch(self, url: str) -> Any:
        """Fetch ``url`` and return the page."""
        ...


class _Cleaner(Protocol):
    """Structural ``PageCleaner`` port."""

    def clean(self, html: str) -> Any:
        """Strip boilerplate from ``html`` and return cleaned text."""
        ...


class _Chunker(Protocol):
    """Structural ``Chunker`` port."""

    def chunk(
        self,
        text: str,
        *,
        source_url: str,
        chunk_size: int = 500,
        overlap: int = 50,
        structure: Any = None,
    ) -> Any:
        """Split ``text`` into chunks tagged with ``source_url``.

        The ``structure`` keyword was added by WP06 so the
        ``HybridChunker`` can consume a ``PageStructure``. The
        local Protocol keeps byte-compat with the WP03
        ``FixedSizeChunker`` (which ignores ``structure``) by
        defaulting the new kwargs.
        """
        ...


class _Embedder(Protocol):
    """Structural ``Embedder`` port."""

    def embed(self, texts: list[str]) -> Any:
        """Embed a batch of texts and return vectors."""
        ...


class _VectorStore(Protocol):
    """Structural ``VectorStore`` port."""

    def upsert(self, chunks: Any) -> None:
        """Persist ``chunks`` atomically."""
        ...


class _Validator(Protocol):
    """Structural validator port."""

    def validate(self, cleaned: Any) -> None:
        """Validate the cleaned page or raise."""
        ...


class _Lock(Protocol):
    """Structural ingestion-lock port."""

    def try_acquire(self, request_id: str) -> bool:
        """Acquire the lock; return True if acquired."""
        ...

    def release(self, request_id: str) -> None:
        """Release the lock held by ``request_id``."""
        ...


class _Analyzer(Protocol):
    """Structural ``PageAnalyzer`` port (WP06).

    Optional in the orchestrator: when ``None`` the analyze step
    is skipped and the chunker receives ``structure=None``.
    """

    def analyze(self, *, source_url: str, text: str, request_id: str) -> Any:
        """Analyze ``text`` and return a ``PageStructure``."""
        ...


_log = structlog.get_logger(__name__)


def _url_hash(url: str) -> str:
    """First 16 hex chars of ``sha256(url)`` for span / log attributes."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


class IngestionService:
    """Orchestrates the ingestion pipeline.

    Attributes:
        scraper: ``PageScraper`` adapter.
        cleaner: ``PageCleaner`` adapter.
        validator: ``PreEmbedValidator`` instance.
        chunker: ``Chunker`` adapter.
        embedder: ``Embedder`` adapter.
        vectorstore: ``VectorStore`` adapter.
        lock: ``FileLockIngestionRunLock`` (M4).
        tracer: Optional ``opentelemetry.trace.Tracer``; when
            ``None`` a default tracer is fetched lazily.
    """

    def __init__(
        self,
        *,
        scraper: _Scraper,
        cleaner: _Cleaner,
        validator: _Validator,
        chunker: _Chunker,
        embedder: _Embedder,
        vectorstore: _VectorStore,
        lock: _Lock,
        analyzer: _Analyzer | None = None,
        tracer: Any = None,
    ) -> None:
        """Initialise the orchestrator.

        Args:
            scraper: ``PageScraper`` adapter.
            cleaner: ``PageCleaner`` adapter.
            validator: ``PreEmbedValidator`` instance.
            chunker: ``Chunker`` adapter.
            embedder: ``Embedder`` adapter.
            vectorstore: ``VectorStore`` adapter.
            lock: ``FileLockIngestionRunLock`` (M4).
            analyzer: Optional ``PageAnalyzer`` adapter (WP06).
                When ``None`` the analyze step is skipped and the
                chunker receives ``structure=None`` (the
                FixedSizeChunker fallback path).
            tracer: Optional ``opentelemetry.trace.Tracer``.
        """
        self.scraper = scraper
        self.cleaner = cleaner
        self.validator = validator
        self.chunker = chunker
        self.embedder = embedder
        self.vectorstore = vectorstore
        self.lock = lock
        self.analyzer = analyzer
        self._tracer_arg = tracer

    def _tracer(self) -> Any:
        """Resolve the OTel tracer; fall back to a default tracer."""
        if self._tracer_arg is not None:
            return self._tracer_arg
        from opentelemetry import trace

        return trace.get_tracer("support_bot.ingestion_service")

    def run(self, *, source_url: str, request_id: str) -> dict[str, Any]:
        """Run the ingestion pipeline.

        Args:
            source_url: The URL to fetch, clean, chunk, embed,
                and upsert.
            request_id: The correlation ID propagated through
                every log line, span, and the lock filename
                (AGENTS.md §6.3).

        Returns:
            A dict with ``status`` (``"ok"`` or ``"skipped"``),
            ``chunk_count`` (int, on success), ``reason`` (on
            skip), and ``request_id``.

        Raises:
            SourcePageUnreachable: When the scraper cannot fetch
                the URL (M1). The lock is released and the
                vectorstore is never touched.
            SourcePageGarbage: When the validator rejects the
                cleaned text (M2). Same handling as M1.
        """
        tracer = self._tracer()
        url_hash = _url_hash(source_url)

        with tracer.start_as_current_span("ingestion.run") as top_span:
            top_span.set_attribute("request.id", request_id)
            top_span.set_attribute("source.url_hash", url_hash)
            bind_contextvars(request_id=request_id, source_url_hash=url_hash)

            _log.info(
                "ingestion.bootstrap",
                source_url_hash=url_hash,
                embedder_backend="local",
                request_id=request_id,
            )

            # 1. Acquire the lock.
            with tracer.start_as_current_span("ingestion.lock") as lock_span:
                lock_span.set_attribute("request.id", request_id)
                _log.debug(
                    "adapter.call.start",
                    adapter="FileLockIngestionRunLock",
                    operation="try_acquire",
                    request_id=request_id,
                )
                started = time.monotonic()
                acquired = self.lock.try_acquire(request_id)
                lock_span.set_attribute(
                    "lock.acquired", acquired
                )
                _log.info(
                    "adapter.call.ok",
                    adapter="FileLockIngestionRunLock",
                    operation="try_acquire",
                    outcome="acquired" if acquired else "skipped",
                    latency_ms=(time.monotonic() - started) * 1000.0,
                )

            if not acquired:
                top_span.set_attribute("decision.path", "__end__")
                _log.info(
                    "ingestion.skipped",
                    reason="run_in_progress",
                    request_id=request_id,
                )
                return {
                    "status": "skipped",
                    "reason": "run_in_progress",
                    "request_id": request_id,
                }

            try:
                # 2. Fetch.
                with tracer.start_as_current_span("ingestion.fetch") as span:
                    span.set_attribute("request.id", request_id)
                    span.set_attribute("source.url_hash", url_hash)
                    _log.debug(
                        "adapter.call.start",
                        adapter="PageScraper",
                        operation="fetch",
                        source_url_hash=url_hash,
                        request_id=request_id,
                    )
                    started = time.monotonic()
                    source_page = self.scraper.fetch(source_url)
                    _log.info(
                        "adapter.call.ok",
                        adapter="PageScraper",
                        operation="fetch",
                        latency_ms=(time.monotonic() - started) * 1000.0,
                        response_bytes=len(getattr(source_page, "raw_html", "")),
                        request_id=request_id,
                    )

                # 3. Clean.
                with tracer.start_as_current_span("ingestion.clean") as span:
                    span.set_attribute("request.id", request_id)
                    html = source_page.raw_html
                    _log.debug(
                        "adapter.call.start",
                        adapter="PageCleaner",
                        operation="clean",
                        html_bytes=len(html),
                        request_id=request_id,
                    )
                    started = time.monotonic()
                    cleaned = self.cleaner.clean(html)
                    span.set_attribute(
                        "cleaner.text_length", len(cleaned.text)
                    )
                    _log.info(
                        "adapter.call.ok",
                        adapter="PageCleaner",
                        operation="clean",
                        latency_ms=(time.monotonic() - started) * 1000.0,
                        cleaned_length=len(cleaned.text),
                        request_id=request_id,
                    )

                # 4. Validate.
                with tracer.start_as_current_span(
                    "ingestion.validate"
                ) as span:
                    span.set_attribute("request.id", request_id)
                    span.set_attribute("min_cleaned_length", 100)
                    _log.debug(
                        "adapter.call.start",
                        adapter="PreEmbedValidator",
                        operation="validate",
                        cleaned_length=len(cleaned.text),
                        request_id=request_id,
                    )
                    started = time.monotonic()
                    self.validator.validate(cleaned)
                    _log.info(
                        "adapter.call.ok",
                        adapter="PreEmbedValidator",
                        operation="validate",
                        outcome="ok",
                        cleaned_length=len(cleaned.text),
                        latency_ms=(time.monotonic() - started) * 1000.0,
                        request_id=request_id,
                    )

                # 5. Analyze (WP06) — between validate and chunk.
                structure = None
                if self.analyzer is not None:
                    with tracer.start_as_current_span(
                        "ingestion.analyze"
                    ) as analyze_span:
                        analyze_span.set_attribute("request.id", request_id)
                        _log.debug(
                            "adapter.call.start",
                            adapter="PageAnalyzer",
                            operation="analyze",
                            cleaned_length=len(cleaned.text),
                            request_id=request_id,
                        )
                        started = time.monotonic()
                        structure = self.analyzer.analyze(
                            source_url=source_url,
                            text=cleaned.text,
                            request_id=request_id,
                        )
                        analyze_span.set_attribute(
                            "analyzer.region_count", len(structure.chunks)
                        )
                        analyze_span.set_attribute(
                            "analyzer.faq_count",
                            sum(
                                1
                                for c in structure.chunks
                                if c.kind == "faq"
                            ),
                        )
                        analyze_span.set_attribute(
                            "analyzer.model", structure.model
                        )
                        _log.info(
                            "adapter.call.ok",
                            adapter="PageAnalyzer",
                            operation="analyze",
                            region_count=len(structure.chunks),
                            faq_count=sum(
                                1
                                for c in structure.chunks
                                if c.kind == "faq"
                            ),
                            model=structure.model,
                            latency_ms=(time.monotonic() - started) * 1000.0,
                            request_id=request_id,
                        )

                # 6. Chunk.
                with tracer.start_as_current_span("ingestion.chunk") as span:
                    span.set_attribute("request.id", request_id)
                    _log.debug(
                        "adapter.call.start",
                        adapter="Chunker",
                        operation="chunk",
                        cleaned_length=len(cleaned.text),
                        request_id=request_id,
                    )
                    started = time.monotonic()
                    chunks = self.chunker.chunk(
                        cleaned.text,
                        source_url=source_url,
                        structure=structure,
                    )
                    span.set_attribute("chunker.chunk_count", len(chunks))
                    _log.info(
                        "adapter.call.ok",
                        adapter="Chunker",
                        operation="chunk",
                        chunk_count=len(chunks),
                        latency_ms=(time.monotonic() - started) * 1000.0,
                        request_id=request_id,
                    )

                # 6. Embed.
                with tracer.start_as_current_span("ingestion.embed") as span:
                    span.set_attribute("request.id", request_id)
                    texts = [c.text for c in chunks]
                    span.set_attribute("embedder.input_count", len(texts))
                    _log.debug(
                        "adapter.call.start",
                        adapter="Embedder",
                        operation="embed",
                        input_count=len(texts),
                        request_id=request_id,
                    )
                    started = time.monotonic()
                    vectors = self.embedder.embed(texts)
                    elapsed_ms = (time.monotonic() - started) * 1000.0
                    dimensions = len(vectors[0]) if vectors else 0
                    span.set_attribute("embedder.dimensions", dimensions)
                    _log.info(
                        "adapter.call.ok",
                        adapter="Embedder",
                        operation="embed",
                        returned=len(vectors),
                        dimensions=dimensions,
                        latency_ms=elapsed_ms,
                        request_id=request_id,
                    )

                # 7. Attach embeddings and upsert.
                if len(vectors) != len(chunks):
                    raise RuntimeError(
                        f"embedder returned {len(vectors)} vectors for "
                        f"{len(chunks)} chunks — pipeline invariant violated"
                    )
                embedded_chunks = [
                    chunk.model_copy(update={"embedding": vec})
                    for chunk, vec in zip(chunks, vectors, strict=True)
                ]

                with tracer.start_as_current_span(
                    "ingestion.upsert"
                ) as span:
                    span.set_attribute("request.id", request_id)
                    span.set_attribute(
                        "vectorstore.chunk_count", len(embedded_chunks)
                    )
                    span.set_attribute("vectorstore.source_url_hash", url_hash)
                    _log.debug(
                        "adapter.call.start",
                        adapter="VectorStore",
                        operation="upsert",
                        chunk_count=len(embedded_chunks),
                        source_url_hash=url_hash,
                        request_id=request_id,
                    )
                    started = time.monotonic()
                    self.vectorstore.upsert(embedded_chunks)
                    _log.info(
                        "adapter.call.ok",
                        adapter="VectorStore",
                        operation="upsert",
                        chunk_count=len(embedded_chunks),
                        latency_ms=(time.monotonic() - started) * 1000.0,
                        request_id=request_id,
                    )

                top_span.set_attribute("decision.path", "ok")
                return {
                    "status": "ok",
                    "chunk_count": len(embedded_chunks),
                    "request_id": request_id,
                }
            finally:
                # Always release the lock, even on failure paths.
                try:
                    self.lock.release(request_id)
                except Exception as exc:  # pragma: no cover - defensive
                    _log.warning(
                        "ingestion.lock_release_failed",
                        error_type=type(exc).__name__,
                        request_id=request_id,
                    )
                clear_contextvars()


__all__ = ["IngestionService"]
