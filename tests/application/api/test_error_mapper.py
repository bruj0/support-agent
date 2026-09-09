"""TDD red: ErrorResponseMapper.

Per AGENTS.md 8 + WP02 T014:

- ``VectorStoreUnavailable`` -> 503 ``{"detail": "vector store unavailable", ...}``
- ``LLMUnavailable`` -> 502 ``{"detail": "answer generation unavailable", ...}``
- ``EmbedderUnavailable`` -> 502 ``{"detail": "embedding unavailable", ...}``
- ``ConfigurationError`` -> 503 ``{"detail": "service not configured", ...}``
- ``pydantic.ValidationError`` -> 422 ``{"detail": "invalid request", "errors": [...], ...}``
- any other ``DomainError`` -> 500 ``{"detail": "internal error", ...}``

Every body string passes through ``SecretScrubber`` before being
written.
"""
from __future__ import annotations

import re


class _StubSecretScrubber:
    """Minimal in-test stub used while SecretScrubber (production
    class) lands in WP02. Mirrors the production contract: any
    secret-shaped substring is replaced with [REDACTED].
    """

    _PAT = re.compile(r"sk-[A-Za-z0-9]{32,}|sk-ant-[A-Za-z0-9-]{32,}")

    def scrub(self, value: str) -> str:
        return self._PAT.sub("[REDACTED]", value)

    def __call__(self, _logger, _method, event_dict):  # type: ignore[no-untyped-def]
        for k, v in list(event_dict.items()):
            if isinstance(v, str):
                event_dict[k] = self.scrub(v)
        return event_dict


StubSecretScrubber = _StubSecretScrubber


def test_error_response_mapper_module_exists() -> None:
    from support_bot.application.api.error_mapper import ErrorResponseMapper

    assert ErrorResponseMapper is not None


def test_error_mapper_routes_vector_store_unavailable_to_503() -> None:
    from support_bot.application.api.error_mapper import ErrorResponseMapper
    from support_bot.domain.shared.errors import VectorStoreUnavailable

    mapper = ErrorResponseMapper(secret_scrubber=StubSecretScrubber())
    response = mapper.to_response(
        VectorStoreUnavailable("down"), request_id="rid"
    )
    assert response.status_code == 503
    body = response.body.decode()
    assert "vector store unavailable" in body
    assert "rid" in body
    # Raw exception message must NOT leak into the body (M5).
    assert "down" not in body


def test_error_mapper_routes_llm_unavailable_to_502() -> None:
    from support_bot.application.api.error_mapper import ErrorResponseMapper
    from support_bot.domain.shared.errors import LLMUnavailable

    mapper = ErrorResponseMapper(secret_scrubber=StubSecretScrubber())
    response = mapper.to_response(
        LLMUnavailable("rate limited"), request_id="rid"
    )
    assert response.status_code == 502
    body = response.body.decode()
    assert "answer generation unavailable" in body
    assert "rate limited" not in body  # M5


def test_error_mapper_routes_embedder_unavailable_to_502() -> None:
    from support_bot.application.api.error_mapper import ErrorResponseMapper
    from support_bot.domain.shared.errors import EmbedderUnavailable

    mapper = ErrorResponseMapper(secret_scrubber=StubSecretScrubber())
    response = mapper.to_response(
        EmbedderUnavailable("upstream timeout"), request_id="rid"
    )
    assert response.status_code == 502
    body = response.body.decode()
    assert "embedding unavailable" in body
    assert "upstream timeout" not in body


def test_error_mapper_routes_configuration_error_to_503() -> None:
    from support_bot.application.api.error_mapper import ErrorResponseMapper
    from support_bot.domain.shared.errors import ConfigurationError

    mapper = ErrorResponseMapper(secret_scrubber=StubSecretScrubber())
    response = mapper.to_response(
        ConfigurationError("OPENAI_API_KEY"), request_id="rid"
    )
    assert response.status_code == 503
    body = response.body.decode()
    assert "service not configured" in body
    # The missing-key name must NOT be echoed (M5: secrets).
    assert "OPENAI_API_KEY" not in body


def test_error_mapper_routes_validation_error_to_422() -> None:
    from pydantic import BaseModel, Field

    from support_bot.application.api.error_mapper import ErrorResponseMapper

    class AskReq(BaseModel):
        question: str = Field(min_length=1)

    mapper = ErrorResponseMapper(secret_scrubber=StubSecretScrubber())
    try:
        AskReq(question="")
    except Exception as exc:
        response = mapper.to_response(exc, request_id="rid")
    assert response.status_code == 422
    body = response.body.decode()
    assert "invalid request" in body


def test_error_mapper_routes_other_domain_error_to_500() -> None:
    from support_bot.application.api.error_mapper import ErrorResponseMapper
    from support_bot.domain.shared.errors import DomainError

    class Weird(DomainError):
        pass

    mapper = ErrorResponseMapper(secret_scrubber=StubSecretScrubber())
    response = mapper.to_response(Weird("oh no"), request_id="rid")
    assert response.status_code == 500
    body = response.body.decode()
    assert "internal error" in body
    assert "oh no" not in body
