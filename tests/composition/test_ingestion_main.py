"""Tests for ``composition.ingestion_main``.

The CLI is the contract for the Helm ``post-install`` Job. We
test ``build_service(settings, request_id)`` directly so we can
inject the WP01 fakes; the ``main()`` entry point is a thin
wrapper that wires the same builder.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from support_bot.composition.ingestion_main import (
    build_service,
    main,
    select_embedder,
)
from support_bot.composition.settings import Settings
from support_bot.domain.ingestion.entities import Chunk

URL = "https://example.com/help"


def _settings(**overrides: object) -> Settings:
    base = {
        "source_url": URL,
        "chroma_host": "localhost",
        "chroma_port": 8000,
        "embedder_backend": "local",
        "lock_dir": "/tmp/support-bot-test-locks",
    }
    base.update(overrides)
    return Settings(**base)


def test_select_embedder_returns_local_embedder() -> None:
    """``embedder_backend='local'`` selects ``SentenceTransformersEmbedder``."""
    settings = _settings(embedder_backend="local")
    embedder = select_embedder(settings)
    assert type(embedder).__name__ == "SentenceTransformersEmbedder"


def test_select_embedder_returns_openai_embedder() -> None:
    """``embedder_backend='openai'`` selects ``OpenAIEmbedder``."""
    settings = _settings(embedder_backend="openai")
    embedder = select_embedder(settings)
    assert type(embedder).__name__ == "OpenAIEmbedder"


def test_build_service_wires_all_adapters() -> None:
    """``build_service`` returns an ``IngestionService`` with all ports wired."""
    settings = _settings()
    service = build_service(settings=settings, request_id="rid-test")
    assert service.scraper is not None
    assert service.cleaner is not None
    assert service.validator is not None
    assert service.chunker is not None
    assert service.embedder is not None
    assert service.vectorstore is not None
    assert service.lock is not None


def test_build_service_uses_fake_embedder_when_selected() -> None:
    """``embedder_backend='fake'`` selects the in-test fake embedder."""
    from tests.fakes.ingestion.embedder import FakeEmbedder

    settings = _settings(embedder_backend="fake")
    service = build_service(
        settings=settings,
        request_id="rid-test",
        fake_embedder_factory=FakeEmbedder,
    )
    assert type(service.embedder).__name__ == "FakeEmbedder"


def test_select_embedder_fake_without_factory_raises() -> None:
    """``embedder_backend='fake'`` without ``fake_factory`` raises."""
    settings = _settings(embedder_backend="fake")
    with pytest.raises(RuntimeError):
        select_embedder(settings)


def test_main_prints_json_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``main`` runs the ingestion Job and prints one JSON line on success."""
    # Replace ``build_service`` with one that returns a fake-wired service.
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
    from tests.fakes.ingestion.chunker import FakeChunker
    from tests.fakes.ingestion.embedder import FakeEmbedder
    from tests.fakes.ingestion.page_scraper import FakePageScraper
    from tests.fakes.ingestion.vectorstore import FakeVectorStore

    class _StubCleaner:
        def clean(self, html: str) -> CleanedPage:
            return CleanedPage(text="x" * 200, removed_boilerplate_count=0)

    scraper = FakePageScraper(
        pages={URL: SourcePage(url=URL, raw_html="<html>x</html>")}
    )
    store = FakeVectorStore()
    lock_dir = tmp_path / "locks"
    fake_service = IngestionService(
        scraper=scraper,
        cleaner=_StubCleaner(),
        validator=PreEmbedValidator(),
        chunker=FakeChunker(),
        embedder=FakeEmbedder(),
        vectorstore=store,
        lock=FileLockIngestionRunLock(lock_dir=lock_dir),
    )

    monkeypatch.setattr(
        "support_bot.composition.ingestion_main.build_service",
        lambda settings, request_id: fake_service,
    )

    rc = main([
        "--source-url", URL,
        "--embedder-backend", "fake",
        "--chroma-host", "localhost",
        "--chroma-port", "8000",
        "--lock-dir", str(lock_dir),
        "--request-id", "rid-cli",
    ])
    captured = capsys.readouterr()
    assert rc == 0
    # The last JSON line in stdout is the result.
    lines = [ln for ln in captured.out.splitlines() if ln.startswith("{")]
    assert lines, captured.out
    payload = json.loads(lines[-1])
    assert payload["status"] == "ok"
    assert payload["request_id"] == "rid-cli"


