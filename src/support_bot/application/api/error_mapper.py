"""``ErrorResponseMapper`` -- typed domain exception -> HTTP.

Per AGENTS.md 8 + WP02 T014.

The mapper dispatches on the **concrete** exception class:

+---------------------------------+--------+--------------------------------+
| Exception                       | Status | Body ``detail``                |
+=================================+========+================================+
| ``VectorStoreUnavailable``      |   503  | "vector store unavailable"     |
+---------------------------------+--------+--------------------------------+
| ``LLMUnavailable``              |   502  | "answer generation unavailable"|
+---------------------------------+--------+--------------------------------+
| ``EmbedderUnavailable``         |   502  | "embedding unavailable"        |
+---------------------------------+--------+--------------------------------+
| ``ConfigurationError``          |   503  | "service not configured"       |
+---------------------------------+--------+--------------------------------+
| ``pydantic.ValidationError``    |   422  | "invalid request" + ``errors`` |
+---------------------------------+--------+--------------------------------+
| any other ``DomainError``       |   500  | "internal error"               |
+---------------------------------+--------+--------------------------------+

Every string that ends up in the response body or in any log
line passes through the configured ``SecretScrubber`` before
being placed. Raw exception messages are never echoed back to
the caller (M5).
"""
from __future__ import annotations

from typing import Any, Protocol

from fastapi.responses import JSONResponse
from pydantic import ValidationError

from support_bot.domain.shared.errors import (
    ConfigurationError,
    DomainError,
    EmbedderUnavailable,
    LLMUnavailable,
    VectorStoreUnavailable,
)


class SecretScrubberLike(Protocol):
    """Minimum surface needed by the mapper."""

    def scrub(self, value: str) -> str:
        """Replace any secret-shaped substring with ``[REDACTED]``.

        Args:
            value: The raw string to scrub.

        Returns:
            The scrubbed string with secrets replaced.
        """
        ...


class ErrorResponseMapper:
    """Translate a domain exception into a scrubbed HTTP response.

    Args:
        secret_scrubber: An object exposing ``scrub(value)``.
            Production wires the real
            ``adapters.secret_scrubber.SecretScrubber``; tests
            use a stub that matches the same Protocol.
    """

    def __init__(self, *, secret_scrubber: SecretScrubberLike) -> None:
        self._scrubber = secret_scrubber

    def to_response(
        self,
        exc: BaseException,
        *,
        request_id: str,
    ) -> JSONResponse:
        """Return the JSONResponse for ``exc``.

        Args:
            exc: The exception raised by the use case or by
                Pydantic input validation. Must be either a
                ``DomainError`` subclass or a ``ValidationError``.
            request_id: The propagated ``X-Request-Id`` for the
                request that produced the error.
        """
        scrub = self._scrubber.scrub
        rid = scrub(request_id)

        # Order matters: most-specific first.
        if isinstance(exc, VectorStoreUnavailable):
            body: dict[str, Any] = {
                "detail": scrub("vector store unavailable"),
                "request_id": rid,
            }
            return JSONResponse(status_code=503, content=body)

        if isinstance(exc, LLMUnavailable):
            body = {
                "detail": scrub("answer generation unavailable"),
                "request_id": rid,
            }
            return JSONResponse(status_code=502, content=body)

        if isinstance(exc, EmbedderUnavailable):
            body = {
                "detail": scrub("embedding unavailable"),
                "request_id": rid,
            }
            return JSONResponse(status_code=502, content=body)

        if isinstance(exc, ConfigurationError):
            body = {
                "detail": scrub("service not configured"),
                "request_id": rid,
            }
            return JSONResponse(status_code=503, content=body)

        if isinstance(exc, ValidationError):
            errors_payload: list[dict[str, Any]] = [
                {
                    "loc": list(err.get("loc", ())),
                    "msg": scrub(str(err.get("msg", ""))),
                    "type": scrub(str(err.get("type", ""))),
                }
                for err in exc.errors()
            ]
            body = {
                "detail": scrub("invalid request"),
                "request_id": rid,
                "errors": errors_payload,
            }
            return JSONResponse(status_code=422, content=body)

        if isinstance(exc, DomainError):
            body = {"detail": scrub("internal error"), "request_id": rid}
            return JSONResponse(status_code=500, content=body)

        # Anything else is treated as an internal error too.
        body = {"detail": scrub("internal error"), "request_id": rid}
        return JSONResponse(status_code=500, content=body)


__all__ = ["ErrorResponseMapper", "SecretScrubberLike"]
