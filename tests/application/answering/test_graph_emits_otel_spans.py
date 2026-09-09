"""TDD: graph + service emit the AGENTS.md 6.4 span attributes.

Per WP02 T019 (review v1 Issue 4 + Issue 7):

- The graph emits ``node.retrieve``, ``node.guard``,
  ``node.guard_edge``, and ``node.generate`` / ``node.refuse``
  spans, each carrying ``request.id``.
- The retrieve node span carries ``route``,
  ``question.text_hash``, ``retrieval.candidate_count``, and
  ``retrieval.top1_similarity`` (AGENTS.md 6.4).
- The guard edge span carries ``decision.path``.
- The generate node span carries ``answer.tokens_in`` and
  ``answer.tokens_out``.
- The ``answering_service.answer`` top-level span carries
  ``request.id``, ``route``, and ``question.text_hash``, plus
  ``decision.path`` on the success path.

Uses the ``in_memory_span_exporter`` fixture from ``conftest.py``
to capture and inspect spans.
"""
from __future__ import annotations

import pytest

from support_bot.application.answering.answering_service import (
    AnsweringService,
)
from support_bot.application.answering.graph import LangGraphWorkflow
from support_bot.domain.answering.entities import AgentState, RetrievedChunk
from tests.fakes.answering.answer_generator import FakeAnswerGenerator
from tests.fakes.answering.low_confidence_policy import StubLowConfidencePolicy
from tests.fakes.answering.retriever import FakeRetriever


def _spans_by_name(exporter, name: str):
    """Return all spans with the given name."""
    return [s for s in exporter.get_finished_spans() if s.name == name]


def test_graph_emits_retrieve_span_with_agents_6_4_attributes(
    in_memory_span_exporter,
) -> None:
    """The ``node.retrieve`` span carries the AGENTS.md 6.4 attributes."""
    _provider, exporter = in_memory_span_exporter
    chunk = RetrievedChunk(
        chunk_id="a" * 40, text="t", source_url="u", similarity=0.9
    )
    workflow = LangGraphWorkflow(
        retriever=FakeRetriever(retrieved_chunks=[chunk]),
        policy=StubLowConfidencePolicy(should_refuse_return=False),
        generator=FakeAnswerGenerator(),
    )
    workflow.compile().invoke(
        AgentState(question="hi", request_id="rid-test")
    )

    retrieve_spans = _spans_by_name(exporter, "node.retrieve")
    assert len(retrieve_spans) == 1
    attrs = retrieve_spans[0].attributes or {}
    assert attrs.get("request.id") == "rid-test"
    assert attrs.get("route") == "POST /ask"
    qhash = attrs.get("question.text_hash")
    assert isinstance(qhash, str)
    assert len(qhash) == 16
    assert all(c in "0123456789abcdef" for c in qhash)
    assert attrs.get("retrieval.candidate_count") == 1
    assert abs(attrs.get("retrieval.top1_similarity") - 0.9) < 1e-6


def test_graph_emits_guard_edge_span_with_decision_path(
    in_memory_span_exporter,
) -> None:
    """The ``node.guard_edge`` span carries ``decision.path``."""
    _provider, exporter = in_memory_span_exporter
    chunk = RetrievedChunk(
        chunk_id="a" * 40, text="t", source_url="u", similarity=0.9
    )
    workflow = LangGraphWorkflow(
        retriever=FakeRetriever(retrieved_chunks=[chunk]),
        policy=StubLowConfidencePolicy(should_refuse_return=False),
        generator=FakeAnswerGenerator(),
    )
    workflow.compile().invoke(
        AgentState(question="hi", request_id="rid-test")
    )
    guard_edge = _spans_by_name(exporter, "node.guard_edge")
    assert len(guard_edge) == 1
    attrs = guard_edge[0].attributes or {}
    assert attrs.get("request.id") == "rid-test"
    assert attrs.get("decision.path") == "generate"


def test_graph_emits_generate_span_with_tokens_attributes(
    in_memory_span_exporter,
) -> None:
    """The ``node.generate`` span carries ``answer.tokens_in`` and
    ``answer.tokens_out`` (AGENTS.md 6.4)."""
    _provider, exporter = in_memory_span_exporter
    chunk = RetrievedChunk(
        chunk_id="a" * 40, text="a" * 50, source_url="u", similarity=0.9
    )
    workflow = LangGraphWorkflow(
        retriever=FakeRetriever(retrieved_chunks=[chunk]),
        policy=StubLowConfidencePolicy(should_refuse_return=False),
        generator=FakeAnswerGenerator(canned="hello"),
    )
    workflow.compile().invoke(
        AgentState(question="hi", request_id="rid-test")
    )
    gen_spans = _spans_by_name(exporter, "node.generate")
    assert len(gen_spans) == 1
    attrs = gen_spans[0].attributes or {}
    assert attrs.get("request.id") == "rid-test"
    # tokens_in = sum of chunk text lengths = 50.
    assert attrs.get("answer.tokens_in") == 50
    # tokens_out = len(answer text) = len("hello") = 5.
    assert attrs.get("answer.tokens_out") == 5


def test_answering_service_emits_top_level_span_with_request_id(
    in_memory_span_exporter,
) -> None:
    """The ``answering_service.answer`` span carries ``request.id``,
    ``route``, ``question.text_hash``, and ``decision.path`` (Issue 7)."""
    _provider, exporter = in_memory_span_exporter
    chunk = RetrievedChunk(
        chunk_id="a" * 40, text="t", source_url="u", similarity=0.9
    )
    service = AnsweringService(
        retriever=FakeRetriever(retrieved_chunks=[chunk]),
        policy=StubLowConfidencePolicy(should_refuse_return=False),
        generator=FakeAnswerGenerator(),
    )
    from support_bot.domain.answering.entities import Question

    service.answer(
        Question(text="hi", request_id="rid-service-test"),
        request_id="rid-service-test",
    )
    top_spans = _spans_by_name(exporter, "answering_service.answer")
    assert len(top_spans) == 1
    attrs = top_spans[0].attributes or {}
    assert attrs.get("request.id") == "rid-service-test"
    assert attrs.get("route") == "POST /ask"
    qhash = attrs.get("question.text_hash")
    assert isinstance(qhash, str) and len(qhash) == 16
    assert attrs.get("decision.path") == "generate"


def test_graph_refuse_path_emits_correct_decision_path(
    in_memory_span_exporter,
) -> None:
    """On the refuse path, ``decision.path == 'refuse'``."""
    _provider, exporter = in_memory_span_exporter
    workflow = LangGraphWorkflow(
        retriever=FakeRetriever(retrieved_chunks=[]),
        policy=StubLowConfidencePolicy(should_refuse_return=True),
        generator=FakeAnswerGenerator(),
    )
    workflow.compile().invoke(
        AgentState(question="hi", request_id="rid-refuse")
    )
    guard_edge = _spans_by_name(exporter, "node.guard_edge")
    assert len(guard_edge) == 1
    assert (guard_edge[0].attributes or {}).get("decision.path") == "refuse"
    assert len(_spans_by_name(exporter, "node.refuse")) == 1
    assert len(_spans_by_name(exporter, "node.generate")) == 0
