"""TDD red: RequestIdMiddleware must be the FIRST middleware in the
FastAPI app (per AGENTS.md 6.2 + WP02 T015, T020 deferred note).

This test asserts that ``app.user_middleware`` (or the Starlette
middleware list) registers RequestIdMiddleware before any other
middleware. The composition root in WP02 (composition/api_app.py)
must wire ``app.add_middleware(RequestIdMiddleware)`` BEFORE any
``app.add_middleware(CORSMiddleware, ...)`` or router inclusion.
"""
from __future__ import annotations

from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware


def test_request_id_middleware_module_exists() -> None:
    from support_bot.application.api.middleware import RequestIdMiddleware

    assert RequestIdMiddleware is not None


def test_request_id_middleware_subclass_of_base_http_middleware() -> None:
    from starlette.middleware.base import BaseHTTPMiddleware

    from support_bot.application.api.middleware import RequestIdMiddleware

    assert issubclass(RequestIdMiddleware, BaseHTTPMiddleware)


def test_composition_root_middleware_order() -> None:
    """The composition root must register RequestIdMiddleware first."""
    # Importing composition.api_app triggers wiring; the
    # ``build_fake_app`` factory exposes the middleware list.
    from support_bot.application.api.metrics_middleware import (
        PrometheusMetricsMiddleware,
    )
    from support_bot.application.api.middleware import RequestIdMiddleware
    from tests.support.build_fake_app import build_fake_app

    app = build_fake_app()
    # Starlette stores middleware in ``user_middleware`` as a list
    # of ``Middleware`` instances, with the LAST ``add_middleware``
    # call at index 0 (outermost layer). The first entry must be
    # the ``RequestIdMiddleware`` because it was added last and
    # is the first to see each request.
    middlewares: list[Middleware] = list(app.user_middleware)
    assert len(middlewares) >= 1, "App must have at least the RequestIdMiddleware"
    first_cls = middlewares[0].cls
    assert first_cls is RequestIdMiddleware, (
        f"First user_middleware entry must be RequestIdMiddleware "
        f"(outermost layer); got {first_cls!r}"
    )
    # PrometheusMetricsMiddleware must be present in the chain.
    assert any(m.cls is PrometheusMetricsMiddleware for m in middlewares), (
        "PrometheusMetricsMiddleware must be wired"
    )
    # If CORS is present, it must come AFTER RequestIdMiddleware,
    # i.e. at a higher index in user_middleware (which means it
    # was added BEFORE RequestIdMiddleware).
    cors_indexes = [
        i for i, m in enumerate(middlewares) if m.cls is CORSMiddleware
    ]
    if cors_indexes:
        assert all(i > 0 for i in cors_indexes), (
            "CORSMiddleware must come AFTER RequestIdMiddleware "
            "(i.e. at a higher index in user_middleware); "
            f"saw cors_indexes={cors_indexes!r}"
        )


def test_request_id_middleware_adds_x_request_id_response_header() -> None:
    """RequestIdMiddleware echoes X-Request-Id back on the response."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from support_bot.application.api.middleware import RequestIdMiddleware

    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/probe")
    def _probe() -> dict[str, str]:
        return {"ok": "true"}

    client = TestClient(app)
    # TestClient + middleware: send a request with no X-Request-Id
    # header; the middleware must generate one and echo it back.
    response = client.get("/probe")
    assert response.status_code == 200
    assert "x-request-id" in response.headers
    header = response.headers["x-request-id"]
    assert isinstance(header, str)
    assert len(header) > 0

    # If we send X-Request-Id, the middleware must echo it back.
    response2 = client.get("/probe", headers={"X-Request-Id": "abc123"})
    assert response2.headers["x-request-id"] == "abc123"
