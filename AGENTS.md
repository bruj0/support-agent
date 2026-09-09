# AGENTS.md — `support-bot`

> **Audience:** contributors and reviewers of this repository.
> **Scope:** cross-cutting rules — architecture, coding style, testing, observability, security — that apply to every layer and every change. The architectural deep-dive lives in [`docs/architecture/architecture.md`](docs/architecture/architecture.md); the project glossary is in [`CONTEXT.md`](CONTEXT.md).
>
> If anything in this file contradicts the architecture doc, the architecture doc wins and this file is wrong. Open a PR against `AGENTS.md` to reconcile.

---

## 0. Operating mode

- **Default branch is `main`.** All feature work targets it.
- **Never rebase, force-push, or amend** a pushed branch. If history is wrong, open a follow-up commit.
- **Conventional Commits.** `feat(<scope>): …`, `test(<layer>): …`, `chore(<scope>): …`, `docs(<scope>): …`. TDD pairs must be **separate commits** (`test(domain): …` then `feat(domain): …`).
- **No secrets in source, in commit messages, or in rendered responses.** `SecretScrubber` enforces this on every log line and every error response.

---

## 1. Architecture — Hexagonal / Ports-and-Adapters

### 1.1 Layering (HARD)

Dependencies point **inward only**:

```
composition   →   adapters   →   application   →   domain
  (top)                                                    (bottom, pure)
```

| Layer         | May import                                  | Must NOT import                                                      |
| ------------- | ------------------------------------------- | -------------------------------------------------------------------- |
| `domain/`     | stdlib only                                 | `application/`, `adapters/`, `composition/`, `langchain`, `langgraph`, `chromadb`, `fastapi`, `requests`, `beautifulsoup4`, `httpx`, `pydantic-settings`, `structlog`, `opentelemetry` (see §6) |
| `application/`| `domain/`                                   | `adapters/`, `composition/`, the SDKs listed above                    |
| `adapters/`   | `domain/`, `application/`, SDKs             | `composition/`                                                       |
| `composition/`| all layers                                  | —                                                                    |

Pydantic v2 (BaseModel, field validators) is fine in `domain/`. `pydantic-settings.BaseSettings` is **only** allowed in `composition/`. `pydantic-settings` is a framework import and is banned from `domain/`.

### 1.2 Ports

- **Definition:** `typing.Protocol` (NOT `abc.ABC`) with Google-style docstrings stating intent, params, return, raises, **and design rationale**.
- **Location:** `src/support_bot/domain/<subsystem>/ports.py`.
- **Conformance:** every adapter must pass an `isinstance(adapter, Port)` test plus an `inspect.signature` check in `tests/adapters/conftest.py`.

### 1.3 Composition root

`composition/` is split into three files: `api_app.py` (FastAPI), `ingestion_main.py` (CLI), `settings.py` (`pydantic-settings`). Adapter choice is a one-line change at the composition root.

### 1.4 Subsystems (from `decomposition.md`)

- **S1 Ingestion Pipeline** — `PageScraper`, `PageCleaner`, `Chunker`, `Embedder`, `VectorStore`, `PreEmbedValidator`, `IngestionRunLock`, `IngestionService`, `IngestionJob`.
- **S2 Retrieval & Answering** — `Retriever`, `LowConfidencePolicy`, `AnswerGenerator`, `LangGraphWorkflow`, `AgentState`, `Answer`.
- **S3 API & Cross-Cutting Safety** — `FastAPIApp`, routes, middleware, `ErrorResponseMapper`, `SecretScrubber`, logging, Prometheus metrics.
- **S4 Helm Packaging & CI** — chart, `values-*.yaml`, CI workflow, architecture tests.

Cross-subsystem contracts live in `tests/architecture/`. A signature change in a port without an updated adapter must fail CI.

### 1.5 LangGraph workflow (S2)

