"""HTML boilerplate-stripping ``PageCleaner`` adapter.

Per WP03 T022.

The cleaner receives a `SourcePage.raw_html` string and returns a
`CleanedPage` carrying the plain-text body and a count of the
boilerplate elements that were removed. When the resulting text
is shorter than the configured minimum length it raises
`SourcePageGarbage` so the ingestion Job can exit non-zero
without writing to the vector store (M2).

Design choices
--------------

The cleaner uses ``beautifulsoup4`` with a hand-picked set of
drop selectors — the assignment's example page is plain HTML with
nav / footer / header / aside / cookie banners / script / style
tags. The heuristic is intentionally conservative: we drop the
known boilerplate elements but otherwise preserve the page's
text content and ordering. A more aggressive approach (CSS
selectors keyed to specific sites) would couple the cleaner to a
specific source URL and is out of scope for the assignment.

The minimum-text-length gate lives in the cleaner (not the
``PreEmbedValidator``) so the failure-injection path runs even
when the cleaner is called directly from a test — the validator
serves as a defence-in-depth check at the application-layer
boundary.
"""
from __future__ import annotations

import re
import time

import structlog
from bs4 import BeautifulSoup

from support_bot.domain.ingestion.entities import CleanedPage
from support_bot.domain.shared.errors import SourcePageGarbage

_log = structlog.get_logger(__name__)


# Tag and selector set from the WP03 T022 spec. Compiled once at
# import time so we don't pay the cost of regex compilation on
# every call. Order is irrelevant — BeautifulSoup's ``decompose``
# is idempotent.
_DROP_TAGS: tuple[str, ...] = (
    "nav",
    "footer",
    "header",
    "aside",
    "script",
    "style",
    "noscript",
)

_DROP_SELECTORS: tuple[str, ...] = (
    '[role="banner"]',
    '[role="navigation"]',
    '[aria-label*="cookie" i]',
    '[class*="cookie" i]',
    '[id*="cookie" i]',
)

_WHITESPACE_RE = re.compile(r"[ \t]+")
_NEWLINE_RE = re.compile(r"\n+")


class BoilerplatePageCleaner:
    """``PageCleaner`` adapter stripping boilerplate via BeautifulSoup.

    Attributes:
        min_text_length: Minimum acceptable length of the cleaned
            text. Pages shorter than this raise
            ``SourcePageGarbage`` (M2).
    """

    def __init__(self, *, min_text_length: int = 100) -> None:
        """Initialise the cleaner.

        Args:
            min_text_length: Minimum acceptable length of the
                cleaned text. Pages shorter than this raise
                ``SourcePageGarbage``.
        """
        self.min_text_length: int = min_text_length

    def clean(self, html: str) -> CleanedPage:
        """Strip boilerplate from ``html`` and return a ``CleanedPage``.

        Args:
            html: The raw HTML body from ``SourcePage.raw_html``.

        Returns:
            A ``CleanedPage`` carrying the plain-text body and
            the count of removed boilerplate elements.

        Raises:
            SourcePageGarbage: When the cleaned text is shorter
                than ``min_text_length`` (M2).
        """
        from opentelemetry import trace  # lazy: SDK-free at import time

        tracer = trace.get_tracer("support_bot.adapter.page_cleaner")
        with tracer.start_as_current_span("adapter.page_cleaner.clean") as span:
            span.set_attribute("cleaner.min_text_length", self.min_text_length)
            _log.debug(
                "adapter.call.start",
                adapter="BoilerplatePageCleaner",
                operation="clean",
                html_bytes=len(html),
                min_text_length=self.min_text_length,
            )
            started = time.monotonic()
            soup = BeautifulSoup(html, "html.parser")

            removed_count = 0
            for tag_name in _DROP_TAGS:
                for element in soup.find_all(tag_name):
                    element.decompose()
                    removed_count += 1

            for selector in _DROP_SELECTORS:
                for element in soup.select(selector):
                    element.decompose()
                    removed_count += 1

            text = soup.get_text(separator="\n")
            text = _WHITESPACE_RE.sub(" ", text)
            text = _NEWLINE_RE.sub("\n", text).strip()

            elapsed_ms = (time.monotonic() - started) * 1000.0
            span.set_attribute("cleaner.removed_boilerplate_count", removed_count)
            span.set_attribute("cleaner.text_length", len(text))

            if len(text) < self.min_text_length:
                span.set_attribute("error.type", "SourcePageGarbage.short_text")
                _log.info(
                    "adapter.call.ok",
                    adapter="BoilerplatePageCleaner",
                    operation="clean",
                    outcome="short_text",
                    cleaned_length=len(text),
                    min_cleaned_length=self.min_text_length,
                    latency_ms=elapsed_ms,
                )
                raise SourcePageGarbage(
                    f"cleaned text shorter than {self.min_text_length} chars"
                )

            _log.info(
                "adapter.call.ok",
                adapter="BoilerplatePageCleaner",
                operation="clean",
                outcome="ok",
                cleaned_length=len(text),
                removed_boilerplate_count=removed_count,
                latency_ms=elapsed_ms,
            )
            return CleanedPage(
                text=text,
                removed_boilerplate_count=removed_count,
            )


__all__ = ["BoilerplatePageCleaner"]
