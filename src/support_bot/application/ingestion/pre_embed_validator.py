"""Pre-embed content validator.

Per WP03 T027.

This is the application-layer defence-in-depth check for misfit
M2: even if the ``BoilerplatePageCleaner`` is bypassed by a
future ingestion path (e.g. ingesting pre-cleaned text from a
CMS), this validator guarantees that the embedder never receives
empty or unusably short content. The cleaner also raises
``SourcePageGarbage`` for short text, but the validator is the
explicit boundary check the application layer relies on.

Design choices
--------------

The validator is a single-method class (no state) so the
application layer can pass it around as a callable. We keep it
in ``application/`` (not ``adapters/``) because it carries no
SDK dependencies and is part of the orchestration logic, not
an external-service wrapper.
"""
from __future__ import annotations

import structlog

from support_bot.domain.ingestion.entities import CleanedPage
from support_bot.domain.shared.errors import SourcePageGarbage

_log = structlog.get_logger(__name__)


class PreEmbedValidator:
    """Reject ``CleanedPage`` content too short to embed meaningfully.

    Attributes:
        min_cleaned_length: Minimum acceptable text length.
            Defaults to ``100`` to match the cleaner's default.
    """

    def __init__(self, *, min_cleaned_length: int = 100) -> None:
        """Initialise the validator.

        Args:
            min_cleaned_length: Minimum acceptable text length.
        """
        self.min_cleaned_length: int = min_cleaned_length

    def validate(self, cleaned: CleanedPage) -> None:
        """Raise ``SourcePageGarbage`` if ``cleaned.text`` is too short.

        Args:
            cleaned: The cleaned page from the boilerplate cleaner.

        Raises:
            SourcePageGarbage: When ``cleaned.text`` is empty
                or shorter than ``min_cleaned_length``.
        """
        length = len(cleaned.text)
        if length < self.min_cleaned_length:
            _log.debug(
                "pre_embed_validator.rejected",
                cleaned_length=length,
                min_cleaned_length=self.min_cleaned_length,
            )
            raise SourcePageGarbage(
                f"cleaned text shorter than {self.min_cleaned_length} chars"
            )


__all__ = ["PreEmbedValidator"]
