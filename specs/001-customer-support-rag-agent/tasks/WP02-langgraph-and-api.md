---
work_package_id: "WP02"
title: "LangGraph workflow + API composition"
lane: "done"
dependencies: ["WP01"]
tdd_red_clean: true
build_validated: true
review_status: "approved"
reviewed_by: "spec-bridge-review"
review_feedback: "Review v1 feedback: 10 issues (4 major + 5 minor + 1 informational) (composition imports tests/fakes; Prometheus series defined but never recorded; AGENTS 6.4 span attributes route/question.text_hash/answer.tokens_in missing; InMemorySpanExporter tests absent), 5 minor (dead except block in AnsweringService; service.version hardcoded; missing test for request.id on top-level span; unused metrics_registry; ruff import-sort fix needed). Re-review after fixes; see specs/001-customer-support-rag-agent/tasks/WP02-review-summary-v1.json."
subsystem: "S2 Retrieval & Answering + S3 API & Cross-Cutting Safety"
misfits_addressed: ["M3 (low-confidence path)", "M5 (secret scrubbing)", "M6 (Chroma-down mapping)", "M8 (LLM hallucination constraint)"]
abstract_components:
  - "application/answering/graph.py"
  - "application/answering/answering_service.py"
  - "application/api/error_mapper.py"
  - "application/api/middleware.py"
  - "application/api/routes.py"
  - "composition/api_app.py"
  - "composition/settings.py"
  - "composition/observability.py"
  - "adapters/secret_scrubber.py"
  - "adapters/structured_logger.py"
  - "adapters/metrics.py"
agent: "spec-bridge-implement"
history:
  - timestamp: "2026-09-06T16:00:00+00:00"
    lane: "doing"
    agent: "spec-bridge-implement"
    action: "starting WP02 implementation -- LangGraph workflow + FastAPI + OTel + single-ID propagation per AGENTS.md"
  - timestamp: "2026-09-06T16:30:00+00:00"
    lane: "doing"
    agent: "spec-bridge-implement"
    action: "tdd red phase clean -- 34 TDD red tests committed in 213572c (tests/conftest.py + tests/application/api/ + tests/application/answering/ + tests/composition/)"
  - timestamp: "2026-09-06T17:00:00+00:00"
    lane: "doing"
    agent: "spec-bridge-implement"
    action: "domain.green: EmbedderUnavailable added to errors.py (AGENTS 8 mapping)"
  - timestamp: "2026-09-06T17:30:00+00:00"
    lane: "doing"
    agent: "spec-bridge-implement"
    action: "adapters.green: SecretScrubber (structlog processor + OTel span filter); composition.green: Settings + init_tracing/shutdown_tracing; application.green: LangGraphWorkflow + AgentState.request_id + AnsweringService(request_id=...) + structured_logger.configure_logging"
  - timestamp: "2026-09-06T18:00:00+00:00"
    lane: "doing"
    agent: "spec-bridge-implement"
    action: "application.api.green: RequestIdMiddleware (FIRST in FastAPI chain), ErrorResponseMapper (DomainError -> HTTP per AGENTS 8), routes (POST /ask + GET /healthz + GET /metrics); composition.api_app.create_app wires everything; adapters.metrics.build_registry for the four AGENTS 6.6 series"
  - timestamp: "2026-09-06T18:30:00+00:00"
    lane: "doing"
    agent: "spec-bridge-implement"
    action: "build validated -- 111 tests passed; mypy --strict clean on application/ + composition/; interrogate --fail-under=100 PASSED; ruff check clean; pytest --cov=src/support_bot/application --cov-fail-under=90 reaches 97.20%; outer-SDK scan clean (langgraph import is in the dedicated workflow module per AGENTS 1.5)"
  - timestamp: "2026-09-06T18:35:00+00:00"
    lane: "for_review"
    agent: "spec-bridge-implement"
    action: "implementation complete -- handed off to spec-bridge-review"
  - timestamp: "2026-09-06T19:00:00+00:00"
    lane: "doing"
    agent: "spec-bridge-review"
    action: "review started"
  - timestamp: "2026-09-06T19:30:00+00:00"
    lane: "planned"
    agent: "spec-bridge-review"
    action: "changes requested: 10 issues (4 major + 5 minor + 1 informational); see WP02-review-summary-v1.json"
  - timestamp: "2026-09-06T20:00:00+00:00"
    lane: "doing"
    agent: "spec-bridge-implement"
    action: "resuming implementation to address review v1 issues (1, 2, 3, 4, 5, 6, 7, 8, 9); reusing worktree"
  - timestamp: "2026-09-06T20:30:00+00:00"
    lane: "doing"
    agent: "spec-bridge-implement"
    action: "build validated -- 116 tests passed (added 5 InMemorySpanExporter tests for Issues 4+7); mypy --strict clean on application/ + composition/; interrogate --fail-under=100 PASSED; ruff check clean; pytest --cov=src/support_bot/application --cov-fail-under=90 reaches 94.74%; outer-SDK scan clean"
  - timestamp: "2026-09-06T20:35:00+00:00"
    lane: "for_review"
    agent: "spec-bridge-implement"
    action: "implementation complete -- handed off to spec-bridge-review (re-review)"
  - timestamp: "2026-09-06T21:00:00+00:00"
    lane: "done"
    agent: "spec-bridge-review"
    action: "review approved -- all 10 issues from v1 resolved, see WP02-review-summary-v2.json"
---

# WP02 — LangGraph workflow + API composition

## Goal

Build the **application services** for answering
(`LangGraphWorkflow`, four nodes, `answering_service`), the **API
edge** (`routes.py`, `RequestIdMiddleware`, `ErrorResponseMapper`),
the `SecretScrubber` adapter, the **structured-JSON logger** and
**Prometheus metrics**, and the **FastAPI composition root**.

