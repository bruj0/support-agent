"""Ingestion-Job CLI entry point.

Per WP03 T030.

``main()`` is the contract for the Helm ``post-install`` Job
(WP05). The Job command is
``["python", "-m", "support_bot.composition.ingestion_main"]``;
the Job's stdout is captured and parsed for the result JSON so
operators can grep ``chunk_count`` after a successful run.

Design choices
--------------

The CLI accepts every required setting on the command line (no
hidden env reads except via ``Settings`` defaults). This makes
the entry point trivially testable and lets the Helm Job pass
values from the ``values.yaml`` directly.

``init_tracing(settings)`` is called **first** (before any
adapter is constructed) so the OTel SDK is up before the first
log line. The composition root never pulls from ``tests/`` in
production code paths (AGENTS.md §1.1); the ``fake`` embedder
selection is opt-in via ``EMBEDDER_BACKEND=fake`` and is
explicitly allowed here as a dev-only escape hatch (mirrors
the WP02 ``answerer_backend='fake'`` precedent).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import structlog

from support_bot.composition.observability import init_tracing
from support_bot.composition.settings import Settings

_log = structlog.get_logger(__name__)


def _build_arg_parser() -> argparse.ArgumentParser:
    """Return the ``argparse`` parser for the ingestion CLI."""
    parser = argparse.ArgumentParser(
        prog="ingestion_main",
        description=(
            "Run the support-bot ingestion Job once. "
            "Emits one JSON line to stdout on success."
        ),
    )
    parser.add_argument(
        "--source-url",
        default=os.environ.get("SOURCE_URL", ""),
        help="The URL to fetch, clean, chunk, embed, and upsert.",
    )
    parser.add_argument(
        "--embedder-backend",
        choices=("local", "openai", "fake"),
        default=os.environ.get("EMBEDDER_BACKEND", "local"),
        help="Embedder adapter to use.",
    )
    parser.add_argument(
        "--chroma-host",
        default=os.environ.get("CHROMA_HOST", "localhost"),
        help="Chroma HTTP host.",
    )
    parser.add_argument(
        "--chroma-port",
        type=int,
        default=int(os.environ.get("CHROMA_PORT", "8000")),
        help="Chroma HTTP port.",
    )
    parser.add_argument(
        "--lock-dir",
        default=os.environ.get("LOCK_DIR", "/var/run/support-bot"),
        help="Directory used by the file-based ingestion lock.",
    )
    parser.add_argument(
        "--request-id",
        default=os.environ.get("REQUEST_ID")
        or os.environ.get("RUN_ID")
        or uuid.uuid4().hex,
        help=(
            "Correlation ID propagated through every log line, "
            "span, and the lock filename (AGENTS.md §6.3). "
            "``RUN_ID`` is a deprecated alias for ``REQUEST_ID``."
        ),
    )
    parser.add_argument(
        "--collection-name",
        default=os.environ.get("CHROMA_COLLECTION", "support_bot"),
        help="Chroma collection name.",
    )
    return parser


def _settings_from_args(args: argparse.Namespace) -> Settings:
    """Build a ``Settings`` instance from CLI args."""
    return Settings(
        source_url=args.source_url,
        chroma_host=args.chroma_host,
        chroma_port=args.chroma_port,
        embedder_backend=args.embedder_backend,
        lock_dir=args.lock_dir,
        request_id=args.request_id,
    )


def select_embedder(
    settings: Settings,
    *,
    fake_factory: Callable[[], Any] | None = None,
) -> Any:
    """Return the embedder adapter selected by ``settings.embedder_backend``.

    Args:
        settings: The composition root settings.
        fake_factory: Optional factory used when
            ``settings.embedder_backend == "fake"``. Production
            code paths must not pass a ``fake_factory`` (the
            ``fake`` backend is dev-only). Tests inject
            ``FakeEmbedder`` via this seam so production code
            never imports ``tests/fakes/*`` (AGENTS.md §1.1).

    Returns:
        An object implementing the ``Embedder`` port.
    """
    if settings.embedder_backend == "openai":
        from support_bot.adapters.embedding_openai import OpenAIEmbedder

        return OpenAIEmbedder(
            model=settings.embedding_model_name,
            api_key=os.environ.get("OPENAI_API_KEY"),
            dimensions=settings.embedding_dimensions,
        )
    if settings.embedder_backend == "fake":
        if fake_factory is None:
            raise RuntimeError(
                "embedder_backend='fake' requires a fake_factory kwarg; "
                "production code must not use the fake backend."
            )
        return fake_factory()
    # default: local sentence-transformers, ingestion-side
    # ``passage`` prefix so E5-family models encode documents
    # correctly.
    from support_bot.adapters.embedding_local import (
        SentenceTransformersEmbedder,
    )

    return SentenceTransformersEmbedder(
        model_name=settings.embedding_model_name,
        input_kind="passage",
    )


def select_scraper(settings: Settings) -> Any:
    """Return the ``PageScraper`` adapter.

    Args:
        settings: The composition root settings.

    Returns:
        A ``RequestsPageScraper`` instance with the standard
        ``User-Agent`` and timeout.
    """
    from support_bot.adapters.http_source import RequestsPageScraper

    return RequestsPageScraper()


def select_cleaner(settings: Settings) -> Any:
    """Return the ``PageCleaner`` adapter."""
    from support_bot.adapters.cleaner import BoilerplatePageCleaner

    return BoilerplatePageCleaner()


def select_chunker(settings: Settings) -> Any:
    """Return the ``Chunker`` adapter selected by ``settings.chunker_backend``.

    WP06 backend selection:
    - ``hybrid`` (default) -> ``HybridChunker`` (consumes a
      ``PageStructure`` from the analyzer; raises
      ``ConfigurationError`` if called with ``structure=None``).
    - ``fixed_size`` -> ``FixedSizeChunker`` (WP03 fallback;
      ignores ``structure``).
    """
    if settings.chunker_backend == "hybrid":
        from support_bot.adapters.hybrid_chunker import HybridChunker

        return HybridChunker()
    from support_bot.adapters.chunker import FixedSizeChunker

    return FixedSizeChunker()


def select_analyzer(
    settings: Settings,
) -> Any:
    """Return the ``PageAnalyzer`` adapter, or ``None`` if disabled.

    WP06 backend selection:
    - ``none`` -> ``None``; the orchestrator skips the analyze
      step and the chunker receives ``structure=None`` (the
      FixedSizeChunker fallback path).
    - ``openai`` -> ``OpenAIPageAnalyzer`` with the configured
      model (``settings.openai_page_analyzer_model``). The
      OpenAI API key is read from the ``OPENAI_API_KEY`` env var.
    """
    if settings.analyzer_backend == "none":
        return None
    from support_bot.adapters.llm_page_analyzer import OpenAIPageAnalyzer

    return OpenAIPageAnalyzer(
        api_key=os.environ.get("OPENAI_API_KEY"),
        model=settings.openai_page_analyzer_model,
    )


def select_vectorstore(
    settings: Settings,
    *,
    collection_name: str = "support_bot",
) -> Any:
    """Return the ``VectorStore`` adapter."""
    from support_bot.adapters.vectorstore_chroma import ChromaVectorStore

    return ChromaVectorStore(
        host=settings.chroma_host,
        port=settings.chroma_port,
        collection_name=collection_name,
    )


def build_service(
    *,
    settings: Settings,
    request_id: str,
    fake_embedder_factory: Callable[[], Any] | None = None,
) -> Any:
    """Wire the full ingestion pipeline and return an ``IngestionService``.

    Args:
        settings: Composition root settings.
        request_id: The correlation ID for this run.
        fake_embedder_factory: Optional factory used when
            ``settings.embedder_backend == "fake"``. Production
            code paths must not pass a ``fake_embedder_factory``
            (the ``fake`` backend is dev-only).

    Returns:
        A fully-wired ``IngestionService``.
    """
    from support_bot.application.ingestion.ingestion_lock import (
        FileLockIngestionRunLock,
    )
    from support_bot.application.ingestion.ingestion_service import (
        IngestionService,
    )
    from support_bot.application.ingestion.pre_embed_validator import (
        PreEmbedValidator,
    )

    lock = FileLockIngestionRunLock(
        lock_dir=Path(settings.lock_dir),
    )
    return IngestionService(
        scraper=select_scraper(settings),
        cleaner=select_cleaner(settings),
        validator=PreEmbedValidator(),
        chunker=select_chunker(settings),
        embedder=select_embedder(
            settings, fake_factory=fake_embedder_factory
        ),
        vectorstore=select_vectorstore(settings),
        lock=lock,
        analyzer=select_analyzer(settings),
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ingestion CLI.

    Args:
        argv: Optional argument list. When ``None``, ``sys.argv[1:]``
            is used (i.e. normal CLI invocation).

    Returns:
        Exit code: ``0`` on success or skipped, non-zero on any
        ingestion failure (``SourcePageUnreachable``,
        ``SourcePageGarbage``, unhandled exception). The
        function also prints the result as one JSON line to
        stdout on success or skip.
    """
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    settings = _settings_from_args(args)
    request_id = args.request_id

    configure_logging = _resolve_configure_logging()
    configure_logging(settings.log_level)

    init_tracing(settings=settings)

    _log.debug(
        "ingestion.bootstrap",
        source_url=settings.source_url,
        embedder_backend=settings.embedder_backend,
        chroma_host=settings.chroma_host,
        request_id=request_id,
    )

    try:
        service = build_service(settings=settings, request_id=request_id)
    except Exception as exc:
        _log.error(
            "ingestion.bootstrap_failed",
            error_type=type(exc).__name__,
            request_id=request_id,
        )
        return 2

    try:
        result = service.run(source_url=settings.source_url, request_id=request_id)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        _log.error(
            "ingestion.run_failed",
            error_type=type(exc).__name__,
            request_id=request_id,
        )
        # The Helm Job captures stdout; emit a JSON line so the
        # operator can grep the error in the post-install hook.
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "request_id": request_id,
                }
            ),
            file=sys.stdout,
            flush=True,
        )
        return 1

    print(json.dumps(result), file=sys.stdout, flush=True)
    if result.get("status") == "ok":
        return 0
    if result.get("status") == "skipped":
        return 0
    return 1


def _resolve_configure_logging() -> Callable[[str], None]:
    """Lazy resolver for ``configure_logging`` to avoid an import cycle."""
    from support_bot.adapters.structured_logger import configure_logging

    return configure_logging


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
