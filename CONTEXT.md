---
context_name: "Support Bot RAG Project"
version: "1"
created: "2026-09-06T10:30:00+00:00"
updated: "2026-09-06T10:30:00+00:00"
---

# Support Bot RAG Project

Single bounded context for the customer-support RAG assistant built for
the VodafoneZiggo internal technical assignment (rendered vendor-neutral
in the spec).

## Language

**SourcePage**:
A fetched HTML page identified by URL, with raw and cleaned text.
_Avoid_: scraped_page, raw_doc, html_doc
_Subsystems_: S1 Ingestion Pipeline
_Files_: src/support_bot/domain/ingestion/entities.py
_Relates to_: Chunk (produces), PageScraper (fetched-by)
_History_:
- 2026-09-06 (001-customer-support-rag-agent): initial definition.

**Chunk**:
A piece of cleaned text with a stable `chunk_id`, parent `source_url`,
ordinal position, and embedding vector reference.
_Avoid_: segment, document_fragment
_Subsystems_: S1 Ingestion Pipeline, S2 Retrieval & Answering
_Files_: src/support_bot/domain/ingestion/entities.py
_Relates to_: SourcePage (derived-from), VectorStore (persisted-by),
RetrievedChunk (instantiates)
_History_:
- 2026-09-06 (001-customer-support-rag-agent): initial definition.

**RetrievedChunk**:
A `Chunk` plus its similarity score to a `Question`, produced by the
retriever.
_Avoid_: hit, search_result
_Subsystems_: S2 Retrieval & Answering
_Files_: src/support_bot/domain/answering/entities.py
_Relates to_: Chunk (specialises), Question (scored-against)
_History_:
- 2026-09-06 (001-customer-support-rag-agent): initial definition.

**Question**:
The raw end-user input string, normalised at the API edge, with the
request_id captured for traceability.
_Avoid_: prompt, user_input, query_string
_Subsystems_: S2 Retrieval & Answering, S3 API & Cross-Cutting Safety
_Files_: src/support_bot/domain/answering/entities.py
_Relates to_: RetrievedChunk (queried-by), Answer (produces)
_History_:
- 2026-09-06 (001-customer-support-rag-agent): initial definition.

**Answer**:
The agent's final response: a string plus a confidence tag and a trace
of node visits.
_Avoid_: response, completion
_Subsystems_: S2 Retrieval & Answering, S3 API & Cross-Cutting Safety
_Files_: src/support_bot/domain/answering/entities.py
_Relates to_: Question (answers), LangGraphWorkflow (produced-by)
_History_:
- 2026-09-06 (001-customer-support-rag-agent): initial definition.

**IngestionRun**:
A record of one ingestion execution (run_id, source_url, status,
started_at, finished_at, chunk_count).
_Avoid_: ingestion_job, build_run
_Subsystems_: S1 Ingestion Pipeline
_Files_: src/support_bot/application/ingestion/ingestion_service.py
_Relates to_: IngestionRunLock (guarded-by), Chunk (produces)
_History_:
- 2026-09-06 (001-customer-support-rag-agent): initial definition.

**AgentState**:
The Pydantic state passed between LangGraph nodes
(`question, retrieved_chunks, answer, confidence, trace`).
_Avoid_: graph_state, workflow_state, message_state
_Subsystems_: S2 Retrieval & Answering
_Files_: src/support_bot/domain/answering/entities.py
_Relates to_: Answer (contains), RetrievedChunk (contains)
_History_:
- 2026-09-06 (001-customer-support-rag-agent): initial definition;
  deliberately Pydantic (LangGraph 1.2.x supports Pydantic state).

**Port**:
A `typing.Protocol` interface declared in `domain/`, implemented by
exactly one or more adapters in `adapters/`.
_Avoid_: interface, contract (keep "contract" for inter-subsystem)
_Subsystems_: S1 Ingestion Pipeline, S2 Retrieval & Answering
_Files_: src/support_bot/domain/ingestion/ports.py,
src/support_bot/domain/answering/ports.py
_Relates to_: Adapter (implemented-by), CompositionRoot (wired-by)
_History_:
- 2026-09-06 (001-customer-support-rag-agent): initial definition.

