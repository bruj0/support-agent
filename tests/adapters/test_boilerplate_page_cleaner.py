"""TDD red tests for ``adapters.cleaner.BoilerplatePageCleaner``.

Per WP03 T022.

The cleaner strips boilerplate from an HTML page using
``beautifulsoup4`` and returns plain text. When the result is
shorter than the configured minimum length it raises
``SourcePageGarbage`` so the ingestion Job can exit non-zero
without writing to the vector store (M2).
"""
from __future__ import annotations

import pytest

from support_bot.adapters.cleaner import BoilerplatePageCleaner
from support_bot.domain.shared.errors import SourcePageGarbage

URL = "https://example.com/help"


def _wrap(body: str) -> str:
    """Return a full HTML document wrapping ``body``."""
    return f"<html><head><title>x</title></head><body>{body}</body></html>"


def test_clean_strips_nav_tag() -> None:
    """`<nav>` is removed."""
    cleaner = BoilerplatePageCleaner(min_text_length=10)
    page = cleaner.clean(_wrap("<nav>menu</nav><p>real content</p>"))
    assert "menu" not in page.text
    assert "real content" in page.text


def test_clean_strips_footer_tag() -> None:
    """`<footer>` is removed."""
    cleaner = BoilerplatePageCleaner(min_text_length=10)
    page = cleaner.clean(_wrap("<footer>copyright 2026</footer><p>real content</p>"))
    assert "copyright" not in page.text
    assert "real content" in page.text


def test_clean_strips_header_tag() -> None:
    """`<header>` is removed."""
    cleaner = BoilerplatePageCleaner(min_text_length=10)
    page = cleaner.clean(_wrap("<header>site header</header><p>real content</p>"))
    assert "site header" not in page.text


def test_clean_strips_aside_tag() -> None:
    """`<aside>` is removed."""
    cleaner = BoilerplatePageCleaner(min_text_length=10)
    page = cleaner.clean(_wrap("<aside>sidebar</aside><p>real content</p>"))
    assert "sidebar" not in page.text


def test_clean_strips_cookie_banner() -> None:
    """Cookie banners matched by aria-label / class / id are removed."""
    cleaner = BoilerplatePageCleaner(min_text_length=10)
    html = _wrap(
        '<div aria-label="cookie consent">accept cookies</div>'
        '<div class="cookie-bar">accept cookies</div>'
        '<div id="cookie-banner">accept cookies</div>'
        "<p>real content</p>"
    )
    page = cleaner.clean(html)
    assert "accept cookies" not in page.text
    assert "real content" in page.text


def test_clean_strips_script_and_style() -> None:
    """`<script>` and `<style>` are removed."""
    cleaner = BoilerplatePageCleaner(min_text_length=10)
    html = _wrap(
        "<script>alert(1)</script><style>body{}</style><p>real content</p>"
    )
    page = cleaner.clean(html)
    assert "alert" not in page.text
    assert "body{}" not in page.text
    assert "real content" in page.text


def test_clean_preserves_paragraphs() -> None:
    """Paragraphs are joined with newlines, content is preserved."""
    cleaner = BoilerplatePageCleaner(min_text_length=10)
    html = _wrap("<p>first paragraph</p><p>second paragraph</p>")
    page = cleaner.clean(html)
    assert "first paragraph" in page.text
    assert "second paragraph" in page.text


def test_clean_records_removed_boilerplate_count() -> None:
    """`CleanedPage.removed_boilerplate_count` reflects what was dropped."""
    cleaner = BoilerplatePageCleaner(min_text_length=10)
    html = _wrap(
        "<nav>m</nav><footer>f</footer><header>h</header>"
        "<script>s</script><style>x</style>"
        "<p>real content</p>"
    )
    page = cleaner.clean(html)
    assert page.removed_boilerplate_count >= 4


def test_clean_raises_source_page_garbage_when_text_too_short() -> None:
    """When cleaned text is shorter than the minimum, raise `SourcePageGarbage`."""
    cleaner = BoilerplatePageCleaner(min_text_length=200)
    html = _wrap("<nav>m</nav><footer>f</footer>")
    with pytest.raises(SourcePageGarbage):
        cleaner.clean(html)


def test_clean_does_not_set_url() -> None:
    """The cleaner does not know the source URL; `CleanedPage.url` is `None`."""
    cleaner = BoilerplatePageCleaner(min_text_length=10)
    html = _wrap("<p>real content here</p>")
    page = cleaner.clean(html)
    assert page.url is None
