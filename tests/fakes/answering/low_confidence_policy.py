"""In-memory `StubLowConfidencePolicy` for unit and contract tests.

Has two dials so tests can drive both paths:

- `should_refuse_return`: the value the policy returns from
  `should_refuse` regardless of input.
- `refusal_message_return`: the value returned from
  `refusal_message`.

The default refusal message matches spec FR-009 acceptance
scenario 1 verbatim. Asserted by the WP01 TDD target
`test_stub_policy_refusal_message_is_spec_string`.
"""
from __future__ import annotations

from support_bot.domain.answering.entities import RetrievedChunk


class StubLowConfidencePolicy:
    """Canned `LowConfidencePolicy` with configurable decisions.

    Attributes:
        should_refuse_return: Value returned from
            `should_refuse` regardless of input. Defaults to
            `False` so tests opt into the refusal path
            explicitly.
        refusal_message_return: Value returned from
            `refusal_message`. Defaults to the spec-mandated
            refusal string.
        should_refuse_calls: List of inputs that have been
            decided (read-only introspection).
    """

    DEFAULT_REFUSAL = "I cannot answer based on the available content."

    def __init__(
        self,
        *,
        should_refuse_return: bool = False,
        refusal_message_return: str = DEFAULT_REFUSAL,
    ) -> None:
        self.should_refuse_return: bool = should_refuse_return
        self.refusal_message_return: str = refusal_message_return
        self.should_refuse_calls: list[list[RetrievedChunk]] = []

    def should_refuse(self, chunks: list[RetrievedChunk]) -> bool:
        self.should_refuse_calls.append(list(chunks))
        if not chunks:
            # Per M3 the policy must refuse on empty retrieval.
            # The stub mirrors this behaviour regardless of the
            # `should_refuse_return` dial so the assertion
            # `test_stub_policy_refuses_empty_retrieval` holds
            # for a freshly-constructed policy. Tests that want
            # to exercise the generate path pass non-empty
            # `chunks` and the dial controls the outcome.
            return True
        return self.should_refuse_return

    def refusal_message(self) -> str:
        return self.refusal_message_return


__all__ = ["StubLowConfidencePolicy"]