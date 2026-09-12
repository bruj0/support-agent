---
version: "1"
project_name: "Support Bot RAG + AWS Infrastructure"
created: "2026-09-12T13:00:00+00:00"
updated: "2026-09-12T15:00:00+00:00"
contexts_count: 4
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
- [AWS Identity & Secrets](../infra/modules/identity/CONTEXT.md) — Per-env
  KMS CMK + Secrets Manager entries + scoped IAM roles + EKS Pod Identity
  associations + GitHub Actions OIDC (EnvCmk, OpenAiSecret, ChromaAuthSecret,
  ExternalSecretsRole, AdotRole, AlbControllerRole, GithubActionsRole,
  GithubOidcProvider, PodIdentityAssociation).

## Inter-Context Relationships

- **Support Bot RAG Project → AWS Foundation**: the application code reads
  VPC outputs (`vpc_id`, `private_subnet_ids`) at deploy time via the
  Helm chart's values.yaml (operator-supplied). Adapters in
  `adapters/` are environment-agnostic.
- **AWS Foundation → AWS EKS Cluster & Compute**: Cluster module consumes
  `vpc_id`, `private_subnet_ids`, `vpc_endpoint_security_group_id` from
  the Foundation module. The Cluster module never references foundation
  resource addresses directly — only outputs.
- **AWS EKS Cluster & Compute → AWS Identity & Secrets**: Identity module
  consumes `eks_cluster_name` and `eks_oidc_provider_arn` from the Cluster
  module. Cluster module also consumes `cmk_arn` and `karpenter_iam_role_arn`
  from Identity as inputs (with placeholder defaults until Identity lands).
- **AWS Identity & Secrets → AWS Foundation**: Identity module is standalone
  w.r.t. Foundation (it does not consume VPC outputs directly — only the
  cluster). The CMK and secrets live in the same AWS account but do not
  depend on VPC placement.
- **AWS Identity & Secrets → Support Bot RAG Project**: the chart's
  additive `templates/externalsecret.yaml` references the Secrets Manager
  entries via the External Secrets Operator. The chart's additive
  `templates/serviceaccount.yaml` carries the EKS Pod Identity association
  annotations. Both are wired through `.Values.externalSecrets` and
  `.Values.serviceAccounts` blocks (added in WP03, default values updated).
