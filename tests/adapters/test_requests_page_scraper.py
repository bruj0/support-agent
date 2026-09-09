"""TDD red tests for ``adapters.http_source.RequestsPageScraper``.

Per WP03 T021.

The adapter wraps ``requests.get`` with a ``User-Agent`` header
and translates non-2xx / timeout / empty-body outcomes into the
typed ``SourcePageUnreachable`` / ``SourcePageGarbage`` exceptions
declared on the ``PageScraper`` port.
"""
from __future__ import annotations

import pytest
import responses

from support_bot.adapters.http_source import RequestsPageScraper
from support_bot.domain.shared.errors import SourcePageUnreachable

URL = "https://example.com/help"
USER_AGENT = "support-bot/1.0"


@responses.activate
def test_fetch_returns_source_page_on_2xx() -> None:
    """A 200 with a non-empty body returns a `SourcePage` with that body."""
    body = "<html><body><h1>Help</h1></body></html>"
    responses.add(responses.GET, URL, body=body, status=200)
    scraper = RequestsPageScraper()
    page = scraper.fetch(URL)
    assert str(page.url) == URL
    assert page.raw_html == body


@responses.activate
def test_fetch_sends_user_agent_header() -> None:
    """The configured `User-Agent` is sent on every request."""
    body = "<html>x</html>"
    responses.add(responses.GET, URL, body=body, status=200)
    scraper = RequestsPageScraper(user_agent=USER_AGENT)
    scraper.fetch(URL)
    sent = responses.calls[0].request
    assert sent.headers["User-Agent"] == USER_AGENT


@responses.activate
def test_fetch_raises_source_page_unreachable_on_404() -> None:
    """A 404 raises `SourcePageUnreachable(url, "404")."""
    responses.add(responses.GET, URL, body="not found", status=404)
    scraper = RequestsPageScraper()
    with pytest.raises(SourcePageUnreachable) as exc:
        scraper.fetch(URL)
    assert exc.value.url == URL
    assert exc.value.reason == "404"


@responses.activate
def test_fetch_raises_source_page_unreachable_on_500() -> None:
    """A 500 raises `SourcePageUnreachable(url, "500")."""
    responses.add(responses.GET, URL, body="oops", status=500)
    scraper = RequestsPageScraper()
    with pytest.raises(SourcePageUnreachable) as exc:
        scraper.fetch(URL)
    assert exc.value.url == URL
    assert exc.value.reason == "500"


@responses.activate
def test_fetch_raises_source_page_unreachable_on_empty_body() -> None:
    """An empty body raises `SourcePageUnreachable(url, "empty")."""
    responses.add(responses.GET, URL, body="", status=200)
    scraper = RequestsPageScraper()
    with pytest.raises(SourcePageUnreachable) as exc:
        scraper.fetch(URL)
    assert exc.value.url == URL
    assert exc.value.reason == "empty"


@responses.activate
def test_fetch_raises_source_page_unreachable_on_timeout() -> None:
    """A ``requests`` timeout raises `SourcePageUnreachable(url, "timeout")`."""
    import requests as _requests

    def _raise_timeout(url: str, **_: object) -> _requests.Response:
        raise _requests.exceptions.Timeout("timed out")

    responses.add_callback(responses.GET, URL, callback=_raise_timeout)
    scraper = RequestsPageScraper(timeout_seconds=0.1)
    with pytest.raises(SourcePageUnreachable) as exc:
        scraper.fetch(URL)
    assert exc.value.url == URL
    assert exc.value.reason == "timeout"


def test_constructor_defaults_are_sensible() -> None:
    """Defaults: timeout=10s, user_agent='support-bot/1.0'."""
    scraper = RequestsPageScraper()
    assert scraper.timeout_seconds == pytest.approx(10.0)
    assert scraper.user_agent.startswith("support-bot")
