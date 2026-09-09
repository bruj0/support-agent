"""Lexical re-ranking retriever (WP06 follow-up).

Wraps an underlying ``Retriever`` (typically ``ChromaRetriever``)
and re-orders the top-N candidates by blending vector similarity
with a token-overlap score against the chunk text.

Why
---
``all-MiniLM-L6-v2`` (the local default embedder) is an English-
centric encoder and ranks Dutch verb-form variants inconsistently.
Concretely, the question ``"Hoe kan ik mijn Ziggo internet
instellen?"`` retrieves ``"Is Internet van Ziggo beschikbaar op
mijn adres?"`` at sim=0.578, while the semantically correct chunk
``"Hoe installeer ik Ziggo Internet?"`` lands at sim=0.323 --
out of the top-k. The text of the correct chunk, however, is
strongly lexically aligned with the question, so a BM25-style
token-overlap score reliably promotes it.

Design choices
--------------
- ``candidate_k = max(20, k * 5)`` from the underlying retriever
  (broad recall), then re-rank and return top-``k``.
- Token overlap is computed on lowercased, whitespace-split
  tokens with a small Dutch stop-word set removed. The score is
  the fraction of question tokens present in the chunk text,
  averaged with the symmetric direction so chunks that merely
  contain question words don't drown out genuinely relevant ones.
- Final score: ``alpha * similarity + (1 - alpha) * lexical``,
  with ``alpha=0.5`` as a defensible default. The two scores are
  both in ``[0, 1]`` so a fixed blend is interpretable.
- Pure Python (no extra deps); deterministic; observable via the
  same ``adapter.call.*`` logging pattern as the other adapters.
"""
from __future__ import annotations

import re
import time
from collections.abc import Iterable
from typing import Any

import structlog

from support_bot.domain.shared.errors import VectorStoreUnavailable
from support_bot.domain.shared.retrieval import RetrievedChunk

_log = structlog.get_logger(__name__)

# Compact Dutch stop-word list -- enough to suppress high-frequency
# function words without dragging in a corpus.
_DUTCH_STOPWORDS: frozenset[str] = frozenset(
    {
        "de", "het", "een", "en", "of", "ik", "je", "jij", "u", "we",
        "wij", "ze", "hij", "zij", "dat", "dit", "die", "naar", "van",
        "in", "op", "aan", "met", "voor", "bij", "tot", "uit", "over",
        "te", "ten", "ter", "is", "was", "ben", "bent", "zijn", "wordt",
        "kan", "kun", "kunt", "mag", "moet", "moeten", "mijn", "jouw",
        "uw", "onze", "hun", "haar", "hem", "wat", "wie", "hoe", "waar",
        "wanneer", "waarom", "welke", "niet", "wel", "ook", "maar",
        "dan", "als", "omdat", "dus", "nog", "al", "alleen", "toch",
        "ja", "nee", "hier", "daar", "nu", "worden", "krijg",
        "krijgen", "heb", "hebt", "heeft", "hebben", "had", "hadden",
        "doe", "doet", "doen", "deze", "zo", "heel",
    }
)

_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ0-9]+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    """Lowercase tokenise ``text``, dropping short tokens and stop-words."""
    return [
        t
        for t in (m.group(0).lower() for m in _TOKEN_RE.finditer(text))
        if len(t) > 1 and t not in _DUTCH_STOPWORDS
    ]


def _stem_prefix(token: str, prefix_len: int = 5) -> str:
    """Return a 5-char prefix for soft-match (handles verb forms).

    Dutch verb forms like ``instellen`` / ``installeer`` /
    ``installatie`` share a 5+ char root, so a prefix match is a
    cheap stemmer that doesn't pull in a corpus.
    """
    return token[:prefix_len] if len(token) >= prefix_len else token


def _prefix_match(stem_a: str, stem_b: str, min_len: int = 4) -> bool:
    """Return True if ``stem_a`` and ``stem_b`` share a ``min_len``-char prefix.

    This is a bidirectional prefix match that catches Dutch verb
    morphology: ``instellen`` (stem ``inste``) ↔ ``installeer``
    (stem ``insta``) ↔ ``installatie`` (stem ``insta``) all
    share the 4-char prefix ``inst``.
    """
    if not stem_a or not stem_b:
        return False
    n = min(len(stem_a), len(stem_b), min_len)
    return stem_a[:n] == stem_b[:n]


def _stems_match(q_stem: str, c_stem: str) -> bool:
    """Bidirectional prefix match between two 5-char stems."""
    return _prefix_match(q_stem, c_stem, min_len=4)


def _lexical_overlap(question_tokens: Iterable[str], chunk_text: str) -> float:
    """Recall-only overlap score in ``[0, 1]``.

    Counts the fraction of question tokens that have a
    stem-prefix match against some chunk token. Question-side
    recall (rather than symmetric F1) is used because question
    tokens are the scarce, intentional signal: a chunk that
    matches 3/3 question stems is more relevant than one that
    matches 1/3 even if the latter's body is shorter and would
    inflate a precision-based score.

    A question token counts as present in the chunk when EITHER
    the exact token OR a 5-char stem with a shared 4-char prefix
    appears among the chunk's tokens. This handles Dutch
    verb-form variants (``instellen`` ↔ ``installeer`` ↔
    ``installatie``) that ``all-MiniLM-L6-v2`` mis-ranks.

    Returns 0.0 when the question has no tokens after filtering.
    """
    q_tokens = list(question_tokens)
    chunk_tokens = _tokenize(chunk_text)
    if not q_tokens:
        return 0.0
    if not chunk_tokens:
        return 0.0
    q_stems = [_stem_prefix(t) for t in q_tokens]
    c_stems = [_stem_prefix(t) for t in chunk_tokens]
    matched = sum(1 for qs in q_stems if any(_stems_match(qs, cs) for cs in c_stems))
    return matched / len(q_stems)


