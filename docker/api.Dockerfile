# syntax=docker/dockerfile:1.7
#
# Multi-stage Dockerfile for the support-bot FastAPI service.
# Per WP04 T033.
#
# Stage 1 (builder): install uv, resolve the locked dependency
# tree, and build the support_bot wheel.
#
# Stage 2 (runtime): copy the wheel + the support_bot source
# into a slim image, install the wheel, switch to a non-root
# user, and expose port 8000 for uvicorn.
#
# The runtime ENTRYPOINT boots the FastAPI composition root
# (``support_bot.composition.api_app:create_app`` -- the
# ``--factory`` flag tells uvicorn to call ``create_app()``
# with no arguments, which builds the production wiring from
# env vars via ``Settings``).

ARG PYTHON_VERSION=3.11.9
ARG DEBIAN_RELEASE=bookworm

# ---- builder ---------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_RELEASE} AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1

COPY --from=ghcr.io/astral-sh/uv:0.4.18 /uv /usr/local/bin/uv

WORKDIR /build

# Copy the locked dependency manifests first so the dependency
# layer is cached across source-only edits.
COPY pyproject.toml uv.lock ./

# Export the locked dependency tree to a ``requirements.txt``
# so the runtime stage can install the exact same versions
# without re-running the resolver. ``uv export`` honours the
# lockfile and the ``--no-dev`` constraint. We strip the
# self-editable entry (``-e file:///build``) because the
# package is installed later via the built wheel.
RUN uv export --no-dev --frozen --format requirements-txt \
        --output-file /tmp/requirements.txt \
 && grep -v '^-e ' /tmp/requirements.txt > /tmp/requirements.clean.txt \
 && mv /tmp/requirements.clean.txt /tmp/requirements.txt

# Install the resolved dependencies into the system Python
# (the runtime stage copies the same prefix below).
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Now copy the source and build the wheel.
COPY src ./src
COPY README.md ./
RUN uv build --wheel --out-dir /wheels

# ---- runtime ---------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_RELEASE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Create a non-root user and group up-front so file ownership
# is correct from the very first layer.
RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --no-create-home app

# Copy the resolved dependency tree from the builder.
COPY --from=builder /usr/local/lib/python${PYTHON_VERSION%.*}/site-packages /usr/local/lib/python${PYTHON_VERSION%.*}/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Install the support_bot wheel.
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl \
    && rm -rf /wheels

# Drop root privileges before declaring the runtime defaults.
# ``USER`` must precede ``ENTRYPOINT`` so the runtime UID
# owns the workdir and any files written at runtime.
USER app
WORKDIR /home/app

# Expose the FastAPI port (per WP04 T033).
EXPOSE 8000

# The composition root builds the production wiring from
# ``Settings()`` (env vars). Per WP04 review v1 Issue 1 we
# switched from ``deploy/start.sh`` (which called ``create_app``
# without an answering_service_factory and exited with
# ``ValueError``) to a Python entrypoint at
# ``support_bot.composition.__main__`` that wires
# ``create_production_answering_service`` into ``create_app``
# before running uvicorn programmatically. The entrypoint is
# unit-tested in ``tests/composition/test_production_entrypoint.py``.
ENTRYPOINT ["python", "-m", "support_bot.composition"]
CMD []
