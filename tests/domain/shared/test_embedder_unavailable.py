"""TDD red: EmbedderUnavailable exception must exist on domain.

Per AGENTS.md 8 (error map) and WP02 T013, the EmbedderUnavailable
exception is referenced in the AnsweringService re-raise list and
the ErrorResponseMapper 502 mapping. WP01 did not create the
class (it was deferred to WP04 per v1 review Issue 9). WP02
introduces it because the application layer needs it now.
"""
from __future__ import annotations

import pytest

from support_bot.domain.shared.errors import (
    ConfigurationError,
    DomainError,
    EmbedderUnavailable,
    LLMUnavailable,
)


class TestEmbedderUnavailable:
    """EmbedderUnavailable is a DomainError subclass."""

    def test_is_domain_error_subclass(self) -> None:
        assert issubclass(EmbedderUnavailable, DomainError)

    def test_carries_reason_payload(self) -> None:
        exc = EmbedderUnavailable("connection refused")
        assert exc.reason == "connection refused"
        assert "connection refused" in str(exc)

    def test_can_be_caught_as_domain_error(self) -> None:
        with pytest.raises(DomainError):
            raise EmbedderUnavailable("upstream timeout")


class TestEmbedderUnavailableIsDistinctFromLLMUnavailable:
    """EmbedderUnavailable must NOT equal LLMUnavailable."""

    def test_different_classes(self) -> None:
        assert EmbedderUnavailable is not LLMUnavailable

    def test_handler_can_route_each_independently(self) -> None:
        # A handler that catches EmbedderUnavailable must not
        # also catch LLMUnavailable -- they map to different
        # HTTP statuses per AGENTS 8.
        try:
            raise LLMUnavailable("rate limited")
        except EmbedderUnavailable:
            pytest.fail("LLMUnavailable must not be caught as EmbedderUnavailable")
        except LLMUnavailable:
            pass

    def test_configuration_error_still_present(self) -> None:
        # Ensure the new exception did not collide with existing
        # exception module exports.
        assert isinstance(ConfigurationError("OPENAI_API_KEY"), DomainError)
