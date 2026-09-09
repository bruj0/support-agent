"""TDD red tests for ``adapters.answerer_openai.OPENAIAnswerGenerator``.

The production ``AnswerGenerator`` adapter is built in WP04 to
complete the docker-compose wiring. The adapter wraps the
``openai`` chat completions API and translates provider errors
and timeouts into the typed ``LLMUnavailable`` exception
declared in ``domain/shared/errors.py``.
"""
from __future__ import annotations

from typing import Any

import pytest

from support_bot.adapters.answerer_openai import OPENAIAnswerGenerator
from support_bot.domain.shared.errors import LLMUnavailable
from support_bot.domain.shared.retrieval import RetrievedChunk


def _chunk(text: str = "context", similarity: float = 0.9) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="a" * 40,
        text=text,
        source_url="https://example.com/help",
        similarity=similarity,
    )


def _install_client(monkeypatch: pytest.MonkeyPatch, response: Any) -> None:
    """Patch ``openai.OpenAI`` so ``chat.completions.create`` returns ``response``."""

    class _CompletionsAPI:
        def create(self, **kwargs: Any) -> Any:
            return response

    class _Chat:
        def __init__(self) -> None:
            self.completions = _CompletionsAPI()

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.chat = _Chat()

    monkeypatch.setattr("openai.OpenAI", _Client)


def _text_response(text: str) -> Any:
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


def test_generate_returns_message_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """``generate`` returns the assistant message content from the OpenAI API."""
    _install_client(monkeypatch, _text_response("the answer"))
    gen = OPENAIAnswerGenerator(api_key="test-key")
    out = gen.generate(question="q?", retrieved=[_chunk()])
    assert out == "the answer"


def test_generate_uses_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default model is ``gpt-4o-mini``."""
    captured: list[dict[str, Any]] = []

    class _CompletionsAPI:
        def create(self, **kwargs: Any) -> Any:
            captured.append(kwargs)
            return _text_response("x")

    class _Chat:
        def __init__(self) -> None:
            self.completions = _CompletionsAPI()

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.chat = _Chat()

    monkeypatch.setattr("openai.OpenAI", _Client)
    gen = OPENAIAnswerGenerator(api_key="test-key")
    gen.generate(question="q?", retrieved=[_chunk()])
    assert captured[0]["model"] == "gpt-4o-mini"


def test_generate_passes_question(monkeypatch: pytest.MonkeyPatch) -> None:
    """The question is forwarded into the messages list."""
    captured: list[dict[str, Any]] = []

    class _CompletionsAPI:
        def create(self, **kwargs: Any) -> Any:
            captured.append(kwargs)
            return _text_response("x")

    class _Chat:
        def __init__(self) -> None:
            self.completions = _CompletionsAPI()

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.chat = _Chat()

    monkeypatch.setattr("openai.OpenAI", _Client)
    gen = OPENAIAnswerGenerator(api_key="test-key")
    gen.generate(question="what is X?", retrieved=[_chunk("X is ...")])
    msgs = captured[0]["messages"]
    joined = " ".join(m["content"] for m in msgs)
    assert "what is X?" in joined


def test_generate_raises_llm_unavailable_on_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider error is translated to ``LLMUnavailable``."""
    import openai as _openai

    class _CompletionsAPI:
        def create(self, **kwargs: Any) -> Any:
            raise _openai.OpenAIError("provider down")

    class _Chat:
        def __init__(self) -> None:
            self.completions = _CompletionsAPI()

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.chat = _Chat()

    monkeypatch.setattr("openai.OpenAI", _Client)
    gen = OPENAIAnswerGenerator(api_key="test-key")
    with pytest.raises(LLMUnavailable):
        gen.generate(question="q?", retrieved=[_chunk()])


def test_generate_raises_llm_unavailable_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A timeout is translated to ``LLMUnavailable``."""
    import openai as _openai

    class _CompletionsAPI:
        def create(self, **kwargs: Any) -> Any:
            raise _openai.APITimeoutError("timed out")

    class _Chat:
        def __init__(self) -> None:
            self.completions = _CompletionsAPI()

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.chat = _Chat()

    monkeypatch.setattr("openai.OpenAI", _Client)
    gen = OPENAIAnswerGenerator(api_key="test-key")
    with pytest.raises(LLMUnavailable):
        gen.generate(question="q?", retrieved=[_chunk()])
