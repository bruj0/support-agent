"""Adapter layer: concrete implementations of domain ports.

Hexagonal layering (AGENTS.md 1.1): this package implements the
ports declared under ``domain/<subsystem>/ports.py``. SDKs
(chromadb, httpx, sentence-transformers, etc.) and
``prometheus_client`` live here.
"""
