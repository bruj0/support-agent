"""Prometheus metrics + recorder helpers for the support-bot API.

Per AGENTS.md 6.6 + WP02 T018.

The module exposes two layers:

- :func:`build_registry` -- build a fresh ``CollectorRegistry``
  with the four required series so tests can build isolated
  registries without polluting the global default.
- :class:`MetricsRecorder` -- a thin wrapper that owns the
  series instances bound to a specific registry and exposes
  ``record_request``, ``observe_adapter``,
  ``set_retrieval_top1`` methods the application / middleware
  call. ``/metrics`` calls ``generate_latest(registry)`` on the
  recorder's registry, so every counter / histogram increment
  shows up on the exposition.

Series (per AGENTS.md 6.6):

- ``request_count_total{route,status}`` -- counter.
- ``request_latency_seconds{route}`` -- histogram.
- ``retrieval_similarity_top1`` -- gauge (updated after retrieval).
- ``adapter_call_latency_seconds{adapter,operation}`` --
  histogram, parallel to the OTel adapter span latency.
"""
from __future__ import annotations

import time
from types import TracebackType

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
)


def build_registry() -> CollectorRegistry:
    """Build a fresh registry with the four AGENTS.md 6.6 series.

    Each call returns a *new* registry so tests can build an
    isolated registry without polluting the global default. The
    composition root (``composition/api_app.py``) calls this
    once at startup.

    Returns:
        A new ``CollectorRegistry`` exposing
        ``request_count_total``, ``request_latency_seconds``,
        ``retrieval_similarity_top1``, and
        ``adapter_call_latency_seconds``.
    """
    registry = CollectorRegistry()

    Counter(
        "request_count_total",
        "Number of HTTP requests handled, partitioned by route and status.",
        labelnames=("route", "status"),
        registry=registry,
    )
    Histogram(
        "request_latency_seconds",
        "Latency of HTTP requests in seconds, partitioned by route.",
        labelnames=("route",),
        registry=registry,
        # 5ms .. 5s; a generous default for an internal API.
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    )
    Gauge(
        "retrieval_similarity_top1",
        "Top-1 similarity score across the most recent retrieval batch.",
        registry=registry,
    )
    Histogram(
        "adapter_call_latency_seconds",
        "Latency of adapter calls in seconds, partitioned by adapter and operation.",
        labelnames=("adapter", "operation"),
        registry=registry,
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    )
    return registry


class MetricsRecorder:
    """Owns the four Prometheus series bound to one registry.

    Use this from ``composition/api_app.py`` so every counter /
    histogram increment lands on the same registry the ``/metrics``
    route exposes.

    Attributes:
        registry: The ``CollectorRegistry`` backing all four
            series. Use ``generate_latest(recorder.registry)``
            to render the exposition.
    """

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        """Build or attach to the four AGENTS.md 6.6 series.

        Args:
            registry: An existing ``CollectorRegistry`` that
                already has the four series registered. When
                ``None`` a fresh registry is built via
                :func:`build_registry`.
        """
        if registry is None:
            registry = build_registry()
        self.registry: CollectorRegistry = registry
        self._requests: Counter = registry._names_to_collectors[
            "request_count_total"
        ]
        self._latency: Histogram = registry._names_to_collectors[
            "request_latency_seconds"
        ]
        self._top1: Gauge = registry._names_to_collectors[
            "retrieval_similarity_top1"
        ]
        self._adapter: Histogram = registry._names_to_collectors[
            "adapter_call_latency_seconds"
        ]

    def record_request(
        self,
        *,
        route: str,
        status: int,
        latency_seconds: float,
    ) -> None:
        """Increment ``request_count_total`` and observe ``request_latency_seconds``.

        Args:
            route: The FastAPI route template, e.g.
                ``"POST /ask"`` or ``"GET /healthz"``.
            status: The HTTP response status code (int).
            latency_seconds: The request latency in seconds.
        """
        self._requests.labels(route=route, status=str(status)).inc()
        self._latency.labels(route=route).observe(latency_seconds)

    def observe_adapter(
        self,
        *,
        adapter: str,
        operation: str,
        latency_seconds: float,
    ) -> None:
        """Record a single adapter-call latency on ``adapter_call_latency_seconds``.

        Args:
            adapter: The adapter class name, e.g. ``"HttpEmbedder"``.
            operation: The operation, e.g. ``"embed"``.
            latency_seconds: The adapter-call latency in seconds.
        """
        self._adapter.labels(adapter=adapter, operation=operation).observe(
            latency_seconds
        )

    def set_retrieval_top1(self, similarity: float) -> None:
        """Update the ``retrieval_similarity_top1`` gauge.

        Args:
            similarity: The top-1 similarity score in ``[0.0, 1.0]``.
        """
        self._top1.set(similarity)


class AdapterCallTimer:
    """Context manager that records adapter latency on exit.

    Usage::

        with AdapterCallTimer(recorder, adapter="HttpEmbedder", operation="embed"):
            vectors = embedder.embed(texts)

    On successful exit (no exception) the timer records
    ``latency_seconds`` on the recorder. On exception the
    exception propagates and the timer does **not** record --
    failed calls are surfaced through their exception, not the
    histogram, so the histogram tracks happy-path latency only.

    Attributes:
        recorder: The :class:`MetricsRecorder` to write to.
        adapter: Adapter class name passed to
            ``observe_adapter``.
        operation: Adapter operation passed to
            ``observe_adapter``.
    """

    def __init__(
        self,
        *,
        recorder: MetricsRecorder,
        adapter: str,
        operation: str,
    ) -> None:
        self.recorder = recorder
        self.adapter = adapter
        self.operation = operation
        self._started: float | None = None

    def __enter__(self) -> AdapterCallTimer:
        """Start the timer and return ``self`` for ``as`` binding."""
        self._started = time.monotonic()
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        """Stop the timer and record latency on successful exit.

        Args:
            _exc_type: Exception class, if any.
            _exc: Exception instance, if any.
            _tb: Traceback, if any.

        Returns:
            ``None`` -- never suppress exceptions.
        """
        if self._started is None or _exc is not None:
            return
        elapsed = time.monotonic() - self._started
        self.recorder.observe_adapter(
            adapter=self.adapter,
            operation=self.operation,
            latency_seconds=elapsed,
        )


__all__ = [
    "AdapterCallTimer",
    "MetricsRecorder",
    "build_registry",
]
