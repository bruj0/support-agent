"""Production answering-service factory for the docker-compose API.

Per WP04 T034 + AGENTS.md 1.3.

The docker-compose ``api`` service boots uvicorn with
``--factory support_bot.composition.api_app:create_app``.
``create_app`` refuses to start without an
``answering_service`` or an ``answering_service_factory``.
The factory in this module builds the production wiring
from the ``Settings`` instance loaded from environment
variables -- it is the only place where the production
code path imports the OpenAI / Chroma / SentenceTransformers
adapters (the composition root itself never pulls from
``tests/fakes/*`` per AGENTS.md 1.1).

Design choices
--------------

The factory deliberately mirrors the structure of
``composition/ingestion_main.py``: select_<port>() helpers
per adapter, then a ``build_answering_service(settings)``
top-level entry point. Keeping the symmetry between the
two composition roots makes the helm Job / docker-compose
``api`` service / docker-compose ``ingestion`` Job all
follow the same pattern.

``answerer_backend="fake"`` is **rejected** here -- the
``fake`` selection is dev-only and would route through
``tests/fakes/*``. Production must use ``openai``.
"""
from __future__ import annotations

import os
from typing import Any

from support_bot.application.answering.answering_service import (
    AnsweringService,
)
from support_bot.composition.settings import Settings


def select_embedder(settings: Settings) -> Any:
    """Return the embedder adapter selected by ``settings.embedder_backend``."""
    if settings.embedder_backend == "openai":
        from support_bot.adapters.embedding_openai import OpenAIEmbedder

        return OpenAIEmbedder(
            model=settings.embedding_model_name,
            api_key=os.environ.get("OPENAI_API_KEY"),
            dimensions=settings.embedding_dimensions,
        )
    if settings.embedder_backend == "fake":
        raise RuntimeError(
            "embedder_backend='fake' is not allowed in the production "
            "factory. Use the docker-compose 'api' service's normal "
            "wiring or run tests via tests/support/build_fake_app.py."
        )
    # default: local sentence-transformers (passage mode for ingestion).
    from support_bot.adapters.embedding_local import (
        SentenceTransformersEmbedder,
    )

    return SentenceTransformersEmbedder(
        model_name=settings.embedding_model_name,
        input_kind="passage",
    )


def select_query_embedder(settings: Settings) -> Any:
    """Return the embedder used at retrieval time.

    Mirrors ``select_embedder`` but uses ``input_kind="query"`` for
    the local backend so E5-family models apply the matching
    ``"query: "`` prefix. For OpenAI the prefix is a no-op and the
    same adapter is returned.
    """
    if settings.embedder_backend == "openai":
        from support_bot.adapters.embedding_openai import OpenAIEmbedder

        return OpenAIEmbedder(
            model=settings.embedding_model_name,
            api_key=os.environ.get("OPENAI_API_KEY"),
            dimensions=settings.embedding_dimensions,
        )
    from support_bot.adapters.embedding_local import (
        SentenceTransformersEmbedder,
    )

    return SentenceTransformersEmbedder(
        model_name=settings.embedding_model_name,
        input_kind="query",
    )


def select_vectorstore(settings: Settings) -> Any:
    """Return the ``VectorStore`` adapter (Chroma HTTP)."""
    from support_bot.adapters.vectorstore_chroma import ChromaVectorStore

    return ChromaVectorStore(
        host=settings.chroma_host,
        port=settings.chroma_port,
        collection_name="support_bot",
    )


def select_retriever(settings: Settings) -> Any:
    """Return a ``Retriever`` adapter backed by Chroma + the chosen embedder.

    The query-side embedder uses ``input_kind="query"`` so E5-family
    models apply the matching ``"query: "`` prefix. The ingestion
    side uses ``input_kind="passage"`` via ``select_embedder``.

    The returned retriever is wrapped in a
    :class:`LexicalRerankRetriever` so Dutch verb-form variants
    (``"instellen"`` vs ``"installeer"``) that mis-rank in pure
    vector space still surface in the top-``k``. The inner
    Chroma retriever fetches a broader candidate set; the
    reranker blends vector similarity with a BM25-style
    token-overlap score.
    """
    from support_bot.adapters.lexical_rerank_retriever import (
        LexicalRerankRetriever,
    )
    from support_bot.adapters.vectorstore_chroma import ChromaRetriever

    inner = ChromaRetriever(
        vectorstore=select_vectorstore(settings),
        embedder=select_query_embedder(settings),
    )
    return LexicalRerankRetriever(inner=inner)


def select_answer_generator(settings: Settings) -> Any:
    """Return the ``AnswerGenerator`` adapter.

    ``answerer_backend="openai"`` selects ``OPENAIAnswerGenerator``
    (production). The ``fake`` backend is rejected -- the
    production factory never pulls from ``tests/fakes/*``.
    """
    if settings.answerer_backend == "openai":
        from support_bot.adapters.answerer_openai import (
            OPENAIAnswerGenerator,
        )

        return OPENAIAnswerGenerator(
            api_key=os.environ.get("OPENAI_API_KEY"),
            model=os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
        )
    if settings.answerer_backend == "fake":
        raise RuntimeError(
            "answerer_backend='fake' is not allowed in the production "
            "factory. The production code path never imports "
            "tests/fakes/* (AGENTS.md 1.1)."
        )
    raise RuntimeError(
        f"Unknown answerer_backend: {settings.answerer_backend!r}. "
        "Production only supports 'openai'."
    )


def select_low_confidence_policy() -> Any:
    """Return the ``LowConfidencePolicy`` adapter.

    The policy is a stateless pure-Python class (no I/O), so
    it lives in ``adapters/`` rather than ``application/``.
    """
    from support_bot.adapters.low_confidence_policy import (
        ThresholdLowConfidencePolicy,
    )

    return ThresholdLowConfidencePolicy()


def build_answering_service(settings: Settings) -> AnsweringService:
    """Build the production ``AnsweringService`` for the FastAPI app.

    Args:
        settings: The composition root settings (already
            loaded from env vars by ``Settings()``).

    Returns:
        A fully-wired ``AnsweringService`` whose workflow is
        the production ``LangGraphWorkflow`` and whose
        dependency ports are the production Chroma /
        OpenAI / SentenceTransformers adapters.

    Raises:
        RuntimeError: If ``answerer_backend`` is anything other
            than ``"openai"``.
    """
    retriever = select_retriever(settings)
    answer_generator = select_answer_generator(settings)
    policy = select_low_confidence_policy()
    return AnsweringService(
        retriever=retriever,
        policy=policy,
        generator=answer_generator,
    )


def create_production_answering_service(
    settings: Settings,
) -> AnsweringService:
    """Adapter for ``create_app(answering_service_factory=...)``.

    Kept as a thin wrapper so the docker-compose startup
    script can pass it directly without an extra
    ``Settings``-aware trampoline.
    """
    return build_answering_service(settings)


__all__ = [
    "build_answering_service",
    "create_production_answering_service",
]
