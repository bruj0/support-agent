# syntax=docker/dockerfile:1.7
#
# Multi-stage Dockerfile for the support-bot ingestion Job.
# Per WP03 T031.
#
# Stage 1 (builder): install uv, resolve the locked dependency
# tree, and build the support_bot wheel.
#
# Stage 2 (runtime): copy the wheel + the support_bot source
# into a slim image, install the wheel, switch to a non-root
# user, and set the entry point to the ingestion CLI.

ARG PYTHON_VERSION=3.11.9
ARG DEBIAN_RELEASE=bookworm

# ---- builder ---------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_RELEASE} AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1

# Install uv from the official image so we don't rely on
# network calls during the build (the uv binary is tiny).
COPY --from=ghcr.io/astral-sh/uv:0.4.18 /uv /usr/local/bin/uv

WORKDIR /build

# Copy only the dependency manifests first so Docker can
# cache the dependency layer across source-only edits.
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
# (we will copy the entire ``/usr/local`` tree to the runtime
# stage below).
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
# (The builder installs everything into the system Python
# prefix; we mirror the same prefix here.)
COPY --from=builder /usr/local/lib/python${PYTHON_VERSION%.*}/site-packages /usr/local/lib/python${PYTHON_VERSION%.*}/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Install the support_bot wheel.
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl \
    && rm -rf /wheels

# Create the lock directory and grant the app user write
# access. The ingestion Job creates ``<lock_dir>/<rid>.lock``
# on every run, so the directory must exist and be writable.
RUN mkdir -p /var/run/support-bot && chown -R app:app /var/run/support-bot

USER app
WORKDIR /home/app

# The default entry point is the ingestion CLI; args are
# supplied at runtime via Helm Job ``args``.
ENTRYPOINT ["python", "-m", "support_bot.composition.ingestion_main"]
CMD []

# Health / readiness: no long-running process; the Job exits
# when ingestion completes. ``HEALTHCHECK`` is omitted on
# purpose (the Job pattern does not benefit from one).
