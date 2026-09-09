"""TDD red: API routes.

Per WP02 T016, T017, T018, T020:

- ``POST /ask`` accepts an ``AskRequest`` body and returns an
  ``AskResponse`` with the answer, confidence, trace, and the
  same ``request_id`` that the middleware echoed in the
  ``X-Request-Id`` header.
- ``GET /healthz`` returns 200 ``{"status": "ok"}``.
- ``GET /metrics`` returns Prometheus exposition.
- ``POST /ask`` returns HTTP 503 when the answering service
  raises ``VectorStoreUnavailable`` (per AGENTS 8); the body
  must NOT leak the original exception message.
- ``POST /ask`` returns HTTP 422 on a malformed body.
"""
from __future__ import annotations


def test_post_ask_returns_high_confidence_answer() -> None:
    """``POST /ask`` returns 200 with answer / confidence / trace / request_id."""
    from fastapi.testclient import TestClient

    from tests.support.build_fake_app import build_fake_app

    app = build_fake_app()
    client = TestClient(app)

    response = client.post("/ask", json={"question": "What is X?"})
    assert response.status_code == 200
    body = response.json()
    assert "answer" in body
    assert "confidence" in body
    assert "trace" in body
    assert "request_id" in body
    # The request_id in the body must match the header.
    assert body["request_id"] == response.headers["x-request-id"]


def test_post_ask_echoes_inbound_request_id() -> None:
    """If the client sends ``X-Request-Id``, the same id must be
    echoed in the header AND in the body."""
    from fastapi.testclient import TestClient

    from tests.support.build_fake_app import build_fake_app

    app = build_fake_app()
    client = TestClient(app)

    response = client.post(
        "/ask",
        json={"question": "What is X?"},
        headers={"X-Request-Id": "inbound-rid-123"},
    )
    assert response.headers["x-request-id"] == "inbound-rid-123"
    assert response.json()["request_id"] == "inbound-rid-123"


def test_get_healthz_returns_200() -> None:
    """``GET /healthz`` returns 200 ``{"status": "ok"}``."""
    from fastapi.testclient import TestClient

    from tests.support.build_fake_app import build_fake_app

    app = build_fake_app()
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_metrics_returns_prometheus_format() -> None:
    """``GET /metrics`` returns the Prometheus exposition from the wired registry."""
    from fastapi.testclient import TestClient

    from tests.support.build_fake_app import build_fake_app

    app = build_fake_app()
    client = TestClient(app)
    # Make a request so the request_count_total counter has data.
    client.post("/ask", json={"question": "hi"})
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    # Prometheus exposition lines.
    assert "# HELP" in response.text or "# TYPE" in response.text
    # Support-bot series must be present because the metrics
    # middleware recorded the POST /ask above.
    assert "request_count_total" in response.text
    assert "request_latency_seconds" in response.text
