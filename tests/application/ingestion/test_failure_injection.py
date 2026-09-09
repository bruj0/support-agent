"""Consolidated failure-injection contract tests for the ingestion pipeline.

Per WP03 T032.

These tests exercise the four canonical scenarios from the
Misfit Interaction Notes in ``spec.md`` end-to-end through the
``IngestionService`` orchestrator, using the WP01 in-memory
fakes. They are the highest-leverage regression suite: any
change to the orchestrator's failure handling will trip one of
these tests.

Scenarios
---------

1. Scraper 5xx -> exit non-zero, store untouched.
2. Cleaner empty -> validator rejects, store untouched.
3. Two concurrent runs -> second skipped (M4).
4. Successful run -> store contains expected chunks.
"""
from __future__ import annotations

import contextlib
import json
import logging
from pathlib import Path

import pytest

from support_bot.application.ingestion.ingestion_lock import (
    FileLockIngestionRunLock,
)
from support_bot.application.ingestion.ingestion_service import (
    IngestionService,
)
from support_bot.application.ingestion.pre_embed_validator import (
    PreEmbedValidator,
)
from support_bot.domain.ingestion.entities import (
    CleanedPage,
    SourcePage,
)
from support_bot.domain.shared.errors import (
    SourcePageGarbage,
    SourcePageUnreachable,
)
from tests.fakes.ingestion.chunker import FakeChunker
from tests.fakes.ingestion.embedder import FakeEmbedder
from tests.fakes.ingestion.page_scraper import FakePageScraper
from tests.fakes.ingestion.vectorstore import FakeVectorStore

URL = "https://example.com/help"
LONG_TEXT = (
    "This is a long paragraph about the support topic. " * 30
)  # > 100 chars


class _StubCleaner:
    """Cleaner that returns the configured text (default: ``LONG_TEXT``)."""

    def __init__(self, text: str = LONG_TEXT) -> None:
        self.text = text
        self.calls: list[str] = []

    def clean(self, html: str) -> CleanedPage:
        self.calls.append(html)
        return CleanedPage(text=self.text, removed_boilerplate_count=0)


def _build_service(
    *,
    scraper: FakePageScraper,
    cleaner: _StubCleaner,
    lock_dir: Path,
    vectorstore: FakeVectorStore | None = None,
    chunker: FakeChunker | None = None,
    embedder: FakeEmbedder | None = None,
) -> IngestionService:
    """Wire a service with sensible defaults for failure-injection tests."""
    return IngestionService(
        scraper=scraper,
        cleaner=cleaner,
        validator=PreEmbedValidator(),
        chunker=chunker or FakeChunker(),
        embedder=embedder or FakeEmbedder(),
        vectorstore=vectorstore or FakeVectorStore(),
        lock=FileLockIngestionRunLock(lock_dir=lock_dir),
    )


# ---------------------------------------------------------------------------
# Scenario 1: scraper 5xx -> exit non-zero, store untouched.
# ---------------------------------------------------------------------------


def test_failure_scenario_1_scraper_5xx_exits_nonzero_store_untouched(
    tmp_path: Path,
) -> None:
    """A scraper failure surfaces as ``SourcePageUnreachable`` and never
    touches the vectorstore (M1, FR-008).
    """
    scraper = FakePageScraper(fail_next=True)
    store = FakeVectorStore()
    service = _build_service(
        scraper=scraper,
        cleaner=_StubCleaner(),
        vectorstore=store,
        lock_dir=tmp_path / "locks",
    )

    with pytest.raises(SourcePageUnreachable):
        service.run(source_url=URL, request_id="rid-1")

    # The vectorstore is untouched.
    assert store.upsert_calls == []
    assert store.delete_calls == []
    assert store.count() == 0


# ---------------------------------------------------------------------------
# Scenario 2: cleaner empty -> validator rejects, store untouched.
# ---------------------------------------------------------------------------


