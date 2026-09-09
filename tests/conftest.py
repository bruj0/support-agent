"""Project-wide pytest fixtures.

- ``reset_structlog`` -- restore the canonical structlog config
  between tests so that kwargs-based log lines work uniformly.
- ``reset_tracer_provider`` -- replace the global OTel
  ``TracerProvider`` between tests so spans from a previous
  test do not leak. The fixture resets the OTel SDK's
  ``_TRACER_PROVIDER_SET_ONCE`` lock because the SDK forbids
  re-setting once a real provider has been installed.
"""
from __future__ import annotations

import pytest

from support_bot.adapters.structured_logger import configure_logging


@pytest.fixture(autouse=True)
def reset_structlog() -> None:
    """Reset structlog to the canonical chain before each test."""
    configure_logging("DEBUG")


@pytest.fixture(autouse=True)
def reset_tracer_provider() -> None:
    """Replace the global TracerProvider with a fresh NoOp one.

    The OTel SDK enforces ``set_tracer_provider`` is called only
    once per process; the lock lives on
    ``trace._TRACER_PROVIDER_SET_ONCE``. Tests that want a real
    provider (e.g. ``InMemorySpanExporter``-backed) explicitly
    reset the lock before installing their own, so this fixture
    does the same on setup + teardown to leave the SDK in a
    clean state for the next test.
    """
    from opentelemetry import trace
    from opentelemetry.trace import NoOpTracerProvider

    # Reset the SDK's "set once" lock so a previous test that
    # installed a real TracerProvider can be overridden.
    trace._TRACER_PROVIDER_SET_ONCE._done = False
    trace.set_tracer_provider(NoOpTracerProvider())
    yield
    trace._TRACER_PROVIDER_SET_ONCE._done = False
    trace.set_tracer_provider(NoOpTracerProvider())


@pytest.fixture
def in_memory_span_exporter():
    """Provide an in-memory OTel span exporter for tests that
    need to assert on emitted spans.

    Yields:
        A ``(provider, exporter)`` tuple. ``provider`` is a
        fresh ``TracerProvider`` with an ``InMemorySpanExporter``
        span processor; ``exporter`` lets the test inspect
        ``get_finished_spans()``. The conftest's
        ``reset_tracer_provider`` fixture cleans up after the
        test.
    """
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    trace._TRACER_PROVIDER_SET_ONCE._done = False
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    yield provider, exporter
