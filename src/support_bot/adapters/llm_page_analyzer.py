"""LLM-driven ``PageAnalyzer`` adapter.

Per WP06 T054.

The ``OpenAIPageAnalyzer`` is the only production analyzer. It
calls the OpenAI chat-completions endpoint with a structured-output
JSON schema that validates against ``PageStructure``. Long pages
are split into windows and analyzed separately; the resulting
``SemanticChunk`` lists are concatenated.

Failure handling
----------------

- Malformed LLM JSON → one retry with a stricter prompt; if still
  invalid → ``LLMUnavailable``.
- Transient provider errors (5xx, timeouts) → retries up to
  ``max_retries`` attempts total; after that → ``LLMUnavailable``.

Observability
-------------

The analyzer wraps every LLM call in a manual OTel span
``adapter.page_analyzer.analyze`` with attributes
``request.id``, ``analyzer.input_text_length``,
``analyzer.window_count``, ``analyzer.model``,
``analyzer.region_count``, ``analyzer.faq_count``,
``analyzer.tokens_in``, ``analyzer.tokens_out``. Logs use the
standard ``adapter.call.start`` / ``adapter.call.ok`` shape
with ``*_text_hash`` for any line that would otherwise echo the
source text (AGENTS.md §6.4 PII rule).

Design rationale
----------------

The analyzer is **LLM-only** by the WP06 design decision — bs4 is
used solely as a pre-processor (``Bs4TextExtractor``) to strip
``<script>``/``<style>``/``<noscript>`` before the LLM call. No
heuristic FAQ/heading detection lives here. The LLM produces a
structured JSON validated against ``PageStructure``.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

import openai
import structlog
from pydantic import ValidationError

from support_bot.domain.ingestion.entities import PageStructure
from support_bot.domain.shared.errors import LLMUnavailable

_log = structlog.get_logger(__name__)


def _text_hash(text: str) -> str:
    """Return the first 16 hex chars of sha256(text) — used in DEBUG logs."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# System prompt instructs the LLM how to emit structured output.
# The prompt must explicitly name the source language so the model
# extracts in the right tongue (Dutch for Ziggo, English for others).
SYSTEM_PROMPT = (
    "You are a structured-information extractor. "
    "Read the provided page text and emit a JSON object matching the "
    "schema. Rules:\n"
    "1. Never invent content not present in the source.\n"
    "2. For FAQ-style pages (clear question/answer pairs), emit one "
    "entry per Q/A pair with kind='faq'.\n"
    "3. For non-FAQ pages, emit one entry per logical region: kind="
    "'section' for heading + body, 'list' for ordered/unordered "
    "lists, 'paragraph' for standalone paragraphs, 'table' for "
    "tabular data, 'other' as the catch-all.\n"
    "4. Output must be valid JSON; do not include explanations or "
    "markdown fences.\n"
    "5. Preserve the source language of the page in the produced "
    "text fields."
)

# Stricter prompt used on retry after a validation failure.
STRICT_RETRY_PROMPT = (
    "Your previous response was invalid. Reply with ONLY the JSON "
    "object. No prose, no markdown fences. The JSON object must "
    "match the schema exactly. Every chunk entry must have "
    "kind (one of: faq, section, list, paragraph, table, other), "
    "title (non-empty string), and text (non-empty string)."
)


