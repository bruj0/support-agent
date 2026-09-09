"""Support Bot — customer-support RAG agent.

Top-level package marker. The hexagonal layering rules
(see plan § Phase 0.4) start here: every layer below
(`domain`, `application`, `adapters`, `composition`) follows the
inward-pointing dependency rule, and only the composition root
(`composition/*`) wires adapters into application services.

The single bounded context of this project is defined in the
project-root `CONTEXT.md`. Domain terms: `SourcePage`, `Chunk`,
`RetrievedChunk`, `Question`, `Answer`, `AgentState`, `Port`,
`Adapter`, `CompositionRoot`, `LangGraphWorkflow`,
`LowConfidencePolicy`, `SecretScrubber`.
"""