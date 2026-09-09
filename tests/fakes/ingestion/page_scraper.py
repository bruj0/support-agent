"""In-memory `FakePageScraper` for unit and contract tests.

Not thread-safe; not async; no I/O. Backed by a configurable
mapping from URL to canned `SourcePage`. The `fail_next` flag
drives the next call into a `SourcePageUnreachable` raise so
WP03's failure-injection tests can exercise the M1 path.
"""
from __future__ import annotations

from support_bot.domain.ingestion.entities import SourcePage
from support_bot.domain.shared.errors import SourcePageUnreachable


class FakePageScraper:
    """Canned `PageScraper` for tests.

    Attributes:
        pages: URL → `SourcePage` mapping. Configure before the
            first call.
        fail_next: When `True`, the next `fetch` raises
            `SourcePageUnreachable`. Auto-resets to `False` after
            one raise so subsequent calls return the canned
            page.
        calls: List of URLs that have been fetched (read-only
            introspection for tests).
    """

    def __init__(
        self,
        pages: dict[str, SourcePage] | None = None,
        *,
        fail_next: bool = False,
    ) -> None:
        self.pages: dict[str, SourcePage] = dict(pages or {})
        self.fail_next: bool = fail_next
        self.calls: list[str] = []

    def fetch(self, url: str) -> SourcePage:
        """Return the canned `SourcePage` for `url`.

        Raises:
            SourcePageUnreachable: when `fail_next` is `True` (M1
            failure injection).
        """
        self.calls.append(url)
        if self.fail_next:
            self.fail_next = False
            raise SourcePageUnreachable(url, "injected")
        page = self.pages.get(url)
        if page is None:
            raise SourcePageUnreachable(url, "no canned page")
        return page


__all__ = ["FakePageScraper"]