"""TDD contract for ``adapters.llm_page_analyzer.OpenAIPageAnalyzer``.

Per WP06 T054.

The analyzer drives the LLM with a structured-output JSON schema
that validates against ``PageStructure``. Failure modes:

- LLM returns malformed JSON (parse error) → one retry with a
  stricter prompt; if still invalid → ``LLMUnavailable``.
- Transient provider errors (5xx, timeout) → tenacity retries up
  to ``max_retries``; if all fail → ``LLMUnavailable``.

Long pages are windowed: each window is analyzed separately and
the resulting ``SemanticChunk`` lists are concatenated.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from support_bot.adapters.llm_page_analyzer import OpenAIPageAnalyzer
from support_bot.domain.ingestion.entities import PageStructure
from support_bot.domain.shared.errors import LLMUnavailable


def _ok_response(payload: dict[str, Any]) -> Any:
    """Build a mock OpenAI response carrying a JSON ``payload``."""
    text = json.dumps(payload)

    class _Choice:
        def __init__(self, message: Any) -> None:
            self.message = message

    class _Message:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Resp:
        def __init__(self, choices: list[_Choice]) -> None:
            self.choices = choices

    return _Resp([_Choice(_Message(text))])


def _valid_payload() -> dict[str, Any]:
    return {
        "source_url": "https://example.com/help",
        "chunks": [
            {
                "kind": "faq",
                "title": "How do I install my modem?",
                "text": "Plug it into the wall socket.",
                "anchor": None,
            },
            {
                "kind": "section",
                "title": "FAQ",
                "text": "Common questions about your Ziggo subscription.",
                "anchor": "faq",
            },
        ],
        "model": "gpt-4o-mini",
        "generated_at": datetime(2026, 9, 7, tzinfo=UTC).isoformat(),
    }


def _install_client(
    monkeypatch: pytest.MonkeyPatch, response: Any, *, calls: list[Any] | None = None
) -> None:
    """Patch ``openai.OpenAI`` so ``chat.completions.create`` returns ``response``.

    When ``calls`` is provided, every invocation appends its kwargs
    to ``calls`` for assertion.
    """

    class _CompletionsAPI:
        def create(self, **kwargs: Any) -> Any:
            if calls is not None:
                calls.append(kwargs)
            return response

    class _Chat:
        def __init__(self) -> None:
            self.completions = _CompletionsAPI()

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.chat = _Chat()

    monkeypatch.setattr("openai.OpenAI", _Client)


def test_analyze_returns_valid_page_structure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A well-formed LLM JSON response validates as a PageStructure."""
    _install_client(monkeypatch, _ok_response(_valid_payload()))
    analyzer = OpenAIPageAnalyzer(api_key="test-key")
    result = analyzer.analyze(
        source_url="https://example.com/help",
        text="x" * 200,
        request_id="rid-1",
    )
    assert isinstance(result, PageStructure)
    assert len(result.chunks) == 2
    assert result.chunks[0].kind == "faq"


def test_analyze_uses_default_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default model is ``gpt-4o-mini``."""
    captured: list[dict[str, Any]] = []
    _install_client(monkeypatch, _ok_response(_valid_payload()), calls=captured)
    analyzer = OpenAIPageAnalyzer(api_key="test-key")
    analyzer.analyze(
        source_url="https://example.com/help",
        text="x" * 200,
        request_id="rid-1",
    )
    assert captured[0]["model"] == "gpt-4o-mini"


def test_analyze_uses_response_format_json_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The LLM is invoked with a JSON-schema response_format."""
    captured: list[dict[str, Any]] = []
    _install_client(monkeypatch, _ok_response(_valid_payload()), calls=captured)
    analyzer = OpenAIPageAnalyzer(api_key="test-key")
    analyzer.analyze(
        source_url="https://example.com/help",
        text="x" * 200,
        request_id="rid-1",
    )
    rf = captured[0]["response_format"]
    assert rf["type"] == "json_schema"


def test_analyze_retries_on_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First call returns malformed JSON; second returns valid JSON."""
    captured: list[dict[str, Any]] = []

    class _Flaky:
        def __init__(self) -> None:
            self.n = 0

        def create(self, **kwargs: Any) -> Any:
            captured.append(kwargs)
            self.n += 1
            if self.n == 1:
                # Malformed JSON: missing required keys.
                return _ok_response({"this is not a PageStructure": True})
            return _ok_response(_valid_payload())

    class _Chat:
        def __init__(self) -> None:
            self.completions = _Flaky()

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.chat = _Chat()

    monkeypatch.setattr("openai.OpenAI", _Client)
    analyzer = OpenAIPageAnalyzer(api_key="test-key")
    result = analyzer.analyze(
        source_url="https://example.com/help",
        text="x" * 200,
        request_id="rid-1",
    )
    assert len(captured) == 2
    assert isinstance(result, PageStructure)


def test_analyze_raises_llm_unavailable_after_max_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When every retry returns malformed JSON, ``LLMUnavailable`` is raised."""
    _install_client(
        monkeypatch, _ok_response({"this is not a PageStructure": True})
    )
    analyzer = OpenAIPageAnalyzer(api_key="test-key", max_retries=2)
    with pytest.raises(LLMUnavailable):
        analyzer.analyze(
            source_url="https://example.com/help",
            text="x" * 200,
            request_id="rid-1",
        )


def test_analyze_raises_llm_unavailable_on_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A persistent provider error raises ``LLMUnavailable`` after retries."""
    import openai as _openai

    class _CompletionsAPI:
        def create(self, **kwargs: Any) -> Any:
            raise _openai.APIConnectionError(request=MagicMock())

    class _Chat:
        def __init__(self) -> None:
            self.completions = _CompletionsAPI()

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.chat = _Chat()

    monkeypatch.setattr("openai.OpenAI", _Client)
    analyzer = OpenAIPageAnalyzer(api_key="test-key", max_retries=1)
    with pytest.raises(LLMUnavailable):
        analyzer.analyze(
            source_url="https://example.com/help",
            text="x" * 200,
            request_id="rid-1",
        )


def test_analyze_windows_long_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Long text is split into multiple LLM calls and results concatenated."""
    calls: list[dict[str, Any]] = []
    _install_client(monkeypatch, _ok_response(_valid_payload()), calls=calls)
    analyzer = OpenAIPageAnalyzer(
        api_key="test-key", max_input_chars=200
    )
    text = "x" * 600
    result = analyzer.analyze(
        source_url="https://example.com/help",
        text=text,
        request_id="rid-1",
    )
    # 600 / 200 = 3 windows (the last is partial).
    assert len(calls) >= 2
    # Each call returns the same fixture (2 chunks); total = N * 2.
    assert len(result.chunks) == len(calls) * 2


def test_analyze_returns_empty_structure_when_chunks_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty chunks list is a valid response."""
    payload = dict(_valid_payload())
    payload["chunks"] = []
    _install_client(monkeypatch, _ok_response(payload))
    analyzer = OpenAIPageAnalyzer(api_key="test-key")
    result = analyzer.analyze(
        source_url="https://example.com/help",
        text="x" * 200,
        request_id="rid-1",
    )
    assert result.chunks == []


class MagicMock:
    """Tiny MagicMock-like for OpenAI exception kwargs."""

    def __getattr__(self, name: str) -> MagicMock:
        return self

    def __call__(self, *args: Any, **kwargs: Any) -> MagicMock:
        return self