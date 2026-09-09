"""M3 foundation: refusal is decided at the port boundary.

The system must not invent an answer when retrieval returns zero
chunks (M3). This test asserts that the `StubLowConfidencePolicy`
refuses on empty input, and that the refusal message matches the
spec FR-009 acceptance scenario 1.

This is a *failing* test when first written — it commits before the
policy stub is implemented, per the test-first mandate (FR-007).
"""
from __future__ import annotations

from support_bot.domain.answering.entities import RetrievedChunk
from tests.fakes.answering.low_confidence_policy import StubLowConfidencePolicy


class TestStubLowConfidencePolicyRefusesEmpty:
    """The stub refuses empty retrieval — see plan § Phase 0.5."""

    def test_stub_policy_refuses_empty_retrieval(self) -> None:
        policy = StubLowConfidencePolicy()
        assert policy.should_refuse([]) is True

    def test_stub_policy_refusal_message_is_spec_string(self) -> None:
        policy = StubLowConfidencePolicy()
        assert policy.refusal_message() == (
            "I cannot answer based on the available content."
        )

    def test_stub_policy_accepts_when_should_refuse_return_is_false(self) -> None:
        policy = StubLowConfidencePolicy(should_refuse_return=False)
        # When should_refuse_return is False and chunks are
        # non-empty, the policy must NOT refuse. (Empty retrieval
        # is always refused — see the previous test — so we
        # pass a dummy chunk here.)
        dummy = RetrievedChunk(
            chunk_id="a" * 40, text="x",
            source_url="u", similarity=0.5,
        )
        assert policy.should_refuse([dummy]) is False


def test_module_is_importable() -> None:
    """Sanity: the module under test is importable."""
    assert StubLowConfidencePolicy is not None