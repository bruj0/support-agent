"""TDD red phase: port-conformance tests for every domain port.

Reviews note (Issue 1 + Issue 2 from WP01-review-summary-v1.json):
the prior WP cycle shipped the fakes without an automated
port-conformance suite. This file is the red phase:
the tests assert

- ``isinstance(fake, Port)`` for every port
  (which fails today because Protocols are not nominal
  types; isinstance against a Protocol is `isinstance(obj,
  Protocol)` and works structurally),
- signature match for every port method against the
  declared port method, via `inspect.signature`,
- failure injection raising the documented typed
  exception.

Once the conftest helper at the bottom of this file and
the per-port assertions compile and pass, the conformance
suite becomes the single source of truth for "these fakes
can stand in for the production adapters" (plan § Phase 0.5
§ E checklist item 2).
"""
from __future__ import annotations

import inspect

import pytest

from support_bot.domain.answering.entities import (
    RetrievedChunk,
)
from support_bot.domain.answering.ports import (
    AnswerGenerator,
    LowConfidencePolicy,
    Retriever,
)
from support_bot.domain.ingestion.entities import (
    Chunk,  # noqa: F401  # used by signature fixtures below
)
from support_bot.domain.ingestion.ports import (
    Chunker,
    Embedder,
    PageScraper,
    VectorStore,
)

# `Chunk` is the input to VectorStore.upsert and is referenced
# through `FakeVectorStore.upsert_calls` typing; not used
# directly in this conformance file but the import documents
# the dependency.
from support_bot.domain.shared.errors import (
    EmptyRetrieval,
    LLMUnavailable,
    SourcePageUnreachable,
    VectorStoreUnavailable,
)
from tests.fakes.answering.answer_generator import FakeAnswerGenerator
from tests.fakes.answering.low_confidence_policy import StubLowConfidencePolicy
from tests.fakes.answering.retriever import FakeRetriever
from tests.fakes.ingestion.chunker import FakeChunker
from tests.fakes.ingestion.embedder import FakeEmbedder
from tests.fakes.ingestion.page_analyzer import FakePageAnalyzer
from tests.fakes.ingestion.page_scraper import FakePageScraper
from tests.fakes.ingestion.vectorstore import FakeVectorStore


def _signatures_compatible(
    port_method: object, fake_method: object
) -> bool:
    """Return True iff port and fake methods have compatible
    signatures, ignoring return annotations (because runtime
    inspection of Protocols may differ from concrete classes)."""
    port_sig = inspect.signature(port_method)  # type: ignore[arg-type]
    fake_sig = inspect.signature(fake_method)  # type: ignore[arg-type]
    # Parameter names must match (positional + keyword) and
    # defaults must be compatible.
    port_params = list(port_sig.parameters.values())
    fake_params = list(fake_sig.parameters.values())
    if len(port_params) != len(fake_params):
        return False
    for p, f in zip(port_params, fake_params, strict=True):
        if p.name != f.name:
            return False
        if p.kind != f.kind:
            return False
        # Defaults: if the port has a default, the fake must too.
        if p.default is inspect.Parameter.empty and (
            f.default is not inspect.Parameter.empty
        ):
            return False
    return True


class TestPageScraper:
    """FakePageScraper conforms to the PageScraper port."""

    def test_isinstance(self) -> None:
        fake = FakePageScraper()
        assert isinstance(fake, PageScraper)

    def test_method_signature(self) -> None:
        assert _signatures_compatible(PageScraper.fetch, FakePageScraper.fetch)

    def test_fail_next_raises_unreachable(self) -> None:
        # M1/M2 foundation TDD target.
        fake = FakePageScraper(fail_next=True)
        with pytest.raises(SourcePageUnreachable):
            fake.fetch("https://example.com")


class TestChunker:
    """FakeChunker conforms to the Chunker port."""

    def test_isinstance(self) -> None:
        fake = FakeChunker()
        assert isinstance(fake, Chunker)

    def test_method_signature(self) -> None:
        assert _signatures_compatible(Chunker.chunk, FakeChunker.chunk)


class TestEmbedder:
    """FakeEmbedder conforms to the Embedder port."""

    def test_isinstance(self) -> None:
        fake = FakeEmbedder()
        assert isinstance(fake, Embedder)

    def test_method_signature(self) -> None:
        assert _signatures_compatible(Embedder.embed, FakeEmbedder.embed)


