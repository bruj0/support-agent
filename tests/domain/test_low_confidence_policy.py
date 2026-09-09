"""Tests for the answering-domain ports and their fakes.

These tests are the **first** tests committed in WP01. They prove
that the misfit-derived behaviors (M3 refusal, M6 typed exception,
M8 LLM not called on empty retrieval) are wired at the *port*
boundary, before any application code lands.
"""