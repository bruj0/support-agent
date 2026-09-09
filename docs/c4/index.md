# C4 Architecture — `support-bot`

> **Audience:** anyone reviewing the public `support-agent`
> repository who wants a C4-model view of the system in
> addition to the prose walkthrough in
> [`docs/architecture/architecture.md`](../architecture/architecture.md).
>
> The C4 model is a hierarchical set of diagrams:
>
> - **Level 1 — System Context:** one diagram showing the
>   system as a black box, its users, and the external
>   systems it talks to.
> - **Level 2 — Containers:** one diagram zooming into the
>   system to show the deployable units (processes /
>   containers / pods) and how they communicate.
> - **Level 3 — Components:** one diagram per container
>   showing the major software components inside it and
>   their dependencies.
> - **Level 4 — Code:** class / function-level diagrams
>   for the most complex components (we cover these in
>   the **Deep Dives** section rather than as UML).
>
> Source of truth: the diagrams in this folder were
> generated from the actual code in `src/support_bot/`
> and the Helm chart in `deploy/helm/support-bot/`.

## Table of contents

| Level | Document | What it shows |
|---|---|---|
| 1 | [System Context](1-system-context.md) | The Ziggo customer on one side; OpenAI, Chroma, and the source web page on the other. |
| 2 | [Containers](2-containers.md) | The FastAPI service, the ingestion Job, and the Chroma container — how they communicate, what they depend on. |
| 3 | [Components](3-components.md) | The hexagonal layers (`domain` / `application` / `adapters` / `composition`) inside the API service, the ports, and the wired adapters. |
| 4 | [Deep Dive — Ingestion pipeline](4-deep-dive-ingestion.md) | Stages A and B: how a source page becomes 17 persisted vectors in Chroma. |
| 4 | [Deep Dive — Answering workflow](4-deep-dive-answering.md) | The LangGraph topology, state evolution, conditional edge, refusal path. |
| 4 | [Deep Dive — Observability](4-deep-dive-observability.md) | Single `request_id` propagation through middleware → use case → AgentState → OTel span → log line → metric. |
| 4 | [Deep Dive — Deployment](4-deep-dive-deployment.md) | Helm chart layout: API Deployment + Chroma StatefulSet + ingestion Job + PVC + Secret templates. |

## Companion documents (not C4)

- [`../architecture.md`](../architecture/architecture.md) — the prose walkthrough of the source tree.
- [`../architecture/local-flow.md`](../architecture/local-flow.md) — the local-flow diagram + 9-step walkthroughs.
- [`../architecture/aws-flow.md`](../architecture/aws-flow.md) — the AWS production diagram + scaling / security / failure-mode tables.
- [`../index.md`](../index.md) — the README rendered as the site home.
