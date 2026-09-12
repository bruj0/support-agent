---
context_name: "Observability & Policy"
version: "1"
subsystem: "infra/modules/observability"
created: "2026-09-12T20:00:00+00:00"
updated: "2026-09-12T20:00:00+00:00"
---

# Observability & Policy

Observability & Policy is the cross-cutting substrate that enforces the policy constraints and emits the telemetry signals every other subsystem depends on. The ADOT collector receives OTLP traces + metrics from the application pods and exports them to AWS X-Ray + CloudWatch EMF; the namespace PSS labels enforce Kubernetes pod security standards; the NetworkPolicy resources deny by default and allow by exception per workload (api, chroma).

## Language

**AdotCollectorHelm**:
The AWS Distro for OpenTelemetry collector installed via Helm as a DaemonSet on `hostNetwork=true`, with Pod Identity association to the `AdotRole`. Receives OTLP on `:4317` (gRPC) / `:4318` (HTTP) and exports traces to awsxray + metrics to awsemf.
_Avoid_: otel_collector, collector, otel
_Subsystems_: Observability & Policy, Identity & Secrets
_Files_: infra/modules/observability/main.tf, infra/modules/observability/outputs.tf
_Relates to_: AdotRole (Pod Identity assumption)

**ApplicationLogGroup**:
The CloudWatch Logs group `/aws/eks/support-bot-<env>/application` that retains the application pods' stdout for 30 days, encrypted with the per-env CMK from Identity.
_Avoid_: app_logs, api_logs
_Subsystems_: Observability & Policy
_Files_: infra/modules/observability/main.tf
_Relates to_: EnvCmk (KMS key)

**OtelLogGroup**:
The CloudWatch Logs group `/aws/eks/support-bot-<env>/otel` that retains the ADOT collector's own logs for 7 days, encrypted with the per-env CMK.
_Avoid_: otel_logs, collector_logs, adot_logs
_Subsystems_: Observability & Policy
_Files_: infra/modules/observability/main.tf
_Relates to_: EnvCmk (KMS key)

**PodSecurityStandards**:
The set of labels attached to the `support-bot` namespace that enforces Kubernetes Pod Security Standards in `restricted` mode for enforce + warn + audit. The labels are applied via `kubernetes_manifest` on the Namespace resource.
_Avoid_: pss, pod_security, namespace_labels
_Subsystems_: Observability & Policy
_Files_: infra/modules/observability/main.tf
_Relates to_: ApplicationWorkload (governed by these labels)

**NetworkPolicies**:
The trio of `networking.k8s.io/v1` NetworkPolicy resources in the `support-bot` namespace that implement "deny by default, allow by exception": `default-deny` (empty podSelector, both Ingress+Egress in policyTypes), `api-allow` (allows API pod ingress from any namespace pod, egress to Chroma:8000, OpenAI :443, ADOT :4318, kube-dns :53, EKS API :443), `chroma-allow` (allows Chroma pod ingress from API pod, egress to ADOT:4318, kube-dns:53, EKS API :443).
_Avoid_: netpol, network_policy_rules, firewall_rules
_Subsystems_: Observability & Policy, Edge & Traffic (ALB ingress allowed via podSelector wildcard)
_Files_: infra/modules/observability/main.tf, deploy/helm/support-bot/templates/networkpolicy.yaml
_Relates to_: VpcCniAddon (prerequisite — NetworkPolicy enforcement requires enableNetworkPolicy=true on the VPC CNI addon, set in WP02)

**VpcCniNetworkPolicy**:
The VPC CNI add-on configuration that enables NetworkPolicy enforcement (`enableNetworkPolicy=true`). Owned by S2 Cluster & Compute (set in WP02 main.tf `aws_eks_addon.vpc_cni` configuration). WP06's NetworkPolicies have no effect without this add-on configuration; this is a sequencing requirement.
_Avoid_: vpc_cni_policy, network_policy_addon
_Subsystems_: Cluster & Compute
_Files_: (set in modules/cluster/main.tf)
_Relates to_: NetworkPolicies (prerequisite)

## Relationships

- An **AdotCollectorHelm** exports traces to awsxray + metrics to awsemf, and writes its own log to an OtelLogGroup.
- **PodSecurityStandards** labels govern the `support-bot` namespace; admitted pods must satisfy `restricted` mode in enforce + warn + audit.
- A **NetworkPolicies** deny by default (`default-deny`) and allow by exception (per-workload `*-allow` policies).

## Flagged Ambiguities

- "OTel" vs "OTel collector" — resolved: prefer **AdotCollectorHelm** for the AWS Distro; "OpenTelemetry Collector" acceptable only when referring to the upstream project.
- "policy" vs "NetworkPolicy" — resolved: **NetworkPolicies** always refers to the `networking.k8s.io/v1` NetworkPolicy resources; "security policy" is the abstract concept, not a Kubernetes object.
- The default-deny NetworkPolicy uses `podSelector: {}` (empty selector) which selects ALL pods in the namespace. Combined with per-workload allow policies, this implements "deny by default, allow by exception". When the operator adds a new workload, they must add a corresponding allow policy or it will be unable to receive traffic.
