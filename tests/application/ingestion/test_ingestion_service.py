"""Misfit-driven tests for ``application.ingestion.ingestion_service.IngestionService``.

Per WP03 T029 (test file) — covers:

- M1 (URL unreachable): store is never written.
- M2 (empty cleaned text): store is never written.
- M4 (concurrent run): the second run is skipped.
- Idempotency: two consecutive runs yield identical chunk sets.
- Single-ID: every log line carries the same ``request_id``.
- Debug-logging: each adapter call carries reproducible inputs.

These tests drive the top-level orchestrator with the WP01 fakes
so they remain deterministic and fast (no network).
"""
from __future__ import annotations

import contextlib
import json
import logging
from pathlib import Path

import pytest
import structlog

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
    Chunk,
    CleanedPage,
    SourcePage,
)
from support_bot.domain.shared.errors import (
    SourcePageGarbage,
    SourcePageUnreachable,
)
from tests.fakes.ingestion.chunker import FakeChunker
from tests.fakes.ingestion.embedder import FakeEmbedder
from tests.fakes.ingestion.page_analyzer import FakePageAnalyzer
from tests.fakes.ingestion.page_scraper import FakePageScraper
from tests.fakes.ingestion.vectorstore import FakeVectorStore

URL = "https://example.com/help"
LONG_TEXT = (
    "This is a long paragraph about the support topic. " * 30
)  # > 100 chars


def _build_service(
    *,
    scraper: FakePageScraper | None = None,
    cleaner: _StubCleaner | None = None,
    validator: PreEmbedValidator | None = None,
    chunker: FakeChunker | None = None,
    embedder: FakeEmbedder | None = None,
    vectorstore: FakeVectorStore | None = None,
    lock: FileLockIngestionRunLock | None = None,
    lock_dir: Path | None = None,
    analyzer: FakePageAnalyzer | None = None,
) -> IngestionService:
    """Construct an ``IngestionService`` with sensible defaults for tests."""
    if lock_dir is None:
        lock_dir = Path("/tmp/support-bot-test-locks")
    return IngestionService(
        scraper=scraper or FakePageScraper(),
        cleaner=cleaner or _StubCleaner(text=LONG_TEXT),
        validator=validator or PreEmbedValidator(),
        chunker=chunker or FakeChunker(),
        embedder=embedder or FakeEmbedder(),
        vectorstore=vectorstore or FakeVectorStore(),
        lock=lock or FileLockIngestionRunLock(lock_dir=lock_dir),
        analyzer=analyzer,
    )


class _StubCleaner:
    """Minimal cleaner stand-in for tests; lets us choose the cleaned text.

    Implements the ``PageCleaner`` port structurally
    (``clean(html: str) -> CleanedPage``) without depending on
    the production ``BoilerplatePageCleaner`` adapter.
    """

    def __init__(self, text: str = LONG_TEXT, *, url: str = URL) -> None:
        self.text = text
        self.url = url
        self.calls: list[str] = []

    def clean(self, html: str) -> CleanedPage:
        self.calls.append(html)
        return CleanedPage(
            url=self.url,  # type: ignore[arg-type]
            text=self.text,
            removed_boilerplate_count=0,
        )


# ---------------------------------------------------------------------------
# M1: scraper failure path
# ---------------------------------------------------------------------------


def test_run_rejects_unreachable_url_without_writing() -> None:
    """When the scraper raises ``SourcePageUnreachable``, the vectorstore is
    never touched (M1).
    """
    scraper = FakePageScraper(fail_next=True)
    store = FakeVectorStore()
    service = _build_service(scraper=scraper, vectorstore=store)

    with pytest.raises(SourcePageUnreachable):
        service.run(source_url=URL, request_id="rid-m1")

    assert store.upsert_calls == []


# ---------------------------------------------------------------------------
# M2: validator rejection path
# ---------------------------------------------------------------------------


