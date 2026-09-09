"""Composition-root configuration (pydantic-settings).

Per AGENTS.md §9 + WP02 T015a (observability) and T017 (api_app).

Only this module imports ``pydantic_settings.BaseSettings``;
``domain/``, ``application/``, ``adapters/`` must never import
from ``pydantic-settings`` (AGENTS.md §1.1).

Environment variables are read once at process start; the
``Settings`` instance is passed into the composition root
``create_app(settings=settings)``.
"""
from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide configuration loaded from env vars + .env.

    Attributes mirror AGENTS.md §9. ``CHROMA_HOST`` and
    ``CHROMA_PORT`` map to ``chroma_host`` and ``chroma_port``
    because pydantic-settings normalises the case.

    The ``request_id`` default is generated lazily (per request)
    by the FastAPI middleware; for the ingestion Job the
    composition root reads ``REQUEST_ID`` (with ``RUN_ID`` as a
    deprecated alias) and passes it into
    ``IngestionService.run``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Ingestion
    source_url: str = ""
    lock_dir: str = "/var/run/support-bot"
    request_id: str = ""

    # Vector store
    chroma_host: str = "localhost"
    chroma_port: int = 8000

    # Provider selection
    # Default is now ``openai`` because:
    # - multilingual-e5-large (the local default until WP06
    #   follow-up) requires ~2 GB of weights plus the torch
    #   runtime; keeping it as the default bloats every Docker
    #   build. The base image no longer installs
    #   ``sentence-transformers`` (it's an optional extra).
    # - ``text-embedding-3-large`` is the MTEB multilingual top
    #   performer among OpenAI models and removes the
    #   6-second-CPU ingest bottleneck.
    # Operators who need offline embeddings set
    # ``EMBEDDER_BACKEND=local`` and install the ``local-embedder``
    # extra.
    embedder_backend: Literal["local", "openai", "fake"] = "openai"
    # Model name used by both backends:
    # - openai: defaults to ``text-embedding-3-large`` (3072d,
    #   optionally truncated via ``embedding_dimensions``).
    # - local: any sentence-transformers model id, e.g.
    #   ``intfloat/multilingual-e5-large``.
    embedding_model_name: str = "text-embedding-3-large"
    # Optional Matryoshka truncation for OpenAI embeddings.
    # When set, OpenAI returns vectors of this length instead
    # of the model's natural dimensionality. Ignored by the
    # local backend. Leave empty to use the model's full dim.
    embedding_dimensions: int | None = 1024
    answerer_backend: Literal["openai", "fake"] = "fake"

    # WP06 — semantic analyzer (LLM-driven) + chunker backends.
    analyzer_backend: Literal["openai", "none"] = "openai"
    chunker_backend: Literal["fixed_size", "hybrid"] = "hybrid"
    openai_page_analyzer_model: str = "gpt-4o-mini"

    # Logging
    log_level: str = "INFO"

    # OpenTelemetry
    otel_exporter_otlp_endpoint: str = ""
    otel_service_namespace: str = "support-bot"
    otel_deployment_environment: str = "dev"
    otel_traces_sampler: str = "parentbased_traceidratio"
    otel_traces_sampler_arg: float = 1.0

    # Service identity
    service_name: str = "support-bot"
    service_version: str = "0.1.0"


__all__ = ["Settings"]
