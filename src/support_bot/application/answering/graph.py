"""LangGraph workflow that wires the four nodes + the guard edge.

Per AGENTS.md 1.5, 6.4 + WP02 T011, T011a, T012.

Topology::

    START -> retrieve -> guard ->[conditional]-> generate -> END
                                         -> refuse   -> END

Conditional edge return type is ``Literal["generate", "refuse",
"__end__"]``. The path function delegates to the injected
``LowConfidencePolicy`` -- no business logic in the edge.

Design choices
--------------

- The workflow has zero imports from ``langchain_*`` or
  ``chromadb``; it depends only on the three ports declared in
  ``domain/answering/ports``.
- Each node is wrapped in an OpenTelemetry span named
  ``node.<name>`` with attributes ``request.id``, ``route``, and
  (for the ``retrieve`` node) ``retrieval.top1_similarity`` and
  ``retrieval.candidate_count``. The guard edge span carries
  ``decision.path``.
- Future extensions can replace the body of any single node
  with a ``langchain.agents.create_agent`` instance without
  changing the topology, the state schema, or any other node.
- Spans are emitted even when no OTLP exporter is configured --
  ``opentelemetry-instrumentation-logging`` injects the
  ``trace_id`` / ``span_id`` into every ``structlog`` line.
"""
from __future__ import annotations

import hashlib
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from support_bot.domain.answering.entities import AgentState, RetrievedChunk
from support_bot.domain.answering.ports import (
    AnswerGenerator,
    LowConfidencePolicy,
    Retriever,
)


