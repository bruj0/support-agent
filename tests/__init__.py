"""Top-level test package marker.

`tests/fakes/test_port_conformance.py` imports
`tests.fakes.answering.*` so `tests/` must be importable as a
package. Pytest auto-discovers tests under `testspaths = ["tests"]`
per `pyproject.toml`; this marker file makes
`import tests.fakes.answering.answer_generator` work.

The `tests/` package itself does not contain production code; the
production package is `support_bot.*` under `src/`.
"""