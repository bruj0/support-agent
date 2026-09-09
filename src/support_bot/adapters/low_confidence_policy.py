"""Threshold-based ``LowConfidencePolicy`` adapter (production default).

Per WP04 T034.

The policy refuses when:

1. The retriever returned no chunks (an empty collection), OR
2. The top-1 chunk similarity is strictly below the configured
   ``threshold``.

The threshold is operator-tunable via the composition root.
The default is ``0.5`` -- safe for cosine-similarity on
Chroma's default distance function, where the top hit on a
relevant query typically lands in ``[0.5, 0.85]`` and a noisy
hit lands below ``0.5``.

Design choices
--------------

The policy is intentionally simple and stateless: no learned
classifier, no calibration, no per-query history. A future
WP may swap in a learned classifier via the same
``LowConfidencePolicy`` port; the application layer does not
need to change.

The refusal message is fixed in the domain
(``domain/answering/ports.py`` -- matches spec FR-009 acceptance
scenario 1 verbatim) so the policy always returns the same
string the spec mandates.
"""
from __future__ import annotations

from support_bot.domain.shared.retrieval import RetrievedChunk

DEFAULT_THRESHOLD = 0.5
SPEC_REFUSAL_MESSAGE = "I cannot answer based on the available content."


class ThresholdLowConfidencePolicy:
    """Threshold-based ``LowConfidencePolicy`` adapter.

    Attributes:
        threshold: The minimum top-1 similarity required to
            NOT refuse. Strictly below this triggers refusal.
    """

    def __init__(self, *, threshold: float = DEFAULT_THRESHOLD) -> None:
        """Initialise the policy.

        Args:
            threshold: Minimum top-1 similarity required to NOT
                refuse. Must be in ``[0.0, 1.0]``.
        """
        if threshold < 0.0 or threshold > 1.0:
            raise ValueError(
                f"threshold ({threshold}) must be in [0.0, 1.0]"
            )
        self.threshold: float = threshold

    def should_refuse(self, chunks: list[RetrievedChunk]) -> bool:
        """Return ``True`` when the agent should refuse.

        Refusal triggers:
        - The chunk list is empty.
        - The top-1 similarity is strictly below ``threshold``.
        """
        if not chunks:
            return True
        top_similarity = max(chunk.similarity for chunk in chunks)
        return top_similarity < self.threshold

    def refusal_message(self) -> str:
        """Return the spec-mandated refusal string."""
        return SPEC_REFUSAL_MESSAGE


__all__ = ["ThresholdLowConfidencePolicy"]
