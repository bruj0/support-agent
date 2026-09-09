"""TDD red tests for ``adapters.embedding_openai.OpenAIEmbedder``.

Per WP03 T025.

The embedder wraps the ``openai`` SDK and translates provider
errors and timeouts into the typed ``EmbedderUnavailable``
exception declared in ``domain/shared/errors.py``.
"""
from __future__ import annotations

from typing import Any

import pytest

from support_bot.adapters.embedding_openai import OpenAIEmbedder
from support_bot.domain.shared.errors import EmbedderUnavailable


def _make_response(vectors: list[list[float]]) -> Any:
    """Build a stub OpenAI response shape with ``data[i].embedding``."""

    class _Item:
        def __init__(self, vec: list[float]) -> None:
            self.embedding = vec

    class _Resp:
        def __init__(self, data: list[_Item]) -> None:
            self.data = data

    return _Resp([_Item(v) for v in vectors])


def _install_client(monkeypatch: pytest.MonkeyPatch, response: Any) -> None:
    """Patch ``openai.OpenAI`` so ``embeddings.create`` returns ``response``."""

    class _EmbeddingsAPI:
        def create(self, **kwargs: Any) -> Any:
            return response

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.embeddings = _EmbeddingsAPI()

    monkeypatch.setattr("openai.OpenAI", _Client)


def test_embed_returns_vectors_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Vectors are returned in the same order as the input texts."""
    _install_client(
        monkeypatch, _make_response([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
    )
    embedder = OpenAIEmbedder(api_key="test-key")
    vectors = embedder.embed(["a", "b", "c"])
    assert vectors == [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]


def test_embed_uses_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default model is ``text-embedding-3-small``."""
    captured: list[dict[str, Any]] = []

    class _EmbeddingsAPI:
        def create(self, **kwargs: Any) -> Any:
            captured.append(kwargs)
            return _make_response([[0.0, 0.0]])

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.embeddings = _EmbeddingsAPI()

    monkeypatch.setattr("openai.OpenAI", _Client)
    embedder = OpenAIEmbedder(api_key="test-key")
    embedder.embed(["x"])
    assert captured[0]["model"] == "text-embedding-3-small"


def test_embed_passes_input_texts(monkeypatch: pytest.MonkeyPatch) -> None:
    """The input list is forwarded to the API as ``input``."""
    captured: list[dict[str, Any]] = []

    class _EmbeddingsAPI:
        def create(self, **kwargs: Any) -> Any:
            captured.append(kwargs)
            return _make_response([[0.0, 0.0], [0.0, 0.0]])

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.embeddings = _EmbeddingsAPI()

    monkeypatch.setattr("openai.OpenAI", _Client)
    embedder = OpenAIEmbedder(api_key="test-key")
    embedder.embed(["hello", "world"])
    assert captured[0]["input"] == ["hello", "world"]


def test_embed_raises_embedder_unavailable_on_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider error is translated to ``EmbedderUnavailable``."""
    import openai as _openai

    class _EmbeddingsAPI:
        def create(self, **kwargs: Any) -> Any:
            raise _openai.OpenAIError("provider down")

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.embeddings = _EmbeddingsAPI()

    monkeypatch.setattr("openai.OpenAI", _Client)
    embedder = OpenAIEmbedder(api_key="test-key")
    with pytest.raises(EmbedderUnavailable):
        embedder.embed(["x"])


def test_embed_raises_embedder_unavailable_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A timeout is translated to ``EmbedderUnavailable``."""
    import openai as _openai

    class _EmbeddingsAPI:
        def create(self, **kwargs: Any) -> Any:
            raise _openai.APITimeoutError("timed out")

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.embeddings = _EmbeddingsAPI()

    monkeypatch.setattr("openai.OpenAI", _Client)
    embedder = OpenAIEmbedder(api_key="test-key")
    with pytest.raises(EmbedderUnavailable):
        embedder.embed(["x"])


def test_embed_empty_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty input list returns an empty list without calling the API."""
    called = {"count": 0}

    class _EmbeddingsAPI:
        def create(self, **kwargs: Any) -> Any:
            called["count"] += 1
            return _make_response([])

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.embeddings = _EmbeddingsAPI()

    monkeypatch.setattr("openai.OpenAI", _Client)
    embedder = OpenAIEmbedder(api_key="test-key")
    assert embedder.embed([]) == []
    assert called["count"] == 0
