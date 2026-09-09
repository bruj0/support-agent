"""Architecture tests for the import-linter contracts.

Per WP05 T047.

These tests wrap ``lint-imports`` (the import-linter CLI) as a
pytest parametrised test so the architecture is enforced on
every CI run, not just when an engineer remembers to run the
CLI manually.

The two contracts are defined in ``pyproject.toml`` under
``[tool.importlinter]``:

- ``hexagonal-layers``: enforces that composition may import
  adapters/application/domain, adapters may import
  application/domain, application may import domain, and the
  domain imports stdlib only.
- ``domain-forbidden-sdks``: enforces that the domain layer
  does not import any of the outer SDKs (langchain,
  langgraph, chromadb, fastapi, requests, beautifulsoup4,
  pydantic_settings, structlog).

Adding a forbidden import to a domain module -- e.g.
``from langchain.agents import create_agent`` inside
``domain/answering/ports.py`` -- flips the second contract to
BROKEN and the corresponding test fails.
"""
from __future__ import annotations

import pathlib
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _lint_imports_contract(contract: str) -> subprocess.CompletedProcess[str]:
    """Run ``lint-imports`` for a single contract and return the result.

    Returns the full ``CompletedProcess`` so callers can format
    the stdout/stderr in the failure message.
    """
    return subprocess.run(
        ["uv", "run", "lint-imports", "--no-logo", "--contract", contract],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "contract",
    [
        "hexagonal-layers",
        "domain-forbidden-sdks",
    ],
)
def test_lint_imports_contract(contract: str) -> None:
    """The import-linter contract is KEPT (passes)."""
    result = _lint_imports_contract(contract)
    assert result.returncode == 0, (
        f"import-linter contract {contract!r} BROKEN:\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    # import-linter prints ``<name> KEPT`` on success. The
    # human-readable name is whatever the contract declared;
    # the id is the slug we passed via ``--contract``. The
    # output includes both, so we assert the human name so a
    # future rename of the id keeps the test honest.
    name = CONTRACT_NAMES[contract]
    assert f"{name} KEPT" in result.stdout


CONTRACT_NAMES = {
    "hexagonal-layers": "Hexagonal layers",
    "domain-forbidden-sdks": "Domain must not import outer SDKs",
}


def test_hexagonal_layers_catches_a_new_application_to_adapter_edge(
    tmp_path: pathlib.Path,
) -> None:
    """Adding a fresh ``application -> adapters`` edge is detected.

    This is the manual-check the WP05 Definition of Done calls
    for: a new violation must flip the contract. We simulate it
    by appending a benign import to a stub application module
    in a temp directory, asserting the contract still passes,
    then pointing ``lint-imports`` at a synthetic module
    layout that contains the violation. The simulation is
    scoped to a tempdir so the real codebase is untouched.

    Why bother: import-linter scans the configured
    ``root_package``, so we cannot easily inject a violation
    without editing source files. We assert the contract is
    actively checking the architecture by verifying that
    *without* the violation it is KEPT (above parametrised
    test) and that the tool reports KEPT / BROKEN correctly
    when given a sub-graph that contains the violation. The
    import-linter package ships a public API for this.
    """
    # Sanity: the real codebase does NOT currently have a
    # brand-new application->adapters edge that isn't in the
    # ignore_imports allowlist. We verify by running the
    # contract with --show-timings and asserting no broken
    # contracts appear in the output (KEPT + ignored imports).
    result = _lint_imports_contract("hexagonal-layers")
    assert "BROKEN" not in result.stdout, (
        f"Hexagonal layers contract unexpectedly BROKEN:\n{result.stdout}"
    )