- **Explicit `langgraph.graph.StateGraph`** with `START` / `END` sentinels. No `create_agent` (yet) — the forward-compat escape hatch lives inside the `generate` node body.
- **Pydantic `AgentState`** (not TypedDict).
- **`Literal["generate", "refuse", "__end__"]`** return types on conditional-edge path functions.
- **Nodes are `Callable[[AgentState], dict]`** returning a partial state update. Nodes import only ports; they must not import `langchain`, `langgraph`, or `chromadb`.
- **Topology:** `START → retrieve → guard →[conditional]→ generate → END` or `→ refuse → END`. The conditional edge delegates to the injected `LowConfidencePolicy` — no business logic in the edge function.

---

## 2. Tech stack (pinned)

### 2.1 Language & runtime
- **Python 3.11.** Base image `python:3.11.9-slim-bookworm`.
- **uv** for dependency management. `pyproject.toml` with hatchling, package layout `src/support_bot`.

### 2.2 Pinned direct deps
`fastapi>=0.115,<0.116` · `uvicorn[standard]>=0.30,<0.32` · `pydantic>=2.7,<3` · `pydantic-settings>=2.3,<3` · `langgraph>=1.2.10,<2` · `langchain>=1.3,<2` · `langchain-core>=1.4,<2` · `langchain-openai>=0.1,<1` · `chromadb>=0.5,<1` · `sentence-transformers>=3.0,<4` · `requests>=2.32,<3` · `beautifulsoup4>=4.12,<5` · `prometheus-client>=0.20,<1` · `structlog>=24.1,<25` · **`opentelemetry-api>=1.27,<2`** · **`opentelemetry-sdk>=1.27,<2`** · **`opentelemetry-exporter-otlp>=1.27,<2`** · **`opentelemetry-instrumentation-fastapi>=0.48b0,<1`** · **`opentelemetry-instrumentation-httpx>=0.48b0,<1`** · **`opentelemetry-instrumentation-logging>=0.48b0,<1`** · **`opentelemetry-instrumentation-chromadb`** (whichever release is current; pin at first install).

> The four **bold** OpenTelemetry entries are **new with this AGENTS.md** — see §6.

### 2.3 Test/lint toolchain
`pytest>=8.2,<9` + `pytest-asyncio>=0.23,<1` (mode `auto`) + `pytest-cov>=5.0,<6` · `import-linter>=2.0,<3` · `interrogate>=1.7,<2` · `ruff>=0.5,<1` (`select = ["E","F","I","B","UP","SIM","PL"]`) · `mypy>=1.10,<2` with `--strict`.

### 2.4 Storage & deploy
- Chroma only, no SQL DB. `chromadb/chroma:0.5.4` server image, accessed via **`chromadb.HttpClient`** (NOT `PersistentClient`).
- Docker Compose for local; Kubernetes 1.28+ for prod; Helm v3 chart.
- PVC `persistentVolumeReclaimPolicy: Retain`. Ingestion Job: `helm.sh/hook: post-install,post-upgrade` + `helm.sh/hook-delete-policy: hook-succeeded`. `pre-install` hook validates required Secrets.

### 2.5 Provider selection
- Embedder: `local` (default — `sentence-transformers/all-MiniLM-L6-v2`, 384 dims) | `openai` (`text-embedding-3-small`, 1536 dims). Selector: `EMBEDDER_BACKEND`.
- Answerer: `openai` (default — `ChatOpenAI` with a "context-only" system prompt) | `fake` (tests/dev). Selector: `ANSWERER_BACKEND`.

---

## 3. Coding style

### 3.1 Docstrings (HARD)
- Google-style, on every module, class, and public function. State **intent, parameters, return, raised exceptions, and design rationale**.
- CI gate: `interrogate --fail-under 100` on `domain/`, `application/`, `composition/`. `exclude = ["tests"]`, `ignore-init-method = true`.

### 3.2 Types
- **Pydantic v2 frozen models** (`frozen=True`) for all entities and value objects.
- `mypy --strict` clean across the source tree. New code must not introduce `Any` without a `# type: ignore[xxx]` + comment.
- `Confidence = Literal["high", "low"]` — Pydantic validator rejects any other string.
- Field-level validators for invariant clamping (e.g., `RetrievedChunk.similarity ∈ [0.0, 1.0]`).

