"""Shared retrieval entity.

`RetrievedChunk` was originally placed in `domain/answering/entities.py`
because the agent's `Retriever` port was the only consumer. After the
WP01 review v1 (Issue 8) the `VectorStore.query` port (in
`domain/ingestion/ports.py`) was extended to return
`list[RetrievedChunk]` too, so both subsystems depend on the entity.

We move the canonical definition to `domain/shared/` (the same
location as `domain/shared/errors.py`) so both sub-packages can
import without an `ingestion → answering` cross-package import
(which would invert the sub-package dependency direction).
`domain/answering/entities.py` re-exports `RetrievedChunk` for
backward compatibility and for the canonical agent-side import
path used by WP02+.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RetrievedChunk(BaseModel):
    """A `Chunk` plus its similarity score to a `Question`.

    Attributes:
        chunk_id: Foreign key back to a `Chunk`.
        text: The chunk's text content.
        source_url: Parent source URL.
        similarity: Cosine similarity in `[0.0, 1.0]`. Clamped at
            construction so the agent never sees an out-of-range
            score.
    """

    model_config = ConfigDict(frozen=True)

    chunk_id: str = Field(min_length=40, max_length=40)
    text: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    similarity: float

    @field_validator("similarity")
    @classmethod
    def _clamp_similarity(cls, value: float) -> float:
        """Clamp `similarity` into `[0.0, 1.0]`.

        Some vector stores return distances rather than
        similarities; adapters are expected to map to
        `[0, 1]` before constructing the `RetrievedChunk`.
        This validator is the last line of defence against
        out-of-range scores reaching the workflow.
        """
        if value < 0.0:
            return 0.0
        if value > 1.0:
            return 1.0
        return value

    @classmethod
    def from_chunk(
        cls,
        chunk: Any,
        similarity: float,
    ) -> RetrievedChunk:
        """Build a `RetrievedChunk` from a `Chunk` + similarity.

        Adapter code (WP03 Chroma adapter, WP01 in-memory fake)
        uses this factory to construct `RetrievedChunk` from the
        store-native data shape.
        """
        chunk_id = chunk.chunk_id
        text = chunk.text
        source_url = chunk.source_url
        return cls(
            chunk_id=chunk_id,
            text=text,
            source_url=source_url,
            similarity=similarity,
        )


__all__ = ["RetrievedChunk"]
