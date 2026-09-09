"""Test-only factory: build a FastAPI app wired with the fakes.

This module exists so ``composition/api_app.py`` does not need
to import from ``tests/`` at runtime. Tests construct their app
through :func:`build_fake_app` instead of calling
``create_app`` with the ``answering_service=`` kwarg.
"""
from __future__ import annotations

from fastapi import FastAPI
from prometheus_client import CollectorRegistry

from support_bot.adapters.metrics import (
    MetricsRecorder,
    build_registry,
)
from support_bot.application.answering.answering_service import (
    AnsweringService,
)
from support_bot.composition.api_app import create_app
from support_bot.composition.settings import Settings


def build_fake_answering_service(
    *,
    metrics_recorder: MetricsRecorder | None = None,
) -> AnsweringService:
    """Construct an ``AnsweringService`` backed by the in-memory fakes.

    The fakes live under ``tests/fakes/answering/`` and are
    test-only; this function is the one place that wires them
    together (AGENTS.md 1.1: composition/ must not import
    tests/).

    Args:
        metrics_recorder: Optional Prometheus recorder. When
            present, ``retrieval_similarity_top1`` is updated
            after retrieval -- useful for tests that assert the
            gauge reflects the retrieval result.

    Returns:
        A fresh ``AnsweringService`` whose ``Retriever``,
        ``LowConfidencePolicy``, and ``AnswerGenerator`` ports
        are all in-memory fakes.
    """
    # Lazy imports keep ``tests/support/`` import-time side-effect-free.
    from tests.fakes.answering.answer_generator import FakeAnswerGenerator
    from tests.fakes.answering.low_confidence_policy import (
        StubLowConfidencePolicy,
    )
    from tests.fakes.answering.retriever import FakeRetriever

    return AnsweringService(
        retriever=FakeRetriever(),
        policy=StubLowConfidencePolicy(),
        generator=FakeAnswerGenerator(),
        metrics_recorder=metrics_recorder,
    )


def build_fake_registry() -> CollectorRegistry:
    """Build a fresh ``CollectorRegistry`` for tests.

    Returns:
        A new ``CollectorRegistry`` with the four AGENTS.md
        6.6 series registered. Tests that inspect
        ``request_count_total`` etc. should pass the returned
        registry into both ``build_fake_answering_service``
        (via :class:`MetricsRecorder`) and ``create_app``.
    """
    return build_registry()


def build_fake_app(  # type: ignore[no-untyped-def]
    *,
    metrics_registry: CollectorRegistry | None = None,
    answering_service: AnsweringService | None = None,
    settings: Settings | None = None,
    **kwargs,
) -> FastAPI:
    """Build a FastAPI app with the fakes pre-wired.

    Forwards every kwarg to :func:`support_bot.composition.
    api_app.create_app`. The defaults:

    - ``settings`` -> ``Settings(answerer_backend='fake',
      embedder_backend='fake', log_level='WARNING')`` so test
      output is not flooded.
    - ``metrics_registry`` -> a fresh
      :func:`build_fake_registry` so ``/metrics`` returns the
      support-bot series.
    - ``answering_service`` -> a fake service whose
      ``MetricsRecorder`` is bound to the same registry.

    Args:
        metrics_registry: Optional pre-built registry.
        answering_service: Optional pre-built service.
        settings: Optional pre-built settings.
        **kwargs: Forwarded to ``create_app``.

    Returns:
        A configured ``FastAPI`` application with the fake
        answering service and the test metrics recorder
        bound to the same registry.
    """
    if settings is None:
        settings = Settings(
            answerer_backend="fake",
            embedder_backend="fake",
            log_level="WARNING",
        )
    if metrics_registry is None:
        metrics_registry = build_fake_registry()
    recorder = MetricsRecorder(metrics_registry)
    if answering_service is None:
        answering_service = build_fake_answering_service(
            metrics_recorder=recorder,
        )
    return create_app(
        settings=settings,
        answering_service=answering_service,
        metrics_registry=metrics_registry,
        **kwargs,
    )


__all__ = [
    "build_fake_app",
    "build_fake_answering_service",
    "build_fake_registry",
]
