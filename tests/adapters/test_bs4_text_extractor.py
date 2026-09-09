"""TDD contract for ``adapters.bs4_text_extractor.Bs4TextExtractor``.

Per WP06 T053.

The extractor strips ``<script>``, ``<style>``, ``<noscript>``
before the LLM analyzer call. It prefers ``<main>`` content when
present and falls back to the body otherwise. Short results are
rejected as ``SourcePageGarbage`` so the analyzer never sees
empty input.
"""
from __future__ import annotations

import pytest

from support_bot.adapters.bs4_text_extractor import Bs4TextExtractor
from support_bot.domain.shared.errors import SourcePageGarbage


def _extractor(**kw) -> Bs4TextExtractor:
    """Test extractor with a low floor so fixture HTML passes.

    The production default (``min_text_length=100``) is verified
    separately in ``test_min_text_length_enforced``.
    """
    return Bs4TextExtractor(min_text_length=5, **kw)


def test_strips_script_style_noscript() -> None:
    """Inline scripts and styles must not appear in the output."""
    html = (
        "<html><head>"
        "<style>body { color: red; }</style>"
        "<script>alert('xss')</script>"
        "</head><body>"
        "<noscript>Please enable JS</noscript>"
        "<p>Visible content the extractor keeps</p>"
        "</body></html>"
    )
    out = _extractor().extract(html)
    assert "alert" not in out
    assert "color: red" not in out
    assert "Please enable JS" not in out
    assert "Visible content" in out


def test_prefers_main_when_present() -> None:
    """When ``<main>`` exists, the extractor uses it."""
    html = (
        "<html><body>"
        "<header>Header chrome the extractor drops</header>"
        "<main><p>Primary content the extractor keeps</p></main>"
        "<footer>Footer chrome the extractor drops</footer>"
        "</body></html>"
    )
    out = _extractor().extract(html)
    assert "Primary content" in out
    assert "Header chrome" not in out
    assert "Footer chrome" not in out


def test_falls_back_to_body_without_main() -> None:
    """Without ``<main>``, the extractor uses the full body."""
    html = (
        "<html><body>"
        "<p>Article one paragraph the extractor keeps</p>"
        "<p>Article two paragraph the extractor keeps</p>"
        "</body></html>"
    )
    out = _extractor().extract(html)
    assert "Article one" in out
    assert "Article two" in out


def test_collapse_blank_lines() -> None:
    """Runs of blank lines collapse to a single newline."""
    html = "<p>One paragraph the extractor keeps</p>\n\n\n\n<p>Two paragraph the extractor keeps</p>"
    out = _extractor().extract(html)
    assert "\n\n\n" not in out
    assert "One paragraph" in out and "Two paragraph" in out


def test_min_text_length_enforced() -> None:
    """Short results raise ``SourcePageGarbage``."""
    extractor = Bs4TextExtractor(min_text_length=100)
    with pytest.raises(SourcePageGarbage):
        extractor.extract("<p>tiny</p>")


def test_default_min_text_length_is_100() -> None:
    """The production default floor is 100 chars (matches WP03 cleaner)."""
    assert Bs4TextExtractor().min_text_length == 100


def test_custom_min_text_length() -> None:
    """``min_text_length`` is constructor-injected."""
    extractor = Bs4TextExtractor(min_text_length=5)
    out = extractor.extract("<p>five+</p>")
    assert "five+" in out


def test_returns_str() -> None:
    """``extract`` returns a plain ``str`` (not a Soup / Tag)."""
    out = _extractor().extract(
        "<html><body><p>hello world returns-str fixture the extractor keeps</p></body></html>"
    )
    assert isinstance(out, str)