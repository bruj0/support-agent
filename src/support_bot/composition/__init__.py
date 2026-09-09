"""Composition root.

The composition root is the *only* layer allowed to import
from every other layer. It builds the FastAPI app, wires ports
to adapters, configures observability, and registers
middleware. Adapter choice is a one-line change here
(AGENTS.md 1.3).

Hexagonal layering (AGENTS.md 1.1): this package may import
from ``domain/``, ``application/``, ``adapters/``, plus all
third-party SDKs.
"""
