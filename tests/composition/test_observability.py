"""TDD red: composition.observability init_tracing / shutdown_tracing.

Per AGENTS.md 6.4 + WP02 T015a:

- ``init_tracing(settings)`` configures a TracerProvider with a
  parent-based ratio sampler, attaches a no-op span processor
  (spans are still created) when ``OTEL_EXPORTER_OTLP_ENDPOINT``
  is empty, and enables auto-instrumentation for FastAPI/httpx/logging.
- ``shutdown_tracing()`` flushes the global tracer provider; it is
  the atexit-safe shutdown (does NOT create a fresh provider).
- ``reset_tracing_for_tests()`` is the test-only helper that
  flushes, shuts down, AND replaces the global provider so each
  test starts from a clean slate.
- ``init_tracing`` returns a ``Tracer`` so application code can
  open manual spans.

These functions MUST be idempotent on subsequent calls (re-running
init_tracing in tests must not crash).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


def test_observability_module_exists() -> None:
    from support_bot.composition import observability

    assert hasattr(observability, "init_tracing")
    assert hasattr(observability, "shutdown_tracing")
    assert hasattr(observability, "reset_tracing_for_tests")


def test_init_tracing_returns_tracer() -> None:
    from support_bot.composition.observability import (
        init_tracing,
        reset_tracing_for_tests,
    )

    reset_tracing_for_tests()
    tracer = init_tracing()
    assert tracer is not None
    # Tracer must satisfy the OTel Tracer protocol.
    from opentelemetry.trace import Tracer as OtelTracer

    assert isinstance(tracer, OtelTracer)
    reset_tracing_for_tests()


def test_init_tracing_is_idempotent() -> None:
    """Two consecutive init_tracing() calls must not crash; the
    second call replaces the global TracerProvider."""
    from support_bot.composition.observability import (
        init_tracing,
        reset_tracing_for_tests,
    )

    reset_tracing_for_tests()
    t1 = init_tracing()
    t2 = init_tracing()
    # Both calls succeed and return Tracers; the second replaces
    # the global provider.
    assert t1 is not None
    assert t2 is not None
    reset_tracing_for_tests()


def test_shutdown_tracing_is_atexit_safe() -> None:
    """``shutdown_tracing()`` must not spawn a new thread pool.

    It is registered as an ``atexit`` hook by ``init_tracing``;
    constructing a fresh ``TracerProvider`` during interpreter
    shutdown would raise ``RuntimeError: cannot schedule new
    futures after interpreter shutdown``. The function should
    therefore only flush + shut down the existing provider.
    """
    from support_bot.composition.observability import shutdown_tracing

    # No provider configured -> shutdown must be a no-op.
    shutdown_tracing()


def test_settings_module_exists() -> None:
    """composition.settings exposes ``Settings`` BaseSettings."""
    from support_bot.composition.settings import Settings

    assert Settings is not None


def test_settings_fields_match_agents_section_9() -> None:
    """Settings must expose the env keys listed in AGENTS 9."""
    from support_bot.composition.settings import Settings

    # These fields are documented in AGENTS 9; the test pins the
    # names so any rename must be deliberate.
    expected = {
        "chroma_host",
        "chroma_port",
        "embedder_backend",
        "answerer_backend",
        "log_level",
        "lock_dir",
        "request_id",
        "otel_exporter_otlp_endpoint",
        "otel_service_namespace",
        "otel_deployment_environment",
        "otel_traces_sampler",
        "otel_traces_sampler_arg",
        "source_url",
    }
    fields = set(Settings.model_fields.keys())
    missing = expected - fields
    assert not missing, f"Settings missing fields: {missing}"
