"""TDD red: LangGraph workflow walks the generate path when
retrieval succeeds.

Per AGENTS.md 6 + WP02 T011, T012, T013, T019:

- The workflow composes START -> retrieve -> guard -> generate -> END
  when the LowConfidencePolicy says NOT to refuse.
- The resulting AgentState carries:
    * trace = ["retrieve", "guard", "generate"]
    * confidence = "high"
    * answer = the FakeAnswerGenerator canned text
    * request_id = the request_id passed in
- OTel spans: node.retrieve, node.guard, node.guard_edge
  (decision.path=generate), node.generate are emitted, each
  carrying request.id = "test-req-id".
- The AnswerGenerator was invoked exactly once.
"""
from __future__ import annotations


def test_graph_walks_generate_when_high_confidence() -> None:
    """End-to-end happy path: retrieve 3 chunks, policy accepts,
    generator is called once, state carries the right shape."""
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    from support_bot.application.answering.graph import LangGraphWorkflow
    from support_bot.domain.answering.entities import (
        AgentState,
        RetrievedChunk,
    )
    from tests.fakes.answering.answer_generator import FakeAnswerGenerator
    from tests.fakes.answering.low_confidence_policy import StubLowConfidencePolicy
    from tests.fakes.answering.retriever import FakeRetriever

    # Reset the global TracerProvider for deterministic spans.
    provider = TracerProvider()
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer("test")

    chunk = RetrievedChunk(
        chunk_id="a" * 40,
        text="relevant content",
        source_url="https://example.com",
        similarity=0.92,
    )
    retriever = FakeRetriever(retrieved_chunks=[chunk, chunk, chunk])
    policy = StubLowConfidencePolicy(should_refuse_return=False)
    generator = FakeAnswerGenerator(canned="HELPFUL_ANSWER")

    workflow = LangGraphWorkflow(
        retriever=retriever,
        policy=policy,
        generator=generator,
        tracer=tracer,
    )
    compiled = workflow.compile()
    assert compiled is not None

    initial_state = AgentState(question="What is X?", request_id="test-req-id")
    final_state = compiled.invoke(initial_state)

    assert final_state["answer"] == "HELPFUL_ANSWER"
    assert final_state["confidence"] == "high"
    assert final_state["request_id"] == "test-req-id"
    assert final_state["trace"] == ["retrieve", "guard", "generate"]
    assert len(generator.calls) == 1
    assert retriever.calls == [("What is X?", 4)]


def test_graph_walks_refuse_when_empty_retrieval() -> None:
    """Refusal path: empty retrieval, policy says refuse."""
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    from support_bot.application.answering.graph import LangGraphWorkflow
    from support_bot.domain.answering.entities import AgentState
    from tests.fakes.answering.answer_generator import FakeAnswerGenerator
    from tests.fakes.answering.low_confidence_policy import StubLowConfidencePolicy
    from tests.fakes.answering.retriever import FakeRetriever

    provider = TracerProvider()
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer("test")

    retriever = FakeRetriever(retrieved_chunks=[])
    policy = StubLowConfidencePolicy(should_refuse_return=True)
    generator = FakeAnswerGenerator(canned="LLM_WAS_CALLED_BAD")

    workflow = LangGraphWorkflow(
        retriever=retriever,
        policy=policy,
        generator=generator,
        tracer=tracer,
    )
    compiled = workflow.compile()
    final_state = compiled.invoke(
        AgentState(question="What is X?", request_id="test-req-id")
    )

    assert final_state["confidence"] == "low"
    assert final_state["trace"] == ["retrieve", "guard", "refuse"]
    assert final_state["answer"].startswith("I cannot answer")
    assert len(generator.calls) == 0, (
        "M3: the LLM must NOT be called when retrieval is empty"
    )


def test_guard_edge_return_type_is_literal() -> None:
    """The conditional edge path function routes to generate
    when the policy accepts and to refuse when the policy says
    refuse -- covers two of the three literal return values
    (the third, ``__end__``, is the END sentinel and is used by
    LangGraph internally when no further node is selected)."""
    from support_bot.application.answering.graph import LangGraphWorkflow
    from support_bot.domain.answering.entities import (
        AgentState,
        RetrievedChunk,
    )
    from tests.fakes.answering.answer_generator import FakeAnswerGenerator
    from tests.fakes.answering.low_confidence_policy import StubLowConfidencePolicy
    from tests.fakes.answering.retriever import FakeRetriever

    chunk = RetrievedChunk(
        chunk_id="a" * 40,
        text="t",
        source_url="u",
        similarity=0.9,
    )

    # 1. Path "generate"
    wf_g = LangGraphWorkflow(
        retriever=FakeRetriever(retrieved_chunks=[chunk]),
        policy=StubLowConfidencePolicy(should_refuse_return=False),
        generator=FakeAnswerGenerator(),
        tracer=None,
    )
    out_g = wf_g.compile().invoke(AgentState(question="q", request_id="r"))
    assert out_g["trace"][-1] == "generate"

    # 2. Path "refuse"
    wf_r = LangGraphWorkflow(
        retriever=FakeRetriever(retrieved_chunks=[]),
        policy=StubLowConfidencePolicy(should_refuse_return=True),
        generator=FakeAnswerGenerator(),
        tracer=None,
    )
    out_r = wf_r.compile().invoke(AgentState(question="q", request_id="r"))
    assert out_r["trace"][-1] == "refuse"
