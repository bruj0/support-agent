"""TDD red: AnsweringService.

Per AGENTS.md 6.3 + WP02 T013:

- ``AnsweringService.answer(question, *, request_id)`` opens a
  top-level span, threads request_id into AgentState, and
  re-raises typed exceptions (``VectorStoreUnavailable``,
  ``EmbedderUnavailable``, ``LLMUnavailable``) so the API error
  mapper can map them. No wrapping.
- The service emits DEBUG/INFO logs with question.text_hash,
  latency_ms, decision_path, request_id.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging


def test_answering_service_module_exists() -> None:
    from support_bot.application.answering.answering_service import (
        AnsweringService,
    )

    assert AnsweringService is not None


def test_answering_service_threads_request_id_into_state() -> None:
    from support_bot.application.answering.answering_service import (
        AnsweringService,
    )
    from support_bot.domain.answering.entities import Question, RetrievedChunk
    from tests.fakes.answering.answer_generator import FakeAnswerGenerator
    from tests.fakes.answering.low_confidence_policy import StubLowConfidencePolicy
    from tests.fakes.answering.retriever import FakeRetriever

    retriever = FakeRetriever(
        retrieved_chunks=[
            RetrievedChunk(chunk_id="a" * 40, text="t", source_url="u", similarity=0.9)
        ]
    )
    policy = StubLowConfidencePolicy(should_refuse_return=False)
    generator = FakeAnswerGenerator(canned="ANS")

    svc = AnsweringService(
        retriever=retriever,
        policy=policy,
        generator=generator,
    )
    answer = svc.answer(
        Question(text="hi", request_id="rid"), request_id="rid"
    )
    assert answer.text == "ANS"
    assert answer.confidence == "high"
    assert answer.trace == ["retrieve", "guard", "generate"]


def test_answering_service_reraises_typed_exceptions() -> None:
    """The service must re-raise the same typed exception when a
    retriever / embedder / answerer fails -- no wrapping in a
    generic Exception, no swallowing."""
    from support_bot.application.answering.answering_service import (
        AnsweringService,
    )
    from support_bot.domain.answering.entities import Question, RetrievedChunk
    from support_bot.domain.shared.errors import (
        EmbedderUnavailable,
        LLMUnavailable,
        VectorStoreUnavailable,
    )
    from tests.fakes.answering.answer_generator import FakeAnswerGenerator
    from tests.fakes.answering.low_confidence_policy import StubLowConfidencePolicy
    from tests.fakes.answering.retriever import FakeRetriever

    # 1. VectorStoreUnavailable from the retriever
    svc = AnsweringService(
        retriever=FakeRetriever(fail_next=True),
        policy=StubLowConfidencePolicy(),
        generator=FakeAnswerGenerator(),
    )
    try:
        svc.answer(
            Question(text="q", request_id="rid"), request_id="rid"
        )
    except VectorStoreUnavailable as exc:
        assert exc.reason  # original payload preserved
    else:
        raise AssertionError("expected VectorStoreUnavailable")

    # 2. LLMUnavailable from the generator
    svc2 = AnsweringService(
        retriever=FakeRetriever(
            retrieved_chunks=[
                RetrievedChunk(chunk_id="a" * 40, text="t", source_url="u", similarity=0.9)
            ]
        ),
        policy=StubLowConfidencePolicy(should_refuse_return=False),
        generator=FakeAnswerGenerator(fail_next=True),
    )
    try:
        svc2.answer(
            Question(text="q", request_id="rid"), request_id="rid"
        )
    except LLMUnavailable as exc:
        assert exc.reason
    else:
        raise AssertionError("expected LLMUnavailable")

    # 3. EmbedderUnavailable is a distinct subclass of
    # DomainError -- the service does not collapse it into
    # LLMUnavailable.
    assert issubclass(EmbedderUnavailable, Exception)
    assert not issubclass(LLMUnavailable, EmbedderUnavailable)


def test_answering_service_emits_debug_log_with_text_hash() -> None:
    """The service DEBUG log must include question.text_hash
    (sha256 16-hex) and request_id; never raw question text.

    We pick a question text whose lowercase characters are unique
    relative to the other log fields (level, event names, etc.)
    so the substring check is meaningful.
    """
    import structlog

    from support_bot.application.answering.answering_service import (
        AnsweringService,
    )
    from support_bot.domain.answering.entities import Question, RetrievedChunk
    from tests.fakes.answering.answer_generator import FakeAnswerGenerator
    from tests.fakes.answering.low_confidence_policy import StubLowConfidencePolicy
    from tests.fakes.answering.retriever import FakeRetriever

    # A 32-char nonce that does NOT collide with any keyword we
    # expect to find in the log stream (e.g. "high", "level",
    # "request_id", "answer_text_hash", "node.generate.*").
    question_nonce = "zqxvutkmnopq1234zqxvutkmnopq5678"

    # Capture structlog output via a buffer.
    buf = io.StringIO()

    def _writer(_logger, _method, event_dict):  # type: ignore[no-untyped-def]
        buf.write(json.dumps(event_dict) + "\n")
        return event_dict

    # Configure with a writer that captures via a custom no-op
    # logger factory whose underlying logger accepts kwargs.
    class _KwargsLogger:
        def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            pass

        def debug(self, event, **kw) -> None:  # type: ignore[no-untyped-def]
            _writer(self, "debug", {"event": event, **kw})

        def info(self, event, **kw) -> None:  # type: ignore[no-untyped-def]
            _writer(self, "info", {"event": event, **kw})

        def warning(self, event, **kw) -> None:  # type: ignore[no-untyped-def]
            _writer(self, "warning", {"event": event, **kw})

        def error(self, event, **kw) -> None:  # type: ignore[no-untyped-def]
            _writer(self, "error", {"event": event, **kw})

    class _KwargsLoggerFactory:
        def __call__(self, *args, **kwargs) -> _KwargsLogger:  # type: ignore[no-untyped-def,override]
            return _KwargsLogger()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            _writer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        logger_factory=_KwargsLoggerFactory(),
    )

    svc = AnsweringService(
        retriever=FakeRetriever(
            retrieved_chunks=[
                RetrievedChunk(chunk_id="a" * 40, text="t", source_url="u", similarity=0.9)
            ]
        ),
        policy=StubLowConfidencePolicy(should_refuse_return=False),
        generator=FakeAnswerGenerator(),
    )
    svc.answer(Question(text=question_nonce, request_id="rid"), request_id="rid")

    captured = buf.getvalue()
    # The raw question text MUST NOT appear in any log line.
    assert question_nonce not in captured
    # The question text hash MUST appear at least once.
    expected_hash = hashlib.sha256(question_nonce.encode("utf-8")).hexdigest()[:16]
    assert expected_hash in captured
    # request_id MUST appear at least once.
    assert "rid" in captured
