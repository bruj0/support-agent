"""TDD red tests for ``adapters.embedding_local.SentenceTransformersEmbedder``.

Per WP03 T024.

The embedder wraps a sentence-transformers model and returns
``list[list[float]]`` vectors. The model is loaded lazily on the
first call so the test fixture can inject a stub model and avoid
downloading the real ~80 MB ``all-MiniLM-L6-v2`` artifact.
"""
from __future__ import annotations

from typing import Any

import pytest

from support_bot.adapters.embedding_local import SentenceTransformersEmbedder


class _StubModel:
    """Trivial in-memory stand-in for a ``SentenceTransformer`` model.

    Returns one zero vector per input text, with the configured
    dimensionality. Sufficient for asserting structural
    properties (length of returned list, length of each
    vector) without touching real model code.
    """

    def __init__(self, dim: int) -> None:
        self._dim = dim

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self._dim for _ in texts]


def _install_stub(monkeypatch: pytest.MonkeyPatch, *, dim: int = 384) -> None:
    """Patch the embedder to construct ``_StubModel`` instead of loading."""
    monkeypatch.setattr(
        "sentence_transformers.SentenceTransformer",
        lambda *args, **kwargs: _StubModel(dim),
    )


def test_embed_returns_vectors_with_correct_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each input text becomes a vector; the embedding count equals text count."""
    _install_stub(monkeypatch, dim=384)
    embedder = SentenceTransformersEmbedder()
    vectors = embedder.embed(["hello", "world"])
    assert len(vectors) == 2
    assert all(len(v) == 384 for v in vectors)


def test_embed_is_lazy_load(monkeypatch: pytest.MonkeyPatch) -> None:
    """The model is not loaded at construction time."""
    _install_stub(monkeypatch, dim=384)

    # Track that SentenceTransformer is *not* called before embed().
    calls: list[Any] = []

    def _track(*args: Any, **kwargs: Any) -> _StubModel:
        calls.append((args, kwargs))
        return _StubModel(384)

    monkeypatch.setattr("sentence_transformers.SentenceTransformer", _track)

    embedder = SentenceTransformersEmbedder()
    assert calls == []  # not loaded yet

    embedder.embed(["hello"])
    assert len(calls) == 1  # loaded now


def test_embed_custom_model_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """A custom ``model_name`` is passed to the loader."""
    _install_stub(monkeypatch)
    captured: list[tuple[str, ...]] = []

    def _capture(name: str, *args: Any, **kwargs: Any) -> _StubModel:
        captured.append((name,))
        return _StubModel(384)

    monkeypatch.setattr("sentence_transformers.SentenceTransformer", _capture)
    embedder = SentenceTransformersEmbedder(model_name="some-org/some-model")
    embedder.embed(["x"])
    assert captured and captured[0][0] == "some-org/some-model"


def test_embed_empty_list_returns_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty input list returns an empty output list."""
    _install_stub(monkeypatch)
    embedder = SentenceTransformersEmbedder()
    assert embedder.embed([]) == []


def test_embed_preserves_input_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Output order matches input order."""
    _install_stub(monkeypatch, dim=2)
    embedder = SentenceTransformersEmbedder()
    # Use a non-zero stub to distinguish positions.
    monkeypatch.setattr(
        "sentence_transformers.SentenceTransformer",
        lambda *a, **kw: _OrderRecordingModel([[1.0, 0.0], [0.0, 1.0]]),
    )
    vectors = embedder.embed(["a", "b"])
    assert vectors == [[1.0, 0.0], [0.0, 1.0]]


class _OrderRecordingModel:
    def __init__(self, vectors: list[list[float]]) -> None:
        self._vectors = vectors

    def encode(self, texts: list[str]) -> list[list[float]]:
        return self._vectors
