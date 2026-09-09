"""TDD red: SecretScrubber utility (AGENTS.md 7.1 + WP02 T018).

The SecretScrubber:

- replaces OpenAI keys (``sk-`` followed by 32+ alphanumeric chars)
  with ``[REDACTED]``
- replaces Anthropic keys (``sk-ant-`` followed by 32+ chars)
- replaces configured env-var substrings (the value of
  ``OPENAI_API_KEY``, ``EMBEDDING_API_KEY``, ``CHROMA_URL``)
- is exportable as a ``structlog`` processor (callable) so it
  plugs into the processor chain
- is exportable as an OTel span-attribute filter so scrubbed
  attributes never leave the process
"""
from __future__ import annotations


def test_secret_scrubber_module_exists() -> None:
    from support_bot.adapters.secret_scrubber import SecretScrubber

    assert SecretScrubber is not None


def test_scrubs_openai_key() -> None:
    from support_bot.adapters.secret_scrubber import SecretScrubber

    scrubber = SecretScrubber()
    raw = "Authorization: Bearer sk-abcdefghijklmnopqrstuvwxyz0123456789"
    out = scrubber.scrub(raw)
    assert "sk-abcdefghijklmnopqrstuvwxyz0123456789" not in out
    assert "[REDACTED]" in out


def test_scrubs_anthropic_key() -> None:
    from support_bot.adapters.secret_scrubber import SecretScrubber

    scrubber = SecretScrubber()
    raw = "x-anthropic: sk-ant-aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789-AB"
    out = scrubber.scrub(raw)
    assert "sk-ant-aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789-AB" not in out
    assert "[REDACTED]" in out


def test_does_not_scrub_short_openaish() -> None:
    """The OpenAI regex requires 32+ chars after ``sk-``; short
    tokens must NOT be scrubbed."""
    from support_bot.adapters.secret_scrubber import SecretScrubber

    scrubber = SecretScrubber()
    raw = "sk-shortkey"  # too short
    out = scrubber.scrub(raw)
    assert out == raw


def test_scrubs_configured_env_substrings() -> None:
    """Configured substrings (e.g. ``OPENAI_API_KEY`` value) get
    replaced too, even if they do not match the OpenAI regex."""
    from support_bot.adapters.secret_scrubber import SecretScrubber

    scrubber = SecretScrubber(
        extra_substrings=("SECRET_TOKEN_XYZ",)
    )
    raw = "headers: SECRET_TOKEN_XYZ"
    out = scrubber.scrub(raw)
    assert "SECRET_TOKEN_XYZ" not in out
    assert "[REDACTED]" in out


def test_secret_scrubber_callable_for_structlog() -> None:
    """``SecretScrubber`` must be usable directly as a structlog
    processor: ``structlog.processors.JSONRenderer`` consumes
    processors that accept ``(logger, method_name, event_dict)``
    and return the (possibly mutated) ``event_dict``."""
    from support_bot.adapters.secret_scrubber import SecretScrubber

    scrubber = SecretScrubber()
    event_dict = {
        "event": "answer",
        "token": "sk-abcdefghijklmnopqrstuvwxyz0123456789",
        "request_id": "r",
    }
    out = scrubber(None, "info", event_dict)  # type: ignore[arg-type]
    assert out["token"] == "[REDACTED]"
    # The scrubber mutates and returns the dict (structlog
    # processor convention).
    assert out is event_dict or out["event"] == "answer"


def test_secret_scrubber_otel_span_attribute_filter() -> None:
    """``SecretScrubber.as_span_filter`` returns a function
    suitable for ``TracerProvider``'s span attribute filtering
    that scrubs incoming attribute values."""
    from support_bot.adapters.secret_scrubber import SecretScrubber

    scrubber = SecretScrubber()
    filt = scrubber.as_span_filter()
    # The filter must redact the secret substring while keeping
    # the surrounding context (e.g. ``Bearer <key>`` becomes
    # ``Bearer [REDACTED]``).
    out = filt(
        "authorization", "Bearer sk-abcdefghijklmnopqrstuvwxyz0123456789"
    )
    assert "sk-abcdefghijklmnopqrstuvwxyz0123456789" not in out
    assert "[REDACTED]" in out
    # Non-secret attributes pass through unchanged.
    assert filt("route", "POST /ask") == "POST /ask"