def test_failure_scenario_2_cleaner_empty_validator_rejects_store_untouched(
    tmp_path: Path,
) -> None:
    """When the cleaner returns empty text the validator rejects with
    ``SourcePageGarbage`` and the vectorstore is never touched (M2, FR-008).
    """
    scraper = FakePageScraper(
        pages={URL: SourcePage(url=URL, raw_html="<html>x</html>")},
    )
    cleaner = _StubCleaner(text="")  # empty -> validator rejects
    store = FakeVectorStore()
    service = _build_service(
        scraper=scraper,
        cleaner=cleaner,
        vectorstore=store,
        lock_dir=tmp_path / "locks",
    )

    with pytest.raises(SourcePageGarbage):
        service.run(source_url=URL, request_id="rid-2")

    # The vectorstore is untouched.
    assert store.upsert_calls == []
    assert store.delete_calls == []
    assert store.count() == 0


# ---------------------------------------------------------------------------
# Scenario 3: two concurrent runs -> second skipped.
# ---------------------------------------------------------------------------


def test_failure_scenario_3_concurrent_runs_second_skipped(
    tmp_path: Path,
) -> None:
    """When the lock is held the second run returns ``skipped`` (M4)."""
    scraper = FakePageScraper(
        pages={URL: SourcePage(url=URL, raw_html="<html>x</html>")},
    )
    store = FakeVectorStore()
    lock_dir = tmp_path / "locks"

    # First run completes successfully.
    service_a = _build_service(
        scraper=scraper,
        cleaner=_StubCleaner(),
        vectorstore=store,
        lock_dir=lock_dir,
    )
    result_a = service_a.run(source_url=URL, request_id="rid-3a")
    assert result_a["status"] == "ok"

    # Re-acquire the lock to simulate a concurrent run.
    lock = FileLockIngestionRunLock(lock_dir=lock_dir)
    assert lock.try_acquire("rid-3b") is True

    # Second run with the held lock returns skipped.
    service_b = IngestionService(
        scraper=scraper,
        cleaner=_StubCleaner(),
        validator=PreEmbedValidator(),
        chunker=FakeChunker(),
        embedder=FakeEmbedder(),
        vectorstore=store,
        lock=lock,
    )
    result_b = service_b.run(source_url=URL, request_id="rid-3b")
    assert result_b["status"] == "skipped"
    assert result_b["reason"] == "run_in_progress"
    # The lock holder's id is NOT reused; the second run preserves
    # its own request_id (M4 acceptance criterion).
    assert result_b["request_id"] == "rid-3b"


# ---------------------------------------------------------------------------
# Scenario 4: successful run -> store contains expected chunks.
# ---------------------------------------------------------------------------


def test_failure_scenario_4_successful_run_store_contains_chunks(
    tmp_path: Path,
) -> None:
    """A successful run leaves the configured chunks in the vectorstore."""
    scraper = FakePageScraper(
        pages={URL: SourcePage(url=URL, raw_html="<html>x</html>")},
    )
    chunker = FakeChunker()
    store = FakeVectorStore()
    service = _build_service(
        scraper=scraper,
        cleaner=_StubCleaner(),
        chunker=chunker,
        vectorstore=store,
        lock_dir=tmp_path / "locks",
    )

    result = service.run(source_url=URL, request_id="rid-4")
    assert result["status"] == "ok"
    assert result["chunk_count"] == len(store.chunks)
    assert result["chunk_count"] > 0
    # All chunks have a stable chunk_id (FR-012 idempotency).
    for chunk_id in store.chunks:
        assert len(chunk_id) == 40
    # Every chunk references the source URL.
    for chunk in store.chunks.values():
        assert chunk.source_url == URL


# ---------------------------------------------------------------------------
# Extra: every failure path emits one request_id across the structured logs.
# ---------------------------------------------------------------------------


def test_failure_scenarios_emit_consistent_request_id_in_logs(
    tmp_path: Path,
) -> None:
    """On a failed run, every emitted log line carries the same ``request_id``."""
    captured: list[dict[str, object]] = []

    class _Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            with contextlib.suppress(ValueError, TypeError):
                captured.append(json.loads(record.getMessage()))

    handler = _Handler(level=logging.DEBUG)
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)

    try:
        scraper = FakePageScraper(fail_next=True)
        store = FakeVectorStore()
        service = _build_service(
            scraper=scraper,
            cleaner=_StubCleaner(),
            vectorstore=store,
            lock_dir=tmp_path / "locks",
        )
        with pytest.raises(SourcePageUnreachable):
            service.run(source_url=URL, request_id="rid-failure")
    finally:
        root.removeHandler(handler)

    rid_lines = [
        c for c in captured if c.get("request_id") == "rid-failure"
    ]
    assert len(rid_lines) >= 3
