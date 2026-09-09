"""Production entrypoint for the support-bot API container.

Per WP04 review v1 Issue 1.

The previous ``deploy/start.sh`` shell script called
``uvicorn support_bot.composition.api_app:create_app --factory``
without supplying an ``answering_service_factory``. The
composition root (composition/api_app.py) deliberately refuses
to start without one, so the api container exited with
``ValueError`` on boot.

This module is the production entrypoint. It is invoked from
the container via ``python -m support_bot.composition`` (which
runs ``main()`` below). ``main()`` wires the production
factory into ``create_app()`` and runs uvicorn on the
returned ``FastAPI`` instance -- no shell indirection, no
extra configuration surface.

Why a Python module and not a richer shell script:

- Unit-testable in isolation (see
  ``tests/composition/test_production_entrypoint.py``).
- Keeps the production wiring in a single importable symbol
  that downstream tooling (Helm pre-install hook, smoke
  scripts) can reuse.
- ``Settings()`` is constructed in exactly one place -- the
  composition root -- so secrets are never duplicated into a
  side script.

The entrypoint reads ``HOST`` / ``PORT`` env vars (defaults
match the docker-compose port mapping: 0.0.0.0:8000 inside
the container, mapped to 8080 on the host).
"""
from __future__ import annotations

import os

from fastapi import FastAPI

from support_bot.composition.api_app import create_app
from support_bot.composition.production_factory import (
    create_production_answering_service,
)
from support_bot.composition.settings import Settings

__all__ = ["build_production_app", "main"]


def build_production_app(settings: Settings | None = None) -> FastAPI:
    """Build the production ``FastAPI`` app with the real wiring.

    Args:
        settings: Optional pre-built ``Settings``. When ``None``
            (the default) the entrypoint instantiates one from
            ``os.environ``. Tests inject a stub ``Settings``.

    Returns:
        The ``FastAPI`` app ready to be served by uvicorn.
    """
    resolved = settings if settings is not None else Settings()
    return create_app(
        settings=resolved,
        answering_service_factory=create_production_answering_service,
    )


def main() -> None:
    """Run uvicorn on the production ``FastAPI`` app.

    This is the ``python -m support_bot.composition`` entry point.
    ``HOST`` and ``PORT`` env vars override the defaults so the
    Helm chart and docker-compose can map the container port
    without rebuilding the image.
    """
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    app = build_production_app()
    uvicorn.run(app, host=host, port=port, log_config=None)


if __name__ == "__main__":
    main()