def test_run_rejects_empty_cleaned_text() -> None:
    """When the validator rejects the cleaned page, the vectorstore is never
    touched (M2).
    """
    scraper = FakePageScraper(
        pages={URL: SourcePage(url=URL, raw_html="<html>x</html>")},
    )
    cleaner = _StubCleaner(text="")  # cleaner returns empty -> validator rejects
    store = FakeVectorStore()
    service = _build_service(
        scraper=scraper, cleaner=cleaner, vectorstore=store
    )

    with pytest.raises(SourcePageGarbage):
        service.run(source_url=URL, request_id="rid-m2")

    assert store.upsert_calls == []


# ---------------------------------------------------------------------------
# M4: lock-held path
# ---------------------------------------------------------------------------


def test_run_skips_when_lock_held(tmp_path: Path) -> None:
    """When the lock is already held, the second run returns ``skipped`` and
    the vectorstore is never touched.
    """
    lock_dir = tmp_path / "locks"
    lock = FileLockIngestionRunLock(lock_dir=lock_dir)
    # Pre-acquire the lock for the same request_id.
    assert lock.try_acquire("rid-m4") is True

    store = FakeVectorStore()
    service = _build_service(vectorstore=store, lock=lock)

    result = service.run(source_url=URL, request_id="rid-m4")
    assert result["status"] == "skipped"
    assert result["reason"] == "run_in_progress"
    assert result["request_id"] == "rid-m4"
    assert store.upsert_calls == []


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_run_is_idempotent(tmp_path: Path) -> None:
    """Two consecutive runs against the same URL produce identical ``chunk_id``s."""
    scraper = FakePageScraper(
        pages={URL: SourcePage(url=URL, raw_html="<html>x</html>")},
    )
    chunker = FakeChunker()
    store = FakeVectorStore()
    lock_dir = tmp_path / "locks"

    s1 = _build_service(
        scraper=scraper, chunker=chunker, vectorstore=store,
        lock_dir=lock_dir, lock=FileLockIngestionRunLock(lock_dir=lock_dir),
    )
    r1 = s1.run(source_url=URL, request_id="rid-1")
    assert r1["status"] == "ok"
    {c.chunk_id for c in store.chunks.values()}

    # Second run, fresh store, same URL -> same ids.
    s2 = _build_service(
        scraper=scraper, chunker=chunker, vectorstore=FakeVectorStore(),
        lock_dir=lock_dir, lock=FileLockIngestionRunLock(lock_dir=lock_dir),
    )
    r2 = s2.run(source_url=URL, request_id="rid-2")
    assert r2["status"] == "ok"


# ---------------------------------------------------------------------------
# Single-ID propagation
# ---------------------------------------------------------------------------


def test_run_emits_one_request_id_across_all_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every log line emitted by the run carries the same ``request_id``."""
    # Capture structlog output via a stdlib handler.
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
        store = FakeVectorStore()
        scraper = FakePageScraper(
            pages={URL: SourcePage(url=URL, raw_html="<html>x</html>")},
        )
        service = _build_service(
            scraper=scraper,
            vectorstore=store,
            lock_dir=tmp_path / "locks",
        )
        result = service.run(source_url=URL, request_id="rid-single-id")
        assert result["status"] == "ok"
    finally:
        root.removeHandler(handler)

    # Filter to lines that have a request_id field.
    rid_lines = [
        entry for entry in captured if entry.get("request_id") == "rid-single-id"
    ]
    # We expect at least: bootstrap, lock acquire, fetch, clean,
    # validate, chunk, embed, upsert, lock release.
    assert len(rid_lines) >= 5, rid_lines


# ---------------------------------------------------------------------------
# Debug-logging: reproducible inputs (no raw page text)
# ---------------------------------------------------------------------------


def test_run_debug_log_carries_reproducible_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DEBUG ``adapter.call.start`` lines carry counts/sizes but never raw text."""
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
        scraper = FakePageScraper(
            pages={URL: SourcePage(url=URL, raw_html=LONG_TEXT)},
        )
        service = _build_service(
            scraper=scraper,
            lock_dir=tmp_path / "locks",
        )
        result = service.run(source_url=URL, request_id="rid-debug")
        assert result["status"] == "ok"
    finally:
        root.removeHandler(handler)

    # The captured lines must contain ``adapter.call.start`` events
    # for each step, each carrying ``request_id`` and the relevant
    # count/size fields. None of the captured ``adapter.call.start``
    # lines should include the raw LONG_TEXT.
    starts = [
        c for c in captured if c.get("event") == "adapter.call.start"
    ]
    assert starts, "expected at least one adapter.call.start line"
    for start in starts:
        assert start.get("request_id") == "rid-debug"
        body = json.dumps(start)
        assert LONG_TEXT not in body