This WP is the first WP that produces something runnable — but only
against fakes. The real adapters land in WP03 and a future WP.

## Execution constraints

- Product code and tests: only in
  `$WORKTREES_DIR/001-customer-support-rag-agent-WP02/`
- Do **not** merge to main.
- This WP touches `application/`, `composition/`, `adapters/
  secret_scrubber.py`, and `tests/application`, `tests/composition`,
  `tests/api`. It does **not** touch `domain/` (already shipped in
  WP01) or any I/O adapter (lands in WP03).

## Cross-references

- **Plan sections**: § Phase 0.4 (Hexagonal Layering), § Phase 0.5
  (Markaicode hybrid — the `AnswerGenerator` port contract is the
  single seam this WP instantiates), § Implementation Phases (WP02
  row), § Abstract Components (S2 and S3), § Inter-System Contracts
  (S2 → S3 Answer + Domain Exceptions).
- **Spec sections**: § FR-001, FR-002, FR-004, FR-006, FR-007,
  FR-009, FR-010, FR-011, FR-013, FR-014, FR-017.
- **Glossary**: `Answer`, `AgentState`, `LangGraphWorkflow`,
  `LowConfidencePolicy`, `SecretScrubber`, `CompositionRoot`.

## Subtasks

### T011 [P0] `application/answering/graph.py` — `LangGraphWorkflow`

Use `langgraph.graph.StateGraph`, `START`, `END`. The state is the
Pydantic `AgentState` from WP01. Topology:

```
START -> retrieve -> guard ->[conditional]-> generate -> END
                                       -> refuse   -> END
```

Conditional edge return type: `Literal["generate", "refuse",
"__end__"]`. The path function reads `state["retrieved_chunks"]`
and delegates to the injected `LowConfidencePolicy`.

The `compile()` method returns a `CompiledStateGraph`; tests in T019
call `.invoke(AgentState(question="...", request_id="..."))` and
assert the resulting state shape.

**AgentState MUST carry `request_id: str`** (see AGENTS.md §6.3).
Added in T011a below.

**Class docstring** (Google-style) states intent, parameters, return
value, raised exceptions, and design choices including:

- *"The workflow has zero imports from `langchain_*` or `chromadb`;
  it depends only on the three ports declared in
  `domain.answering.ports`."*
- *"Each node is wrapped in an OpenTelemetry span named
  `node.<name>` with attributes `request.id`, `route`, and (for the
  `retrieve` node) `retrieval.top1_similarity` and
  `retrieval.candidate_count`. The guard edge span carries
  `decision.path`. See AGENTS.md §6.4."*
- *"Future extensions can replace the body of any single node with a
  `langchain.agents.create_agent` instance without changing the
  topology, the state schema, or any other node. See plan § Phase
  0.5."*

**Acceptance**: `from application.answering.graph import
LangGraphWorkflow` succeeds; the class has a Google-style docstring;
`interrogate --fail-under 100` passes on this file.

### T011a [P0] `AgentState.request_id` + OTel context propagation

`AgentState` (added in T011) MUST include a `request_id: str` field
(default `""`). The `AnsweringService.answer` method MUST populate
it from its `request_id` parameter (see T013 update).

**OTel span propagation rules** (per AGENTS.md §6.4):

- The `LangGraphWorkflow.compile()` method receives an injected
  `tracer: trace.Tracer` (constructed in `composition/
  observability.py`). The compiled graph stores it.
- Every node function (`retrieve_node`, `guard_node`, `generate_node`,
  `refuse_node`) is wrapped in `tracer.start_as_current_span(
  "node.<name>", attributes={"request.id": state.request_id, ...})`.
- The conditional-edge path function (`_decide`) is wrapped in
  `tracer.start_as_current_span("node.guard_edge")` and sets
  `decision.path` to the returned literal.
- Spans are emitted **even when no OTLP exporter is configured**
  (spans get attached to the active `structlog` log line via
  `opentelemetry-instrumentation-logging`).

### T012 [P0] `application/answering/nodes.py` — four nodes

Each node is a `Callable[[AgentState], dict]` that returns a **partial
state update**. Each imports only ports from `domain/answering`.
Each is wrapped in an OTel span (see T011a).

- `def retrieve_node(state: AgentState, *, retriever: Retriever)
  -> dict` — opens span `node.retrieve`, calls
  `retriever.retrieve(state.question, k=4)`, logs DEBUG with
  `query.text_hash = sha256(question.text).hexdigest()[:16]`,
  `result_count`, `top1_similarity`; returns
  `{"retrieved_chunks": [...], "trace": state.trace + ["retrieve"]}`.
- `def guard_node(state: AgentState, *, policy: LowConfidencePolicy)
  -> dict` — opens span `node.guard`, appends `"guard"` to the trace;
  **does not** decide the next node (that is the conditional edge's
  job).
- `def generate_node(state: AgentState, *, generator:
  AnswerGenerator) -> dict` — opens span `node.generate`, calls
  `generator.generate(state.question, state.retrieved_chunks)`;
  logs DEBUG with `prompt.text_hash`,
  `tokens_in`/`tokens_out` from the result; returns `{"answer":
  text, "confidence": "high", "trace": state.trace +
  ["generate"]}`.
- `def refuse_node(state: AgentState, *, policy:
  LowConfidencePolicy) -> dict` — opens span `node.refuse`; returns
  `{"answer": policy.refusal_message(), "confidence": "low",
  "trace": state.trace + ["refuse"]}`.

