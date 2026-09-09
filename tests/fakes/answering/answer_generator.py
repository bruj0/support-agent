"""In-memory `FakeAnswerGenerator` for unit and contract tests.

Records every call so tests can assert the LLM was *not* called
(M3 — when retrieval is empty, the guard node routes to
`refuse` and the LLM must remain untouched).

The `fail_next` flag drives the next call into a
`LLMUnavailable` raise (M5/M6 / FR-010).
"""
from __future__ import annotations

from support_bot.domain.answering.entities import RetrievedChunk
from support_bot.domain.shared.errors import LLMUnavailable


class FakeAnswerGenerator:
    """Canned `AnswerGenerator` returning a fixed string.

    Attributes:
        canned: The string every `generate` returns.
        fail_next: When `True`, the next call raises
            `LLMUnavailable`.
        calls: List of `(question, retrieved)` pairs that have
            been generated (read-only introspection).
    """

    def __init__(
        self,
        canned: str = "FAKE_ANSWER",
        *,
        fail_next: bool = False,
    ) -> None:
        self.canned: str = canned
        self.fail_next: bool = fail_next
        self.calls: list[tuple[str, list[RetrievedChunk]]] = []

    def generate(self, question: str, retrieved: list[RetrievedChunk]) -> str:
        self.calls.append((question, list(retrieved)))
        if self.fail_next:
            self.fail_next = False
            raise LLMUnavailable("FakeAnswerGenerator injected failure")
        return self.canned


__all__ = ["FakeAnswerGenerator"]