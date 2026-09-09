"""Local ``Embedder`` adapter backed by ``sentence-transformers``.

Per WP03 T024.

The adapter wraps a sentence-transformers model and returns
``list[list[float]]`` vectors. The model is loaded **lazily on
the first call** so the Docker image can start up without paying
the model-load cost when the Job is configured for the
``openai`` embedder instead.

Design choices
--------------

We pick the local model as the default because:

1. The Docker image builds and runs fully offline — no
   outbound calls to OpenAI for ingestion.
2. The default ``intfloat/multilingual-e5-large`` (1024 dims)
   is the MTEB-NL top performer among open
   sentence-transformers-compatible models, and it materially
   outranks ``all-MiniLM-L6-v2`` on Dutch morphology
   (``instellen`` ↔ ``installeer``).
3. The model is still small enough (~2 GB) to keep the
   ingestion image under 5 GB.

E5 prompt prefixes
------------------

E5-family models expect ``"query: "`` / ``"passage: "``
prefixes on the input. The adapter accepts an ``input_kind``
(``"query"`` or ``"passage"``) and applies the matching
prefix automatically. Callers that mix kinds in one batch
should call ``embed`` twice.

The OpenAI embedder is an opt-in alternative selected via
``EMBEDDER_BACKEND=openai`` (see ``adapters/embedding_openai.py``).

Observability
-------------

Each ``embed`` call opens an OTel span ``adapter.embedder.embed``
and emits DEBUG/INFO ``adapter.call.start`` / ``adapter.call.ok``
log lines with ``request_id``, ``input_count``, ``model_name``,
``device``, and ``dimensions`` — enough to reproduce the call
deterministically without logging raw text.
"""
from __future__ import annotations

import time
from typing import Any, Literal

import structlog

_log = structlog.get_logger(__name__)


def _needs_e5_prefix(model_name: str) -> bool:
    """Return True when ``model_name`` is an E5-family model.

    E5 (and its multilingual variant) require ``"query: "`` /
    ``"passage: "`` prefixes; MiniLM and similar models do not.
    """
    lowered = model_name.lower()
    return "e5" in lowered and "bge" not in lowered


class SentenceTransformersEmbedder:
    """``Embedder`` adapter wrapping a ``sentence-transformers`` model.

    Attributes:
        model_name: The HuggingFace model id. Default
            ``intfloat/multilingual-e5-large`` (1024 dims).
        device: The compute device (``"cpu"`` or ``"cuda"``).
        input_kind: ``"passage"`` (default) for ingestion-time
            embeddings; ``"query"`` for retrieval-time embeddings.
            Only honoured when the model is E5-family.
        _model: The lazily-loaded model; ``None`` until the
            first ``embed`` call.
    """

    def __init__(
        self,
        *,
        model_name: str = "intfloat/multilingual-e5-large",
        device: str = "cpu",
        input_kind: Literal["query", "passage"] = "passage",
    ) -> None:
        """Initialise the embedder.

        Args:
            model_name: The HuggingFace model id.
            device: The compute device (``"cpu"`` or ``"cuda"``).
            input_kind: ``"query"`` for retrieval, ``"passage"``
                for ingestion. E5-family models apply the
                matching prefix; non-E5 models ignore it.
        """
        self.model_name: str = model_name
        self.device: str = device
        self.input_kind: Literal["query", "passage"] = input_kind
        self._model: Any = None

    def _ensure_model(self) -> Any:
        """Load the model on first use; return the cached instance thereafter."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts`` into vectors.

        Args:
            texts: The batch of input strings. Empty list
                returns an empty list without loading the
                model.

        Returns:
            One vector per input text, in the same order. Each
            vector is a ``list[float]`` of the model's
            dimensionality.

        Raises:
            Any exception from the underlying library is
            re-raised after logging ``error.type`` on the
            span. Callers may wrap in ``LLMUnavailable`` (per
            the WP03 spec).
        """
        from opentelemetry import trace  # lazy: SDK-free at import

        tracer = trace.get_tracer("support_bot.adapter.embedder_local")
        with tracer.start_as_current_span("adapter.embedder.embed") as span:
            span.set_attribute("embedder.backend", "local")
            span.set_attribute("embedder.input_count", len(texts))
            span.set_attribute("embedder.model_name", self.model_name)
            span.set_attribute("embedder.device", self.device)
            _log.debug(
                "adapter.call.start",
                adapter="SentenceTransformersEmbedder",
                operation="embed",
                input_count=len(texts),
                model_name=self.model_name,
                device=self.device,
            )
            started = time.monotonic()
            try:
                if not texts:
                    elapsed_ms = (time.monotonic() - started) * 1000.0
                    span.set_attribute("embedder.dimensions", 0)
                    _log.info(
                        "adapter.call.ok",
                        adapter="SentenceTransformersEmbedder",
                        operation="embed",
                        returned=0,
                        latency_ms=elapsed_ms,
                    )
                    return []
                model = self._ensure_model()
                # E5-family models need ``"query: "`` /
                # ``"passage: "`` prefixes. For other models
                # the prefix would be a no-op cost.
                if _needs_e5_prefix(self.model_name):
                    prefix = "query: " if self.input_kind == "query" else "passage: "
                    prefixed = [prefix + t for t in texts]
                else:
                    prefixed = texts
                vectors = model.encode(prefixed)
                # ``encode`` returns ``numpy.ndarray`` (or list-of-list on
                # older versions). Convert to ``list[list[float]]``.
                if hasattr(vectors, "tolist"):
                    vectors = vectors.tolist()
                elapsed_ms = (time.monotonic() - started) * 1000.0
                dimensions = len(vectors[0]) if vectors else 0
                span.set_attribute("embedder.dimensions", dimensions)
                span.set_attribute("embedder.returned_count", len(vectors))
                _log.info(
                    "adapter.call.ok",
                    adapter="SentenceTransformersEmbedder",
                    operation="embed",
                    returned=len(vectors),
                    dimensions=dimensions,
                    latency_ms=elapsed_ms,
                )
                return [list(map(float, v)) for v in vectors]
            except Exception as exc:
                elapsed_ms = (time.monotonic() - started) * 1000.0
                span.set_attribute("error.type", type(exc).__name__)
                _log.info(
                    "adapter.call.ok",
                    adapter="SentenceTransformersEmbedder",
                    operation="embed",
                    outcome="error",
                    error_type=type(exc).__name__,
                    latency_ms=elapsed_ms,
                )
                raise


__all__ = ["SentenceTransformersEmbedder"]
