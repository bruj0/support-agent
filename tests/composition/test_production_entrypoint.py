"""TDD red tests for ``composition.__main__.build_production_app``.

The docker entrypoint (formerly ``deploy/start.sh``) must
return a real FastAPI app with the production AnsweringService
wired in. Per WP04 review v1 Issue 1.

The entrypoint is intentionally a Python function (not a CLI
parser) so it can be unit-tested without spawning a subprocess.
The container calls ``python -m support_bot.composition`` which
in turn invokes ``build_production_app()`` and runs uvicorn on
the returned app object.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI

from support_bot.composition import __main__ as entrypoint
from support_bot.composition.__main__ import build_production_app
from support_bot.composition.settings import Settings


def _openai_settings() -> Settings:
    """A ``Settings`` instance wired for the openai backend.

    The default ``answerer_backend='fake'`` is rejected by the
    production factory (per AGENTS.md 1.1), so production tests
    must explicitly opt into ``openai``.
    """
    return Settings(answerer_backend="openai")


def test_build_production_app_returns_fastapi_instance() -> None:
    """The factory returns a real FastAPI instance (not a coroutine)."""
    app = build_production_app(settings=_openai_settings())
    assert isinstance(app, FastAPI)


def test_build_production_app_wires_answering_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wired AnsweringService is the production wiring, not the test fakes.

    We patch ``create_production_answering_service`` to a
    sentinel so we can assert the entrypoint called it. The
    sentinel raises so the assertion below can verify the
    factory was invoked (without forcing the test to construct
    a real OpenAI client).
    """
    captured: dict[str, Any] = {}

    def sentinel_factory(settings: Any) -> Any:
        captured["settings"] = settings
        captured["called"] = True
        raise RuntimeError("sentinel: factory was wired")

    monkeypatch.setattr(
        entrypoint, "create_production_answering_service", sentinel_factory
    )

    with pytest.raises(RuntimeError, match="sentinel"):
        entrypoint.build_production_app(settings=_openai_settings())
    assert captured.get("called") is True
    assert isinstance(captured["settings"], Settings)


def test_build_production_app_loads_settings_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When called without a Settings arg, the entrypoint builds one.

    The ``Settings`` defaults depend on the local ``.env`` file
    (or the absence of one), which is fragile in a unit test --
    the production factory would happily accept ``openai``
    whenever the operator's ``.env`` says so, hiding the path
    the entrypoint is exercising. We force ``ANSWERER_BACKEND=fake``
    and ``EMBEDDER_BACKEND=local`` so the factory rejects the
    default and we observe the ``RuntimeError('fake')`` path.
    """
    monkeypatch.setenv("ANSWERER_BACKEND", "fake")
    monkeypatch.delenv("SOURCE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="answerer_backend='fake'"):
        entrypoint.build_production_app()
