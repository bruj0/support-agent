"""Tests for the answering-domain entities."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from support_bot.domain.answering.entities import (
    AgentState,
    Answer,
    Confidence,
    Question,
    RetrievedChunk,
)


def _retrieved_chunk(similarity: float = 0.5) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="a" * 40,
        text="hello",
        source_url="https://example.com",
        similarity=similarity,
    )


class TestQuestion:
    """`Question` is the user's input + request_id."""

    def test_construction_requires_text(self) -> None:
        with pytest.raises(ValidationError):
            Question(text="", request_id="r")  # type: ignore[call-arg]

    def test_text_max_length_enforced(self) -> None:
        with pytest.raises(ValidationError):
            Question(text="x" * 2001, request_id="r")  # type: ignore[call-arg]

    def test_frozen(self) -> None:
        q = Question(text="hi", request_id="r")
        with pytest.raises(ValidationError):
            q.text = "tampered"  # type: ignore[misc]


class TestRetrievedChunk:
    """`RetrievedChunk.similarity` is clamped to `[0, 1]`."""

    def test_clamps_negative_similarity_to_zero(self) -> None:
        chunk = _retrieved_chunk(similarity=-0.5)
        assert chunk.similarity == 0.0

    def test_clamps_similarity_above_one(self) -> None:
        chunk = _retrieved_chunk(similarity=1.5)
        assert chunk.similarity == 1.0

    def test_accepts_in_range(self) -> None:
        chunk = _retrieved_chunk(similarity=0.7)
        assert chunk.similarity == 0.7


class TestAnswer:
    """`Answer` is the final agent response."""

    def test_confidence_must_be_high_or_low(self) -> None:
        with pytest.raises(ValidationError):
            Answer(
                text="x",
                confidence="maybe",  # type: ignore[arg-type]
            )

    def test_confidence_accepts_both_values(self) -> None:
        for c in ("high", "low"):
            Answer(text="x", confidence=c)  # type: ignore[arg-type]

    def test_default_top_similarity_is_zero(self) -> None:
        ans = Answer(text="x", confidence="low")
        assert ans.top_similarity == 0.0

    def test_default_trace_is_empty_list(self) -> None:
        ans = Answer(text="x", confidence="low")
        assert ans.trace == []

    def test_top_similarity_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Answer(text="x", confidence="low", top_similarity=1.5)
        with pytest.raises(ValidationError):
            Answer(text="x", confidence="low", top_similarity=-0.1)


class TestAgentState:
    """`AgentState` is the Pydantic state for the LangGraph
    workflow.

    Per the WP01 M3 Pydantic TDD target: confidence must reject
    values other than `high` / `low`.
    """

    def test_default_confidence_is_low(self) -> None:
        state = AgentState()
        assert state.confidence == "low"

    def test_confidence_literal_type(self) -> None:
        # The Confidence literal type must be the union of the
        # two strings — assert by introspection of the
        # `__args__` tuple.
        assert set(Confidence.__args__) == {"high", "low"}

    def test_confidence_rejects_invalid_value(self) -> None:
        with pytest.raises(ValidationError):
            AgentState(confidence="maybe")  # type: ignore[arg-type]

    def test_default_question_is_empty_string(self) -> None:
        state = AgentState()
        assert state.question == ""

    def test_default_retrieved_chunks_is_empty_list(self) -> None:
        state = AgentState()
        assert state.retrieved_chunks == []

    def test_state_is_mutable_for_langgraph(self) -> None:
        # LangGraph mutates the state in place; the entity is
        # intentionally NOT frozen.
        state = AgentState(question="x")
        state.question = "y"
        assert state.question == "y"