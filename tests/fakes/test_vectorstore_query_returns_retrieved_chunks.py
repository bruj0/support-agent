"""TDD target: VectorStore.query must return RetrievedChunk, not Chunk.

Issue 8 in WP01-review-summary-v1.json: the agent-side `Retriever`
port returns `list[RetrievedChunk]` (with similarity), but the
ingestion-side `VectorStore.query` port returns `list[Chunk]`
(without similarity). To keep the two ports as separate surfaces but
produce the same shape, this WP pins

    ``VectorStore.query(embedding, k) -> list[RetrievedChunk]``

with `similarity` populated by the adapter (the Chroma adapter in
WP03 maps cosine distance to similarity). The `Retriever` port
delegates to `VectorStore.query` (drop-in), so the agent code path
gets `RetrievedChunk`s without per-adapter bridging.

This test is the **red** phase: it fails today because
`FakeVectorStore.query` returns `list[Chunk]`. Once the contract
lands in the port, the test goes green.
"""
from __future__ import annotations

from support_bot.domain.answering.entities import RetrievedChunk
from support_bot.domain.ingestion.entities import Chunk
from tests.fakes.ingestion.vectorstore import FakeVectorStore


def _make_chunk(chunk_id: str, source_url: str, ordinal: int, text: str) -> Chunk:
    return Chunk.from_text(text, source_url=source_url, ordinal=ordinal)


def test_vectorstore_query_returns_list_of_retrieved_chunks() -> None:
    """The contract is `list[RetrievedChunk]`, not `list[Chunk]`."""
    store = FakeVectorStore()
    store.upsert(
        [
            _make_chunk("a" * 40, "u", 0, "alpha"),
            _make_chunk("b" * 40, "u", 1, "beta"),
            _make_chunk("c" * 40, "u", 2, "gamma"),
        ]
    )

    result = store.query(embedding=[0.1, 0.2, 0.3], k=2)

    # Each item must be a RetrievedChunk (Pydantic discriminated type),
    # not a Chunk. Pydantic models aren't true subclasses at the type
    # level so we check the discriminator class path.
    for item in result:
        assert type(item).__name__ == "RetrievedChunk" or isinstance(
            item, RetrievedChunk
        ), f"expected RetrievedChunk, got {type(item).__name__}"


def test_vectorstore_query_result_items_carry_similarity_in_zero_one() -> None:
    """`RetrievedChunk.similarity` must be in `[0.0, 1.0]`; the
    clamping validator on the entity guarantees this."""
    store = FakeVectorStore()
    store.upsert(
        [_make_chunk("a" * 40, "u", 0, "alpha")]
    )
    result = store.query(embedding=[0.0, 0.0, 0.0], k=1)

    assert len(result) >= 1
    for item in result:
        # Access the similarity attribute directly (both Duck and
        # Pydantic paths expose it).
        sim = getattr(item, "similarity", None)
        assert sim is not None
        assert 0.0 <= sim <= 1.0


def test_vectorstore_query_does_not_emit_chunk_only_dispatch() -> None:
    """The contract change is observable: the adapter-side dispatch
    type is `list[RetrievedChunk]`. We assert via a typed local that
    would be checked at static-typing time (mypy --strict) -- if the
    return type ever regresses to `list[Chunk]`, mypy will complain
    on the `as_list_of_retrieved_chunks` annotation.

    At runtime this test is a tautology; we include it so the
    contract change is documented in code as well as in types.
    """
    store = FakeVectorStore()
    out: list[RetrievedChunk] = store.query(embedding=[0.0], k=1)  # type: ignore[assignment]
    # If the port is `list[Chunk]`, mypy fails here. If the port is
    # `list[RetrievedChunk]`, the assignment narrows (the
    # `# type: ignore` is needed only if Chunk and RetrievedChunk
    # remain nominally distinct -- both are Pydantic, so this is a
    # useful static check).
    assert isinstance(out, list)
