"""In-memory fakes that implement every domain port.

These fakes power the application tests in WP02 and the adapter
contract tests in WP03. Every fake declares `fail_next: bool` (or a
per-method equivalent) so failure-injection tests can drive it into
raising the appropriate typed exception.

Every fake carries a Google-style docstring explaining what is faked
and what is *not* (e.g. `FakeVectorStore` is not thread-safe).
"""