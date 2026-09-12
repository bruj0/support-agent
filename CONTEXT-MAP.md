---
version: "1"
project_name: "Support Bot RAG + AWS Infrastructure"
created: "2026-09-12T13:00:00+00:00"
updated: "2026-09-12T13:00:00+00:00"
contexts_count: 3
---

# Context Map

This project has multiple bounded contexts. Each context owns its
canonical vocabulary; cross-context relationships are mapped below.

## Contexts

- [Support Bot RAG Project](../CONTEXT.md) — Application domain vocabulary
  for the customer-support RAG assistant (SourcePage, Chunk, AgentState,
  Port, Adapter, LangGraphWorkflow, etc.). One bounded context for the
  Python application.
- [AWS Foundation (VPC substrate)](../infra/modules/foundation/CONTEXT.md) —
  Per-environment VPC substrate consumed by every other subsystem module
  (FoundationVpc, PublicSubnet, PrivateSubnet, NatGateway, VpcEndpoint,
  RootModule).
- [AWS EKS Cluster & Compute](../infra/modules/cluster/CONTEXT.md) — EKS
  control plane + OIDC + baseline compute + Karpenter v1 controller that
  hosts every workload (EksCluster, OidcProvider, BaselineNodeGroup,
  VpcCniAddon, PodIdentityAgentAddon, KarpenterController,
  KarpenterNodePool, KarpenterEc2NodeClass).

## Inter-Context Relationships

- **Support Bot RAG Project → AWS Foundation**: the application code reads
  VPC outputs (`vpc_id`, `private_subnet_ids`) at deploy time via the
  Helm chart's values.yaml (operator-supplied). Adapters in
  `adapters/` are environment-agnostic.
- **AWS Foundation → AWS EKS Cluster & Compute**: Cluster module consumes
  `vpc_id`, `private_subnet_ids`, `vpc_endpoint_security_group_id` from
  the Foundation module. The Cluster module never references foundation
  resource addresses directly — only outputs.
- **AWS EKS Cluster & Compute → AWS Foundation (planned WP03)**: identity
  (CMK ARN, Karpenter node role ARN) lives in WP03's identity module;
  Cluster module consumes both as inputs with placeholder values until
  WP03 ships.
