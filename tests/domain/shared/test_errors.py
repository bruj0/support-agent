"""Tests for the shared domain exception hierarchy."""
from __future__ import annotations

from support_bot.domain.shared.errors import (
    ConfigurationError,
    DomainError,
    EmptyRetrieval,
    LLMUnavailable,
    SourcePageGarbage,
    SourcePageUnreachable,
    VectorStoreUnavailable,
)


class TestDomainErrorHierarchy:
    """Every domain exception inherits from `DomainError` and
    carries the right context."""

    def test_source_page_unreachable_carries_url_and_reason(self) -> None:
        exc = SourcePageUnreachable("https://x", "timeout")
        assert exc.url == "https://x"
        assert exc.reason == "timeout"
        assert "https://x" in str(exc)
        assert "timeout" in str(exc)
        assert isinstance(exc, DomainError)

    def test_source_page_garbage_carries_reason(self) -> None:
        exc = SourcePageGarbage("cleaned text empty")
        assert exc.reason == "cleaned text empty"
        assert isinstance(exc, DomainError)

    def test_vector_store_unavailable_carries_reason(self) -> None:
        exc = VectorStoreUnavailable("connection refused")
        assert exc.reason == "connection refused"
        assert isinstance(exc, DomainError)

    def test_llm_unavailable_carries_reason(self) -> None:
        exc = LLMUnavailable("rate limited")
        assert exc.reason == "rate limited"
        assert isinstance(exc, DomainError)

    def test_empty_retrieval_has_no_payload(self) -> None:
        exc = EmptyRetrieval()
        assert isinstance(exc, DomainError)

    def test_configuration_error_carries_name(self) -> None:
        exc = ConfigurationError("OPENAI_API_KEY")
        assert exc.name == "OPENAI_API_KEY"
        assert isinstance(exc, DomainError)

    def test_all_can_be_caught_as_domain_error(self) -> None:
        # A single handler can catch the base for logging.
        for exc in (
            SourcePageUnreachable("u", "r"),
            SourcePageGarbage("r"),
            VectorStoreUnavailable("r"),
            LLMUnavailable("r"),
            EmptyRetrieval(),
            ConfigurationError("n"),
        ):
            try:
                raise exc
            except DomainError as caught:
                assert caught is exc