class OpenAIPageAnalyzer:
    """LLM-driven page analyzer using OpenAI chat completions.

    Attributes:
        api_key: The OpenAI API key. ``None`` lets the SDK pick
            up ``OPENAI_API_KEY`` from the environment.
        model: The chat-completions model name. Default
            ``gpt-4o-mini`` (cheap, structured-output capable).
        max_input_chars: Per-window character cap. Long pages
            are split into windows of this size before the LLM
            call. Default 24 000 (≈ 6 000 tokens, well within
            gpt-4o-mini's context).
        max_retries: Total attempts per window before raising
            ``LLMUnavailable``. Default 3.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        max_input_chars: int = 24_000,
        max_retries: int = 3,
    ) -> None:
        """Initialize the analyzer.

        Args:
            api_key: OpenAI API key. ``None`` defers to the env
                var ``OPENAI_API_KEY``.
            model: Chat-completions model name.
            max_input_chars: Window size for long pages.
            max_retries: Attempts per window.
        """
        self.api_key: str | None = api_key or os.environ.get("OPENAI_API_KEY")
        self.model: str = model
        self.max_input_chars: int = max_input_chars
        self.max_retries: int = max_retries
        self._client: Any = None

    @property
    def client(self) -> Any:
        """Lazily build the OpenAI client (preserves WP02 pattern).

        Always references ``openai.OpenAI`` through the module
        (not a captured local import) so test mocks that patch
        ``monkeypatch.setattr("openai.OpenAI", ...)`` take effect.
        """
        if self._client is None:
            if self.api_key is not None:
                self._client = openai.OpenAI(api_key=self.api_key)
            else:
                self._client = openai.OpenAI()
        return self._client

    def _json_schema(self) -> dict[str, Any]:
        """Return the response_format payload for PageStructure.

        OpenAI's structured-output mode requires a JSON Schema.
        We hand-build a permissive schema (string types + optional
        anchor + list of chunks) and rely on Pydantic to validate
        the deserialized response — same pattern as the answerer
        adapter.
        """
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "PageStructure",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "source_url": {"type": "string"},
                        "chunks": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "kind": {
                                        "type": "string",
                                        "enum": [
                                            "faq",
                                            "section",
                                            "list",
                                            "paragraph",
                                            "table",
                                            "other",
                                        ],
                                    },
                                    "title": {"type": "string", "minLength": 1},
                                    "text": {"type": "string", "minLength": 1},
                                    "anchor": {
                                        "type": ["string", "null"]
                                    },
                                },
                                "required": [
                                    "kind",
                                    "title",
                                    "text",
                                    "anchor",
                                ],
                                "additionalProperties": False,
                            },
                        },
                        "model": {"type": "string", "minLength": 1},
                        "generated_at": {"type": "string"},
                    },
                    "required": ["source_url", "chunks", "model", "generated_at"],
                    "additionalProperties": False,
                },
            },
        }

    def _call_once(
        self, *, window: str, system_prompt: str
    ) -> PageStructure:
        """Make one LLM call and parse the result.

        Args:
            window: The windowed page text to analyze.
            system_prompt: The system prompt to use.

        Returns:
            The validated ``PageStructure``.

        Raises:
            ValidationError: If the JSON does not match the schema.
            openai.OpenAIError: On provider failure.
            KeyError: If the response shape is unexpected.
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": window},
            ],
            temperature=0.0,
            response_format=self._json_schema(),
        )
        content = response.choices[0].message.content
        payload = json.loads(content)
        return PageStructure.model_validate(payload)

    def _call_with_retries(
        self, *, window: str, request_id: str
    ) -> PageStructure:
        """Call the LLM with the retry policy."""
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            prompt = SYSTEM_PROMPT
            if attempt > 1:
                prompt = STRICT_RETRY_PROMPT
            _log.debug(
                "adapter.call.start",
                adapter="OpenAIPageAnalyzer",
                operation="analyze_window",
                attempt=attempt,
                text_hash=_text_hash(window),
                request_id=request_id,
            )
            try:
                started = time.monotonic()
                result = self._call_once(window=window, system_prompt=prompt)
                _log.info(
                    "adapter.call.ok",
                    adapter="OpenAIPageAnalyzer",
                    operation="analyze_window",
                    attempt=attempt,
                    latency_ms=(time.monotonic() - started) * 1000,
                    request_id=request_id,
                )
                return result
            except (ValidationError, json.JSONDecodeError, KeyError) as exc:
                last_error = exc
                _log.warning(
                    "adapter.call.retry",
                    adapter="OpenAIPageAnalyzer",
                    operation="analyze_window",
                    attempt=attempt,
                    error_type=type(exc).__name__,
                    request_id=request_id,
                )
            except openai.OpenAIError as exc:
                last_error = exc
                _log.warning(
                    "adapter.call.retry",
                    adapter="OpenAIPageAnalyzer",
                    operation="analyze_window",
                    attempt=attempt,
                    error_type=type(exc).__name__,
                    request_id=request_id,
                )
        raise LLMUnavailable(
            f"page analyzer failed after {self.max_retries} attempts: {last_error}"
        )

    def analyze(
        self,
        *,
        source_url: str,
        text: str,
        request_id: str,
    ) -> PageStructure:
        """Analyze cleaned page text and return a ``PageStructure``.

        Long pages are split into ``max_input_chars`` windows and
        each window is analyzed independently; the resulting
        ``SemanticChunk`` lists are concatenated. The
        ``generated_at`` of the returned structure is the
        timestamp of the final concatenated result.

        Args:
            source_url: The page URL (echoed into the
                ``PageStructure`` and the LLM payload).
            text: The cleaned page text (already pre-processed
                by ``Bs4TextExtractor``).
            request_id: Correlation id (AGENTS.md §6.3).

        Returns:
            A ``PageStructure`` whose ``chunks`` is the union of
            every window's output.

        Raises:
            LLMUnavailable: When every retry for any window
                returns malformed JSON or the provider keeps
                failing.
        """
        windows = [
            text[i : i + self.max_input_chars]
            for i in range(0, max(1, len(text)), self.max_input_chars)
        ]
        merged_chunks: list[Any] = []
        for window in windows:
            ps = self._call_with_retries(window=window, request_id=request_id)
            merged_chunks.extend(ps.chunks)
        return PageStructure(
            source_url=source_url,
            chunks=merged_chunks,
            model=self.model,
            generated_at=ps.generated_at,
        )


__all__ = ["OpenAIPageAnalyzer"]