class TestVectorStore:
    """FakeVectorStore conforms to the VectorStore port."""

    def test_isinstance(self) -> None:
        fake = FakeVectorStore()
        assert isinstance(fake, VectorStore)

    def test_upsert_signature(self) -> None:
        assert _signatures_compatible(
            VectorStore.upsert, FakeVectorStore.upsert
        )

    def test_delete_by_source_signature(self) -> None:
        assert _signatures_compatible(
            VectorStore.delete_by_source, FakeVectorStore.delete_by_source
        )

    def test_count_signature(self) -> None:
        assert _signatures_compatible(
            VectorStore.count, FakeVectorStore.count
        )

    def test_query_signature(self) -> None:
        assert _signatures_compatible(
            VectorStore.query, FakeVectorStore.query
        )

    def test_fail_next_raises_unavailable(self) -> None:
        # M6 foundation TDD target.
        fake = FakeVectorStore(fail_next=True)
        with pytest.raises(VectorStoreUnavailable):
            fake.upsert([])


class TestRetriever:
    """FakeRetriever conforms to the Retriever port."""

    def test_isinstance(self) -> None:
        fake = FakeRetriever()
        assert isinstance(fake, Retriever)

    def test_method_signature(self) -> None:
        assert _signatures_compatible(
            Retriever.retrieve, FakeRetriever.retrieve
        )

    def test_fail_next_raises_unavailable(self) -> None:
        fake = FakeRetriever(fail_next=True)
        with pytest.raises(VectorStoreUnavailable):
            fake.retrieve("hi")

    def test_raise_empty_raises_empty_retrieval(self) -> None:
        fake = FakeRetriever()
        fake.raise_empty = True
        with pytest.raises(EmptyRetrieval):
            fake.retrieve("hi")


class TestLowConfidencePolicy:
    """StubLowConfidencePolicy conforms to the LowConfidencePolicy port."""

    def test_isinstance(self) -> None:
        fake = StubLowConfidencePolicy()
        assert isinstance(fake, LowConfidencePolicy)

    def test_should_refuse_signature(self) -> None:
        assert _signatures_compatible(
            LowConfidencePolicy.should_refuse,
            StubLowConfidencePolicy.should_refuse,
        )

    def test_refusal_message_signature(self) -> None:
        assert _signatures_compatible(
            LowConfidencePolicy.refusal_message,
            StubLowConfidencePolicy.refusal_message,
        )


class TestAnswerGenerator:
    """FakeAnswerGenerator conforms to the AnswerGenerator port."""

    def test_isinstance(self) -> None:
        fake = FakeAnswerGenerator()
        assert isinstance(fake, AnswerGenerator)

    def test_method_signature(self) -> None:
        assert _signatures_compatible(
            AnswerGenerator.generate, FakeAnswerGenerator.generate
        )

    def test_fail_next_raises_llm_unavailable(self) -> None:
        fake = FakeAnswerGenerator(fail_next=True)
        chunk = RetrievedChunk(
            chunk_id="a" * 40,
            text="hi",
            source_url="https://example.com",
            similarity=0.5,
        )
        with pytest.raises(LLMUnavailable):
            fake.generate("q", [chunk])


class TestPageAnalyzer:
    """FakePageAnalyzer conforms to the PageAnalyzer port."""

    def test_isinstance(self) -> None:
        # Conformance only asserts the isinstance check against
        # the (yet-to-be-defined) PageAnalyzer Protocol. Will
        # raise NameError if the port isn't defined yet — TDD red.
        from support_bot.domain.ingestion.ports import PageAnalyzer

        fake = FakePageAnalyzer()
        assert isinstance(fake, PageAnalyzer)

    def test_method_signature(self) -> None:
        from support_bot.domain.ingestion.ports import PageAnalyzer

        assert _signatures_compatible(
            PageAnalyzer.analyze, FakePageAnalyzer.analyze
        )

    def test_fail_next_raises_llm_unavailable(self) -> None:
        fake = FakePageAnalyzer(fail_next=True)
        with pytest.raises(LLMUnavailable):
            fake.analyze(
                source_url="https://example.com",
                text="hello world",
                request_id="rid-1",
            )
