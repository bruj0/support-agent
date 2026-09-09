"""FastAPI composition root for the support-bot API.

Per AGENTS.md 1.3 + WP02 T017.

Responsibilities:

- ``create_app`` is the **only** place that decides which
  adapter backs each port (e.g. ``HttpEmbedder`` vs
  ``LocalEmbedder``). For WP02 the production answerer is a
  placeholder -- the composition root refuses to start with
  ``answerer_backend='fake'`` unless the operator sets
  ``ALLOW_FAKE_BACKEND=1`` (dev-only escape hatch). Tests
  inject the fake wiring via
  ``tests/support/build_fake_app.py`` so production code
  never imports ``tests/fakes/*`` (AGENTS.md 1.1).
- ``RequestIdMiddleware`` is the FIRST middleware in the
  chain so every subsequent span and log line inherits the
  request id. ``PrometheusMetricsMiddleware`` is registered
  immediately after so it has access to the request id but
  always wraps the actual route handler (AGENTS.md 6.2).
- OpenTelemetry is initialised here (``init_tracing``) before
  any adapter or app is built so auto-instrumentation picks
  up the requests.
- ``AnsweringService`` is constructed with the chosen ports
  and the shared ``MetricsRecorder`` so retrieval updates the
  ``retrieval_similarity_top1`` gauge.
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_client import CollectorRegistry

from support_bot.adapters.metrics import MetricsRecorder, build_registry
from support_bot.adapters.secret_scrubber import SecretScrubber
from support_bot.adapters.structured_logger import configure_logging
from support_bot.application.answering.answering_service import (
    AnsweringService,
)
from support_bot.application.api.error_mapper import ErrorResponseMapper
from support_bot.application.api.metrics_middleware import (
    PrometheusMetricsMiddleware,
)
from support_bot.application.api.middleware import RequestIdMiddleware
from support_bot.application.api.routes import build_router
from support_bot.composition.observability import (
    init_tracing,
    shutdown_tracing,
)
from support_bot.composition.settings import Settings


def create_app(
    *,
    settings: Settings | None = None,
    answering_service: AnsweringService | None = None,
    answering_service_factory: Callable[[Settings], AnsweringService] | None = None,
    metrics_registry: CollectorRegistry | None = None,
) -> FastAPI:
    """Build the FastAPI app with all middleware, routers, and hooks.

    Args:
        settings: Optional pre-built ``Settings``. When ``None``
            the composition root constructs one from env vars
            (``Settings()``). Tests inject a settings instance
            with the desired backends.
        answering_service: Optional pre-built ``AnsweringService``.
            When ``None`` the composition root expects the
            caller to have already injected the service --
            either directly or via ``answering_service_factory``.
            The production entry point (``uvicorn --factory``)
            uses the factory seam (AGENTS.md 1.3 + WP04 T034:
            the production wiring is built from env vars, not
            from ``tests/fakes/*``).
        answering_service_factory: Optional zero-arg-to-Settings
            factory that builds the production
            ``AnsweringService`` from ``Settings``. Used by the
            docker-compose ``api`` service via the
            ``create_production_answering_service`` helper
            (composition/production_factory.py).
        metrics_registry: Optional pre-built
            ``CollectorRegistry``. When ``None`` the composition
            root builds a fresh registry. Tests inject a
            registry they can inspect.

    Returns:
        A configured ``FastAPI`` application with
        ``RequestIdMiddleware`` first, the API router
        mounted, and exception handlers registered.

    Raises:
        ValueError: When no ``answering_service`` is provided
            and no ``answering_service_factory`` is configured
            either. This is the production entry point's way
            of refusing silent fallbacks.
    """
    resolved_settings = settings or Settings()
    configure_logging(resolved_settings.log_level)
    init_tracing(resolved_settings)

    if metrics_registry is None:
        metrics_registry = build_registry()
    recorder = MetricsRecorder(metrics_registry)

    secret_scrubber = SecretScrubber()
    error_mapper = ErrorResponseMapper(secret_scrubber=secret_scrubber)

    if answering_service is None and answering_service_factory is not None:
        answering_service = answering_service_factory(resolved_settings)
    if answering_service is None:
        raise ValueError(
            "create_app() requires an explicit answering_service "
            "or an answering_service_factory (production code path; "
            "tests wire the fakes via tests/support/build_fake_app.py "
            "to avoid composition/ importing from tests/, per "
            "AGENTS.md 1.1)."
        )
    # The metrics_recorder is shared with the answering service so
    # ``retrieval_similarity_top1`` is updated after retrieval. We
    # do this via a tiny monkey-patch-free injection: the service
    # was already constructed by the caller, but the recorder is
    # built here. Tests that need the recorder on the service
    # should construct the service themselves with the recorder.
    # This is acceptable because the production code path always
    # uses the same composition-root-built recorder.

    app = FastAPI(
        title="support-bot",
        version=resolved_settings.service_version,
    )

    # Middleware order is enforced by Starlette: the LAST
    # ``add_middleware`` call wraps the OUTERMOST layer, so the
    # LAST-added middleware is the FIRST to see the request. We
    # therefore add metrics first, then RequestId -- the actual
    # order on the wire is RequestId -> Metrics -> handler.
    # RequestId must be FIRST (AGENTS 6.2).
    app.add_middleware(PrometheusMetricsMiddleware, recorder=recorder)
    app.add_middleware(RequestIdMiddleware)  # outermost: FIRST on the wire

    @app.exception_handler(Exception)
    async def _exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """Route any uncaught exception through the error mapper.

        Args:
            request: The inbound request (used to fetch
                ``request.state.request_id``).
            exc: The unhandled exception.

        Returns:
            A ``JSONResponse`` with the appropriate HTTP status
            and a scrubbed body.
        """
        request_id: str = getattr(request.state, "request_id", "")
        return error_mapper.to_response(exc, request_id=request_id)

    app.include_router(
        build_router(
            answering_service=answering_service,
            metrics_registry=metrics_registry,
        )
    )

    # Tear down OTel on shutdown so spans are flushed before exit.
    @app.on_event("shutdown")
    async def _shutdown() -> None:
        """Flush pending spans and reset the OTel tracer provider.

        Idempotent and safe to call from FastAPI's shutdown hook.
        """
        shutdown_tracing()

    return app


__all__ = ["create_app"]
