"""In-memory ``FakePageAnalyzer`` for unit and contract tests.

Per WP06 T052.

Returns a deterministic ``PageStructure`` so application tests can
assert the analyzer step ran and ``IngestionService`` produced
correctly-populated ``Chunk`` objects. The fake never calls the
LLM.
"""
from __future__ import annotations

from datetime import UTC, datetime

from support_bot.domain.ingestion.entities import (
    ContentKind,
    PageStructure,
    SemanticChunk,
)


class FakePageAnalyzer:
    """Canned ``PageAnalyzer`` that returns a fixed ``PageStructure``.

    Attributes:
        fail_next: When ``True``, the next call raises
            ``LLMUnavailable`` (per the WP06 design rationale, the
            analyzer port declares ``LLMUnavailable`` as its
            failure mode).
        region_count: Number of fake ``SemanticChunk`` entries to
            emit (default 3: one FAQ + two sections).
        model: Model name stamped into the produced
            ``PageStructure``.
    """

    def __init__(
        self,
        *,
        fail_next: bool = False,
        region_count: int = 3,
        model: str = "fake-analyzer/0.1",
    ) -> None:
        self.fail_next: bool = fail_next
        self.region_count: int = region_count
        self.model: str = model
        self.calls: list[tuple[str, str, str]] = []

    def analyze(
        self,
        *,
        source_url: str,
        text: str,
        request_id: str,
    ) -> PageStructure:
        """Return a fixed ``PageStructure`` for any input.

        Args:
            source_url: The URL the analyzer was invoked for
                (echoed into the produced entity).
            text: The cleaned page text (length determines the
                emitted chunks' text payload for visual sanity).
            request_id: Correlation id (recorded into
                ``self.calls`` for assertion).

        Returns:
            A ``PageStructure`` with ``region_count`` entries.

        Raises:
            LLMUnavailable: When ``fail_next`` is set.
        """
        self.calls.append((source_url, text, request_id))
        if self.fail_next:
            self.fail_next = False
            from support_bot.domain.shared.errors import LLMUnavailable
            raise LLMUnavailable("FakePageAnalyzer injected failure")
        kinds: list[ContentKind] = ["faq", "section", "section"]
        chunks: list[SemanticChunk] = []
        for i in range(self.region_count):
            kind = kinds[i % len(kinds)]
            payload = text[: 40 + i * 10] if text else "placeholder"
            chunks.append(
                SemanticChunk(
                    kind=kind,
                    title=f"Region {i}",
                    text=payload,
                    anchor=f"region-{i}" if i % 2 == 0 else None,
                )
            )
        return PageStructure(
            source_url=source_url,
            chunks=chunks,
            model=self.model,
            generated_at=datetime.now(tz=UTC),
        )


__all__ = ["FakePageAnalyzer"]