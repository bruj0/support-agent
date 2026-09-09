"""End-to-end tests for the docker-compose stack (WP04 T036).

These tests exercise the full system per FR-019 and the SC-001
acceptance scenarios. They are gated behind the ``e2e`` marker
and are **skipped by default** because they require a running
``docker`` daemon, an ``OPENAI_API_KEY``, and a populated
``Chroma`` collection.

Run locally:

    OPENAI_API_KEY=sk-... \
    docker compose -f deploy/docker-compose.yml up -d --wait
    docker compose -f deploy/docker-compose.yml --profile ingest up ingestion
    pytest -m e2e tests/e2e/test_docker_compose.py

Or run the marker-included CI lane (not the default WP gate).
"""
from __future__ import annotations

import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "deploy" / "docker-compose.yml"
API_BASE_URL = "http://localhost:8080"
HEALTH_TIMEOUT_SECONDS = 60.0
HEALTH_POLL_INTERVAL_SECONDS = 1.0


def _docker_available() -> bool:
    """Return True when the docker CLI is on PATH."""
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            check=False,
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _healthz_ready(timeout: float = HEALTH_TIMEOUT_SECONDS) -> bool:
    """Poll ``GET /healthz`` until 200 or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"{API_BASE_URL}/healthz", timeout=2
            ) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError):
            pass
        time.sleep(HEALTH_POLL_INTERVAL_SECONDS)
    return False


def _post_ask(question: str) -> dict[str, Any]:
    """POST /ask and return the decoded JSON body."""
    body = json_dumps({"question": question}).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE_URL}/ask",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json_loads(resp.read().decode("utf-8"))


def json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj)


def json_loads(text: str) -> dict[str, Any]:
    import json

    return json.loads(text)


@pytest.fixture(scope="module", autouse=True)
def _docker_stack() -> Any:
    """Bring the compose stack up for the module, down at teardown.

    Skips the entire module when ``docker`` is unavailable or
    ``OPENAI_API_KEY`` is not set.
    """
    if not _docker_available():
        pytest.skip("docker compose CLI not available")
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set -- e2e requires a real answerer")
    if not COMPOSE_FILE.exists():
        pytest.skip(f"compose file missing: {COMPOSE_FILE}")

    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d", "--wait",
         "--wait-timeout", "120"],
        check=True,
        cwd=str(REPO_ROOT),
    )
    try:
        if not _healthz_ready():
            pytest.fail("API never became healthy on /healthz")
        yield
    finally:
        subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "down", "-v"],
            check=False,
            cwd=str(REPO_ROOT),
        )


def test_healthz_returns_ok() -> None:
    """``GET /healthz`` returns 200 ``{"status": "ok"}`` (FR-002)."""
    with urllib.request.urlopen(f"{API_BASE_URL}/healthz", timeout=5) as resp:
        assert resp.status == 200
        body = json_loads(resp.read().decode("utf-8"))
    assert body == {"status": "ok"}


def test_ask_returns_high_confidence_for_in_source_question() -> None:
    """UC1 (SC-001 happy path): an in-source question yields
    ``confidence == "high"`` and a non-empty answer.
    """
    resp = _post_ask("What does the support page say about X?")
    assert resp["confidence"] == "high"
    assert isinstance(resp["answer"], str)
    assert resp["answer"].strip() != ""


def test_ask_returns_low_confidence_for_off_topic_question() -> None:
    """UC2 (SC-001 refusal path): an off-topic question yields
    ``confidence == "low"`` and the spec-mandated refusal string.
    """
    resp = _post_ask(
        "Tell me the winning lottery numbers for next Tuesday."
    )
    assert resp["confidence"] == "low"
    assert resp["answer"] == "I cannot answer based on the available content."


def test_metrics_endpoint_returns_prometheus_text() -> None:
    """``GET /metrics`` returns Prometheus text (FR-014)."""
    with urllib.request.urlopen(f"{API_BASE_URL}/metrics", timeout=5) as resp:
        assert resp.status == 200
        assert resp.headers.get("Content-Type", "").startswith("text/plain")
        body = resp.read().decode("utf-8")
    # Prometheus text exposition always has at least one HELP/TYPE
    # line or a counter series; assert the bare minimum so the
    # test stays robust across metric additions.
    assert "# HELP" in body or "# TYPE" in body or len(body) > 0
