"""OpenAI ``Embedder`` adapter.

Per WP03 T025.

The adapter wraps the official ``openai`` SDK and translates
provider errors and timeouts into the typed
``EmbedderUnavailable`` exception declared in
``domain/shared/errors.py``.

Design choices
--------------

This adapter is opt-in: when ``EMBEDDER_BACKEND=openai`` the
composition root builds this adapter; otherwise the default
``sentence-transformers`` adapter is used. Production deployments
that don't want outbound calls during ingestion should keep the
default.

Observability
-------------

Each ``embed`` call opens an OTel span
``adapter.embedder.embed`` with ``embedder.backend="openai"`` and
emits DEBUG/INFO ``adapter.call.start`` / ``adapter.call.ok``
log lines with ``request_id``, ``input_count``, ``model``,
``dimensions``, and ``latency_ms``. The ``api_key`` is never
logged (it is the secret that the ``SecretScrubber`` would
strip anyway).
"""
from __future__ import annotations

import time
from typing import Any

import structlog

from support_bot.domain.shared.errors import EmbedderUnavailable

_log = structlog.get_logger(__name__)


class OpenAIEmbedder:
    """``Embedder`` adapter backed by the OpenAI Embeddings API.

    Attributes:
        model: The OpenAI model id. Default
            ``text-embedding-3-small`` (1536 dims).
        api_key: The OpenAI API key. ``None`` lets the SDK pick
            up the env var (``OPENAI_API_KEY``).
        _client: The lazy ``openai.OpenAI`` client.
    """

    def __init__(
        self,
        *,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        dimensions: int | None = None,
    ) -> None:
        """Initialise the embedder.

        Args:
            model: The OpenAI model id. Default
                ``text-embedding-3-small`` (1536 dims).
                ``text-embedding-3-large`` (3072 dims, default
                truncated to 1024 via ``dimensions``) is the
                recommended choice for Dutch / multilingual.
            api_key: The OpenAI API key. ``None`` lets the SDK
                pick up the env var (``OPENAI_API_KEY``).
            dimensions: Optional Matryoshka truncation. When
                set, OpenAI returns vectors of this length
                instead of the model's natural dimensionality.
                Supported by ``text-embedding-3-*`` models.
        """
        self.model: str = model
        self.api_key: str | None = api_key
        self.dimensions: int | None = dimensions
        self._client: Any = None

    def _ensure_client(self) -> Any:
        """Build the ``OpenAI`` client lazily on first use."""
        if self._client is None:
            from openai import OpenAI

            if self.api_key is not None:
                self._client = OpenAI(api_key=self.api_key)
            else:
                self._client = OpenAI()
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts`` via OpenAI's Embeddings API.

        Args:
            texts: The batch of input strings. Empty list
                returns an empty list without instantiating
                the client.

        Returns:
            One vector per input text, in the same order.

        Raises:
            EmbedderUnavailable: On any provider error or
                timeout. The original exception is chained
                via ``__cause__`` so the on-call engineer can
                inspect the SDK error message.
        """
        from opentelemetry import trace  # lazy: SDK-free at import

        tracer = trace.get_tracer("support_bot.adapter.embedder_openai")
        with tracer.start_as_current_span("adapter.embedder.embed") as span:
            span.set_attribute("embedder.backend", "openai")
            span.set_attribute("embedder.input_count", len(texts))
            span.set_attribute("embedder.model", self.model)
            if self.dimensions is not None:
                span.set_attribute("embedder.dimensions_requested", self.dimensions)
            _log.debug(
                "adapter.call.start",
                adapter="OpenAIEmbedder",
                operation="embed",
                input_count=len(texts),
                model=self.model,
                dimensions=self.dimensions,
            )
            started = time.monotonic()
            try:
                if not texts:
                    elapsed_ms = (time.monotonic() - started) * 1000.0
                    span.set_attribute("embedder.dimensions", 0)
                    _log.info(
                        "adapter.call.ok",
                        adapter="OpenAIEmbedder",
                        operation="embed",
                        returned=0,
                        latency_ms=elapsed_ms,
                    )
                    return []
                client = self._ensure_client()
                kwargs: dict[str, Any] = {"model": self.model, "input": texts}
                if self.dimensions is not None:
                    kwargs["dimensions"] = self.dimensions
                response = client.embeddings.create(**kwargs)
                vectors = [list(map(float, d.embedding)) for d in response.data]
                elapsed_ms = (time.monotonic() - started) * 1000.0
                dimensions = len(vectors[0]) if vectors else 0
                span.set_attribute("embedder.dimensions", dimensions)
                span.set_attribute("embedder.returned_count", len(vectors))
                _log.info(
                    "adapter.call.ok",
                    adapter="OpenAIEmbedder",
                    operation="embed",
                    returned=len(vectors),
                    dimensions=dimensions,
                    latency_ms=elapsed_ms,
                )
                return vectors
            except EmbedderUnavailable:
                raise
            except Exception as exc:
                elapsed_ms = (time.monotonic() - started) * 1000.0
                span.set_attribute("error.type", type(exc).__name__)
                _log.info(
                    "adapter.call.ok",
                    adapter="OpenAIEmbedder",
                    operation="embed",
                    outcome="error",
                    error_type=type(exc).__name__,
                    latency_ms=elapsed_ms,
                )
                raise EmbedderUnavailable(str(exc)) from exc


__all__ = ["OpenAIEmbedder"]
