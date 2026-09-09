"""Shared domain helpers — exception hierarchy + cross-subsystem entities.

The `shared/` package exists so the two sub-packages
(`ingestion/` and `answering/`) can share types without
introducing a one-way import from one sub-package into the
other. Currently holds:

- `errors.py` — typed exception hierarchy (DomainError and
  subclasses; raised by adapters and caught by the application
  layer).
- `retrieval.py` — `RetrievedChunk`, used by both the
  ingestion `VectorStore.query` port and the answering
  `Retriever` port.
"""
from .errors import (
    ConfigurationError,
    DomainError,
    EmbedderUnavailable,
    EmptyRetrieval,
    LLMUnavailable,
    SourcePageGarbage,
    SourcePageUnreachable,
    VectorStoreUnavailable,
)
from .retrieval import RetrievedChunk

__all__ = [
    "ConfigurationError",
    "DomainError",
    "EmbedderUnavailable",
    "EmptyRetrieval",
    "LLMUnavailable",
    "RetrievedChunk",
    "SourcePageGarbage",
    "SourcePageUnreachable",
    "VectorStoreUnavailable",
]
