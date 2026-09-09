"""OpenTelemetry SDK initialization + global Tracer accessor.

Per AGENTS.md §6.4 + WP02 T015a.

Two functions:

- ``init_tracing(settings: Settings | None = None) -> Tracer``
  configures a ``TracerProvider`` with a parent-based ratio
  sampler, attaches a no-op span processor when
  ``OTEL_EXPORTER_OTLP_ENDPOINT`` is empty (spans are still
  created and attached to logs), and enables auto-instrumentation
  for FastAPI / httpx / logging. Returns the application-level
  ``Tracer`` used to open manual spans around LangGraph nodes
  and adapter calls.

- ``shutdown_tracing() -> None`` flushes and resets the global
  provider. Tests call this in teardown; production calls it at
  process exit.

The module is intentionally side-effect-free until ``init_tracing``
is called — importing it does not install any provider.

Auto-instrumentation is enabled **once per process**; calling
``init_tracing`` twice replaces the global provider but does not
double-instrument the FastAPI app.

The OTel ``Resource.service.version`` attribute is read at module
import time from the installed ``support-bot`` distribution
metadata (per the WP02 T015a spec). When the package is not
installed (e.g. a test run that bypasses ``uv``), the value
falls back to ``settings.service_version``.
"""
from __future__ import annotations

import atexit
import contextlib
import logging

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBasedTraceIdRatio

from .settings import Settings


def _read_installed_version() -> str:
    """Return the installed ``support-bot`` version, or empty.

    Looks up the distribution metadata at import time so the
    OTel ``service.version`` resource attribute reflects the
    deployed artifact. Returns an empty string when the
    distribution is not importable (e.g. running ``pytest``
    without ``uv`` having installed the package); the caller
    is expected to fall back to ``settings.service_version``.

    Returns:
        The installed version string, e.g. ``"0.1.0"``;
        or an empty string when not installed.
    """
    try:
        from importlib.metadata import PackageNotFoundError
        from importlib.metadata import version as _pkg_version

        return _pkg_version("support-bot")
    except PackageNotFoundError:
        return ""
    except Exception:  # pragma: no cover - defensive
        return ""


_INSTALLED_VERSION: str = _read_installed_version()

_INITIALISED = False
_INSTRUMENTED_HTTPX = False
_INSTRUMENTED_LOGGING = False


def _build_resource(settings: Settings) -> Resource:
    """Build the OpenTelemetry ``Resource`` describing this process.

    Args:
        settings: The composition root ``Settings`` instance;
            only the service-identity and deployment fields are
            read.

    Returns:
        A ``Resource`` carrying the four AGENTS.md 6.4 identity
        attributes. ``service.version`` falls back to
        ``settings.service_version`` when the installed
        distribution does not advertise a version.
    """
    version = _INSTALLED_VERSION or settings.service_version
    return Resource.create(
        {
            "service.name": settings.service_name,
            "service.namespace": settings.otel_service_namespace,
            "deployment.environment": settings.otel_deployment_environment,
            "service.version": version,
        }
    )


def _attach_exporter(provider: TracerProvider, settings: Settings) -> bool:
    """Attach an OTLP/HTTP exporter when an endpoint is configured.

    Returns True iff an exporter was attached. Otherwise the
    provider keeps only a no-op span processor; spans are still
    created and attached to logs (via the logging
    instrumentation) but discarded.
    """
    endpoint = settings.otel_exporter_otlp_endpoint.strip()
    if not endpoint:
        return False
    # Lazy import to avoid pulling the OTLP/HTTP exporter into
    # processes that don't need it.
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )

    exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")
    processor = BatchSpanProcessor(exporter)
    provider.add_span_processor(processor)
    return True


def _instrument_httpx() -> None:
    """Install the httpx auto-instrumentor once per process.

    Future calls are no-ops (idempotent). The instrumentor covers
    every ``httpx.Client`` and ``httpx.AsyncClient`` constructed
    after this call, so the embedder / answerer / cleaner
    adapters automatically participate in the trace.
    """
    global _INSTRUMENTED_HTTPX
    if _INSTRUMENTED_HTTPX:
        return
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    HTTPXClientInstrumentor().instrument()
    _INSTRUMENTED_HTTPX = True


def _instrument_logging() -> None:
    """Install the logging auto-instrumentor once per process.

    Adds ``trace_id`` / ``span_id`` to every stdlib log record so
    ``structlog`` (when configured with the stdlib factory) can
    correlate log lines with the active span.
    """
    global _INSTRUMENTED_LOGGING
    if _INSTRUMENTED_LOGGING:
        return
    from opentelemetry.instrumentation.logging import LoggingInstrumentor

    LoggingInstrumentor().instrument(set_logging_format=True)
    _INSTRUMENTED_LOGGING = True


def init_tracing(settings: Settings | None = None) -> trace.Tracer:
    """Initialise the global OpenTelemetry tracer.

    Called once at process start by both ``composition/api_app.py``
    and ``composition/ingestion_main.py``. Subsequent calls
    replace the global provider but do not double-instrument
    third-party libraries (httpx, logging).

    Args:
        settings: The composition root ``Settings``. When
            ``None`` a fresh ``Settings()`` is built from env
            vars.

    Returns:
        The application-level ``Tracer`` for manual spans.
    """
    global _INITIALISED

    if settings is None:
        settings = Settings()

    provider = TracerProvider(
        resource=_build_resource(settings),
        sampler=ParentBasedTraceIdRatio(settings.otel_traces_sampler_arg),
    )
    exporter_attached = _attach_exporter(provider, settings)
    trace.set_tracer_provider(provider)

    _instrument_httpx()
    _instrument_logging()

    if not _INITIALISED:
        atexit.register(shutdown_tracing)
        _INITIALISED = True

    log = logging.getLogger(__name__)
    log.info(
        "tracing.initialised",
        extra={
            "sampler": settings.otel_traces_sampler,
            "sampler_arg": settings.otel_traces_sampler_arg,
            "exporter_configured": exporter_attached,
            "service_name": settings.service_name,
            "service_version": _INSTALLED_VERSION or settings.service_version,
        },
    )

    return trace.get_tracer(settings.service_name)


def shutdown_tracing() -> None:
    """Flush spans and tear down the global tracer provider.

    Registered as an ``atexit`` hook by :func:`init_tracing` so
    production processes flush their spans before exit.

    Constructing a new :class:`TracerProvider` would spin up a
    resource-detector thread pool, which is not safe during
    interpreter shutdown (``atexit`` runs after non-daemon
    thread pools are torn down, raising
    ``RuntimeError: cannot schedule new futures after
    interpreter shutdown``). We therefore only flush + shut down
    here; tests that want to reset the global tracer provider
    between runs should call :func:`reset_tracing_for_tests`
    instead.
    """
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        with contextlib.suppress(Exception):  # pragma: no cover - shutdown best-effort
            provider.force_flush()
        with contextlib.suppress(Exception):  # pragma: no cover - shutdown best-effort
            provider.shutdown()


def reset_tracing_for_tests() -> None:
    """Reset the global tracer provider for the next test.

    Creates a fresh :class:`TracerProvider` so each test starts
    from a clean slate. Safe to call repeatedly. **Not safe to
    call from ``atexit``** — use :func:`shutdown_tracing` for that.
    """
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        with contextlib.suppress(Exception):  # pragma: no cover - shutdown best-effort
            provider.force_flush()
        with contextlib.suppress(Exception):  # pragma: no cover - shutdown best-effort
            provider.shutdown()
    trace.set_tracer_provider(TracerProvider())


__all__ = ["init_tracing", "reset_tracing_for_tests", "shutdown_tracing"]
