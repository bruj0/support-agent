"""Ingestion-domain port interfaces.

A port is a `typing.Protocol` declaring the shape of a dependency
without specifying its implementation. The domain **owns** the port;
adapters in `adapters/` implement it. See plan § Phase 0.4 for the
full layering rationale.

Five ports in this module:

- `PageScraper` — fetch the configured `SOURCE_URL`.
- `PageCleaner` — strip boilerplate and return plain text.
- `Chunker` — split cleaned text into fixed-size chunks.
- `Embedder` — embed text into vectors.
- `VectorStore` — persist and query chunks.

Every port has a Google-style docstring stating intent, parameters,
return value, raised exceptions, and design choices.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..shared.retrieval import RetrievedChunk
from .entities import Chunk, CleanedPage, PageStructure, SourcePage


@runtime_checkable
class PageScraper(Protocol):
    """Fetch the configured `SOURCE_URL` and return a `SourcePage`.

    Implementations live in `adapters/` (concretely:
    `adapters/http_source.py` for the `requests`+`BeautifulSoup`
    implementation).

    Contract:
        - On HTTP non-2xx, DNS / TCP failure, or timeout, raise
          `SourcePageUnreachable(url, reason)`.
        - On empty body, raise `SourcePageUnreachable(url,
          "empty")`.
        - Otherwise return a `SourcePage` with the raw HTML and
          the fetch timestamp.

    Design choices
    --------------
    The port returns a `SourcePage` rather than a string so the
    caller has a stable place to record fetch metadata without
    touching the HTML. The cleaner receives `SourcePage.raw_html`
    directly.

    Why a Protocol (and not an ABC): Protocols are structural —
    adapters need not inherit from anything in `domain/`, which
    preserves the inward-pointing dependency rule.
    """

    def fetch(self, url: str) -> SourcePage:  # pragma: no cover
        """Fetch `url` and return a `SourcePage`. See class docstring."""
        ...  # pragma: no cover


@runtime_checkable
class PageCleaner(Protocol):
    """Strip boilerplate and return a `CleanedPage`.

    Implementations live in `adapters/cleaner.py`.

    Contract:
        - Drop `<nav>`, `<footer>`, `<header>`, `<aside>`, cookie
          banners, `<script>`, `<style>`, `<noscript>`.
        - Return a `CleanedPage` with the plain text and the count
          of removed boilerplate elements.

    Design choices
    --------------
    The cleaner returns a structured `CleanedPage` (not just a
    string) so the ingestion pipeline can log how much
    boilerplate was removed without re-parsing the HTML.
    """

    def clean(self, html: str) -> CleanedPage:  # pragma: no cover
        """Strip boilerplate from `html` and return a `CleanedPage`."""
        ...  # pragma: no cover


@runtime_checkable
class Chunker(Protocol):
    """Split cleaned text into `Chunk` objects.

    Implementations live in `adapters/chunker.py` (FixedSizeChunker)
    and `adapters/hybrid_chunker.py` (HybridChunker, WP06).

    Contract:
        - Default `chunk_size` is 500 characters, default `overlap`
          is 50.
        - Use the `Chunk.from_text` factory so the chunk_id is
          stable across runs.
        - Ordinals must be monotonic starting at 0.
        - When `structure` is supplied, the chunker SHOULD consume
          it to produce semantically coherent chunks (WP06
          ``HybridChunker``). When ``structure`` is ``None`` the
          chunker MUST fall back to char-based slicing
          (``FixedSizeChunker``) — keeping the WP03 contract
          intact for backward compatibility.

    Design choices
    --------------
    Char-based chunking (vs token-based): simpler, deterministic,
    language-agnostic. The 500/50 defaults come from the
    technical assignment. The port exposes the parameters as
    keyword arguments so the application layer can tune them in
    future without changing the contract.
    """

    def chunk(
        self,
        text: str,
        *,
        source_url: str,
        chunk_size: int = 500,
        overlap: int = 50,
        structure: PageStructure | None = None,
    ) -> list[Chunk]:
        """Split `text` into `Chunk`s with stable ids. See class docstring."""
        ...  # pragma: no cover


@runtime_checkable
class PageAnalyzer(Protocol):
    """Analyze cleaned page text and return a structured ``PageStructure``.

    Implementations live in `adapters/llm_page_analyzer.py`
    (WP06: LLM-driven, structured-output JSON schema).

    Contract:
        - Return a ``PageStructure`` whose ``source_url`` matches
          the ``source_url`` passed in.
        - The returned structure MUST contain at least one
          ``SemanticChunk`` per logical region of the page
          (FAQ Q/A pair, heading + body, list, paragraph, table).
          An empty ``chunks`` list is permitted when the page has
          no detectable structure.
        - On unrecoverable LLM failure (5xx after retries,
          JSON parse error after one retry with a stricter
          prompt), raise ``LLMUnavailable``. The orchestrator
          surfaces this as a typed ingestion error.

    Design choices
    --------------
    LLM-only (per WP06 design decision): bs4 is used solely as a
    pre-processor (``Bs4TextExtractor``) to strip
    ``<script>``/``<style>``/``<noscript>`` before the LLM call;
    no heuristic FAQ/heading detection. The LLM produces
    structured JSON validated against ``PageStructure`` — any
    malformed output triggers a single retry with a stricter
    prompt before falling back to ``LLMUnavailable``.

    Why a single ``analyze`` method (vs ``async``): the ingestion
    Job runs synchronously and the orchestration layer wraps
    each step in its own OTel span; an async port would force
    every consumer to await the analyzer. The LLM adapter
    handles its own internal concurrency if needed.
    """

    def analyze(  # pragma: no cover
        self,
        *,
        source_url: str,
        text: str,
        request_id: str,
    ) -> PageStructure:
        """Analyze ``text`` and return a ``PageStructure``.

        Args:
            source_url: The URL the analyzer was invoked for
                (echoed into the produced entity).
            text: The cleaned page text to analyze.
            request_id: Correlation id for logging + tracing
                (AGENTS.md §6.3).
        """
        ...  # pragma: no cover


@runtime_checkable
class Embedder(Protocol):
    """Embed text into vectors.

    Implementations live in `adapters/embedding_local.py`
    (sentence-transformers, default) and `adapters/embedding_openai.py`
    (OpenAI, opt-in via `EMBEDDER_BACKEND=openai`).

    Contract:
        - Return one vector per input text, in the same order.
        - Vector dimensionality is implementation-defined but
          stable; the Chroma adapter enforces the same
          dimensionality at upsert time.

    Design choices
    --------------
    `embed` takes a `list[str]` and returns a `list[list[float]]`
    to allow batched calls. The adapter chooses the internal
    batch size; the application layer never has to know.
    """

    def embed(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover
        """Embed `texts` into vectors. See class docstring."""
        ...  # pragma: no cover


@runtime_checkable
class VectorStore(Protocol):
    """Persist and query `Chunk` objects.

    Implementations live in `adapters/vectorstore_chroma.py`
    (using `chromadb.HttpClient`).

    Contract:
        - `upsert(chunks)` writes chunks; duplicates (by
          `chunk_id`) overwrite existing entries. **Atomic**
          from the caller's perspective — partial writes must
          not be visible.
        - `delete_by_source(source_url)` removes every chunk
          whose `source_url` matches; returns the count
          deleted.
        - `count()` returns the total number of chunks.
        - `query(embedding, k)` returns the top-`k`
          `RetrievedChunk`s ordered by similarity
          (descending). The adapter is responsible for
          mapping its native similarity score (Chroma
          returns cosine distance; some stores return raw
          inner-product) into the `[0.0, 1.0]` range
          required by `RetrievedChunk.similarity`.

    Design choices
    --------------
    `delete_by_source` exists so re-ingestion of a changed page
    can clear the old index before the new run writes (FR-003
    acceptance scenario 2: "the next ingestion run rebuilds the
    index from the new content"). The pre-embed validator
    (WP03) rejects empty / short content before any delete is
    issued, so the store is never partially cleared.

    Why `query` returns `list[RetrievedChunk]` rather than
    `list[Chunk]`: the `Retriever` port (domain/answering)
    also returns `list[RetrievedChunk]`, so the two surfaces
    are aligned and the agent code path needs no
    per-adapter bridging. `RetrievedChunk` lives in
    `domain/shared/` because both ingestion and answering
    entities depend on it.
    """

    def upsert(self, chunks: list[Chunk]) -> None:  # pragma: no cover
        """Persist `chunks` atomically. See class docstring."""
        ...  # pragma: no cover

    def delete_by_source(self, source_url: str) -> int:  # pragma: no cover
        """Remove chunks with `source_url`. Returns the deleted count."""
        ...  # pragma: no cover

    def count(self) -> int:  # pragma: no cover
        """Return the total number of chunks in the store."""
        ...  # pragma: no cover

    def query(self, embedding: list[float], k: int = 4) -> list[RetrievedChunk]:  # pragma: no cover
        """Return top-`k` `RetrievedChunk`s ordered by similarity
        (descending)."""
        ...  # pragma: no cover


__all__ = [
    "Chunker",
    "Embedder",
    "PageCleaner",
    "PageScraper",
    "VectorStore",
]