**Debug-logging rule** (per AGENTS.md §6.5): every non-trivial branch
inside each node emits a DEBUG-level `structlog` line with enough
context to reproduce the call deterministically (counts, sizes,
hash of content where the content itself is sensitive). The raw
question/answer text is NEVER logged or placed in span attributes —
only `sha256(text).hexdigest()[:16]` as `*.text_hash`.

**Design rule**: every node imports only ports. None of these
functions may import `langchain`, `langgraph`, `chromadb`, or
`opentelemetry` directly — the span is opened via the
`Tracer` injected into the graph by the composition root.

### T013 [P0] `application/answering/answering_service.py`

`class AnsweringService`:

- `def __init__(self, *, retriever: Retriever, policy:
  LowConfidencePolicy, generator: AnswerGenerator, tracer:
  trace.Tracer | None = None) -> None` — `tracer` is the OTel tracer
  built once in `composition/observability.py`.
- `def answer(self, question: Question, *, request_id: str) -> Answer`
  — opens a top-level span `answering_service.answer` with attribute
  `request.id = request_id`, builds a fresh `LangGraphWorkflow`,
  calls `.invoke(AgentState(question=question.text,
  request_id=request_id))`, and converts the resulting state into
  an `Answer`. Translates `VectorStoreUnavailable` /
  `EmbedderUnavailable` / `LLMUnavailable` to typed re-raises
  (re-raise the same typed exception, do not wrap) so the API
  error mapper can map them.
- DEBUG log: `answering_service.start` with `question.text_hash`,
  `request_id`. INFO log: `answering_service.ok` with `confidence`,
  `latency_ms`, `decision_path`, `request_id`.

### T014 [P0] `application/api/error_mapper.py`

`class ErrorResponseMapper`:

- Takes a `SecretScrubber` (composition root wires the concrete
  implementation).
- `def to_response(self, exc: Exception) -> JSONResponse` — switch on
  exception type:
  - `VectorStoreUnavailable` → 503, body
    `{"detail": "vector store unavailable", "request_id":
    <current>}` (the detail string is the **public** constant; the
    underlying message is *not* echoed).
  - `LLMUnavailable` → 502, body
    `{"detail": "answer generation unavailable", "request_id":
    <current>}`.
  - `ConfigurationError` → 503, body
    `{"detail": "service not configured", "request_id": <current>}`.
  - `pydantic.ValidationError` → 422, body
    `{"detail": "invalid request", "errors": [...], "request_id":
    <current>}` (formatted as `errors()` output).
  - Any other `DomainError` → 500, body
    `{"detail": "internal error", "request_id": <current>}`.
- **Every body string** is passed through
  `scrubber.scrub(str(body))` before being placed in the JSON
  response or written to a log line.

### T015 [P0] `application/api/middleware.py` — `RequestIdMiddleware`

`BaseHTTPMiddleware` (FastAPI built-in). On request: read
`X-Request-Id` from headers if present, otherwise generate
`uuid4().hex`. **Bind it both ways** (per AGENTS.md §6.3):

1. to the `structlog` context via
   `structlog.contextvars.bind_contextvars(request_id=...)`, so
   every log line in the request scope carries it;
2. to the OTel active span via
   `trace.get_current_span().set_attribute("request.id", request_id)`
   so the auto-instrumented FastAPI span and every child span
   inherit it.

On response: add `X-Request-Id` header. On `finally`: clear the
contextvar with `structlog.contextvars.clear_contextvars()`.

**Deferred note from plan Open Questions**: this middleware **must**
be added first in the FastAPI app (`app.add_middleware(...)` before
any other middleware). T017 verifies and T020's integration test
asserts the order.

### T015a [P0] OTel SDK initialisation in `composition/observability.py`

Create `src/support_bot/composition/observability.py` exposing
`init_tracing(*, service_name: str = "support-bot", settings:
Settings) -> trace.Tracer` and `shutdown_tracing() -> None`.
`init_tracing` does:

1. Build a `Resource` with `service.name`, `service.namespace`
   (`OTEL_SERVICE_NAMESPACE`), `deployment.environment`
   (`OTEL_DEPLOYMENT_ENVIRONMENT`), `service.version` (read from
   `pyproject.toml` at import time).
2. Configure a `TracerProvider` with a `ParentBasedTraceIdRatio`
   sampler using `OTEL_TRACES_SAMPLER_ARG`.
3. If `OTEL_EXPORTER_OTLP_ENDPOINT` is set, attach a
   `BatchSpanProcessor` + `OTLPSpanExporter`. Otherwise attach a
   no-op processor (spans are still created and attached to logs).
4. Enable auto-instrumentation:
   `FastAPIInstrumentor.instrument_app(app)`,
   `HTTPXClientInstrumentor().instrument()`,
   `LoggingInstrumentor().instrument()`.
5. Set the global `trace.TRACE_PROVIDER` so adapter code that calls
   `trace.get_tracer(...)` works.
6. Log an INFO-level `tracing.initialised` line with the chosen
   sampler and whether an exporter is configured.

`composition/api_app.py` and `composition/ingestion_main.py` both
call `init_tracing(settings=settings)` once at startup before
building the app / running the service.

### T016 [P0] `application/api/routes.py` — three routes

Pydantic models first:

- `class AskRequest(BaseModel)` — `question: str = Field(min_length=1,
  max_length=2000)`.
- `class AskResponse(BaseModel)` — `answer: str`, `confidence:
  Literal["high", "low"]`, `trace: list[str]`, `request_id: str`.
- `class HealthResponse(BaseModel)` — `status: Literal["ok",
  "degraded"]`.

Routes (FastAPI `APIRouter`):

