"""Typed domain exception hierarchy.

These exceptions are raised by adapters and application services and
caught by `application/api/error_mapper.py`, which translates them
into HTTP responses. Keeping the **types** in the domain layer is
deliberate: the application layer must not catch SDK-specific
exceptions (e.g. `chromadb.errors.NotFoundError`) directly, because
that would couple the domain to a specific SDK.

Design choices
--------------

- **Single root** (`DomainError`) so the API layer can catch a
  single base type for logging, and so individual exceptions can be
  caught specifically by the error mapper.
- **Two empty-collection exceptions** — `EmptyRetrieval` is
  informational (the guard node maps it to refusal), while
  `SourcePageGarbage` is a failure (the ingestion Job exits
  non-zero without writing).
- **No HTTP-awareness** — none of these exceptions know about HTTP
  status codes; that mapping lives in the application layer's
  `ErrorResponseMapper` (plan § Phase 0.4 / Inter-System Contracts:
  S2 → S3).

Cross-references
----------------

- Plan § Phase 0.4 (Hexagonal Layering).
- Plan § Abstract Components / S2 / entities — exception types.
- Spec FR-008 (IF/THEN), FR-009 (IF/THEN), FR-010 (IF/THEN),
  FR-011 (IF/THEN), FR-012 (IF/THEN).
"""
from __future__ import annotations


class DomainError(Exception):
    """Root of the domain exception hierarchy.

    All other domain exceptions inherit from this class. The
    application layer catches `DomainError` for logging and the
    `ErrorResponseMapper` switches on the concrete subclass.
    """


class SourcePageUnreachable(DomainError):
    """The configured `SOURCE_URL` could not be fetched.

    Raised by `PageScraper` adapters on non-2xx HTTP status, on
    request timeout, or on DNS / TCP errors. The ingestion Job maps
    this to a non-zero exit (FR-008) and never writes to the vector
    store (M1, M2).
    """

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"source page unreachable: {url} ({reason})")
        self.url = url
        self.reason = reason


class SourcePageGarbage(DomainError):
    """Cleaned page content is empty or unusably short.

    Raised by `PreEmbedValidator` (WP03) when the cleaner produces
    text shorter than the configured minimum length. The ingestion
    Job treats this as a failure (FR-008) and never writes to the
    vector store (M2).
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"source page content unusable: {reason}")
        self.reason = reason


class VectorStoreUnavailable(DomainError):
    """The vector store adapter could not complete an operation.

    Raised by `VectorStore` adapters on connection / 5xx / timeout.
    The API layer maps this to HTTP 503 (FR-011) without leaking the
    Chroma URI (M5). The retrieval node propagates this so the
    workflow exits cleanly.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"vector store unavailable: {reason}")
        self.reason = reason


class LLMUnavailable(DomainError):
    """The LLM provider could not produce an answer.

    Raised by `AnswerGenerator` adapters on provider error or
    timeout. The API layer maps this to HTTP 502 (FR-010) without
    leaking the API key (M5).
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"answer generator unavailable: {reason}")
        self.reason = reason


class EmbedderUnavailable(DomainError):
    """The embedding provider could not produce vectors.

    Raised by `Embedder` adapters on provider error or timeout.
    The API layer maps this to HTTP 502 (AGENTS.md §8) without
    leaking the API key (M5). Distinct from `LLMUnavailable`
    because a future WP may run the embedder against a different
    vendor (e.g. sentence-transformers locally) than the chat
    provider (OpenAI), and the two failure modes must not be
    conflated in observability.

    Added in WP02 (AGENTS.md §8) after WP01 v1 review deferred the
    class (Issue 9) — the application layer's error mapper now
    needs it.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"embedder unavailable: {reason}")
        self.reason = reason


class EmptyRetrieval(DomainError):
    """The retriever returned no chunks.

    Raised by `Retriever` adapters when the underlying collection
    is empty. **Informational**, not a failure — the guard node
    catches this and routes to the refusal path (FR-009).
    """

    def __init__(self) -> None:
        super().__init__("retrieval returned no chunks")


class ConfigurationError(DomainError):
    """A required configuration value is missing or invalid.

    Raised by the composition root at startup when an env var or
    Secret is missing. The API layer maps this to HTTP 503 (the
    service is not configured to handle requests) without leaking
    the missing-key name.
    """

    def __init__(self, name: str) -> None:
        super().__init__(f"configuration error: {name}")
        self.name = name


__all__ = [
    "DomainError",
    "SourcePageUnreachable",
    "SourcePageGarbage",
    "VectorStoreUnavailable",
    "LLMUnavailable",
    "EmbedderUnavailable",
    "EmptyRetrieval",
    "ConfigurationError",
]