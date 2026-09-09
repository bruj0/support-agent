"""Application API layer.

Hexagonal layering (AGENTS.md 1.1): this sub-package contains
the FastAPI middleware, error mapper, and router glue. It may
import from ``domain/`` and may import ``fastapi`` because that
is part of the application-layer's HTTP-bound surface; it must
NOT import from ``adapters/`` or ``composition/``.
"""