### 3.3 Vocabulary (from `CONTEXT.md`)

**Use:** `SourcePage`, `Chunk`, `RetrievedChunk`, `Question`, `Answer`, `IngestionRun`, `AgentState`, `Port`, `Adapter`, `CompositionRoot`, `LangGraphWorkflow`, `LowConfidencePolicy`, `SecretScrubber`, `CleanedPage`.

**Avoid:** `scraped_page`, `raw_doc`, `html_doc`, `segment`, `document_fragment`, `hit`, `search_result`, `prompt`, `user_input`, `query_string`, `response`, `completion`, `ingestion_job`, `build_run`, `graph_state`, `workflow_state`, `message_state`, `interface`, `contract` (keep for inter-subsystem), `driver`, `gateway`, `main`, `entrypoint`, `bootstrap`, `agent`, `rag_chain`, `confidence_checker`, `redactor`, `masker`.

### 3.4 Layout
- Source under `src/support_bot/{domain,application,adapters,composition}/`.
- Tests mirror source: `tests/{domain,application,adapters,composition,architecture,api,e2e}/`.
- Fakes under `tests/fakes/{ingestion,answering}/`.
- Docker under `docker/` (`api.Dockerfile`, `ingestion.Dockerfile`).
- Deploy under `deploy/docker-compose.yml` and `deploy/helm/support-bot/`.
- Docs under `docs/architecture/`.

---

## 4. Testing

