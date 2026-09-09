"""Answering-domain port interfaces.

Three ports in this module:

- `Retriever` — fetch `RetrievedChunk`s for a question.
- `LowConfidencePolicy` — decide whether to refuse or generate,
  and supply the refusal message.
- `AnswerGenerator` — produce the final answer string.

All three are `typing.Protocol`s owned by the domain and
implemented by adapters in `adapters/` (or, in tests, by
`tests/fakes/`).

Why the `Retriever` and `VectorStore.query` are separate ports:
they share storage (the same Chroma collection) but expose
different APIs. The application layer depends on `Retriever`,
which is the question-shaped surface; storage-level concerns
(upsert, delete, count) stay on `VectorStore`.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

# `RetrievedChunk` is defined in `domain/shared/retrieval.py`
# (post WP01 review v1 Issue 8). Re-exported via `entities` for
# canonical agent-side path; we import from `shared` to keep
# this module dependency-graph simple.
from ..shared.retrieval import RetrievedChunk


@runtime_checkable
class Retriever(Protocol):
    """Fetch `RetrievedChunk`s for a question.

    Implementations live in `adapters/vectorstore_chroma.py`
    (`ChromaRetriever`).

    Contract:
        - Return up to `k` chunks ordered by similarity
          (descending).
        - Raise `VectorStoreUnavailable` on Chroma connection /
          5xx / timeout.
        - Raise `EmptyRetrieval` when the underlying collection
          is empty (informational; the guard node catches it).

    Design choices
    --------------
    The retriever shares its storage with the `VectorStore` port
    (same Chroma collection) but exposes a question-shaped surface
    so the workflow does not depend on vector-store internals.
    `RetrievedChunk.similarity` is in `[0, 1]`; the adapter is
    responsible for converting from distance to similarity if
    needed.
    """

    def retrieve(self, question: str, k: int = 4) -> list[RetrievedChunk]:  # pragma: no cover
        """Fetch top-`k` chunks for `question`. See class docstring."""
        ...  # pragma: no cover


@runtime_checkable
class LowConfidencePolicy(Protocol):
    """Decide whether the agent should refuse or generate.

    Implementations live in `adapters/` (concretely the threshold-
    based default in WP02). The application layer depends on this
    port, **not** on a concrete class, so the policy can be
    swapped (e.g. for a higher-quality learned refusal
    classifier) without changing the graph topology.

    Contract:
        - `should_refuse(chunks)` returns `True` when the agent
          should produce a refusal answer instead of calling the
          LLM.
        - `refusal_message()` returns the static refusal string
          shown to the user when `should_refuse` is `True`.

    Design choices
    --------------
    The default refusal message is fixed in the domain:
    `"I cannot answer based on the available content."` This
    matches spec FR-009 acceptance scenario 1 and is asserted by
    the WP01 TDD target
    `test_stub_policy_refusal_message_is_spec_string`.
    """

    def should_refuse(self, chunks: list[RetrievedChunk]) -> bool:  # pragma: no cover
        """Return `True` if the agent should refuse on `chunks`."""
        ...  # pragma: no cover

    def refusal_message(self) -> str:  # pragma: no cover
        """Return the static refusal string."""
        ...  # pragma: no cover


@runtime_checkable
class AnswerGenerator(Protocol):
    """Produce the final answer string from a question and context.

    Implementations live in `adapters/answerer_openai.py` (the
    default shipped in WP02) and `adapters/answerer_create_agent.py`
    (a future WP opt-in via `ANSWERER_BACKEND=create_agent`).

    Contract:
        - The returned string is the answer shown to the user.
          When the policy refused, the application layer does not
          call this method (M3).
        - On provider error or timeout, raise `LLMUnavailable`.

    Design choices
    --------------
    The **adapter** owns the system prompt that constrains the
    model to answer only from retrieved context; the **domain**
    owns the rule that this constraint must exist (asserted by
    the WP02 TDD target `test_routes_ask_returns_low_confidence_on_empty_retrieval`).
    This split keeps the domain free of LLM-specific language
    while making the constraint auditable per-adapter.

    Why the port is a single method (not a class that holds the
    model and the prompt): we want the application layer to be
    able to swap implementations without changing the graph.
    Future extensions may add a `model_name` parameter to
    `generate` or split it into `prepare` + `generate`; those
    are out of scope for WP01.
    """

    def generate(self, question: str, retrieved: list[RetrievedChunk]) -> str:  # pragma: no cover
        """Generate an answer from `question` and `retrieved` context."""
        ...  # pragma: no cover


__all__ = ["AnswerGenerator", "LowConfidencePolicy", "Retriever"]
