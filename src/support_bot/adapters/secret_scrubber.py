"""Secret-scrubbing utility used by every error response, log line,
and OpenTelemetry span attribute.

Per AGENTS.md §7.1 + WP02 T018.

Three scrubbers, in priority order:

1. ``OpenAI`` keys: ``sk-`` followed by 32+ alphanumeric chars.
2. ``Anthropic`` keys: ``sk-ant-`` followed by 32+ chars (digits,
   letters, hyphen).
3. Configured substrings (default: the value of ``OPENAI_API_KEY``,
   ``EMBEDDING_API_KEY``, ``CHROMA_URL`` env vars when set, plus
   anything the caller passes via ``extra_substrings``).

Replacement is the literal string ``"[REDACTED]"``. The scrubber is
exposed two ways:

- ``SecretScrubber.scrub(s) -> str`` for direct use (the API error
  mapper calls this on every response body).
- ``SecretScrubber.__call__(logger, method_name, event_dict)``
  so it slots into a ``structlog`` processor chain.
- ``SecretScrubber.as_span_filter() -> Callable[[str, str], str]``
  returns a function suitable for an OpenTelemetry span
  attribute filter; the filter is called with
  ``(attribute_key, attribute_value)`` and returns the
  (possibly scrubbed) string.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

_OPENAI_RE = re.compile(r"sk-[A-Za-z0-9]{32,}")
_ANTHROPIC_RE = re.compile(r"sk-ant-[A-Za-z0-9-]{32,}")


def _default_extra_substrings() -> tuple[str, ...]:
    """Build the configured-substring set from env vars (when set).

    Only includes non-empty values, so an unset env var never
    matches the empty string.
    """
    import os

    out: list[str] = []
    for name in ("OPENAI_API_KEY", "EMBEDDING_API_KEY", "CHROMA_URL"):
        value = os.environ.get(name)
        if value:
            out.append(value)
    return tuple(out)


class SecretScrubber:
    """Scrubs API keys, Anthropic tokens, and configured substrings.

    Attributes:
        extra_substrings: A tuple of additional substrings to
            scrub (e.g. ``OPENAI_API_KEY`` value when known).
    """

    def __init__(
        self,
        *,
        extra_substrings: tuple[str, ...] | None = None,
    ) -> None:
        if extra_substrings is None:
            extra_substrings = _default_extra_substrings()
        self.extra_substrings: tuple[str, ...] = tuple(extra_substrings)

    def scrub(self, value: str) -> str:
        """Return ``value`` with every secret replaced by
        ``"[REDACTED]"``."""
        if not value:
            return value
        out = _OPENAI_RE.sub("[REDACTED]", value)
        out = _ANTHROPIC_RE.sub("[REDACTED]", out)
        for sub in self.extra_substrings:
            if sub and sub in out:
                out = out.replace(sub, "[REDACTED]")
        return out

    def __call__(
        self,
        _logger: Any,
        _method_name: str,
        event_dict: dict[str, Any],
    ) -> dict[str, Any]:
        """structlog processor: scrub every string value in the
        event dict. Mutates and returns the dict (structlog
        processor convention)."""
        for k, v in list(event_dict.items()):
            if isinstance(v, str):
                event_dict[k] = self.scrub(v)
        return event_dict

    def as_span_filter(self) -> Callable[[str, str], str]:
        """Return a function ``(attr_key, attr_value) -> str``
        suitable for use as an OpenTelemetry span attribute
        filter; the filter redacts any value that looks like a
        secret."""

        def _filter(attr_key: str, attr_value: str) -> str:
            # Only filter string values; non-string values
            # (numbers, bools, lists) pass through unchanged.
            if not isinstance(attr_value, str):
                return attr_value  # type: ignore[return-value]
            return self.scrub(attr_value)

        return _filter


__all__ = ["SecretScrubber"]