### 4.1 TDD is mandatory (HARD)
- For every domain or application-service change, **commit a failing test before the implementation.** The commit log must show `test(...): …` then `feat(...): …` pairs.
- TDD targets are pinned per WP per misfit (see each WP's "TDD Targets" section).

### 4.2 Coverage thresholds
| Package      | Min line coverage | Enforced by |
| ------------ | ----------------- | ----------- |
| `domain/`    | 90% | CI gate |
| `application/` | 90% | CI gate |
| `adapters/`  | 70% | CI gate (NFR-007) |
| overall      | 80% | CI gate |

`[tool.coverage.report].fail_under = 90` must be declared in `pyproject.toml` (currently only supplied via CLI — fix as housekeeping).

### 4.3 Test layers
- **Unit** — `tests/domain/` (pure), `tests/application/` (with fakes), `tests/fakes/` (port conformance + signature match via `inspect.signature`).
- **Contract** — per adapter, against mock servers (`responses`/`pytest-httpserver`) and `chromadb.EphemeralClient`.
- **Failure injection** — canonical scenarios per misfit (e.g., scraper 5xx, cleaner empty, concurrent runs).
- **Architecture** — `tests/architecture/test_imports.py` shells out to `lint-imports`; `tests/architecture/test_helm.py` runs `helm template` and a secret scan.
- **E2E** — `tests/e2e/test_docker_compose.py`, marker `e2e`, deselected by default (`pytest -m 'not e2e'`).

### 4.4 Hard-coded constants
- `LowConfidencePolicy.refusal_message()` MUST return exactly `"I cannot answer based on the available content."` — asserted in `tests/fakes/test_low_confidence_policy_foundation.py`.

### 4.5 Idempotency
- `chunk_id = sha1(source_url + ":" + str(ordinal))[:40]` — stable; upserts are idempotent.
- `IngestionRunLock` TTL-keyed file at `<LOCK_DIR>/<run_id>.lock`, `ttl_seconds=600` default. Concurrent run returns `{"status": "skipped", "reason": "run_in_progress"}`. Acquire in `try` / release in `finally`.

---

## 5. Git workflow

- **Default branch is `main`.** Feature branches off `main`; PRs target `main`.
- **Conventional Commits** for every change:
  - `feat(<scope>): …` — implementation
  - `test(<layer>): …` — paired with the feat for TDD
  - `chore(<scope>): …` — housekeeping (e.g., `.gitignore`, lockfile churn, CI)
  - `docs(<scope>): …` — README, docs/architecture/
- **TDD split.** `test(domain): …` and `feat(domain): …` are **separate commits** — a paired commit is not a substitute for the test-first rule.
- **No `git push --force`, no `git commit --amend` after push, no `git filter-branch`.** If history is wrong, open a follow-up commit.

---

## 6. Observability — logging, metrics, tracing

This section combines the observability requirements with **three rules that govern every implementation**:

1. **OpenTelemetry for distributed tracing** in addition to the existing structured logs. Initialised in `composition/observability.py`; auto-instrumentation for FastAPI / httpx / logging; manual spans around every LangGraph node, every adapter call, the guard edge.
2. **A single `request_id` propagates through every layer** that touches a request — API middleware → use case parameter → `AgentState.request_id` → OTel `request.id` span attribute → adapter call logs → metric exemplar. The ingestion Job uses the same rule: `REQUEST_ID` env var becomes the `request_id` for the whole run; the lock file is `<LOCK_DIR>/<request_id>.lock`.
3. **All implementations must log enough to be debuggable** — DEBUG-level logs with enough context to reproduce every non-trivial branch, not just INFO summaries.

### 6.1 Structured logging — `structlog` JSON to stdout
- ISO timestamps, JSON renderer.
- Required fields per request: `timestamp`, `request_id`, `route`, `status_code`, `latency_ms`.
- Ingestion container emits the same shape with `route` set to the ingestion step name.

### 6.2 Request ID propagation — middleware is the FIRST middleware in FastAPI
- `RequestIdMiddleware` (a `BaseHTTPMiddleware`) reads `X-Request-Id` from inbound headers or generates `uuid4().hex`.
- Echoes `X-Request-Id` back on the response.
- Binds the value to **both**:
  - a `contextvars.ContextVar` so every `structlog` log line in the request scope inherits `request_id`,
  - the active OTel span via `trace.get_current_span().set_attribute("request.id", request_id)` so every span emitted in the request scope inherits the same attribute (even when no OTLP exporter is configured).
- Test: `tests/application/api/test_request_id_middleware_is_first.py`.

### 6.3 Single ID across all layers
- The `request_id` from `RequestIdMiddleware` MUST be:
  - attached to every log line emitted in the request scope via `structlog.contextvars.bind_contextvars(request_id=...)` in middleware `dispatch` (cleared in `finally`),
  - passed into the use case as an explicit parameter (`AskQuestionUseCase.execute(question: Question, *, request_id: str)` — `AnsweringService.answer(question, *, request_id=request_id)`),
  - stored in `AgentState` as `request_id: str` so LangGraph nodes can read it,
  - included as a span attribute (`request.id`) on every OTel span,
  - emitted in every metric label *or* as an exemplar (preferred for histograms),
  - logged at the start and end of every adapter call (`adapter.call.start`, `adapter.call.ok` with `adapter`, `operation`, `request_id`, `latency_ms`).
- **No layer may re-generate a new ID.** If a downstream service issues its own ID (e.g. Chroma), log both with explicit field names (`upstream_request_id`, never reuse the field `request_id`).
- The ingestion Job uses the same rule: `REQUEST_ID` env var (default `uuid4().hex`; `RUN_ID` is a deprecated alias) becomes the `request_id` for the whole run; fetch/clean/chunk/embed/upsert each emit a child OTel span named after the step and the same `request_id` in every log line. The lock file is named `<lock_dir>/<request_id>.lock` so on-disk artefacts, logs, spans, and Helm Job stdout all share one ID.

### 6.4 OpenTelemetry tracing
- **OTel SDK initialised in `composition/observability.py`**, imported once at the start of both `api_app.py` and `ingestion_main.py` (in that order — before building any adapter, app, or use case).
- Exporter: **OTLP/HTTP**, endpoint from `OTEL_EXPORTER_OTLP_ENDPOINT` env var (no exporter configured → spans still created and attached to logs, but discarded — this is the dev default).
- Resource attributes: `service.name=support-bot`, `service.namespace=<from env>`, `deployment.environment=<from env>`, `service.version=<from pyproject>`.
- **Auto-instrumentation** enabled at startup:
  - `opentelemetry-instrumentation-fastapi` (covers FastAPI routes),
  - `opentelemetry-instrumentation-httpx` (covers the HTTP embedder / answerer / cleaner adapters),
  - `opentelemetry-instrumentation-logging` (injects `trace_id` / `span_id` into every `structlog` log line),
  - `opentelemetry-instrumentation-chromadb` (covers the Chroma client).
- **Manual spans** are required around:
  - each LangGraph node (`tracer.start_as_current_span("node.<name>")` inside the node),
  - each adapter call (`tracer.start_as_current_span("adapter.<port>.<method>")`),
  - the guard / conditional edge in the LangGraph workflow (`node.guard_edge` with `decision.path`),
  - each ingestion step (`ingestion.run`, `ingestion.lock`, `ingestion.fetch`, `ingestion.clean`, `ingestion.analyze`, `ingestion.validate`, `ingestion.chunk`, `ingestion.embed`, `ingestion.upsert`).
- Span attributes that MUST be set:
  - `request.id` (= the propagated `request_id`),
  - `route` (FastAPI route template, e.g. `POST /ask`),
  - `question.text_hash` (sha256 hex of the user question — never the raw text),
  - `retrieval.top1_similarity`, `retrieval.candidate_count` (after the `retrieve` node),
  - `decision.path` (`generate` | `refuse` | `__end__`) on the guard span,
  - `answer.tokens_in`, `answer.tokens_out` when the answerer is called,
  - `embedder.backend`, `embedder.input_count`, `embedder.dimensions` on `adapter.embedder.embed`,
  - `vectorstore.chunk_count`, `vectorstore.source_url` on `adapter.vectorstore.upsert`,
  - `analyzer.region_count`, `analyzer.faq_count`, `analyzer.model`, `analyzer.tokens_in`, `analyzer.tokens_out` on `adapter.page_analyzer.analyze` and `ingestion.analyze`,
  - `source.url` on `ingestion.run`,
  - on validation rejection: `rejected.cleaned_length`, `min_cleaned_length`.
- **Sampling:** parent-based ratio. Default `OTEL_TRACES_SAMPLER=parentbased_traceidratio`, `OTEL_TRACES_SAMPLER_ARG=1.0` (sample everything in dev). Production: `0.1`.
- **PII rule:** never put the raw question or answer text in span attributes or span names. Use `sha256(text).hexdigest` (first 16 chars) as `*.text_hash`. The full text goes only to logs (after `SecretScrubber`).

### 6.5 Debug-level detail
- Every non-trivial branch MUST emit a debug-level log with enough context to diagnose without re-running. The bar: given only the log line and the line number, an engineer can explain *why* this branch was taken.
- Minimum `structlog` processors per module:
  1. `structlog.contextvars.merge_contextvars` (picks up `request_id`, `trace_id`, `span_id`),
  2. `structlog.processors.add_log_level`,
  3. `structlog.processors.TimeStamper(fmt="iso", utc=True)`,
  4. `SecretScrubber()` (custom processor — see §7.1),
  5. `structlog.processors.JSONRenderer()`.
- Recommended per-call shape (illustrating both halves of an adapter call):
  ```python
  logger.debug("adapter.call.start", adapter="HttpEmbedder",
               operation="embed", request_id=request_id,
               input_count=len(texts), batch_size=self._batch_size)
  # ... do the work ...
  logger.info("adapter.call.ok", adapter="HttpEmbedder",
              operation="embed", request_id=request_id,
              latency_ms=elapsed_ms, returned=len(vectors),
              dimensions=self._dimensions)
  ```
- The DEBUG-level line MUST include enough inputs to reproduce the call deterministically (counts, sizes, `*_text_hash` where the content itself is sensitive). INFO / ERROR lines MUST NOT include inputs that could leak secrets or large payload bodies. Use `*_text_hash` consistently when the content is text.

### 6.6 Metrics (Prometheus)
- `GET /metrics` — text/plain Prometheus exposition.
- Required series:
  - `request_count_total{route,status}` — counter, incremented on every response,
  - `request_latency_seconds{route}` — histogram (with `request_id` as OpenMetrics exemplar),
  - `retrieval_similarity_top1` — gauge, updated after `retrieve` (before generate / refuse),
  - `adapter_call_latency_seconds{adapter,operation}` — histogram (a parallel `prometheus_client.Histogram`; OTel → Prometheus bridge is acceptable as a follow-up).
- Where both Prometheus and OTel metrics exist, **prefer OTel** for new code; Prometheus stays for backwards compatibility with the existing `GET /metrics` endpoint.

### 6.7 Health endpoint
- `GET /healthz` returns 200 `{"status": "ok"}` regardless of Chroma reachability (per FR-002).

---

## 7. Security & secrets

### 7.1 `SecretScrubber` (HARD)
- One utility in `adapters/secret_scrubber.py`. Regex set: OpenAI `r"sk-[A-Za-z0-9]{32,}"`, Anthropic `r"sk-ant-[A-Za-z0-9-]{32,}"`, plus configurable substring set for `OPENAI_API_KEY`, `EMBEDDING_API_KEY`, `CHROMA_URL`. Replaces with `"[REDACTED]"`.
- Invoked by:
  - the `ErrorResponseMapper` on every error response body,
  - the `structlog` processor chain on every log line (see §6.5),
  - the OTel span-attribute filter (so scrubbed attributes never leave the process).
- Failure-injection tests assert: response bodies and log lines never contain `sk-` followed by 32+ chars.
- CI secret-scan: `helm template … | ( ! grep -E 'sk-[A-Za-z0-9]{32,}' )`.

### 7.2 Secrets handling
- API keys via env vars or mounted Kubernetes Secrets. Never in source, never baked into images, never logged, never returned in responses.
- `.env.example` lists every required env var with placeholders only.
- Helm Secret templates: `value:` is empty by default; values are supplied by the operator at install time.

### 7.3 Containers
- Multi-stage Dockerfiles, `USER app` (non-root), no secrets baked in.

---

## 8. Error mapping

| Exception (domain or application) | HTTP status | Body                                       |
| --------------------------------- | ----------- | ------------------------------------------ |
| `VectorStoreUnavailable`          | 503         | `{"detail": "vector store unavailable"}`   |
| `LLMUnavailable`                  | 502         | `{"detail": "answer generation unavailable"}` |
| `EmbedderUnavailable`             | 502         | `{"detail": "embedding unavailable"}`      |
| `ConfigurationError`              | 503         | `{"detail": "service not configured"}`     |
| `pydantic.ValidationError`        | 422         | `{"detail": "invalid request", "errors": [...]}` |
| any other `DomainError`           | 500         | `{"detail": "internal error"}`             |

All response body strings pass through `SecretScrubber` before placement or logging.

---

## 9. Configuration (`composition/settings.py`)

`BaseSettings` (`pydantic-settings`). Required keys:
- `SOURCE_URL` (default `""`)
- `CHROMA_HOST`, `CHROMA_PORT`
- `EMBEDDER_BACKEND` (`local`|`openai`)
- `ANSWERER_BACKEND` (`openai`|`fake`)
- `LOG_LEVEL` (default `INFO`)
- `LOCK_DIR` (default `/var/run/support-bot`)
- `REQUEST_ID` (default `uuid4().hex` — used as the request_id for the whole ingestion run; `RUN_ID` is a deprecated alias)
- `OTEL_EXPORTER_OTLP_ENDPOINT` (default empty → no exporter, spans attached to logs only)
- `OTEL_SERVICE_NAMESPACE`, `OTEL_DEPLOYMENT_ENVIRONMENT`
- `OTEL_TRACES_SAMPLER` (default `parentbased_traceidratio`)
- `OTEL_TRACES_SAMPLER_ARG` (default `1.0`)
- Secrets (never in defaults): `OPENAI_API_KEY`, `EMBEDDING_API_KEY`, `CHROMA_AUTH_TOKEN`.

---

## 10. Performance targets (NFR-001/002)

- `POST /ask` p95 < 3 s with up to 10,000 indexed chunks.
- `GET /healthz` p99 < 50 ms.
- Ingestion completes for the source page in < 60 s on a single CPU.
- API must survive a Chroma restart without crashing (next request after recovery succeeds).

---

## 11. Documentation deliverables

`README.md` has four sections: (1) local Docker Compose, (2) model / library / vector-store rationale, (3) LangGraph workflow design, (4) AWS view (EKS + ALB + Secrets Manager + EBS PVCs). Plus [`docs/architecture/local-flow.md`](docs/architecture/local-flow.md) and [`docs/architecture/aws-flow.md`](docs/architecture/aws-flow.md) with their prose walkthroughs. The spec-bridge artefacts live under `specs/001-customer-support-rag-agent/` — `spec.md`, `plan.md`, `decomposition.md`, `tasks.md`, and per-work-package task prompts in `tasks/WP*.md`. They are kept in-tree so a reviewer can trace each design decision back to the requirement and the WP that implemented it.

---

## 12. Summary of HARD rules (cheat-sheet)

1. Hexagonal layering — inward only; SDKs banned from `domain/`.
2. TDD — failing test committed before implementation, visible in commit log.
3. 100% docstring coverage on `domain/`, `application/`, `composition/` (`interrogate`).
4. ≥ 90% line coverage on `domain/` and `application/`; ≥ 70% on `adapters/`; ≥ 80% overall.
5. Worktree-only work — never edit `main` directly.
6. Conventional Commits — `feat(WP<NN>)`, paired `test(...)`, `chore(...)`, `docs(...)`.
7. Typed exceptions only — `DomainError` hierarchy; never bare `Exception`.
8. Secret scrubbing at every error response, every log line, every OTel attribute (`SecretScrubber`).
9. Structured JSON logs to stdout with `timestamp`, `request_id`, `route`, `status_code`, `latency_ms`.
10. `RequestIdMiddleware` is the FIRST middleware; `X-Request-Id` echoed on the response.
11. **OpenTelemetry tracing is mandatory**: SDK initialised in `composition/observability.py`; OTLP exporter via env; auto-instrumentation for FastAPI/httpx/logging/chromadb; manual spans around every LangGraph node, every adapter call, the guard edge, and every ingestion step; `request.id`, `route`, `*.text_hash` (sha256) and decision attributes on every span. No raw question/answer text in spans.
12. **Single request ID across all layers**: middleware → use case param → `AgentState.request_id` → OTel `request.id` attribute → adapter call logs → metrics exemplar. Never re-generate a downstream ID in the `request_id` field. `REQUEST_ID` env var (alias `RUN_ID`) for the ingestion Job.
13. **Debuggable logging**: DEBUG-level log per non-trivial branch with enough context to reproduce; INFO/ERROR lines carry latency_ms, status, counts, and IDs but never raw payloads or secrets.
14. Pydantic v2 frozen models; `mypy --strict` clean.
15. No `pydantic-settings` or `structlog` or `opentelemetry` in `domain/`.
16. `import-linter` enforces both `layers` (exhaustive) and `forbidden` SDK contracts.
17. Chroma via `chromadb.HttpClient`, not `PersistentClient`.
18. LangGraph 1.2.x: `START`/`END` sentinels, Pydantic `AgentState`, `Literal[...]` return types.
19. Stable chunk IDs: `sha1(source_url + ":" + ordinal)[:40]`.
20. Refusal message constant: exactly `"I cannot answer based on the available content."`.
21. Multi-stage non-root Dockerfiles, `python:3.11.9-slim-bookworm`, no secrets baked in.
22. Helm PVC `Retain`; ingestion Job `post-install,post-upgrade` + `hook-delete-policy: hook-succeeded`; `pre-install` hook validates required Secrets.
23. CI runs pytest, interrogate, lint-imports, helm lint, helm template --validate, secret scan — fail the build on any failure.