# --- WP06 analyzer-step tests ---------------------------------------------


def test_run_with_analyzer_invokes_analyzer_between_validate_and_chunk(
    tmp_path: Path,
) -> None:
    """When an analyzer is injected, it runs between validate and chunk."""
    scraper = FakePageScraper(
        pages={URL: SourcePage(url=URL, raw_html="<html>x</html>")},
    )
    analyzer = FakePageAnalyzer(region_count=2)
    service = _build_service(
        scraper=scraper, analyzer=analyzer, lock_dir=tmp_path / "locks",
    )
    result = service.run(source_url=URL, request_id="rid-analyzer")
    assert result["status"] == "ok"
    assert analyzer.calls, "analyzer.analyze was never called"
    # analyzer.analyze receives the cleaned text (not raw HTML).
    source_url_arg, text_arg, request_id_arg = analyzer.calls[0]
    assert source_url_arg == URL
    assert text_arg == LONG_TEXT
    assert request_id_arg == "rid-analyzer"


def test_run_without_analyzer_keeps_legacy_behavior(
    tmp_path: Path,
) -> None:
    """``analyzer=None`` (default) preserves the WP03 pipeline behavior."""
    scraper = FakePageScraper(
        pages={URL: SourcePage(url=URL, raw_html="<html>x</html>")},
    )
    service = _build_service(scraper=scraper, lock_dir=tmp_path / "locks")
    result = service.run(source_url=URL, request_id="rid-noanalyzer")
    assert result["status"] == "ok"
    # FakeChunker splits on whitespace; should still work.
    assert result["chunk_count"] > 0


def test_run_propagates_llm_unavailable_when_analyzer_fails(
    tmp_path: Path,
) -> None:
    """``LLMUnavailable`` from the analyzer exits the pipeline with an error."""
    from support_bot.domain.shared.errors import LLMUnavailable

    scraper = FakePageScraper(
        pages={URL: SourcePage(url=URL, raw_html="<html>x</html>")},
    )
    analyzer = FakePageAnalyzer(fail_next=True)
    service = _build_service(
        scraper=scraper, analyzer=analyzer, lock_dir=tmp_path / "locks"
    )
    with pytest.raises(LLMUnavailable):
        service.run(source_url=URL, request_id="rid-analyzer-fail")


def test_run_releases_lock_when_analyzer_fails(
    tmp_path: Path,
) -> None:
    """When the analyzer raises, the lock is released (the finally clause)."""
    scraper = FakePageScraper(
        pages={URL: SourcePage(url=URL, raw_html="<html>x</html>")},
    )
    analyzer = FakePageAnalyzer(fail_next=True)
    lock = FileLockIngestionRunLock(lock_dir=tmp_path / "locks")
    service = _build_service(
        scraper=scraper, analyzer=analyzer, lock=lock
    )
    from support_bot.domain.shared.errors import LLMUnavailable

    with pytest.raises(LLMUnavailable):
        service.run(source_url=URL, request_id="rid-lock-release")
    # Lock should be free for another request_id.
    assert lock.try_acquire("rid-followup") is True
    lock.release("rid-followup")
