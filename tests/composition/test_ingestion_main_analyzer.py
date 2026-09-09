"""TDD contract for the WP06 composition wiring.

Per WP06 T057.

Covers the new ``select_analyzer`` and the ``select_chunker``
backend branch in ``composition.ingestion_main``:

- ``ANALYZER_BACKEND=openai`` -> ``OpenAIPageAnalyzer`` wired
  with the configured model.
- ``ANALYZER_BACKEND=none`` -> no analyzer; ``build_service``
  produces an ``IngestionService`` with ``analyzer=None``.
- ``CHUNKER_BACKEND=hybrid`` -> ``HybridChunker`` selected.
- ``CHUNKER_BACKEND=fixed_size`` -> ``FixedSizeChunker`` selected
  (WP03 fallback path).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from support_bot.composition.ingestion_main import (
    build_service,
    select_analyzer,
    select_chunker,
)
from support_bot.composition.settings import Settings


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "source_url": "https://example.com/help",
        "chroma_host": "localhost",
        "chroma_port": 8000,
        "embedder_backend": "local",
        "lock_dir": "/tmp/support-bot-test-locks",
        "analyzer_backend": "openai",
        "chunker_backend": "hybrid",
        "openai_page_analyzer_model": "gpt-4o-mini",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_select_analyzer_returns_none_when_disabled() -> None:
    """``analyzer_backend='none'`` returns ``None`` (analyzer step skipped)."""
    settings = _settings(analyzer_backend="none")
    assert select_analyzer(settings) is None


def test_select_analyzer_returns_openai_page_analyzer() -> None:
    """``analyzer_backend='openai'`` returns an ``OpenAIPageAnalyzer``."""
    settings = _settings(analyzer_backend="openai")
    with patch.dict(
        "os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False
    ):
        analyzer = select_analyzer(settings)
    assert analyzer is not None
    assert type(analyzer).__name__ == "OpenAIPageAnalyzer"
    assert analyzer.model == "gpt-4o-mini"


def test_select_analyzer_uses_configured_model() -> None:
    """``openai_page_analyzer_model`` propagates to the analyzer."""
    settings = _settings(
        analyzer_backend="openai", openai_page_analyzer_model="gpt-4o"
    )
    with patch.dict(
        "os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False
    ):
        analyzer = select_analyzer(settings)
    assert analyzer is not None
    assert analyzer.model == "gpt-4o"


def test_select_chunker_returns_hybrid_for_hybrid_backend() -> None:
    """``chunker_backend='hybrid'`` selects ``HybridChunker``."""
    settings = _settings(chunker_backend="hybrid")
    chunker = select_chunker(settings)
    assert type(chunker).__name__ == "HybridChunker"


def test_select_chunker_returns_fixed_size_for_fixed_size_backend() -> None:
    """``chunker_backend='fixed_size'`` selects ``FixedSizeChunker`` (WP03)."""
    settings = _settings(chunker_backend="fixed_size")
    chunker = select_chunker(settings)
    assert type(chunker).__name__ == "FixedSizeChunker"


def test_build_service_wires_analyzer_when_openai_backend() -> None:
    """``build_service`` injects the analyzer into ``IngestionService``."""
    settings = _settings(analyzer_backend="openai")
    with patch.dict(
        "os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False
    ):
        service = build_service(settings=settings, request_id="rid-comp")
    assert service.analyzer is not None
    assert type(service.analyzer).__name__ == "OpenAIPageAnalyzer"


def test_build_service_omits_analyzer_when_none_backend() -> None:
    """``analyzer_backend='none'`` -> ``IngestionService.analyzer is None``."""
    settings = _settings(analyzer_backend="none")
    service = build_service(settings=settings, request_id="rid-comp-none")
    assert service.analyzer is None


def test_build_service_wires_hybrid_chunker_for_hybrid_backend() -> None:
    """``build_service`` selects the hybrid chunker when backend='hybrid'."""
    settings = _settings(chunker_backend="hybrid")
    service = build_service(settings=settings, request_id="rid-hc")
    assert type(service.chunker).__name__ == "HybridChunker"


def test_build_service_wires_fixed_size_chunker_for_fixed_size_backend() -> None:
    """``build_service`` selects the fixed-size chunker when backend='fixed_size'."""
    settings = _settings(chunker_backend="fixed_size")
    service = build_service(settings=settings, request_id="rid-fs")
    assert type(service.chunker).__name__ == "FixedSizeChunker"