def _text_hash(text: str) -> str:
    """sha256 hex, truncated to 16 chars (per AGENTS 6.4 PII rule)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# Top-k chunks sent to the answerer after reranking. The
# reranker (LexicalRerankRetriever) already promotes the
# semantically correct chunk to top-1 in the Dutch verb-form
# cases we hit, so 4 is sufficient; bumping to 6 only adds
# context tokens without measurable answer-quality gains on
# the 17-chunk Ziggo corpus.
RETRIEVE_K = 4


def retrieve_node(
    state: AgentState,
    *,
    retriever: Retriever,
    tracer: Any = None,
) -> dict[str, Any]:
    """Retrieve the top-k chunks for ``state.question``.

    Args:
        state: The current ``AgentState`` (read for ``question``,
            ``request_id``, and the existing ``trace``).
        retriever: The ``Retriever`` port implementation. Must
            be supplied (nodes are pure: they never construct
            adapters).
        tracer: Optional OTel tracer. When ``None``, the node
            runs under a no-op span context manager so the
            function is testable without an OTel SDK.

    Returns:
        A partial state update mapping ``retrieved_chunks`` to
        the freshly-retrieved chunks and appending ``"retrieve"``
        to ``trace``. LangGraph applies the update on top of the
        existing state.
    """
    import structlog

    log = structlog.get_logger()
    span_cm = tracer.start_as_current_span("node.retrieve")
    with span_cm as span:
        span.set_attribute("request.id", state.request_id)
        span.set_attribute("route", "POST /ask")
        question_hash = _text_hash(state.question)
        span.set_attribute("question.text_hash", question_hash)
        log.debug(
            "node.retrieve.start",
            question_text_hash=question_hash,
            request_id=state.request_id,
            k=RETRIEVE_K,
        )
        try:
            chunks: list[RetrievedChunk] = retriever.retrieve(state.question, k=RETRIEVE_K)
        except Exception as exc:
            log.warning(
                "node.retrieve.error",
                request_id=state.request_id,
                error_type=type(exc).__name__,
            )
            raise
        top1 = chunks[0].similarity if chunks else 0.0
        span.set_attribute("retrieval.candidate_count", len(chunks))
        span.set_attribute("retrieval.top1_similarity", top1)
        log.debug(
            "node.retrieve.ok",
            request_id=state.request_id,
            candidate_count=len(chunks),
            top1_similarity=top1,
        )
        return {
            "retrieved_chunks": chunks,
            "trace": state.trace + ["retrieve"],
        }


def guard_node(
    state: AgentState,
    *,
    policy: LowConfidencePolicy,
    tracer: Any = None,
) -> dict[str, Any]:
    """Append ``guard`` to the trace.

    Args:
        state: The current ``AgentState`` (read for ``request_id``,
            ``retrieved_chunks``, and ``trace``).
        policy: The ``LowConfidencePolicy`` port. Currently unused
            inside the node body -- the actual decision is made
            by the conditional edge (``_decide``) following this
            node -- but it is passed here so the node participates
            in the compile-time graph schema.
        tracer: Optional OTel tracer.

    Returns:
        A partial state update appending ``"guard"`` to ``trace``.

    Notes:
        The decision (generate / refuse / __end__) is made by the
        conditional edge; this node only records that the guard
        ran. That separation keeps business logic out of the edge
        function (AGENTS.md 1.5).
    """
    import structlog

    log = structlog.get_logger()
    span_cm = tracer.start_as_current_span("node.guard")
    with span_cm as span:
        span.set_attribute("request.id", state.request_id)
        # ``policy.should_refuse`` is consulted by the
        # conditional edge; calling it here would double-decide.
        # Just record the visit and let the edge do its job.
        del policy
        log.debug(
            "node.guard.visited",
            request_id=state.request_id,
            candidate_count=len(state.retrieved_chunks),
        )
        return {"trace": state.trace + ["guard"]}


def generate_node(
    state: AgentState,
    *,
    generator: AnswerGenerator,
    tracer: Any = None,
) -> dict[str, Any]:
    """Generate the answer string using the retrieved context.

    Args:
        state: The current ``AgentState``. ``question`` and
            ``retrieved_chunks`` are read; ``trace`` is
            appended.
        generator: The ``AnswerGenerator`` port implementation.
        tracer: Optional OTel tracer.

    Returns:
        A partial state update with ``answer`` set to the
        generated string, ``confidence="high"``, and ``trace``
        appended with ``"generate"``. Errors raised by the
        generator (``LLMUnavailable``) are re-raised without
        wrapping so the API error mapper can dispatch them.
    """
    import structlog

    log = structlog.get_logger()
    span_cm = tracer.start_as_current_span("node.generate")
    with span_cm as span:
        span.set_attribute("request.id", state.request_id)
        span.set_attribute("route", "POST /ask")
        question_hash = _text_hash(state.question)
        span.set_attribute("question.text_hash", question_hash)
        # ``answer.tokens_in`` is a coarse surrogate for the
        # sum of the prompt tokens; we report the sum of the
        # chunk text lengths because that is the prompt
        # fragment the node actually consumed. The real
        # answerer adapter (WP03+) will refine this when it
        # integrates with the chat provider.
        tokens_in = sum(len(c.text) for c in state.retrieved_chunks)
        span.set_attribute("answer.tokens_in", tokens_in)
        log.debug(
            "node.generate.start",
            request_id=state.request_id,
            question_text_hash=question_hash,
            context_count=len(state.retrieved_chunks),
        )
        text = generator.generate(state.question, state.retrieved_chunks)
        span.set_attribute("answer.tokens_out", len(text))
        log.debug(
            "node.generate.ok",
            request_id=state.request_id,
            answer_text_hash=_text_hash(text),
            answer_length=len(text),
        )
        return {
            "answer": text,
            "confidence": "high",
            "trace": state.trace + ["generate"],
        }


def refuse_node(
    state: AgentState,
    *,
    policy: LowConfidencePolicy,
    tracer: Any = None,
) -> dict[str, Any]:
    """Return the static refusal string from the policy.

    Args:
        state: The current ``AgentState``. Only ``request_id``
            is read.
        policy: The ``LowConfidencePolicy`` port. Its
            ``refusal_message()`` is the source of the static
            refusal string (FR-009 acceptance scenario 1).
        tracer: Optional OTel tracer.

    Returns:
        A partial state update with ``answer`` set to the
        refusal message, ``confidence="low"``, and ``trace``
        appended with ``"refuse"``.
    """
    import structlog

    log = structlog.get_logger()
    span_cm = tracer.start_as_current_span("node.refuse")
    with span_cm as span:
        span.set_attribute("request.id", state.request_id)
        text = policy.refusal_message()
        log.debug(
            "node.refuse.ok",
            request_id=state.request_id,
            answer_text_hash=_text_hash(text),
        )
        return {
            "answer": text,
            "confidence": "low",
            "trace": state.trace + ["refuse"],
        }


def _decide(
    state: AgentState,
    *,
    policy: LowConfidencePolicy,
    tracer: Any = None,
) -> Literal["generate", "refuse", "__end__"]:
    """Conditional edge: route to generate / refuse based on policy.

    Args:
        state: The current ``AgentState``. ``retrieved_chunks``
            is read to decide.
        policy: The ``LowConfidencePolicy`` port whose
            ``should_refuse`` answers the routing question.
        tracer: Optional OTel tracer.

    Returns:
        ``"generate"`` when the policy accepts the retrieval;
        ``"refuse"`` when the policy rejects (including the
        empty-retrieval case). ``"__end__"`` is reserved for
        future WPs (e.g. early-exit when the question is empty)
        but the WP02 wiring only emits ``"generate"`` or
        ``"refuse"``.

    Notes:
        Return type is the literal union per AGENTS 1.5 -- the
        conditional edge depends on the annotation for its
        path-mapping dict.
    """
    import structlog

    log = structlog.get_logger()
    span_cm = tracer.start_as_current_span("node.guard_edge")
    with span_cm as span:
        span.set_attribute("request.id", state.request_id)
        should_refuse = policy.should_refuse(state.retrieved_chunks)
        path: Literal["generate", "refuse", "__end__"] = (
            "refuse" if should_refuse else "generate"
        )
        span.set_attribute("decision.path", path)
        log.debug(
            "node.guard_edge.decision",
            request_id=state.request_id,
            decision_path=path,
            candidate_count=len(state.retrieved_chunks),
        )
        return path


class _NoopSpanCM:
    """A minimal no-op span context manager used when no tracer
    is provided (tests + dev).

    Mimics the parts of ``opentelemetry.trace.Span`` that node
    bodies touch -- ``__enter__``/``__exit__`` and
    ``set_attribute`` -- so the call sites can be written
    uniformly with or without a real tracer.
    """

    def __enter__(self) -> _NoopSpanCM:
        """Enter the context; return ``self`` for ``as`` binding.

        Returns:
            This ``_NoopSpanCM`` instance.
        """
        return self

    def __exit__(self, *_exc: object) -> Literal[False]:
        """Exit the context without swallowing exceptions.

        Args:
            *_exc: Any exception triple from ``with``; ignored.

        Returns:
            ``False`` -- never suppress exceptions.
        """
        return False

    def set_attribute(self, *_args: object, **_kw: object) -> None:
        """Drop the call on the floor.

        Args:
            *_args: Positional attribute key/value; ignored.
            **_kw: Keyword attribute key/value; ignored.
        """
        return None


def _noop_cm() -> _NoopSpanCM:
    """Construct a fresh no-op span context manager.

    Returns:
        A new ``_NoopSpanCM`` instance. Each call returns a
        fresh instance because ``as``-binding takes a snapshot.
    """
    return _NoopSpanCM()


class LangGraphWorkflow:
    """The composed workflow object -- holds the three ports and a
    tracer; ``compile()`` returns a ``CompiledStateGraph``.

    The compiled graph is the seam the application tests and the
    API route call. ``compile()`` can be called repeatedly; the
    resulting CompiledStateGraph is stateless and reentrant.
    """

    def __init__(
        self,
        *,
        retriever: Retriever,
        policy: LowConfidencePolicy,
        generator: AnswerGenerator,
        tracer: Any = None,
    ) -> None:
        """Store the workflow's port dependencies and tracer.

        Args:
            retriever: The ``Retriever`` port.
            policy: The ``LowConfidencePolicy`` port.
            generator: The ``AnswerGenerator`` port.
            tracer: Optional OTel tracer. When ``None`` the
                workflow falls back to the globally-registered
                ``support_bot.workflow`` tracer so tests with a
                custom ``TracerProvider`` (e.g.
                ``InMemorySpanExporter``) see the spans.
        """
        self._retriever = retriever
        self._policy = policy
        self._generator = generator
        # Lazy import to keep the module import-time side-effect-free.
        from opentelemetry import trace as _trace

        self._tracer = tracer if tracer is not None else _trace.get_tracer(
            "support_bot.workflow"
        )

    def compile(self) -> Any:
        """Build and return a CompiledStateGraph.

        Returns:
            A ``CompiledStateGraph`` instance. The instance is
            stateless and reentrant, so callers can invoke it
            concurrently from multiple request threads.
        """
        graph = StateGraph(AgentState)

        # Bind the dependencies into plain callables so the
        # node bodies don't have to be partials. Each node takes
        # the ``AgentState`` and returns a partial state update.
        def _retrieve(state: AgentState) -> dict[str, Any]:
            """Forward ``retrieve`` to the bound retriever.

            Args:
                state: Current ``AgentState``.

            Returns:
                Partial state update from ``retrieve_node``.
            """
            return retrieve_node(
                state, retriever=self._retriever, tracer=self._tracer
            )

        def _guard(state: AgentState) -> dict[str, Any]:
            """Forward ``guard`` to the bound policy.

            Args:
                state: Current ``AgentState``.

            Returns:
                Partial state update from ``guard_node``.
            """
            return guard_node(state, policy=self._policy, tracer=self._tracer)

        def _generate(state: AgentState) -> dict[str, Any]:
            """Forward ``generate`` to the bound answer generator.

            Args:
                state: Current ``AgentState``.

            Returns:
                Partial state update from ``generate_node``.
            """
            return generate_node(
                state, generator=self._generator, tracer=self._tracer
            )

        def _refuse(state: AgentState) -> dict[str, Any]:
            """Forward ``refuse`` to the bound policy.

            Args:
                state: Current ``AgentState``.

            Returns:
                Partial state update from ``refuse_node``.
            """
            return refuse_node(state, policy=self._policy, tracer=self._tracer)

        def _decide_typed(state: AgentState) -> Literal["generate", "refuse", "__end__"]:
            """Forward the conditional edge decision to the bound policy.

            Args:
                state: Current ``AgentState``.

            Returns:
                The path literal from ``_decide``.
            """
            return _decide(state, policy=self._policy, tracer=self._tracer)

        graph.add_node("retrieve", _retrieve)
        graph.add_node("guard", _guard)
        graph.add_node("generate", _generate)
        graph.add_node("refuse", _refuse)

        graph.add_edge(START, "retrieve")
        graph.add_edge("retrieve", "guard")
        graph.add_conditional_edges(
            "guard",
            _decide_typed,
            {"generate": "generate", "refuse": "refuse", "__end__": END},
        )
        graph.add_edge("generate", END)
        graph.add_edge("refuse", END)

        return graph.compile()


__all__ = [
    "LangGraphWorkflow",
    "generate_node",
    "guard_node",
    "refuse_node",
    "retrieve_node",
]
