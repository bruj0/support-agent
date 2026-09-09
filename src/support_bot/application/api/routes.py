"""FastAPI router for the support-bot API.

Per WP02 T016 + T017:

- ``POST /ask`` -- accepts ``AskRequest`` and dispatches to the
  configured ``AnsweringService``. The request id is taken from
  ``request.state.request_id`` (set by ``RequestIdMiddleware``)
  so the response body and the ``X-Request-Id`` header are
  always consistent.
- ``GET /healthz`` -- returns ``{"status": "ok"}`` regardless of
  Chroma reachability (FR-002).
- ``GET /metrics`` -- Prometheus exposition. The router reads
  the exposition from the ``CollectorRegistry`` it was given;
  the composition root wires the same registry to
  ``PrometheusMetricsMiddleware`` so /metrics returns the
  counters / histograms the middleware recorded.

Exceptions raised by the answering service are caught by the
top-level ``exception_handler`` registered in
``composition/api_app.py``; this router only translates the
*happy path* into an ``AskResponse``.
"""
from __future__ import annotations

from fastapi import APIRouter, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    generate_latest,
)
from pydantic import BaseModel, Field

from support_bot.application.answering.answering_service import (
    AnsweringService,
)


class AskRequest(BaseModel):
    """Body of ``POST /ask``.

    Attributes:
        question: The user's question text (1-2000 chars, FR-001).
    """

    question: str = Field(min_length=1, max_length=2000)


class AskResponse(BaseModel):
    """Body of the successful ``POST /ask`` response.

    Attributes:
        answer: The agent's answer (or the static refusal string).
        confidence: ``"high"`` or ``"low"``.
        trace: Node names visited, in order (for observability).
        request_id: The same id echoed in the ``X-Request-Id``
            response header.
        top_similarity: Top-1 retrieval similarity (0.0-1.0).
    """

    answer: str
    confidence: str
    trace: list[str]
    request_id: str
    top_similarity: float = 0.0


def build_router(
    *,
    answering_service: AnsweringService,
    metrics_registry: CollectorRegistry,
) -> APIRouter:
    """Build the APIRouter with /ask, /healthz, /metrics wired.

    Args:
        answering_service: The application-layer use case to
            invoke from ``POST /ask``. The router does not own
            its lifecycle -- the composition root creates it
            and the FastAPI app owns it.
        metrics_registry: The Prometheus ``CollectorRegistry``
            the ``PrometheusMetricsMiddleware`` writes to. The
            ``/metrics`` route renders this registry, so the
            returned exposition reflects every increment /
            observation the middleware performed.

    Returns:
        A new ``APIRouter`` ready to be ``app.include_router``-ed.
    """
    router = APIRouter()

    @router.post("/ask", response_model=AskResponse)
    async def ask(
        body: AskRequest, request: Request
    ) -> AskResponse:
        """Dispatch a question to the answering service.

        Args:
            body: The ``AskRequest`` payload from the caller.
            request: The inbound HTTP request -- used to read
                ``request.state.request_id`` populated by
                ``RequestIdMiddleware``.

        Returns:
            An ``AskResponse`` containing the answer,
            confidence, trace, request_id, and top similarity.
        """
        request_id: str = getattr(request.state, "request_id", "")
        # The service enforces the request_id contract.
        from support_bot.domain.answering.entities import Question

        answer = answering_service.answer(
            Question(text=body.question, request_id=request_id),
            request_id=request_id,
        )
        return AskResponse(
            answer=answer.text,
            confidence=answer.confidence,
            trace=list(answer.trace),
            request_id=request_id,
            top_similarity=answer.top_similarity,
        )

    @router.get("/healthz")
    async def healthz() -> dict[str, str]:
        """Return liveness status.

        Per FR-002 the response is always 200 ``{"status": "ok"}``
        regardless of Chroma reachability -- readiness is a
        separate concern.

        Returns:
            The static ``{"status": "ok"}`` body.
        """
        # Per FR-002: 200 regardless of Chroma reachability.
        return {"status": "ok"}

    @router.get("/metrics")
    async def metrics() -> Response:
        """Return the Prometheus exposition for the wired registry.

        Returns:
            A FastAPI ``Response`` whose body is the latest
            snapshot of the configured ``CollectorRegistry``
            rendered with ``generate_latest(registry)``.
        """
        payload: bytes = generate_latest(metrics_registry)
        return Response(content=payload, media_type=CONTENT_TYPE_LATEST)

    return router


__all__ = ["AskRequest", "AskResponse", "build_router"]
