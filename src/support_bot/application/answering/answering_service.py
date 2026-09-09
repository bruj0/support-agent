"""AnsweringService -- the application-layer use case.

Per AGENTS.md 6.3 + WP02 T013.

Owns the LangGraph workflow and translates the typed exceptions
emitted by adapters (``VectorStoreUnavailable``,
``EmbedderUnavailable``, ``LLMUnavailable``) by re-raising them
without wrapping -- the API error mapper needs the typed
exception to choose the right HTTP status (AGENTS 8).

Each call opens a top-level span ``answering_service.answer``
with attribute ``request.id``, ``route``, and
``question.text_hash``. The span also carries ``decision.path``
on successful exit and ``error.type`` on the failure path
(per AGENTS.md 6.4). DEBUG/INFO logs are emitted per the
AGENTS.md 6.5 contract; raw question/answer text is **never**
logged, only the sha256 16-hex prefix.

Prometheus wiring (AGENTS.md 6.6):

- After retrieval, ``metrics_recorder.set_retrieval_top1`` is
  called so ``retrieval_similarity_top1`` reflects the latest
  answer.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

from opentelemetry import trace

from support_bot.adapters.metrics import MetricsRecorder
from support_bot.domain.answering.entities import (
    AgentState,
    Answer,
    Question,
)
from support_bot.domain.answering.ports import (
    AnswerGenerator,
    LowConfidencePolicy,
    Retriever,
)
from support_bot.domain.shared.errors import (
    EmbedderUnavailable,
    LLMUnavailable,
    VectorStoreUnavailable,
)

from .graph import LangGraphWorkflow


def _text_hash(text: str) -> str:
    """sha256 hex, first 16 chars (per AGENTS 6.4 PII rule)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _decision_path(trace_list: list[str]) -> str:
    """Return the last node name in the trace, or ``"__end__"``
    when the trace is empty."""
    return trace_list[-1] if trace_list else "__end__"


class AnsweringService:
    """The application-layer use case for S2.

    Construct once at process start; call ``answer(...)`` per
    request. The service holds the three ports, an optional
    OTel tracer (built in ``composition/observability.py``),
    and an optional ``MetricsRecorder`` (built by the
    composition root, owned by ``/metrics``).
    """

    def __init__(
        self,
        *,
        retriever: Retriever,
        policy: LowConfidencePolicy,
        generator: AnswerGenerator,
        tracer: Any | None = None,
        metrics_recorder: MetricsRecorder | None = None,
    ) -> None:
        """Store the ports, tracer, and metrics recorder.

        Args:
            retriever: The ``Retriever`` port.
            policy: The ``LowConfidencePolicy`` port.
            generator: The ``AnswerGenerator`` port.
            tracer: Optional OTel tracer; ``None`` selects
                no-op spans (test/dev mode).
            metrics_recorder: Optional Prometheus recorder.
                When present, ``retrieval_similarity_top1`` is
                updated after retrieval.
        """
        self._retriever = retriever
        self._policy = policy
        self._generator = generator
        self._tracer = tracer
        self._metrics_recorder = metrics_recorder

    def answer(self, question: Question, *, request_id: str) -> Answer:
        """Run the workflow for ``question`` and return an
        ``Answer``.

        Re-raises typed adapter exceptions
        (``VectorStoreUnavailable``, ``EmbedderUnavailable``,
        ``LLMUnavailable``) so the API error mapper can map
        them. Other ``DomainError`` subclasses propagate
        without wrapping.

        Args:
            question: The user's question (carries the
                ``text`` and the propagated ``request_id``).
            request_id: The propagated ``X-Request-Id`` for
                this request. Threads through ``AgentState``
                into every node span and log line
                (AGENTS.md 6.3).

        Returns:
            The ``Answer`` produced by the workflow.

        Raises:
            VectorStoreUnavailable: Re-raised from the retriever
                when the vector store is unavailable (FR-011).
            EmbedderUnavailable: Re-raised from any future
                embedder adapter (WP03+).
            LLMUnavailable: Re-raised from the answer generator
                when the chat provider is unavailable (FR-010).
        """
        # Lazy imports keep the module side-effect-free.
        import structlog

        log = structlog.get_logger()
        tracer = self._tracer or trace.get_tracer("support_bot.answering")
        question_hash = _text_hash(question.text)

        started = time.monotonic()
        with tracer.start_as_current_span("answering_service.answer") as span:
            span.set_attribute("request.id", request_id)
            span.set_attribute("route", "POST /ask")
            span.set_attribute("question.text_hash", question_hash)
            log.debug(
                "answering_service.start",
                question_text_hash=question_hash,
                request_id=request_id,
            )
            workflow = LangGraphWorkflow(
                retriever=self._retriever,
                policy=self._policy,
                generator=self._generator,
                tracer=tracer,
            )
            compiled = workflow.compile()
            initial = AgentState(question=question.text, request_id=request_id)
            try:
                final = compiled.invoke(initial)
            except (
                VectorStoreUnavailable,
                EmbedderUnavailable,
                LLMUnavailable,
            ) as exc:
                latency_ms = int((time.monotonic() - started) * 1000)
                span.set_attribute("error.type", type(exc).__name__)
                span.set_attribute("decision.path", "__end__")
                log.warning(
                    "answering_service.error",
                    error_type=type(exc).__name__,
                    decision_path="__end__",
                    latency_ms=latency_ms,
                    request_id=request_id,
                )
                # Re-raise typed adapter exceptions; no wrapping
                # -- the API error mapper dispatches on the
                # concrete exception type (AGENTS 8).
                raise

            latency_ms = int((time.monotonic() - started) * 1000)
            retrieved_chunks = final["retrieved_chunks"]
            top_similarity = (
                retrieved_chunks[0].similarity if retrieved_chunks else 0.0
            )
            if self._metrics_recorder is not None:
                self._metrics_recorder.set_retrieval_top1(top_similarity)
            answer = Answer(
                text=final["answer"],
                confidence=final["confidence"],
                trace=list(final["trace"]),
                top_similarity=top_similarity,
            )
            decision_path = _decision_path(answer.trace)
            span.set_attribute("decision.path", decision_path)
            log.info(
                "answering_service.ok",
                confidence=answer.confidence,
                latency_ms=latency_ms,
                decision_path=decision_path,
                request_id=request_id,
            )
            return answer


__all__ = ["AnsweringService"]
