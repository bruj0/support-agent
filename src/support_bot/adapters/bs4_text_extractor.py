"""``beautifulsoup4``-based HTML text extractor used as a pre-processor.

Per WP06 T053.

The ``Bs4TextExtractor`` is the *only* place the WP06 ingestion
pipeline uses ``beautifulsoup4``. It strips ``<script>``,
``<style>``, and ``<noscript>``, prefers ``<main>`` content when
present (otherwise falls back to body), collapses runs of blank
lines, and rejects short results as ``SourcePageGarbage``.

Design rationale
----------------
Per the WP06 design decision the analyzer is **LLM-only**: bs4 is
not used for FAQ/heading detection (that responsibility belongs
to the LLM). The extractor's job is just to reduce noise before
the LLM call so the structured-output prompt sees clean text and
the token budget is not burned on boilerplate.

The extractor is a pure function over HTML — no I/O, no
observability instrumentation, no request_id (it runs inside
the LLM analyzer span).
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag
from typing import cast

from support_bot.domain.shared.errors import SourcePageGarbage

_DROP_TAGS = ("script", "style", "noscript")

_BLANK_LINE_RUN = re.compile(r"\n{3,}")


class Bs4TextExtractor:
    """Strip noise from raw HTML and return plain text for the analyzer.

    Attributes:
        min_text_length: Minimum number of characters the result
            must contain. Results shorter than this raise
            ``SourcePageGarbage`` so the analyzer never sees
            effectively-empty input.
    """

    def __init__(self, *, min_text_length: int = 100) -> None:
        """Initialize the extractor.

        Args:
            min_text_length: Floor on the extracted text length.
                ``SourcePageGarbage`` is raised if the result
                is shorter. Default 100.
        """
        self.min_text_length: int = min_text_length

    def extract(self, html: str) -> str:
        """Extract clean text from ``html``.

        Args:
            html: The full HTML body returned by the scraper.

        Returns:
            A plain-text string with ``<script>``, ``<style>``,
            ``<noscript>`` removed and blank lines collapsed.

        Raises:
            SourcePageGarbage: If the result is shorter than
                ``self.min_text_length``.
        """
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(_DROP_TAGS):
            tag.decompose()
        main_tag = soup.find("main")
        body_tag = soup.body
        # ``soup`` is always a Tag at this point (we just built
        # it from a non-empty html string). ``or soup`` is the
        # runtime safety net for the degenerate empty-html case;
        # cast to ``Tag`` so mypy accepts ``.get_text``.
        if isinstance(main_tag, Tag):
            root: Tag = main_tag
        elif isinstance(body_tag, Tag):
            root = body_tag
        else:
            root = cast(Tag, soup)
        text = root.get_text(separator="\n")
        text = _BLANK_LINE_RUN.sub("\n\n", text).strip()
        if len(text) < self.min_text_length:
            raise SourcePageGarbage(
                reason=(
                    f"bs4_text_extractor produced {len(text)} chars "
                    f"< min_text_length {self.min_text_length}"
                ),
            )
        return text


__all__ = ["Bs4TextExtractor"]