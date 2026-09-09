"""Domain layer — pure logic, entities, and port interfaces.

The domain layer is the **innermost** layer of the hexagonal
architecture (plan § Phase 0.4). It owns:

- **Entities** — Pydantic models representing the business nouns
  (`SourcePage`, `Chunk`, `Question`, `Answer`, `AgentState`).
- **Ports** — `typing.Protocol` interfaces that the application
  layer depends on. Adapters in `adapters/` implement them.
- **Errors** — typed exception hierarchy that propagates across
  layers and is mapped to HTTP responses by `application/api/`.

The domain **must not** import from any other layer or from any
third-party I/O SDK. The `import-linter` configuration in WP05
enforces this mechanically.
"""