class LexicalRerankRetriever:
    """``Retriever`` adapter that re-ranks an underlying retriever's output.

    Attributes:
        inner: The underlying ``Retriever`` (typically
            ``ChromaRetriever``).
        alpha: Blend weight for vector similarity; the remainder
            is the lexical overlap score. Default ``0.5``.
        candidate_k_multiplier: Fetch ``max(candidate_k_multiplier * k,
            20)`` from the inner retriever. Default ``5``.
    """

    def __init__(
        self,
        *,
        inner: Any,
        alpha: float = 0.5,
        candidate_k_multiplier: int = 5,
    ) -> None:
        """Initialise the reranker.

        Args:
            inner: The wrapped retriever.
            alpha: Blend weight for vector similarity (0..1).
            candidate_k_multiplier: Multiplier on ``k`` for the
                inner-retriever fetch. Clamped so the fetch is
                at least 20.
        """
        if not 0.0 <= alpha <= 1.0:
            raise ValueError(f"alpha ({alpha}) must be in [0.0, 1.0]")
        self.inner: Any = inner
        self.alpha: float = alpha
        self.candidate_k_multiplier: int = max(1, candidate_k_multiplier)

    def retrieve(self, question: str, k: int = 4) -> list[RetrievedChunk]:
        """Fetch top-``k`` chunks, re-ranked by blended score.

        Args:
            question: The user's question.
            k: Maximum chunks to return.

        Returns:
            ``RetrievedChunk`` list, length ``<= k``, ordered by
            blended score (descending). Each chunk's ``similarity``
            is set to the blended score so the existing guard /
            threshold logic keeps working unchanged.

        Raises:
            VectorStoreUnavailable: Propagated from the inner retriever.
        """
        from opentelemetry import trace  # lazy: SDK-free at import

        tracer = trace.get_tracer("support_bot.adapter.lexical_rerank")
        with tracer.start_as_current_span("adapter.retriever.rerank") as span:
            span.set_attribute("retriever.k", k)
            span.set_attribute("retriever.alpha", self.alpha)
            question_tokens = _tokenize(question)
            span.set_attribute("retriever.question_token_count", len(question_tokens))

            fetch_k = max(k * self.candidate_k_multiplier, 20)
            _log.debug(
                "adapter.call.start",
                adapter="LexicalRerankRetriever",
                operation="retrieve",
                k=k,
                fetch_k=fetch_k,
                alpha=self.alpha,
                question_token_count=len(question_tokens),
            )
            started = time.monotonic()
            try:
                # Inner retriever (ChromaRetriever) accepts `query=`;
                # the Retriever Protocol advertises `question=`. Try
                # the more specific name first, then fall back.
                try:
                    candidates = self.inner.retrieve(query=question, k=fetch_k)  # type: ignore[call-arg]
                except TypeError:
                    candidates = self.inner.retrieve(question=question, k=fetch_k)
            except VectorStoreUnavailable:
                raise
            except Exception as exc:  # pragma: no cover -- defensive
                raise VectorStoreUnavailable(str(exc)) from exc

            # If the inner store is small (< k), nothing to rerank.
            if len(candidates) <= k:
                elapsed_ms = (time.monotonic() - started) * 1000.0
                _log.info(
                    "adapter.call.ok",
                    adapter="LexicalRerankRetriever",
                    operation="retrieve",
                    outcome="passthrough",
                    returned=len(candidates),
                    latency_ms=elapsed_ms,
                )
                return list(candidates)

            scored: list[tuple[RetrievedChunk, float]] = []
            for c in candidates:
                lex = _lexical_overlap(question_tokens, c.text)
                blended = self.alpha * c.similarity + (1.0 - self.alpha) * lex
                scored.append((c, blended))

            scored.sort(key=lambda t: t[1], reverse=True)
            top = scored[:k]
            # Replace similarity with the blended score so the guard
            # / LowConfidencePolicy sees a single, comparable metric.
            reranked: list[RetrievedChunk] = []
            for chunk, blended in top:
                reranked.append(
                    RetrievedChunk(
                        chunk_id=chunk.chunk_id,
                        text=chunk.text,
                        source_url=chunk.source_url,
                        similarity=max(0.0, min(1.0, blended)),
                    )
                )
            span.set_attribute("retriever.candidate_count", len(candidates))
            span.set_attribute("retriever.top_score", top[0][1] if top else 0.0)
            elapsed_ms = (time.monotonic() - started) * 1000.0
            _log.info(
                "adapter.call.ok",
                adapter="LexicalRerankRetriever",
                operation="retrieve",
                returned=len(reranked),
                candidate_count=len(candidates),
                top_score=top[0][1] if top else 0.0,
                latency_ms=elapsed_ms,
            )
            return reranked


__all__ = ["LexicalRerankRetriever"]