**Adapter**:
A concrete class in `adapters/` that implements one or more ports.
_Avoid_: driver, gateway (use the hexagonal vocabulary)
_Subsystems_: S1 Ingestion Pipeline, S2 Retrieval & Answering
_Files_: src/support_bot/adapters/vectorstore_chroma.py,
src/support_bot/adapters/answerer_openai.py
_Relates to_: Port (implements), CompositionRoot (selected-by)
_History_:
- 2026-09-06 (001-customer-support-rag-agent): initial definition.

**Composition Root**:
The single place where adapters are wired into application services.
Split across `composition/api_app.py`, `composition/ingestion_main.py`,
and `composition/settings.py`.
_Avoid_: main, entrypoint, bootstrap
_Subsystems_: composition
_Files_: src/support_bot/composition/api_app.py
_Relates to_: Adapter (selects), ApplicationService (wires)
_History_:
- 2026-09-06 (001-customer-support-rag-agent): initial definition.

**LangGraphWorkflow**:
The application service that builds the
`retrieve → guard → generate|refuse` `StateGraph`. Topology stays on
raw `StateGraph`; the `generate` node body is the future swap target
(Markaicode 2026 hybrid).
_Avoid_: agent, rag_chain
_Subsystems_: S2 Retrieval & Answering
_Files_: src/support_bot/application/answering/graph.py
_Relates to_: AgentState (operates-on), Retriever (calls), AnswerGenerator
 (calls)
_History_:
- 2026-09-06 (001-customer-support-rag-agent): initial definition.

**LowConfidencePolicy**:
A port that decides whether to refuse or generate, and supplies the
refusal message. Default impl: threshold-based.
_Avoid_: confidence_checker
_Subsystems_: S2 Retrieval & Answering
_Files_: src/support_bot/domain/answering/ports.py
_Relates to_: RetrievedChunk (decides-on)
_History_:
- 2026-09-06 (001-customer-support-rag-agent): initial definition.

**SecretScrubber**:
The single utility that strips API keys and Chroma URIs from any
string before logging or responding.
_Avoid_: redactor, masker
_Subsystems_: S3 API & Cross-Cutting Safety
_Files_: src/support_bot/adapters/secret_scrubber.py
_Relates to_: ErrorResponseMapper (invoked-by)
_History_:
- 2026-09-06 (001-customer-support-rag-agent): initial definition.

## Relationships

- A **Port** is implemented by exactly one or more **Adapter** classes.
- An **Adapter** is selected and instantiated only at the
  **Composition Root**.
- An **IngestionRun** is guarded by an `IngestionRunLock` and produces
  zero or more **Chunk** entities.
- A **Chunk** is persisted by a `VectorStore` adapter and re-materialised
  as a **RetrievedChunk** during a query.
- A **Question** is the input to a **LangGraphWorkflow**, which produces
  an **Answer** and updates the **AgentState**.
- A **SecretScrubber** is invoked by every error and log path at the API
  edge.

## Flagged Ambiguities

- "Agent" was used to mean both the LangGraph workflow and a future
  `create_agent` adapter — resolved: `LangGraphWorkflow` for the
  topology, `AnswerGenerator` for the adapter (so the `create_agent`
  hybrid swap lands as an adapter, not a workflow rewrite).
- "Vector store" was used to mean both Chroma and the abstract port
  — resolved: `VectorStore` (port) and `Chroma` (adapter implementing
  both `VectorStore` and `Retriever`).
- "Chunking" was used to mean both the algorithm and the service that
  runs it — resolved: `Chunker` (port) and `ChunkingService` (a future
  application service if needed; WP01 ships the port and a default
  adapter).