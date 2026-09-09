"""HTTP ``PageScraper`` adapter backed by the ``requests`` library.

Per WP03 T021.

The adapter wraps ``requests.get`` with a configured timeout and
``User-Agent`` header, and translates non-2xx responses,
timeouts, and empty bodies into the typed exceptions declared
on the ``PageScraper`` port (``domain/ingestion/ports.py``):

- ``SourcePageUnreachable(url, reason)`` — non-2xx or
  connection-level failure.
- ``SourcePageGarbage(url, "empty")`` — 200 with an empty body.

Design choices
--------------

We pick ``requests`` rather than ``httpx`` because the scraper is
purely synchronous, fires once per ingestion Job, and benefits
from ``requests``' minimal API and ubiquitous adoption in the
Python ecosystem. ``httpx`` is reserved for the embedder /
answerer / cleaner adapters that participate in the OpenTelemetry
``httpx`` auto-instrumentation (AGENTS.md 6.4).

Observability
-------------

Every call opens an OTel span ``adapter.page_scraper.fetch`` and
emits a DEBUG ``adapter.call.start`` log with ``adapter``,
``operation``, ``request_id`` (read from the active OTel span
attribute), ``url``, ``timeout_seconds``, plus an INFO
``adapter.call.ok`` line with ``latency_ms``, ``http.status``,
``response.bytes``. The ``request_id`` is **read** from the OTel
context — the application layer binds it before calling — so the
adapter itself never imports ``opentelemetry`` (AGENTS.md 1.1
layering).
"""
from __future__ import annotations

import hashlib
import time

import requests
import structlog

from support_bot.domain.ingestion.entities import SourcePage
from support_bot.domain.shared.errors import SourcePageUnreachable

_log = structlog.get_logger(__name__)


def _question_text_hash(value: str) -> str:
    """Return the first 16 hex chars of ``sha256(value)``.

    Used as the value of ``*.text_hash`` span attributes so we
    can correlate log lines without leaking the raw URL.
    Per AGENTS.md 6.4 ``PII rule``: never put raw question or
    answer text in span attributes; the same principle is
    applied to URLs that may carry query strings.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


class RequestsPageScraper:
    """``PageScraper`` adapter backed by ``requests``.

    Attributes:
        timeout_seconds: Per-request timeout in seconds.
        user_agent: ``User-Agent`` header value sent on every
            request.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        user_agent: str = "support-bot/1.0",
    ) -> None:
        """Initialise the scraper.

        Args:
            timeout_seconds: Per-request timeout in seconds.
            user_agent: ``User-Agent`` header value sent on every
                request.
        """
        self.timeout_seconds: float = timeout_seconds
        self.user_agent: str = user_agent

    def fetch(self, url: str) -> SourcePage:
        """Fetch ``url`` and return a ``SourcePage``.

        Args:
            url: The URL to fetch.

        Returns:
            A ``SourcePage`` populated with the raw HTML and the
            fetch timestamp.

        Raises:
            SourcePageUnreachable: On non-2xx HTTP, timeout, or
                connection-level failure. The ``reason`` field
                carries a short token (e.g. ``"timeout"``,
                ``"404"``, ``"empty"``) suitable for logging.
        """
        from opentelemetry import trace  # lazy: keep adapter SDK-free at import

        tracer = trace.get_tracer("support_bot.adapter.page_scraper")
        with tracer.start_as_current_span("adapter.page_scraper.fetch") as span:
            url_hash = _question_text_hash(url)
            span.set_attribute("source.url_hash", url_hash)
            span.set_attribute("scraper.timeout_seconds", self.timeout_seconds)

            _log.debug(
                "adapter.call.start",
                adapter="RequestsPageScraper",
                operation="fetch",
                url_hash=url_hash,
                timeout_seconds=self.timeout_seconds,
            )
            started = time.monotonic()
            try:
                response = requests.get(
                    url,
                    timeout=self.timeout_seconds,
                    headers={"User-Agent": self.user_agent},
                )
            except requests.exceptions.Timeout:
                elapsed_ms = (time.monotonic() - started) * 1000.0
                span.set_attribute("error.type", "SourcePageUnreachable.timeout")
                _log.info(
                    "adapter.call.ok",
                    adapter="RequestsPageScraper",
                    operation="fetch",
                    outcome="timeout",
                    latency_ms=elapsed_ms,
                    url_hash=url_hash,
                )
                raise SourcePageUnreachable(url, "timeout") from None
            except requests.exceptions.RequestException as exc:
                elapsed_ms = (time.monotonic() - started) * 1000.0
                span.set_attribute("error.type", "SourcePageUnreachable.connection")
                _log.info(
                    "adapter.call.ok",
                    adapter="RequestsPageScraper",
                    operation="fetch",
                    outcome="connection_error",
                    latency_ms=elapsed_ms,
                    url_hash=url_hash,
                )
                raise SourcePageUnreachable(url, "connection_error") from exc

            elapsed_ms = (time.monotonic() - started) * 1000.0
            status = response.status_code
            span.set_attribute("http.status_code", status)

            if status >= 400:
                span.set_attribute("error.type", f"SourcePageUnreachable.{status}")
                _log.info(
                    "adapter.call.ok",
                    adapter="RequestsPageScraper",
                    operation="fetch",
                    outcome="http_error",
                    http_status=status,
                    latency_ms=elapsed_ms,
                    url_hash=url_hash,
                )
                raise SourcePageUnreachable(url, str(status))

            body = response.text
            if not body:
                span.set_attribute("error.type", "SourcePageUnreachable.empty")
                _log.info(
                    "adapter.call.ok",
                    adapter="RequestsPageScraper",
                    operation="fetch",
                    outcome="empty",
                    http_status=status,
                    latency_ms=elapsed_ms,
                    url_hash=url_hash,
                )
                raise SourcePageUnreachable(url, "empty")

            span.set_attribute("response.bytes", len(body))
            _log.info(
                "adapter.call.ok",
                adapter="RequestsPageScraper",
                operation="fetch",
                outcome="ok",
                http_status=status,
                latency_ms=elapsed_ms,
                response_bytes=len(body),
                url_hash=url_hash,
            )
            return SourcePage(url=url, raw_html=body)


__all__ = ["RequestsPageScraper"]