def test_main_returns_nonzero_on_unreachable_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``main`` exits non-zero when the scraper raises ``SourcePageUnreachable``."""
    from support_bot.application.ingestion.ingestion_lock import (
        FileLockIngestionRunLock,
    )
    from support_bot.application.ingestion.ingestion_service import (
        IngestionService,
    )
    from support_bot.application.ingestion.pre_embed_validator import (
        PreEmbedValidator,
    )
    from support_bot.domain.ingestion.entities import CleanedPage
    from tests.fakes.ingestion.chunker import FakeChunker
    from tests.fakes.ingestion.embedder import FakeEmbedder
    from tests.fakes.ingestion.page_scraper import FakePageScraper
    from tests.fakes.ingestion.vectorstore import FakeVectorStore

    class _StubCleaner:
        def clean(self, html: str) -> CleanedPage:
            return CleanedPage(text="x" * 200, removed_boilerplate_count=0)

    scraper = FakePageScraper(fail_next=True)
    store = FakeVectorStore()
    lock_dir = tmp_path / "locks"
    fake_service = IngestionService(
        scraper=scraper,
        cleaner=_StubCleaner(),
        validator=PreEmbedValidator(),
        chunker=FakeChunker(),
        embedder=FakeEmbedder(),
        vectorstore=store,
        lock=FileLockIngestionRunLock(lock_dir=lock_dir),
    )

    monkeypatch.setattr(
        "support_bot.composition.ingestion_main.build_service",
        lambda settings, request_id: fake_service,
    )

    rc = main([
        "--source-url", URL,
        "--embedder-backend", "fake",
        "--chroma-host", "localhost",
        "--chroma-port", "8000",
        "--lock-dir", str(lock_dir),
        "--request-id", "rid-fail",
    ])
    assert rc != 0
    assert store.upsert_calls == []


def test_main_handles_skipped_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``main`` exits 0 when the lock is held and the run is skipped."""
    from support_bot.application.ingestion.ingestion_lock import (
        FileLockIngestionRunLock,
    )
    from support_bot.application.ingestion.ingestion_service import (
        IngestionService,
    )
    from support_bot.application.ingestion.pre_embed_validator import (
        PreEmbedValidator,
    )
    from support_bot.domain.ingestion.entities import CleanedPage
    from tests.fakes.ingestion.chunker import FakeChunker
    from tests.fakes.ingestion.embedder import FakeEmbedder
    from tests.fakes.ingestion.page_scraper import FakePageScraper
    from tests.fakes.ingestion.vectorstore import FakeVectorStore

    class _StubCleaner:
        def clean(self, html: str) -> CleanedPage:
            return CleanedPage(text="x" * 200, removed_boilerplate_count=0)

    lock_dir = tmp_path / "locks"
    lock = FileLockIngestionRunLock(lock_dir=lock_dir)
    # Pre-acquire the lock so the next run is skipped.
    assert lock.try_acquire("rid-skip") is True

    fake_service = IngestionService(
        scraper=FakePageScraper(),
        cleaner=_StubCleaner(),
        validator=PreEmbedValidator(),
        chunker=FakeChunker(),
        embedder=FakeEmbedder(),
        vectorstore=FakeVectorStore(),
        lock=lock,
    )

    monkeypatch.setattr(
        "support_bot.composition.ingestion_main.build_service",
        lambda settings, request_id: fake_service,
    )

    rc = main([
        "--source-url", URL,
        "--embedder-backend", "fake",
        "--chroma-host", "localhost",
        "--chroma-port", "8000",
        "--lock-dir", str(lock_dir),
        "--request-id", "rid-skip",
    ])
    captured = capsys.readouterr()
    assert rc == 0
    lines = [ln for ln in captured.out.splitlines() if ln.startswith("{")]
    payload = json.loads(lines[-1])
    assert payload["status"] == "skipped"
