"""Ingestion-application services.

This package contains the use-case layer that orchestrates the
ingestion ports (``domain/ingestion/ports.py``). Adapters live
in ``adapters/``; this package depends only on the domain
layer, never on SDKs.

Modules
-------

- ``pre_embed_validator`` -- rejects empty / short cleaned pages
  before the embedder runs (M2).
- ``ingestion_lock`` -- TTL-keyed file-based lock for
  concurrent-run protection (M4).
- ``ingestion_service`` -- the top-level orchestrator that
  wires scraper -> cleaner -> validator -> chunker -> embedder
  -> vector store.
"""
