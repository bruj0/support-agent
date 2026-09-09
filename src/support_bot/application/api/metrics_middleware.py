"""``PrometheusMetricsMiddleware`` -- records ``request_count_total``
and ``request_latency_seconds`` per request.

Per AGENTS.md 6.6 + WP02 T018:

- For every HTTP response, increment
  ``request_count_total{route,status}`` and observe
  ``request_latency_seconds{route}``.
- The route label is the FastAPI route template
  (``request.scope.get("route").path``) -- falls back to the
  raw path when no route is matched (404s).
- The middleware is registered AFTER ``RequestIdMiddleware`` so
  it inherits the request id via the request state and can log
  under the same request scope.

The middleware is a thin facade over the
:class:`support_bot.adapters.metrics.MetricsRecorder` so the
metrics recorder owns the registry, and the middleware does
not need to know about Prometheus directly.
"""
from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from support_bot.adapters.metrics import MetricsRecorder


class PrometheusMetricsMiddleware(BaseHTTPMiddleware):
    """Record request count + latency on every response.

    Attributes:
        recorder: The :class:`MetricsRecorder` that owns the
            registry. The composition root constructs the
            recorder once and reuses it across requests.
    """

    def __init__(self, app, *, recorder: MetricsRecorder) -> None:  # type: ignore[no-untyped-def]
        """Store the recorder reference.

        Args:
            app: The ASGI application this middleware wraps.
            recorder: The ``MetricsRecorder`` whose registry
                the increments land on. The middleware never
                replaces the recorder (the registry is owned by
                the composition root).
        """
        super().__init__(app)
        self._recorder = recorder

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        """Time the downstream call, then record the result.

        Args:
            request: The inbound HTTP request.
            call_next: The next handler in the ASGI chain.

        Returns:
            The downstream ``Response`` unchanged. As a side
            effect, ``request_count_total`` and
            ``request_latency_seconds`` are updated.
        """
        started = time.monotonic()
        response: Response = await call_next(request)
        elapsed = time.monotonic() - started
        route_label = _route_label(request)
        status = response.status_code
        self._recorder.record_request(
            route=route_label,
            status=status,
            latency_seconds=elapsed,
        )
        return response


def _route_label(request: Request) -> str:
    """Return the FastAPI route template, or the raw path for 404s.

    Args:
        request: The inbound HTTP request.

    Returns:
        The route label to use in
        ``request_count_total{route=...}`` /
        ``request_latency_seconds{route=...}``. Falls back to
        ``"UNKNOWN"`` when no path is available.
    """
    route = request.scope.get("route")
    if route is not None:
        # ``route.path`` is the FastAPI route template (e.g.
        # ``"/ask"``); the HTTP method is on ``request.method``.
        method = request.method.upper()
        return f"{method} {route.path}"
    # No matched route (404). Use the raw path so the operator
    # can see which path was attempted.
    raw_path = request.url.path
    if not raw_path:
        return "UNKNOWN"
    return f"{request.method.upper()} {raw_path}"


__all__ = ["PrometheusMetricsMiddleware"]
