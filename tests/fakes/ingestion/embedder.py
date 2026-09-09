"""In-memory `FakeEmbedder` for unit and contract tests.

Returns deterministic zero vectors of the requested
dimensionality. Tests assert structural properties (length of
returned list, length of each vector) rather than numeric
content.
"""
from __future__ import annotations

from support_bot.domain.shared.errors import LLMUnavailable


class FakeEmbedder:
    """Canned `Embedder` returning zero vectors.

    Attributes:
        dim: Vector dimensionality. Defaults to 384 to match
            the `all-MiniLM-L6-v2` model (WP04).
        fail_next: When `True`, the next call raises
            `LLMUnavailable` (treating the embedding provider
            as a typed-error source). The domain has no
            separate `EmbedderUnavailable` exception, so the
            typed exception is shared with the LLM provider —
            both are upstream-text-generation paths from the domain's
            perspective.
        calls: List of batches the fake has been asked to embed.
    """

    def __init__(self, *, dim: int = 384, fail_next: bool = False) -> None:
        self.dim: int = dim
        self.fail_next: bool = fail_next
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self.fail_next:
            self.fail_next = False
            raise LLMUnavailable("FakeEmbedder injected failure")
        return [[0.0] * self.dim for _ in texts]


__all__ = ["FakeEmbedder"]