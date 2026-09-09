"""TDD red tests for ``application.ingestion.pre_embed_validator.PreEmbedValidator``.

Per WP03 T027.

The validator is a defence-in-depth check at the application
boundary: even if the cleaner is bypassed (e.g. a future WP
ingests pre-cleaned text from another source), the validator
guarantees that the embedder never receives empty or unusably
short content. This is the second line of defence for misfit M2.
"""
from __future__ import annotations

import pytest

from support_bot.application.ingestion.pre_embed_validator import PreEmbedValidator
from support_bot.domain.ingestion.entities import CleanedPage
from support_bot.domain.shared.errors import SourcePageGarbage


def test_validate_accepts_text_at_min_length() -> None:
    """A page with exactly the minimum length is accepted."""
    validator = PreEmbedValidator(min_cleaned_length=100)
    page = CleanedPage(text="x" * 100, removed_boilerplate_count=0)
    validator.validate(page)  # no raise


def test_validate_accepts_text_above_min_length() -> None:
    """A page longer than the minimum is accepted."""
    validator = PreEmbedValidator(min_cleaned_length=100)
    page = CleanedPage(text="x" * 200, removed_boilerplate_count=0)
    validator.validate(page)


def test_validate_rejects_empty_text() -> None:
    """An empty page raises ``SourcePageGarbage``."""
    validator = PreEmbedValidator(min_cleaned_length=100)
    page = CleanedPage(text="", removed_boilerplate_count=0)
    with pytest.raises(SourcePageGarbage):
        validator.validate(page)


def test_validate_rejects_text_below_min_length() -> None:
    """A page below the minimum raises ``SourcePageGarbage``."""
    validator = PreEmbedValidator(min_cleaned_length=100)
    page = CleanedPage(text="x" * 50, removed_boilerplate_count=0)
    with pytest.raises(SourcePageGarbage):
        validator.validate(page)


def test_validate_default_min_length() -> None:
    """The default minimum is 100 characters."""
    validator = PreEmbedValidator()
    assert validator.min_cleaned_length == 100


def test_validate_custom_min_length() -> None:
    """A custom ``min_cleaned_length`` is respected."""
    validator = PreEmbedValidator(min_cleaned_length=500)
    page = CleanedPage(text="x" * 400, removed_boilerplate_count=0)
    with pytest.raises(SourcePageGarbage):
        validator.validate(page)


def test_validate_zero_min_length_accepts_empty_text() -> None:
    """A zero-min-length validator accepts empty text (no rejection rule)."""
    validator = PreEmbedValidator(min_cleaned_length=0)
    validator.validate(CleanedPage(text="", removed_boilerplate_count=0))
