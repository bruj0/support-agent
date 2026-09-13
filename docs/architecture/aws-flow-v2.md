# Alternative AWS View (v2)

This document supersedes `aws-flow.md`. It describes the OpenTofu-managed
infrastructure that this feature (`002-alternative-aws-infrastructure`)
provisions.

## Topology

```
Route 53 ─▶ ACM (TLS) ─▶ WAFv2 ─▶ ALB (internal-scheme, TLS termination)
                                  │
                          (AWS LBC, target-type: ip)
                                  │
                  ┌───────────────┼─────────────────┐
                  ▼ ▼
 EKS private subnets (3 AZs)        EKS public subnets (none)
                  ┌──────────────────────────────┐
                  │  API Deployment (HPA 2–6)     │
                  │  Ingestion Job (post-install)│
                  │  Chroma Deployment (1)      │
                  └──────────────────────────────┘
                                  │
                  ┌───────────────┼─────────────────┐
                  ▼               ▼                  ▼
         AWS Secrets Mgr    ADOT Collector     CloudWatch Logs
         (Pod Identity)     (hostNetwork)      (application + otel)
                                  │
                                  ▼
                            AWS X-Ray + AMP
```

## Six subsystems

| Subsystem | Module | Components |
|---|---|---|
| S1 Foundation | `infra/modules/foundation/` | VPC, subnets, NAT, VPC endpoints |
| S2 Cluster & Compute | `infra/modules/cluster/` | EKS, baseline MNG, Karpenter v1 NodePool |
| S3 Identity & Secrets | `infra/modules/identity/` | KMS CMK, Secrets Manager, IAM roles (scoped) |
| S4 Edge & Traffic | `infra/modules/edge/` | ACM, Route53, WAFv2, ALBC, Ingress |
| S5 Data Plane & Storage | `infra/modules/storage/` | StorageClass, ECR, DLM |
| S6 Observability & Policy | `infra/modules/observability/` | ADOT, NetworkPolicy, PSS |

## Secrets chain

Secrets Manager → ESO → Kubernetes Secret → env var.

The OpenAI key is supplied at `tofu apply` time via `TF_VAR_openai_api_key`.
It is written to Secrets Manager (`prevent_destroy = true`), encrypted
with the per-env CMK. ESO (with Pod Identity) reads it every `refreshInterval`
(default 1m) and updates the Kubernetes Secret. The chart's Deployment
templates read the env var from the Kubernetes Secret — no key ever
appears in HCL, in `helm template` output, in Terraform state (encrypted
with the bootstrap CMK), or in CloudWatch logs.

## Karpenter

One `NodePool` (`burst`) with:

- capacity types `["spot", "on-demand"]`
- instance generation `>= 5`, categories `["c", "m", "r"]`
- `consolidationPolicy = WhenEmptyOrUnderutilized`

Baseline MNG (2× `m7i.large` On-Demand) covers steady-state; Karpenter
absorbs HPA scale-out to replicas 6.

## Chart boundary

The chart is **additive-only**:

- New templates: `externalsecret.yaml`, `serviceaccount.yaml`, `ingress.yaml`, `networkpolicy.yaml`.
- Existing 8 templates: unchanged.
- Existing values: additive keys keys (`persistence.storageClassName`, `externalSecrets`, `serviceAccounts`, `ingress`, `networkPolicies`, `podLabels`).
- **The chart is never installed by OpenTofu.** Deployment is a downstream CI/CD feature.

## What is NOT in this feature

- Helm chart installation (downstream CI/CD feature)
- GitHub Actions CI/CD workflow (separate feature)
- Argo CD / Flux GitOps (separate feature)
- Multi-region DR
- Cosign signing enforcement on EKS (separate feature)
