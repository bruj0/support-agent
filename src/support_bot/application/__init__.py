"""Application layer: use cases and orchestration.

Hexagonal layering (AGENTS.md 1.1): this layer imports from
``domain/`` only. SDKs, FastAPI, and pydantic-settings live in
``adapters/`` and ``composition/``.
"""
