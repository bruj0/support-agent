"""Structured JSON logger configuration.

Per AGENTS.md 6.5 + WP02 T018.

``configure_logging(level)`` builds the processor chain:

  1. ``structlog.contextvars.merge_contextvars`` -- picks up
     ``request_id`` (set by ``RequestIdMiddleware``) and
     ``trace_id`` / ``span_id`` (set by the OTel logging
     instrumentation).
  2. ``structlog.processors.add_log_level``.
  3. ``structlog.processors.TimeStamper(fmt="iso", utc=True)``.
  4. ``SecretScrubber()`` -- replaces API keys with ``[REDACTED]``.
  5. ``structlog.processors.JSONRenderer()`` -- final JSON line.

Idempotent: calling twice in the same process replaces the
chain with the same processors.

The ``wrapper_class`` is a structlog filtering bound logger at
the requested level. Production code uses the configured logger;
tests can either reuse it or install their own writer.
"""
from __future__ import annotations

import logging

import structlog

from .secret_scrubber import SecretScrubber


def configure_logging(level: str = "INFO") -> None:
    """Install the canonical structlog processor chain.

    Called once at process start by ``composition/api_app.py``
    and ``composition/ingestion_main.py``. Subsequent calls
    replace the chain.
    """
    numeric_level = logging.getLevelName(level.upper())
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO

    # ``structlog.stdlib.LoggerFactory`` wraps a stdlib logger;
    # the stdlib logging level is set so the wrapper respects
    # ``level``. ``structlog.stdlib.render_to_logging_args``
    # converts the kwargs into a single message + ``extra``
    # payload so stdlib handlers (and the OTel logging
    # instrumentation) see them.
    logging.basicConfig(
        level=numeric_level,
        format="%(message)s",
        force=True,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            SecretScrubber(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


__all__ = ["configure_logging"]