- `POST /ask` — accepts `AskRequest`. The handler **reads the
  current `request_id` from the `RequestIdMiddleware`-bound contextvar**
  (`structlog.contextvars.get_contextvars()["request_id"]`) — never
  mints a new one — opens an OTel span with attribute `route =
  "POST /ask"` and `question.text_hash = sha256(question).hexdigest
  [:16]`, calls `answering_service.answer(Question(text=req.
  question), request_id=request_id)`, and returns
  `AskResponse(..., request_id=request_id)`. On exception, the
  `ErrorResponseMapper` is invoked.
- `GET /healthz` — always returns 200 with `{"status": "ok"}` if the
  process is up. Does **not** check Chroma (per spec FR-002).
- `GET /metrics` — `prometheus_client.generate_latest()` with the
  correct content type. Exposes `request_count_total{route,
  status}`, `request_latency_seconds{route}` (histogram with
  `request_id` as an exemplar), and `retrieval_similarity_top1`
  gauge (per FR-014).

### T017 [P0] `composition/api_app.py` — FastAPI composition root

`def create_app(*, answering_service: AnsweringService | None = None,
settings: Settings | None = None) -> FastAPI`:

- Middleware order: `RequestIdMiddleware` **first**, then
  `CORSMiddleware` (default config), then the router.
- `answering_service` is taken from the `settings` env if not
  provided (default factory wires `FakeRetriever`,
  `StubLowConfidencePolicy`, `FakeAnswerGenerator` when env says
  `ANSWERER_BACKEND=fake` — this is the path WP02 tests against).
- The `ANSWERER_BACKEND` factory lives in
  `composition/settings.py`. In WP02 the factory has only the
  `fake` branch; WP03 (or a later WP) adds the real
  `OpenAIAnswerGenerator` branch via `OpenAIAnswerGenerator` from
  `adapters.answerer_openai.py`. The Markaicode hybrid adapter is
  out of scope for this WP.

### T018 [P0] Structured-JSON logging + Prometheus metrics

- `src/support_bot/adapters/secret_scrubber.py` — `SecretScrubber`
  with a compiled regex for OpenAI keys (`r"sk-[A-Za-z0-9]{32,}"`),
  Anthropic keys (`r"sk-ant-[A-Za-z0-9-]{32,}"`), and a
  configurable substring set for env-provided secrets
  (`OPENAI_API_KEY`, `EMBEDDING_API_KEY`, `CHROMA_URL`).
  `scrub(s: str) -> str` replaces each match with `"[REDACTED]"`.
  Also exported as a `structlog` processor (`SecretScrubber()
  .__call__`) so it can be plugged into the processor chain (see
  AGENTS.md §6.5), and as an OTel span-attribute filter so
  scrubbed attributes never leave the process.
- `src/support_bot/adapters/structured_logger.py` —
  `configure_logging(level: str)` sets up `structlog` with the
  full processor chain from AGENTS.md §6.5:
  `merge_contextvars` → `add_log_level` → `TimeStamper` →
  `SecretScrubber` → `JSONRenderer`. The `request_id`,
  `trace_id`, `span_id` are picked up automatically by
  `merge_contextvars` once `RequestIdMiddleware` and the OTel
  logging instrumentation have run.
- `src/support_bot/adapters/metrics.py` — Prometheus registry +
  `REQUEST_COUNT`, `REQUEST_LATENCY`, `RETRIEVAL_TOP1` definitions.
  `ADAPTER_CALL_LATENCY` (histogram, labels `adapter`,
  `operation`) is added too — every adapter call records
  `adapter_call.start` and `adapter_call.end` debug/info logs
  with `request_id`, `latency_ms`, and emits a sample to this
  histogram.
- `application/api/middleware.py` records `REQUEST_COUNT` and
  `REQUEST_LATENCY` on every response (with `request_id` attached
  as an OpenMetrics exemplar). The `RETRIEVAL_TOP1` gauge is
  updated by the `answering_service` after retrieval (before
  generation or refusal).

### T019 [P0] Application tests (graph + service)

`tests/application/answering/` with at least:

- `test_graph_walks_generate_when_high_confidence.py` — wires
  `FakeRetriever` (returns 3 chunks), `StubLowConfidencePolicy`
  (`should_refuse=False`), `FakeAnswerGenerator` (returns canned
  text). Uses `InMemorySpanExporter` from `opentelemetry-sdk.
  testing` to capture spans; the `TracerProvider` is reset per
  test. Invokes the workflow with `AgentState(question="...",
  request_id="test-req-id")`. Asserts:
  - `state.trace == ["retrieve", "guard", "generate"]`
  - `state.confidence == "high"`
  - `state.answer == "..."`
  - `state.request_id == "test-req-id"` (single-ID rule).
  - The LLM was called exactly once.
  - Spans: `node.retrieve`, `node.guard`, `node.guard_edge`
    (`decision.path=generate`), `node.generate` were emitted,
    each with `request.id == "test-req-id"`.
- `test_graph_walks_refuse_when_empty_retrieval.py` — same wiring
  except `FakeRetriever` returns `[]` and `StubLowConfidencePolicy
  .should_refuse` returns `True`. Asserts:
  - `state.trace == ["retrieve", "guard", "refuse"]`
  - `state.confidence == "low"`
  - `state.answer.startswith("I cannot answer based on the available
    content.")`
  - The LLM was **never** called.
  - `decision.path == "refuse"` on the guard-edge span.
- `test_answering_service_propagates_typed_exceptions.py` — drives
  `FakeRetriever` to raise `VectorStoreUnavailable` and asserts the
  service re-raises the same typed exception (no wrapping). Also
  asserts the failure was recorded as an OTel span event with
  `exception.type = "VectorStoreUnavailable"`.
