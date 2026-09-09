"""TDD red tests for ``adapters.low_confidence_policy.ThresholdLowConfidencePolicy``.

Per WP04 T034 + AGENTS.md §3.3 vocabulary.

The threshold-based policy is the default production
implementation of the ``LowConfidencePolicy`` port. It refuses
when the top-1 similarity is below ``threshold`` OR when the
collection returned no chunks (an empty retrieval).
"""
from __future__ import annotations

import pytest

from support_bot.adapters.low_confidence_policy import (
    ThresholdLowConfidencePolicy,
)
from support_bot.domain.shared.retrieval import RetrievedChunk


def _chunk(similarity: float = 0.9, *, text: str = "x") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="a" * 40,
        text=text,
        source_url="https://example.com/",
        similarity=similarity,
    )


def test_refuses_on_empty_retrieval() -> None:
    """An empty retrieval triggers refusal."""
    policy = ThresholdLowConfidencePolicy(threshold=0.5)
    assert policy.should_refuse([]) is True


def test_refuses_when_top_similarity_below_threshold() -> None:
    """A top-1 similarity below the threshold triggers refusal."""
    policy = ThresholdLowConfidencePolicy(threshold=0.5)
    assert policy.should_refuse([_chunk(0.1), _chunk(0.05)]) is True


def test_does_not_refuse_when_top_similarity_at_threshold() -> None:
    """A top-1 similarity exactly equal to the threshold does NOT refuse."""
    policy = ThresholdLowConfidencePolicy(threshold=0.5)
    assert policy.should_refuse([_chunk(0.5)]) is False


def test_does_not_refuse_when_top_similarity_above_threshold() -> None:
    """A top-1 similarity above the threshold does NOT refuse."""
    policy = ThresholdLowConfidencePolicy(threshold=0.5)
    assert policy.should_refuse([_chunk(0.9)]) is False


def test_refusal_message_matches_spec_string() -> None:
    """The refusal message matches the spec-mandated string (FR-009)."""
    policy = ThresholdLowConfidencePolicy()
    assert policy.refusal_message() == "I cannot answer based on the available content."


def test_default_threshold_is_sensible() -> None:
    """The default threshold is non-empty (operator-tunable, not 0)."""
    policy = ThresholdLowConfidencePolicy()
    assert policy.threshold > 0.0


def test_custom_threshold() -> None:
    """A custom threshold is respected."""
    policy = ThresholdLowConfidencePolicy(threshold=0.8)
    assert policy.should_refuse([_chunk(0.7)]) is True
    assert policy.should_refuse([_chunk(0.85)]) is False
