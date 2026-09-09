"""OpenAI ``AnswerGenerator`` adapter (production).

Per WP04 T034.

The adapter wraps the ``openai`` chat-completions API and
translates provider errors and timeouts into the typed
``LLMUnavailable`` exception declared in
``domain/shared/errors.py``.

Design choices
--------------

The system prompt is fixed here (the domain owns the rule
that the model must answer only from retrieved context --
``domain/answering/ports.py`` -- but the prompt wording is
per-adapter). The default model is ``gpt-4o-mini`` (cheap
and fast for short RAG answers).

Observability
-------------

Each ``generate`` call opens an OTel span
``adapter.answerer.generate`` with ``request.id`` (read from
the active OTel context, which the application layer sets
before the call) and emits DEBUG/INFO ``adapter.call.start``
/ ``adapter.call.ok`` log lines with ``model``,
``question_text_hash``, ``context_chunk_count``, and
``latency_ms``. The ``api_key`` is never logged (the
``SecretScrubber`` strips it anyway).
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

import structlog

from support_bot.domain.shared.errors import LLMUnavailable
from support_bot.domain.shared.retrieval import RetrievedChunk

_log = structlog.get_logger(__name__)

DEFAULT_MODEL = "gpt-4o-mini"
SYSTEM_PROMPT = (
    "You are a support assistant. Answer ONLY using the context "
    "below. If the answer is not in the context, say you don't "
    "know. Do not invent URLs, prices, or people."
)


def _question_text_hash(text: str) -> str:
    """First 16 hex chars of ``sha256(text)`` for span attributes."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class OPENAIAnswerGenerator:
    """``AnswerGenerator`` adapter backed by the OpenAI Chat Completions API.

    Attributes:
        model: The OpenAI model id. Default ``gpt-4o-mini``.
        api_key: The OpenAI API key. ``None`` lets the SDK pick
            up ``OPENAI_API_KEY`` from the env.
        _client: The lazy ``openai.OpenAI`` client.
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
    ) -> None:
        """Initialise the answer generator.

        Args:
            model: OpenAI chat model id.
            api_key: OpenAI API key (defaults to ``OPENAI_API_KEY`` env var).
        """
        self.model: str = model
        self.api_key: str | None = api_key
        self._client: Any = None

    def _ensure_client(self) -> Any:
        """Build the OpenAI client lazily on first use."""
        if self._client is None:
            from openai import OpenAI

            if self.api_key is not None:
                self._client = OpenAI(api_key=self.api_key)
            else:
                self._client = OpenAI()
        return self._client

    def generate(
        self,
        question: str,
        retrieved: list[RetrievedChunk],
    ) -> str:
        """Generate an answer from ``question`` and ``retrieved`` context.

        Args:
            question: The user's question.
            retrieved: The top-k ``RetrievedChunk``s returned by
                the retriever. They are concatenated into the
                system prompt's "context" block.

        Returns:
            The assistant message content.

        Raises:
            LLMUnavailable: On any provider error or timeout.
        """
        from opentelemetry import trace  # lazy: SDK-free at import

        tracer = trace.get_tracer("support_bot.adapter.answerer_openai")
        with tracer.start_as_current_span("adapter.answerer.generate") as span:
            q_hash = _question_text_hash(question)
            span.set_attribute("answerer.model", self.model)
            span.set_attribute("answerer.context_chunk_count", len(retrieved))
            span.set_attribute("question.text_hash", q_hash)
            _log.debug(
                "adapter.call.start",
                adapter="OPENAIAnswerGenerator",
                operation="generate",
                model=self.model,
                question_text_hash=q_hash,
                context_chunk_count=len(retrieved),
            )
            started = time.monotonic()
            context = "\n\n".join(
                f"[{i+1}] {chunk.text}" for i, chunk in enumerate(retrieved)
            ) or "(no context)"
            messages = [
                {"role": "system", "content": f"{SYSTEM_PROMPT}\n\nContext:\n{context}"},
                {"role": "user", "content": question},
            ]
            try:
                client = self._ensure_client()
                response = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                )
                content = response.choices[0].message.content or ""
                elapsed_ms = (time.monotonic() - started) * 1000.0
                span.set_attribute("answerer.tokens_out", len(content))
                _log.info(
                    "adapter.call.ok",
                    adapter="OPENAIAnswerGenerator",
                    operation="generate",
                    model=self.model,
                    latency_ms=elapsed_ms,
                    answer_length=len(content),
                )
                return content
            except LLMUnavailable:
                raise
            except Exception as exc:
                elapsed_ms = (time.monotonic() - started) * 1000.0
                span.set_attribute("error.type", type(exc).__name__)
                _log.info(
                    "adapter.call.ok",
                    adapter="OPENAIAnswerGenerator",
                    operation="generate",
                    outcome="error",
                    error_type=type(exc).__name__,
                    latency_ms=elapsed_ms,
                )
                raise LLMUnavailable(str(exc)) from exc


__all__ = ["OPENAIAnswerGenerator"]