- `test_answering_service_debug_log_includes_text_hash.py` —
  captures the `structlog` output during a successful answer and
  asserts the DEBUG line `answering_service.start` carries
  `question.text_hash` (16-hex chars), `request_id`, and never
  carries the raw question text.

### T020 [P0] API tests (routes, middleware, error mapper)

`tests/api/` with at least:

- `test_routes_ask_returns_high_confidence.py` — wires a `TestClient`
  with the FastAPI app and a fake answering service. Sends
  `POST /ask {"question": "..."}`; asserts HTTP 200, body shape,
  `X-Request-Id` header echoed.
- `test_routes_ask_returns_low_confidence_on_empty_retrieval.py` —
  same but the fake answering service returns `Answer(confidence=
  "low", ...)`. Asserts HTTP 200, `confidence == "low"`.
- `test_routes_ask_maps_vector_store_unavailable_to_503.py` — fake
  service raises `VectorStoreUnavailable`. Asserts HTTP 503, body
  detail does **not** contain the `CHROMA_URL` value or any
  substring of `OPENAI_API_KEY`.
- `test_routes_ask_maps_llm_unavailable_to_502.py` — fake raises
  `LLMUnavailable`. Asserts HTTP 502, body scrubbed.
- `test_routes_ask_returns_422_on_malformed_body.py` — sends
  `{}`. Asserts HTTP 422, no raw request body echoed.
- `test_healthz_returns_200.py` — `GET /healthz` returns 200.
- `test_metrics_returns_prometheus_format.py` — `GET /metrics`
  returns text/plain with `request_count_total{...}` and
  `request_latency_seconds_...`.
- `test_request_id_middleware_is_first.py` — inspects
  `app.user_middleware` order; the first entry is the
  `RequestIdMiddleware`.
- `test_request_id_propagates_to_log_lines.py` — runs a request
  through the app with a captured log handler; asserts the log
  line carries the same `request_id` as the response header.
- `test_request_id_propagates_to_otel_spans.py` — runs `POST
  /ask` with `InMemorySpanExporter`; asserts the FastAPI auto-span
  and every child span carry `request.id` matching the
  `X-Request-Id` response header.
- `test_response_emits_ask_response_request_id.py` — `POST /ask`
  asserts the response body field `request_id` matches the
  `X-Request-Id` response header.

## TDD Targets (from Misfits)

These tests land **first**, before the code they cover.

- M3: `test_graph_walks_refuse_when_empty_retrieval.py` proves the
  refusal path runs **without** invoking the LLM.
- M5: `test_routes_ask_maps_vector_store_unavailable_to_503.py`
  and `test_routes_ask_maps_llm_unavailable_to_502.py` prove the
  response body and log lines never contain a key substring.
- M6: `test_routes_ask_maps_vector_store_unavailable_to_503.py`
  proves Chroma-down → HTTP 503.
- M8: `test_graph_walks_generate_when_high_confidence.py` proves
  the `generate` node calls `AnswerGenerator.generate` (the
  adapter owns the system-prompt constraint; the test asserts
  the contract is satisfied by being invoked with the retrieved
  chunks).

## Acceptance Criteria

This WP is **done** when:

- [ ] `pytest tests/application tests/composition tests/api -q`
      is green.
- [ ] `pytest --cov=src/support_bot/application
            --cov-fail-under=90 -q` is green.
- [ ] `interrogate --fail-under 100 src/support_bot/application
      src/support_bot/composition` is green.
- [ ] `tests/api/test_request_id_middleware_is_first.py` passes
      (deferred FastAPI middleware-order note from plan).
- [ ] No code in `application/` or `composition/` imports from
      `langchain`, `langgraph`, `chromadb`, `fastapi`,
      `beautifulsoup4`, `requests`, or `opentelemetry` (except
      `composition/observability.py` which initialises the SDK and
      re-exports the `Tracer` it builds).
- [ ] All TDD targets above are passing tests.
- [ ] `AgentState.request_id` is set on every invocation; no span
      or log line in the request scope carries an upstream ID in
      the `request_id` field.

## Definition of Done

```bash
uv run pytest tests/application tests/composition tests/api -q
uv run pytest --cov=src/support_bot/application \
              --cov-fail-under=90 tests/application -q
uv run interrogate --fail-under=100 \
  src/support_bot/application src/support_bot/composition
git grep -nE 'from langchain|from langgraph|from chromadb|from requests|from bs4|from beautifulsoup4' src/support_bot/application/ src/support_bot/composition/ \
  && echo "FAIL" && exit 1 \
  || echo "OK"
```

Commit history (per TDD rule §4.1) — **separate commits** in this order:

1. `test(application): graph walks generate when high confidence
    with request_id + OTel assertions`
2. `test(application): graph walks refuse when empty retrieval with
    OTel guard-edge decision.path`
3. `test(api): request id propagates to OTel spans`
4. `test(api): response AskResponse carries matching request_id`
5. `feat(application): LangGraphWorkflow + AgentState.request_id +
    OTel-wrapped nodes + AnsweringService(request_id=...)`
6. `feat(adapters): SecretScrubber processor + structlog chain +
    ADAPTER_CALL_LATENCY`
7. `feat(composition): observability.init_tracing + shutdown_tracing`
8. `feat(application): RequestIdMiddleware binds request_id to
    structlog AND OTel active span`
9. `feat(application): ErrorResponseMapper + routes + metrics
    exemplars + AskResponse.request_id`
10. `feat(composition): api_app wires middleware first, init_tracing
     + assembly`
11. `chore(adapters): metrics + structured_logger + SecretScrubber
     processor wiring`

