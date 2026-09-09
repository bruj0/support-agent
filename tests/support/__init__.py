"""Test-only helpers for building the FastAPI app with fakes.

These helpers exist so that ``composition/api_app.py`` does not
need to import from ``tests/`` at runtime (AGENTS.md 1.1).
Production code paths never see this module; it is on the test
PYTHONPATH via ``pyproject.toml [tool.pytest.ini_options]``.
"""
