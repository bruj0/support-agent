"""Architecture tests for the Helm chart.

Per WP05 T048.

Three classes of check:

1. **Template renders all required resources** for every
   shipped values file (``values-dev.yaml``, ``values-prod.yaml``).
   The chart must emit at minimum a ``Deployment``, a
   ``Service``, a ``ConfigMap``, a ``Secret``, a
   ``PersistentVolumeClaim``, and a ``Job``.
2. **The rendered manifest contains no literal API keys.**
   ``Secret.value`` must be empty at render time so the
   operator must supply keys via ``--set`` or an external
   secret manager (M7 / NFR-003).
3. **``helm lint`` exits 0** so the chart passes basic schema
   and value validation.

These tests require ``helm`` on ``PATH``. They are CI-gated
and run in the ``.github/workflows/ci.yml`` job added by WP05.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "deploy" / "helm" / "support-bot"

REQUIRED_KINDS = (
    "Deployment",
    "Service",
    "ConfigMap",
    "Secret",
    "PersistentVolumeClaim",
    "Job",
)

# ConfigMap keys that MUST be rendered by ``helm template`` so the
# API + ingestion containers see every setting the application
# reads via ``composition.settings``. Each key is asserted against
# the pattern ``KEY: "value"`` (Helm renders quoted strings).
REQUIRED_CONFIGMAP_KEYS = (
    "SOURCE_URL",
    "CHROMA_HOST",
    "CHROMA_PORT",
    "LOG_LEVEL",
    "ANSWERER_BACKEND",
    "EMBEDDER_BACKEND",
    # WP06 — semantic analyzer + hybrid chunker backends.
    "ANALYZER_BACKEND",
    "CHUNKER_BACKEND",
    "OPENAI_PAGE_ANALYZER_MODEL",
    "LOW_CONFIDENCE_THRESHOLD",
)

OPENAI_KEY_REGEX = re.compile(r"sk-[A-Za-z0-9]{32,}")


def _helm_available() -> bool:
    """Return True when the helm CLI is on PATH."""
    return shutil.which("helm") is not None


def _helm_template(values_file: pathlib.Path) -> str:
    """Render the chart with the given values file; return stdout."""
    result = subprocess.run(
        [
            "helm",
            "template",
            "support-bot",
            str(CHART),
            "--values",
            str(values_file),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _render(values_file: str) -> str:
    """Render the chart against the named values file in the chart dir.

    The values schema requires a non-empty ``secret.openaiApiKey`` (see
    WP05 v1 review Issue 1 / values.schema.json), so we always pass a
    short placeholder that satisfies the schema's ``minLength`` check
    but is short enough not to match the secret-scan regex.
    """
    return _helm_template_with_overrides(
        [
            "--values",
            str(CHART / values_file),
            "--set",
            "secret.openaiApiKey=sk-AAAAAAAAAAAAAAAAAAAA",
        ],
    ).stdout


@pytest.mark.skipif(not _helm_available(), reason="helm CLI not on PATH")
@pytest.mark.parametrize("values_file", ["values-dev.yaml", "values-prod.yaml"])
def test_helm_template_renders_all_required_resources(values_file: str) -> None:
    """``helm template`` with each shipped values file emits every required kind."""
    rendered = _render(values_file)
    for kind in REQUIRED_KINDS:
        assert f"kind: {kind}" in rendered, (
            f"Rendered manifest for {values_file} is missing kind={kind}"
        )


@pytest.mark.skipif(not _helm_available(), reason="helm CLI not on PATH")
@pytest.mark.parametrize("values_file", ["values-dev.yaml", "values-prod.yaml"])
@pytest.mark.parametrize("configmap_key", REQUIRED_CONFIGMAP_KEYS)
def test_helm_template_renders_required_configmap_keys(
    values_file: str, configmap_key: str
) -> None:
    """Every ``Settings`` env var must reach the rendered ConfigMap.

    Driven by ``REQUIRED_CONFIGMAP_KEYS``. Adding a new key to
    ``composition.settings.Settings`` MUST be reflected in the chart
    ConfigMap; this test fails fast if the wiring is missed. WP06
    added ``ANALYZER_BACKEND``, ``CHUNKER_BACKEND``, and
    ``OPENAI_PAGE_ANALYZER_MODEL``.
    """
    rendered = _render(values_file)
    needle = f"{configmap_key}:"
    assert needle in rendered, (
        f"Rendered manifest for {values_file} is missing ConfigMap key "
        f"{configmap_key!r}. Update deploy/helm/support-bot/templates/"
        f"configmap.yaml and values.schema.json."
    )


@pytest.mark.skipif(not _helm_available(), reason="helm CLI not on PATH")
def test_helm_template_does_not_contain_secret_values() -> None:
    """The rendered manifest contains no literal OpenAI-style keys (NFR-003).

    We pass a deliberately short placeholder (``sk-AAAA`` -- 7 base62 chars)
    that is long enough to satisfy the schema's ``minLength`` check but short
    enough not to match the 32+-char regex used to detect a real OpenAI key.
    This separates the two concerns: the schema enforces non-empty + sk-
    prefix, the secret-scan enforces no-real-keys-baked-in.
    """
    rendered = _helm_template_with_overrides(
        [
            "--set",
            "secret.openaiApiKey=sk-AAAAAAAAAAAAAAAAAAAA",
        ],
    ).stdout
    matches = OPENAI_KEY_REGEX.findall(rendered)
    assert not matches, (
        f"Rendered manifest contains {len(matches)} literal OpenAI-style key(s): "
        f"{matches[:3]}... Secret values must be supplied at install time, not "
        "baked into the chart."
    )


@pytest.mark.skipif(not _helm_available(), reason="helm CLI not on PATH")
def test_helm_lint_passes_with_valid_overrides() -> None:
    """``helm lint --set secret.openaiApiKey=...`` exits 0 (basic chart + value validation).

    ``helm lint`` validates values against ``values.schema.json``, so a
    chart with empty defaults (which is the NFR-003 contract: secrets MUST
    be supplied at install time) will FAIL lint by default. That is the
    intended M7 behaviour -- a misconfigured install fails fast at the
    client. This test asserts that lint PASSES once the operator supplies
    a valid ``secret.openaiApiKey`` override.
    """
    result = subprocess.run(
        [
            "helm",
            "lint",
            str(CHART),
            "--values",
            str(CHART / "values-dev.yaml"),
            "--set",
            "secret.openaiApiKey=sk-AAAAAAAAAAAAAAAAAAAA",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"helm lint with valid overrides failed (rc={result.returncode}):\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


@pytest.mark.skipif(not _helm_available(), reason="helm CLI not on PATH")
def test_helm_lint_rejects_default_empty_values() -> None:
    """``helm lint`` (no overrides) exits non-zero with a clear error.

    This is the structural M7 fix -- the chart ships with intentionally
    empty ``secret.openaiApiKey`` defaults (NFR-003: secrets MUST be supplied
    at install time), and the JSON schema rejects those empty defaults so
    that ``helm lint`` catches a misconfigured install at the client
    without ever contacting the cluster. This test pins that behaviour.
    """
    result = subprocess.run(
        ["helm", "lint", str(CHART)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0, (
        "helm lint succeeded with empty secret.openaiApiKey -- the schema "
        "is no longer enforcing the non-empty contract.\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "openaiApiKey" in combined, (
        "helm lint failed but the error does not mention openaiApiKey.\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


def _helm_template_with_overrides(overrides: list[str]) -> subprocess.CompletedProcess[str]:
    """Run ``helm template`` with the given ``--set`` overrides; return the result.

    The chart is rendered against ``values-dev.yaml`` (the operator-facing
    baseline) plus whatever overrides the caller wants to test.
    """
    return subprocess.run(
        [
            "helm",
            "template",
            "support-bot",
            str(CHART),
            "--values",
            str(CHART / "values-dev.yaml"),
            *overrides,
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.skipif(not _helm_available(), reason="helm CLI not on PATH")
def test_helm_schema_rejects_empty_openai_api_key() -> None:
    """A bad install with an empty ``secret.openaiApiKey`` must fail fast.

    Per WP05 v1 review (Issue 1, M7 resolution): Helm 3 validates values
    against ``values.schema.json`` BEFORE rendering any templates. A bad
    install must therefore fail at the client with a non-zero exit code
    rather than hanging in ``pending-install`` the way the previous
    pre-install-hook implementation did.
    """
    result = _helm_template_with_overrides(
        [
            "--set",
            "secret.openaiApiKey=",
            "--set",
            "config.sourceUrl=https://example.com/internet",
        ],
    )
    assert result.returncode != 0, (
        "helm template succeeded with an empty openaiApiKey -- the chart "
        "is missing values.schema.json or the schema does not enforce a "
        "non-empty secret.openaiApiKey. M7 is not resolved.\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    assert "openaiApiKey" in result.stderr or "openaiApiKey" in result.stdout, (
        "helm template failed but the error message does not mention "
        "openaiApiKey -- operators will not know how to fix the install.\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


@pytest.mark.skipif(not _helm_available(), reason="helm CLI not on PATH")
def test_helm_schema_rejects_missing_source_url() -> None:
    """A bad install with an empty ``config.sourceUrl`` must fail fast.

    Symmetric to ``test_helm_schema_rejects_empty_openai_api_key``: the
    schema must also reject an empty ``config.sourceUrl`` because the
    ingestion pipeline cannot scrape an unset URL (M7).
    """
    result = _helm_template_with_overrides(
        [
            "--set",
            "secret.openaiApiKey=sk-test1234567890abcdefghij",
            "--set",
            "config.sourceUrl=",
        ],
    )
    assert result.returncode != 0, (
        "helm template succeeded with an empty sourceUrl -- the chart is "
        "missing values.schema.json or the schema does not enforce a "
        "non-empty config.sourceUrl.\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    assert "sourceUrl" in result.stderr or "sourceUrl" in result.stdout, (
        "helm template failed but the error message does not mention "
        "sourceUrl -- operators will not know how to fix the install.\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


@pytest.mark.skipif(not _helm_available(), reason="helm CLI not on PATH")
def test_helm_schema_rejects_malformed_openai_api_key() -> None:
    """A bad install with a non-OpenAI-shaped ``secret.openaiApiKey`` must fail fast.

    The schema enforces a ``sk-...`` prefix so that operators catch
    typos (e.g. pasting the Chroma token into the OpenAI slot) at install
    time rather than at first request.
    """
    result = _helm_template_with_overrides(
        [
            "--set",
            "secret.openaiApiKey=this-is-not-an-openai-key",
            "--set",
            "config.sourceUrl=https://example.com/internet",
        ],
    )
    assert result.returncode != 0, (
        "helm template succeeded with a malformed openaiApiKey -- the "
        "schema should reject anything that does not match sk-<base62>.\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


@pytest.mark.skipif(not _helm_available(), reason="helm CLI not on PATH")
def test_helm_schema_accepts_valid_values() -> None:
    """A well-formed install must still succeed end-to-end.

    The schema must not be so strict that the happy path breaks. This
    test exercises the values-dev.yaml baseline plus two valid overrides
    (sk-prefixed key, https URL) and asserts the chart renders to a
    successful manifest.
    """
    result = _helm_template_with_overrides(
        [
            "--set",
            "secret.openaiApiKey=sk-test1234567890abcdefghijklmnopqrstuvwxyz",
            "--set",
            "config.sourceUrl=https://example.com/internet",
        ],
    )
    assert result.returncode == 0, (
        "helm template failed with valid values -- the schema is too strict.\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