Final commit message:
`feat(WP02): LangGraph workflow, API composition, error mapper,
scrubber, OpenTelemetry tracing, single-ID propagation`.
Signal `lane: for_review`.

---

## Review Summary (v1)
status: implemented

WP02 implements the LangGraph workflow, the FastAPI composition root, and the four AGENTS.md 6.6 Prometheus series. Build health (mypy --strict, ruff, interrogate 100%) and the WP02 acceptance test gates pass. However, several substantive issues remain that block approval: (1) the Prometheus series are defined but never recorded, so /metrics returns an empty exposition; (2) required OTel span attributes (route, question.text_hash on retrieve_node, answer.tokens_in) are missing; (3) the conditional-edge annotation says Literal[generate, refuse, __end__] but only generate/refuse are emitted -- this is documented; (4) the composition root imports from tests/ which is a layering violation; (5) service.version is hardcoded rather than read from pyproject.toml; (6) the answering_service has a dead except-DomainError-pass block and no DEBUG log on the error path; (7) the InMemorySpanExporter TDD target from T019 is missing. All are major or minor; none are critical/compilation-blocking. Recommend changes_requested and re-review.

| Criterion | Verdict |
|-----------|---------|
| [ ] `pytest tests/application tests/composition tests/api -q` | ✅ -- 111 tests pass |
| [ ] `pytest --cov=src/support_bot/application | ✅ -- 97.20% coverage on application/ |
| [ ] `interrogate --fail-under 100 src/support_bot/application | ✅ |
| [ ] `tests/api/test_request_id_middleware_is_first.py` passes | ✅ |
| [ ] No code in `application/` or `composition/` imports from | ⚠️ -- Only langgraph.graph in application/answering/graph.py (the dedicated workflow module carve-out). However composition/api_app.py imports from tests/fakes/*, which is a layering violation. |
| [ ] All TDD targets above are passing tests. | ⚠️ -- Most are present but InMemorySpanExporter-based span-attribute tests from T019 are missing. |
| [ ] `AgentState.request_id` is set on every invocation; no span | ⚠️ -- request.id is set on spans, but AGENTS.md 6.4-required attributes (route, question.text_hash on retrieve_node spans, answer.tokens_in) are missing. |
| Misfit Resolution: each misfit in misfits_addressed has a passing test | ⚠️ -- M3 refuse-without-LLM is tested, M5 scrubber is tested, M6 503 mapping is tested, M8 generate-prompt is tested. But each test only covers the happy path; full TDD targets per the WP02 prompt (InMemorySpanExporter assertions, error_type events) are not in place. |
| Subsystem Boundary Respect: no undeclared cross-subsystem coupling | ❌ -- composition/api_app.py imports from tests/. See Issue 1. |
| Contract Compliance: implementation matches plan.md inter-system contracts | ⚠️ -- Routes + middleware + error mapper match the plan. But the /metrics endpoint always calls generate_latest() with no registry argument, so the custom metrics_registry passed into create_app is silently dropped -- tests that inject a registry get an empty exposition. |
| No New Misfits: no new failure modes introduced without documenting them | ✅ |
| Build Health -- language type-checker exits 0 | ✅ -- mypy --strict clean on application/ + composition/ |

### Issues

**Issue 1 -- Major: composition/api_app.py imports from tests/fakes/ (layering violation)**

AGENTS.md 1.1 forbids composition/ from importing test-only code at runtime; the fakes live under tests/ and are part of the test pyramid, not the production runtime. _build_default_answering_service() pulls in FakeRetriever, StubLowConfidencePolicy, FakeAnswerGenerator directly, so the production Docker image would have to ship the entire tests/ tree. The composition root should expose a port-only factory (or refuse to start) when answerer_backend='fake' is set in production -- the 'fake' backend is meant for dev/test, and the composition root should be selected via env or import path, not via a hardcoded tests/ import.

Suggested fix:

```
Move the fake wiring into a separate tests-only helper (e.g. tests/support/build_fake_app()) that constructs AnsweringService with fakes and calls create_app(answering_service=...). The production composition root should reject answerer_backend='fake' with a ConfigurationError unless an explicit override env var is set (e.g. ALLOW_FAKE_BACKEND=1 for dev).
```

Misfits: M3 | Subtasks: WP03, WP04, WP05 | Files: src/support_bot/composition/api_app.py

**Issue 2 -- Major: Prometheus metrics series are defined but never recorded**

adapters/metrics.py builds a CollectorRegistry with the four AGENTS.md 6.6 series (request_count_total, request_latency_seconds, retrieval_similarity_top1, adapter_call_latency_seconds). However: (a) no middleware records request_count_total or observes request_latency_seconds on each response; (b) the answering service never updates retrieval_similarity_top1 after retrieval; (c) adapter_call_latency_seconds is never observed. As a result, /metrics returns an exposition without the support-bot series (only the default platform collectors). The metrics_registry parameter passed into create_app() is silently dropped because the /metrics route calls generate_latest() with no registry argument.

Suggested fix:

```
Wire the metrics in composition/api_app.py: (1) add a PrometheusMetricsMiddleware that increments request_count_total and observes request_latency_seconds (with request_id as OpenMetrics exemplar) on every response, after RequestIdMiddleware so the request_id is available; (2) have AnsweringService.answer update retrieval_similarity_top1 after retrieval; (3) have the /metrics route call generate_latest(registry) with the actual registry built in create_app; (4) add a small adapter_call_latency decorator or wrapper that adapter code can opt into. Add tests for each.
```

Misfits: M5, M6 | Subtasks: WP04 | Files: src/support_bot/composition/api_app.py, src/support_bot/application/answering/answering_service.py, src/support_bot/application/api/routes.py, src/support_bot/adapters/metrics.py

**Issue 3 -- Major: AGENTS.md 6.4-required span attributes are missing on node spans**

AGENTS.md 6.4 lists must-have span attributes including route, question.text_hash, retrieval.top1_similarity, retrieval.candidate_count, decision.path, answer.tokens_in, answer.tokens_out. Current implementation: (a) route is never set on any manual node span (only the FastAPI auto-span carries it via HTTP route template, which is a different field); (b) question.text_hash is not set as a span attribute on retrieve_node, generate_node, or the answering_service.answer span (it is logged as query_text_hash, with a different key); (c) answer.tokens_in is not set on generate_node (only answer.tokens_out is).

Suggested fix:

```
Add the missing span attributes: retrieve_node should set 'route' and 'question.text_hash' (in addition to the existing retrieval.* attributes); generate_node should set 'answer.tokens_in' and 'answer.tokens_out'. Use the canonical key 'question.text_hash' (not 'query_text_hash'). Update DEBUG log keys to match the canonical attribute names.
```

Misfits: M5 | Files: src/support_bot/application/answering/graph.py

**Issue 4 -- Major: InMemorySpanExporter span-attribute tests (T019) are missing**

WP02 prompt T019 explicitly requires tests that use opentelemetry.sdk.testing.InMemorySpanExporter to assert that the OTel spans carry the right attributes (request.id, decision.path, retrieval.top1_similarity, retrieval.candidate_count, etc.). None of the WP02 tests use InMemorySpanExporter. As a result, the span-attribute assertions in T011a and the four-node OTel wrapping have no test coverage at the observability layer; the current tests only check structlog log keys.

Suggested fix:

```
Add tests/application/answering/test_graph_emits_otel_spans.py (or similar) using InMemorySpanExporter. For each WP02 acceptance scenario (generate path, refuse path, error path), capture spans and assert: node.retrieve, node.guard, node.guard_edge, node.generate (or node.refuse) are emitted; each carries request.id matching the input state; the guard edge carries decision.path matching the expected path; the retrieve node carries retrieval.top1_similarity and retrieval.candidate_count.
```

Misfits: M5 | Files: tests/application/answering/test_graph_walks_generate_when_high_confidence.py, tests/application/answering/test_graph_walks_refuse_when_empty_retrieval.py

**Issue 5 -- Minor: AnsweringService.answer has dead except-DomainError-pass block and no DEBUG log on error paths**

answering_service.py lines 124-130 contain two except blocks that do nothing except re-raise, eliminating any DEBUG/INFO log on the failure path. AGENTS.md 6.5 requires every non-trivial branch to emit a DEBUG log with enough context to reproduce; the answering_service should log on the error path (e.g. answering_service.error with error_type, decision_path=__end__, latency_ms, request_id).

Suggested fix:

```
Replace the except DomainError: raise with a single except block that logs DEBUG/ERROR with error_type, latency_ms, request_id, and decision_path=__end__ (or the trace at point of failure). The VectorStoreUnavailable/EmbedderUnavailable/LLMUnavailable triple can collapse into a single tuple catch.
```

Files: src/support_bot/application/answering/answering_service.py

**Issue 6 -- Minor: service.version is hardcoded rather than read from pyproject.toml**

WP02 prompt T015a says 'service.version (read from pyproject.toml at import time)'. The current implementation reads settings.service_version which has a static default of '0.1.0' in Settings. The pyproject.toml version is also '0.1.0', so they match by coincidence, but the implementation does not follow the prompt.

Suggested fix:

```
Use importlib.metadata.version('support-bot') at observability.py module import time, falling back to settings.service_version when the package is not installed. Add a test that asserts the resource attributes include service.version equal to the installed version.
```

Files: src/support_bot/composition/observability.py, src/support_bot/composition/settings.py

**Issue 7 -- Minor: request_id span attribute should also be set on the answering_service.answer span (already done) AND test for it is missing**

Per AGENTS.md 6.3 the request_id attribute is set on every span. answering_service.answer correctly sets it. But the test for this attribute on the top-level span is also missing -- there is no test that asserts request.id appears on the answering_service.answer span itself.

Suggested fix:

```
When adding the InMemorySpanExporter tests (Issue 4), include an assertion that the answering_service.answer span carries request.id matching the inbound request_id.
```

Files: tests/application/answering/test_answering_service.py

**Issue 8 -- Minor: Dead code in create_app: metrics_registry unused**

create_app accepts metrics_registry as a kwarg, builds a registry, but never uses it -- /metrics calls generate_latest() with no registry argument, and the registry parameter is dropped on the floor after a no-op if block.

Suggested fix:

```
Either (a) pass the registry into the /metrics route (build_router should accept registry and call generate_latest(registry)), or (b) drop the metrics_registry parameter from create_app until Issue 2 is addressed.
```

Files: src/support_bot/composition/api_app.py, src/support_bot/application/api/routes.py

**Issue 9 -- Minor: ruff fix needed for import sort in api_app.py after the formatter ran**

ruff check src tests reported I001 in src/support_bot/composition/api_app.py (imports un-sorted). Already auto-fixed during this review; needs to be committed.

Suggested fix:

```
Already applied via 'ruff check --fix'; needs a chore(tools) commit to land.
```

Files: src/support_bot/composition/api_app.py

**Issue 10 -- Minor: Conditional edge type annotation promises __end__ but path function never returns it**

Per the WP02 prompt, the conditional edge returns Literal['generate', 'refuse', '__end__'] (AGENTS 1.5 requires the literal union). The current _decide function never actually returns '__end__'; it always emits 'generate' or 'refuse'. This is acceptable per the prompt's '__end__ is reserved for future WPs' note, but the docstring claims '__end__ is reserved for future WPs (e.g. early-exit when the question is empty) but the WP02 wiring only emits generate or refuse' -- which is good. The literal annotation is a forward-compat declaration.

Suggested fix:

```
No code change required; this is informational.
```

### Dependency Notes

WP03 (ingestion container) depends on this WP and will need to re-run implement after these changes if any of Issues 1-3 land -- specifically Issue 2 (metrics middleware), because WP03 wires adapter spans and may want to participate in request_count_total semantics. WP04 (docker-compose) depends on WP02 and would benefit from the metrics middleware being functional. Recommend: implement Issue 1 + Issue 2 + Issue 3 + Issue 4 + Issue 5 in one batch, then re-review.

WP02 is functionally complete (111 tests pass, gates green) but the metrics wiring is dead (Issue 2), the production layering pulls tests/ into the runtime (Issue 1), the OTel span attributes required by AGENTS.md 6.4 are partially missing (Issue 3), and the T019 InMemorySpanExporter tests are absent (Issue 4); request changes.

---

## Review Summary (v2)
status: approved

WP02 review v1 feedback addressed across four TDD-disciplined commits (59160c3 test, 949caca feat, 25362cb feat, e5a80b0 feat). All four major issues plus the five minor issues are resolved. New: 5 InMemorySpanExporter span-attribute tests (Issues 4+7), MetricsRecorder + PrometheusMetricsMiddleware that actually record (Issue 2), tests/support/build_fake_app.py eliminating composition -> tests/fakes imports (Issue 1), service.version from importlib.metadata (Issue 6), DEBUG log on AnsweringService error path (Issue 5), metrics_registry wired into /metrics route (Issue 8), ruff import sort fixed (Issue 9), log key rename query_text_hash -> question_text_hash (Issue 3), span attributes route + question.text_hash + answer.tokens_in added (Issue 3). 116 tests pass, mypy --strict clean, interrogate 100%, ruff clean, 94.74% coverage on application. The conditional-edge Literal annotation remains Literal[generate, refuse, __end__] per AGENTS 1.5 (Issue 10 was informational). Approving.

| Criterion | Verdict |
|-----------|---------|
| [ ] `pytest tests/application tests/composition tests/api -q` | ✅ -- 32 passed in the targeted run; 116 in the full suite. |
| [ ] `pytest --cov=src/support_bot/application | ✅ -- 94.74% coverage on application; >= 90% target reached. |
| [ ] `interrogate --fail-under 100 src/support_bot/application | ✅ -- 100.0% interrogate PASSED. |
| [ ] `tests/api/test_request_id_middleware_is_first.py` passes | ✅ -- 4/4 tests pass; the middleware-order test now also asserts PrometheusMetricsMiddleware is in the chain. |
| [ ] No code in `application/` or `composition/` imports from | ✅ -- Only the dedicated workflow module imports langgraph (AGENTS 1.5 carve-out). composition/ no longer references tests/ at runtime -- the only matches are docstring mentions. (Issue 1 fixed.) |
| [ ] All TDD targets above are passing tests. | ✅ -- Added tests/application/answering/test_graph_emits_otel_spans.py with 5 InMemorySpanExporter tests covering all AGENTS.md 6.4 node-span attributes (Issue 4 fixed). |
| [ ] `AgentState.request_id` is set on every invocation; no span | ✅ -- retrieve_node and generate_node now set route + question.text_hash; generate_node also sets answer.tokens_in (sum of chunk text lengths); top-level answering_service.answer span sets request.id, route, question.text_hash, decision.path (Issues 3 + 7 fixed). |
| Misfit Resolution: each misfit in misfits_addressed has a passing test | ✅ -- M3 refuse-without-LLM tested via tests/application/answering/test_graph_emits_otel_spans.py::test_graph_refuse_path_emits_correct_decision_path; M5 scrubber tested in tests/adapters/test_secret_scrubber.py; M6 503 mapping tested in tests/application/api/test_error_mapper.py; M8 generate path tested via InMemorySpanExporter assertion on node.generate span. |
| Subsystem Boundary Respect: no undeclared cross-subsystem coupling | ✅ -- Issue 1 fixed: composition/api_app.py no longer imports tests/fakes/*. tests/support/build_fake_app.py is the single seam between the composition root and the in-memory fakes. |
| Contract Compliance: implementation matches plan.md inter-system contracts | ✅ -- Issue 2 + 8 fixed: MetricsRecorder + PrometheusMetricsMiddleware now actually record request_count_total and request_latency_seconds on every response, and /metrics renders the same registry the middleware writes to. retrieval_similarity_top1 gauge updated by AnsweringService after retrieval. |
| No New Misfits: no new failure modes introduced without documenting them | ✅ -- No new misfits; tests/support is a pure test-only helper module. |
| Build Health -- language type-checker exits 0 | ✅ -- mypy --strict clean on application/ + composition/ (13 source files). |

### Dependency Notes

WP03 (ingestion container) and WP04 (docker-compose stack) depend on WP02. Both now have a fully wired Prometheus metrics layer to integrate against (the new PrometheusMetricsMiddleware sits before RequestIdMiddleware so spans + log lines + metrics all share the request_id). No code paths in WP03 or WP04 are forced to re-run by these changes; the worktree still has the WP01 baseline so dependents' merges remain additive.

WP02 review v1 issues resolved: composition layering clean, Prometheus series actually recorded with shared registry, AGENTS.md 6.4 span attributes present and tested via InMemorySpanExporter, request_id on top-level span verified, service.version from importlib.metadata, DEBUG log on AnsweringService error path, dead except block removed, ruff clean. Approving.
