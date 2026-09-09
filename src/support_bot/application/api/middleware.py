"""``RequestIdMiddleware`` -- the FIRST middleware in the FastAPI
chain.

Per AGENTS.md 6.2 + WP02 T015:

- Reads ``X-Request-Id`` from the inbound request, or generates
  a fresh ``uuid4().hex`` when missing.
- Binds the value to both:
  * ``structlog.contextvars.bind_contextvars(request_id=...)``
    so every log line in the request scope inherits it;
  * the active OpenTelemetry span via
    ``trace.get_current_span().set_attribute("request.id", ...)``
    so every span emitted in the request scope inherits the
    same attribute (even when no OTLP exporter is configured).
- Echoes ``X-Request-Id`` on the response so the caller can
  correlate logs and traces.
- Clears the contextvar in the ``finally`` block so a worker
  process does not leak ``request_id`` between unrelated
  requests (uvicorn workers are single-threaded by default,
  but the discipline matters for any future multi-threaded
  executor).

This middleware MUST be registered first in the FastAPI app
(``app.add_middleware(RequestIdMiddleware)`` before CORS,
rate limiting, or anything else). ``composition/api_app.py``
encodes that ordering invariant.
"""
from __future__ import annotations

import uuid

import structlog
from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Read or generate a request id, bind it to the request scope.

    The id is taken from the ``X-Request-Id`` header when present
    and falls back to ``uuid4().hex``. It is then:

    1. stored on ``request.state.request_id`` so downstream
       handlers (the router, the error mapper) can read it;
    2. pushed into ``structlog.contextvars`` so the bound
       logger inherits it;
    3. attached as the ``request.id`` attribute on whatever
       OpenTelemetry span is active when this middleware runs
       (FastAPI auto-instrumentation creates a server span
       for each request, so the attribute lands on it).

    The header is echoed on the outbound response.

    Args:
        app: The ASGI application this middleware wraps.
        header_name: The header to read/write. Defaults to
            ``X-Request-Id``.
    """

    def __init__(self, app, header_name: str = "X-Request-Id") -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._header_name = header_name

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        """Bind a request id, forward, and echo the header.

        Args:
            request: The inbound HTTP request.
            call_next: The next handler in the ASGI chain.

        Returns:
            The ``Response`` produced by the downstream handler,
            with ``X-Request-Id`` set to the same id used in
            logs and OTel spans for this request.
        """
        request_id = request.headers.get(self._header_name) or uuid.uuid4().hex
        request.state.request_id = request_id

        # Bind to structlog contextvars so every log line in the
        # request scope (across awaits, sub-tasks) carries the
        # request_id automatically.
        structlog.contextvars.bind_contextvars(request_id=request_id)
        # Attach to the active OTel span so even auto-instrumented
        # spans carry the same id; FastAPI instrumentation creates
        # the parent span, so this lands on it. ``get_current_span``
        # returns a non-recording NoOp when no SDK is configured,
        # which silently ignores the set_attribute call -- exactly
        # what we want for dev.
        span = trace.get_current_span()
        if span is not None:
            span.set_attribute("request.id", request_id)

        try:
            response: Response = await call_next(request)
        finally:
            # Clear the contextvar so the next request on this
            # worker does not inherit the previous request_id.
            structlog.contextvars.unbind_contextvars("request_id")

        response.headers[self._header_name] = request_id
        return response


__all__ = ["RequestIdMiddleware"]
