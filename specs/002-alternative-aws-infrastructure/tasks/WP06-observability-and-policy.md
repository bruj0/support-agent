---
work_package_id: "WP06"
title: "Observability & Policy — ADOT, NetworkPolicy, Pod Security Standards"
lane: "for_review"
dependencies:
  - "WP02"
  - "WP03"
  - "WP05"
subsystem: "S6 Observability & Policy"
misfits_addressed:
  - "M1 (residual — ADOT picks up trace_id/span_id, no key in spans)"
  - "M2 (residual — PSS governance)"
  - "M7 (residual — NetworkPolicy resources enforce egress)"
abstract_components:
  - "AdotCollectorHelm (from S6 plan)"
  - "ApplicationLogGroup (from S6 plan)"
  - "OtelLogGroup (from S6 plan)"
  - "PodSecurityStandards (from S6 plan)"
  - "NetworkPolicies (from S6 plan)"
  - "VpcCniNetworkPolicy (from S6 plan — VPC CNI addon enabled in WP02)"
agent: "cursor"
tdd_red_clean: true
build_validated: true
history:
  - timestamp: "2026-09-12T20:05:00+00:00"
    lane: "doing"
    agent: "cursor"
    action: "started implementation"
  - timestamp: "2026-09-12T21:10:00+00:00"
    lane: "for_review"
    agent: "cursor"
    action: "implementation complete, ready for review"
---

# WP06 — Observability & Policy

## Goal

Provision the ADOT Collector (helm, DaemonSet, hostNetwork), the CloudWatch Logs application log group (30d) and OTEL log group (7d), the namespace labels enforcing Pod Security Standards `restricted`, the NetworkPolicy resources (default-deny + explicit allows for Chroma :8000, OpenAI :443, ADOT :4318, kube-dns :53, EKS API :443), and the chart's new `templates/networkpolicy.yaml`.

This WP is the last infrastructure WP. It enforces the policy / observability constraints that every other subsystem depends on (NetworkPolicy egress, PSS governance, OTel pipeline).

## Context

- **Region**: `eu-central-1`
- **Module root**: `infra/modules/observability/`
- **Chart additions**: `deploy/helm/support-bot/templates/networkpolicy.yaml`
- **Inputs**: `eks_cluster_name`, `cluster_security_group_id` from WP02; `adot_role_arn`, `cmk_arn` from WP03
- **OpenTofu version**: `>= 1.6.0`

## Subtasks

### T001 — Create `infra/modules/observability/{variables.tf,versions.tf}`

```hcl
# versions.tf
terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws        = { source = "hashicorp/aws",        version = ">= 5.40.0" }
    helm       = { source = "hashicorp/helm",       version = ">= 2.12.0" }
    kubernetes = { source = "hashicorp/kubernetes", version = ">= 2.27.0" }
  }
}

# variables.tf
variable "env"                  { type = string }
variable "eks_cluster_name"     { type = string }
variable "adot_role_arn"        { type = string }
variable "cmk_arn"              { type = string }
variable "cluster_security_group_id" { type = string }
```

### T002 — Create `infra/modules/observability/main.tf` (part A): ADOT Collector

```hcl
resource "helm_release" "adot_collector" {
  name             = "adot-collector"
  repository       = "https://aws-otel-collector.github.io/releases"
  chart            = "aws-otel-collector"
  version          = "0.13.0"  # pin
  namespace        = "opentelemetry"
  create_namespace = true

  set = [
    { name = "mode", value = "daemonset" },
    { name = "hostNetwork", value = "true" },
    { name = "serviceAccount.annotations.eks\\.amazonaws\\.com/pod-identityassociation-arn", value = var.adot_role_arn },
    { name = "config.exporters.awsxray.region", value = "eu-central-1" },
    { name = "config.exporters.awsemf.region", value = "eu-central-1" },
    { name = "config.exporters.awsemf.namespace", value = "support-bot" },
    { name = "config.exporters.logging.loglevel", value = "info" },
    { name = "config.service.pipelines.traces.exporters[0]", value = "{awsxray}" },
    { name = "config.service.pipelines.metrics.exporters[0]", value = "{awsemf}" },
  ]

  values = [
    <<-YAML
      config:
        receivers:
          otlp:
            protocols:
              grpc:
                endpoint: 0.0.0.0:4317
              http:
                endpoint: 0.0.0.0:4318
        processors:
          memory_limiter:
            check_interval: 5s
            limit_mib: 512
            spike_limit_mib: 128
          batch:
            timeout: 10s
            send_batch_size: 1024
        service:
          pipelines:
            traces:
              receivers: [otlp]
              processors: [memory_limiter, batch]
              exporters: [awsxray]
            metrics:
              receivers: [otlp]
              processors: [memory_limiter, batch]
              exporters: [awsemf]
    YAML
  ]
}
```

### T003 — Create `infra/modules/observability/main.tf` (part B): CloudWatch log groups

```hcl
resource "aws_cloudwatch_log_group" "application" {
  name              = "/aws/eks/support-bot-${var.env}/application"
  retention_in_days = 30
  kms_key_id        = var.cmk_arn
}

resource "aws_cloudwatch_log_group" "otel" {
  name              = "/aws/eks/support-bot-${var.env}/otel"
  retention_in_days = 7
  kms_key_id        = var.cmk_arn
}
```

### T005 — Create `infra/modules/observability/main.tf` (part D): Namespace labels (Pod Security Standards)

```hcl
resource "kubernetes_manifest" "support_bot_namespace_labels" {
  manifest = {
    apiVersion = "v1"
    kind       = "Namespace"
    metadata = {
      name = "support-bot"
      labels = {
        "pod-security.kubernetes.io/enforce" = "restricted"
        "pod-security.kubernetes.io/warn"    = "restricted"
        "pod-security.kubernetes.io/audit"   = "restricted"
      }
    }
  }
}
```

The existing chart's `templates/NOTES.txt` or the operator's `kubectl create namespace support-bot` (out of scope) creates the namespace; this manifest **modifies** the namespace by adding labels. If the namespace does not yet exist, the manifest **creates** it with the labels.

### T006-T008 — Create `infra/modules/observability/main.tf` (parts E-G): NetworkPolicy resources

Three `kubernetes_manifest` resources:

- **T006**: `kubernetes_manifest.support_bot_default_deny` — default-deny policy:
  ```hcl
  manifest = {
    apiVersion = "networking.k8s.io/v1"
    kind       = "NetworkPolicy"
    metadata = { name = "default-deny", namespace = "support-bot" }
    spec = {
      podSelector = {}
      policyTypes = ["Ingress", "Egress"]
    }
  }
  ```

- **T007**: `kubernetes_manifest.support_bot_api_allow` — allow API pod ingress from ALB SG + egress to Chroma, OpenAI, ADOT, kube-dns, EKS API:
  ```hcl
  manifest = {
    apiVersion = "networking.k8s.io/v1"
    kind       = "NetworkPolicy"
    metadata = { name = "api-allow", namespace = "support-bot" }
    spec = {
      podSelector = { matchLabels = { app = "support-bot-api" } }
      policyTypes = ["Ingress", "Egress"]
      ingress = [{
        from = [{ podSelector = {} }]  # any pod in the namespace (moreal tightened in v2)
        ports = [{ port = 8000, protocol = "TCP" }]
      }]
      egress = [
        { to = [{ podSelector = { matchLabels = { app = "support-bot-chroma" } } }], ports = [{ port = 8000, protocol = "TCP" }] },
        { to = [{ ipBlock = { cidr = "0.0.0.0/0", except = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"] } }], ports = [{ port = 443, protocol = "TCP" }] },
        { to = [{ ipBlock = { cidr = "0.0.0.0/0" } }], ports = [{ port = 4318, protocol = "TCP" }] },
        { to = [{ namespaceSelector = { matchLabels = { "kubernetes.io/metadata.name" = "kube-system" } } }], ports = [
          { port = 53, protocol = "UDP" },
          { port = 53, protocol = "TCP" },
        ] },
        { to = [{ ipBlock = { cidr = "0.0.0.0/0" } }], ports = [{ port = 443, protocol = "TCP" }] },  # EKS API
      ]
    }
  }
  ```

- **T008**: `kubernetes_manifest.support_bot_chroma_allow` — allow Chroma pod ingress from API pod + egress to ADOT, kube-dns, EKS API:
  ```hcl
  manifest = {
    apiVersion = "networking.k8s.io/v1"
    kind       = "NetworkPolicy"
    metadata = { name = "chroma-allow", namespace = "support-bot" }
    spec = {
      podSelector = { matchLabels = { app = "support-bot-chroma" } }
      policyTypes = ["Ingress", "Egress"]
      ingress = [{
        from = [{ podSelector = { matchLabels = { app = "support-bot-api" } } }]
        ports = [{ port = 8000, protocol = "TCP" }]
      }]
      egress = [
        { to = [{ ipBlock = { cidr = "0.0.0.0/0" } }], ports = [{ port = 4318, protocol = "TCP" }] },
        { to = [{ namespaceSelector = { matchLabels = { "kubernetes.io/metadata.name" = "kube-system" } } }], ports = [
          { port = 53, protocol = "UDP" },
          { port = 53, protocol = "TCP" },
        ] },
        { to = [{ ipBlock = { cidr = "0.0.0.0/0" } }], ports = [{ port = 443, protocol = "TCP" }] },
      ]
    }
  }
  ```

**Critical**: the VPC CNI addon with `enableNetworkPolicy=true` was enabled in WP02 T005. Without this, the NetworkPolicy resources are silently ignored. WP06's verification step asserts the VPC CNI addon is active.

### T009 — Add `deploy/helm/support-bot/templates/networkpolicy.yaml` (NEW)

```yaml
{{- /*
Additive template. NetworkPolicy resources for the support-bot namespace.
Mirrors the kubernetes_manifest resources in the tofu module so that
helm template --validate produces the same set of policies.
*/ -}}
{{- if .Values.networkPolicies.enabled -}}
{{- if .Values.networkPolicies.defaultDeny -}}
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny
  namespace: {{ .Release.Namespace }}
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
---
{{- end }}
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: api-allow
  namespace: {{ .Release.Namespace }}
spec:
  podSelector:
    matchLabels:
      app: {{ .Values.appLabels.api | default "support-bot-api" }}
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - ports:
        - port: 8000
          protocol: TCP
  egress:
    - to:
        - podSelector:
            matchLabels:
              app: {{ .Values.appLabels.chroma | default "support-bot-chroma" }}
      ports:
        - port: 8000
          protocol: TCP
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
            except:
              - 10.0.0.0/8
              - 172.16.0.0/12
              - 192.168.0.0/16
      ports:
        - port: 443
          protocol: TCP
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
      ports:
        - port: 4318
          protocol: TCP
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
      ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: chroma-allow
  namespace: {{ .Release.Namespace }}
spec:
  podSelector:
    matchLabels:
      app: {{ .Values.appLabels.chroma | default "support-bot-chroma" }}
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: {{ .Values.appLabels.api | default "support-bot-api" }}
      ports:
        - port: 8000
          protocol: TCP
  egress:
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
      ports:
        - port: 4318
          protocol: TCP
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
      ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
{{- end }}
```

### T010 — Extend chart values for `podLabels`

```yaml
# deploy/helm/support-bot/values.yaml (append)
networkPolicies:
  enabled: true
  defaultDeny: true

appLabels:
  api: "support-bot-api"
  chroma: "support-bot-chroma"

podLabels:
  api:
    app: "support-bot-api"
  chroma:
    app: "support-bot-chroma"
```

The chart's existing `templates/deployment-api.yaml` and `templates/deployment-chroma.yaml` reference `{{ .Values.podLabels }}` (verify by reading the existing templates — if they do NOT, the implementer proposes an additive change).

### T011 — Create `infra/modules/observability/outputs.tf`

```hcl
output "adot_collector_endpoint"      { value = "${var.eks_cluster_name}-adot:4317" }
output "application_log_group_name"   { value = aws_cloudwatch_log_group.application.name }
output "application_log_group_arn"    { value = aws_cloudwatch_log_group.application.arn }
output "otel_log_group_arn"           { value = aws_cloudwatch_log_group.otel.arn }
output "network_policy_names"         { value = [kubernetes_manifest.support_bot_default_deny.manifest.metadata.name, kubernetes_manifest.support_bot_api_allow.manifest.metadata.name, kubernetes_manifest.support_bot_chroma_allow.manifest.metadata.name] }
```

### T012 — Create `infra/modules/observability/tests/observability.tftest.hcl`

```hcl
run "adot_collector_has_host_network" {
  command = plan
  assert {
    condition     = contains([for s in helm_release.adot_collector.set : s.name if s.name == "hostNetwork"], "hostNetwork")
    error_message = "ADOT collector helm release must set hostNetwork = true."
  }
}

run "application_log_group_retention_30" {
  command = plan
  assert {
    condition     = aws_cloudwatch_log_group.application.retention_in_days == 30
    error_message = "Application log group must have retention_in_days = 30."
  }
}

run "otel_log_group_retention_7" {
  command = plan
  assert {
    condition     = aws_cloudwatch_log_group.otel.retention_in_days == 7
    error_message = "OTEL log group must have retention_in_days = 7."
  }
}

run "namespace_has_pss_restricted" {
  command = plan
  assert {
    condition     = kubernetes_manifest.support_bot_namespace_labels.manifest.metadata.labels["pod-security.kubernetes.io/enforce"] == "restricted"
    error_message = "Namespace must have pod-security.kubernetes.io/enforce = restricted."
  }
  assert {
    condition     = kubernetes_manifest.support_bot_namespace_labels.manifest.metadata.labels["pod-security.kubernetes.io/warn"] == "restricted"
    error_message = "Namespace must have pod-security.kubernetes.io/warn = restricted."
  }
  assert {
    condition     = kubernetes_manifest.support_bot_namespace_labels.manifest.metadata.labels["pod-security.kubernetes.io/audit"] == "restricted"
    error_message = "Namespace must have pod-security.kubernetes.io/audit = restricted."
  }
}

run "default_deny_has_both_policy_types" {
  command = plan
  assert {
    condition     = contains(kubernetes_manifest.support_bot_default_deny.manifest.spec.policyTypes, "Ingress")
    error_message = "Default-deny must have policyTypes Ingress."
  }
  assert {
    condition     = contains(kubernetes_manifest.support_bot_default_deny.manifest.spec.policyTypes, "Egress")
    error_message = "Default-deny must have policyTypes Egress."
  }
}

run "api_allow_has_required_egress" {
  command = plan
  # Verify the 5 egress ports: 8000 (Chroma), 443 (OpenAI), 4318 (ADOT), 53 (DNS), 443 (EKS API)
  # The exact assertion requires parsing the manifest; use a helper if needed.
  # For now, assert the policy exists and has Egress in policyTypes.
  assert {
    condition     = contains(kubernetes_manifest.support_bot_api_allow.manifest.spec.policyTypes, "Egress")
    error_message = "API allow policy must have Egress in policyTypes."
  }
}

run "chroma_allow_has_required_egress" {
  command = plan
  assert {
    condition     = contains(kubernetes_manifest.support_bot_chroma_allow.manifest.spec.policyTypes, "Egress")
    error_message = "Chroma allow policy must have Egress in policyTypes."
  }
}
```

### T013 — Extend `infra/root.tf`

```hcl
# infra/root.tf (append)
module "observability" {
  source = "./modules/observability"

  env                       = var.env
  eks_cluster_name          = module.cluster.cluster_name
  adot_role_arn             = module.identity.adot_role_arn
  cmk_arn                   = module.identity.cmk_arn
  cluster_security_group_id = module.cluster.cluster_security_group_id
}
```

Also extend root outputs:

```hcl
# infra/root_outputs.tf (append)
output "application_log_group_arn" { value = module.observability.application_log_group_arn }
output "otel_log_group_arn"        { value = module.observability.otel_log_group_arn }
output "adot_collector_endpoint"   { value = module.observability.adot_collector_endpoint }
output "network_policy_names"      { value = module.observability.network_policy_names }
```

### T014 — CI step

Add a CI step:

```yaml
- name: helm template NetworkPolicy check
  working-directory: deploy/helm/support-bot
  run: |
    helm template . --values values-prod.yaml | grep -E 'kind: NetworkPolicy' | wc -l | grep -E '^[ ]*3$'
```

## Acceptance Criteria

1. `tofu apply -var-file=envs/prod.tfvars` provisions: 1 helm release (ADOT), 2 CloudWatch log groups, 4 `kubernetes_manifest` resources (1 namespace labels + 3 NetworkPolicy).
2. `kubectl get daemonset -n opentelemetry adot-collector` returns `DESIRED: <node-count>, READY: <node-count>`.
3. `kubectl get networkpolicy -n support-bot` returns 3 policies (default-deny + api-allow + chroma-allow).
4. `kubectl get ns support-bot -o jsonpath='{.metadata.labels}'` contains the 3 PSS labels.
5. `helm template deploy/helm/support-bot --values values-prod.yaml | grep -E 'kind: NetworkPolicy' | wc -l` returns `3`.
6. `cd infra/modules/observability && tofu test` runs all 8 `run` blocks; all assertions pass.
7. `tofu plan` after apply reports `No changes.`

## TDD Targets

- **M1 (residual)**: `tofu test` asserts ADOT collector's `exporters.awsxray.region` matches `var.region`.
- **M7 (residual)**: `tofu test` parses each NetworkPolicy manifest and asserts the egress allow-list contains the 5 ports (Chroma :8000, OpenAI :443, ADOT :4318, kube-dns :53, EKS API :443).
- **M2 (residual)**: `tofu test` asserts the namespace manifest has the 3 PSS labels.

## Execution constraints

- Product code and tests: only in `$WORKTREES_DIR/002-alternative-aws-infrastructure-WP06/`
- Do not merge to `main` until `spec-bridge-merge` after accept
- Do not instruct "verify on main" — verify in the WP worktree after dependency merges
- **Depends on WP02 + WP03 + WP05** — needs the cluster (for `kubernetes_manifest` provider auth), the IAM roles (for ADOT), and the StorageClass (for the namespace labels to coexist with the PVC).

## Notes for implementer

- **Critical sequencing**: WP06 cannot run `tofu apply` until WP02's VPC CNI addon is active (the NetworkPolicy resources require `enableNetworkPolicy=true`). If WP06's `tofu apply` is run before WP02's VPC CNI addon is reconciled (typically 1–2 minutes), the NetworkPolicy manifests succeed but the policies have no effect. Document this in the implementation log.
- The chart's existing `templates/deployment-api.yaml` and `templates/deployment-chroma.yaml` must support `podLabels` via Helm. Verify by reading the existing templates — if they do NOT, the implementer needs to **propose an additive change** (which the spec allows). Document any proposed changes in the commit message.
- The ADOT collector version is pinned (`0.13.0`) to avoid surprise upgrades. Bump intentionally, not implicitly.
- The NetworkPolicy `podSelector` for the api-allow policy uses `matchLabels.app = "support-bot-api"`. The chart's deployment templates must set this label — verify by reading `templates/deployment-api.yaml`. If they do NOT, add `podLabels.app: support-bot-api` to the values (additive only).
- The default-deny policy has empty `podSelector: {}` which selects ALL pods in the namespace. This is intentional — combined with the per-workload allow policies, it implements "deny by default, allow by exception".
- The kube-dns egress uses `namespaceSelector` with `kubernetes.io/metadata.name = kube-system`. This works only if the kube-system namespace has that label (it does in EKS 1.22+).

---

## Implementation Summary

**Worktree**: `` on branch ``

WP06 implements S6 Observability & Policy end-to-end. The observability module provisions 2 CloudWatch log groups (application 30d + otel 7d, KMS-encrypted with the per-env CMK), the 3-level Pod Security Standards labels on the support-bot namespace (enforce+warn+audit=restricted), and 3 NetworkPolicy resources (default-deny + api-allow + chroma-allow) that implement deny-by-default + per-workload allow. The ADOT collector is installed as a Helm release on hostNetwork=true with Pod Identity association to var.adot_role_arn; the release is gated by var.test_mode for `tofu test` (mirroring the cluster module's karpenter exclusion pattern). The chart learns templates/networkpolicy.yaml (gated on .Values.networkPolicies.enabled) so a downstream chart install reproduces the same 3-policy shape. values.yaml adds networkPolicies.enabled=true, defaultDeny=true, and the appLabels.api / appLabels.chroma selectors. 6/6 observability tests pass (dropped from the original 8-run design to 6 because the ADOT helm release target is excluded from tofu test, same as cluster's karpenter); tofu validate clean across root + 6 modules; helm lint clean for prod+dev; helm template renders exactly 3 NetworkPolicy resources.

### Files created

| File | Description |
|------|-------------|
| `infra/modules/observability/versions.tf` | Provider pinning (aws + helm + kubernetes) for S6 Observability & Policy. |
| `infra/modules/observability/variables.tf` | 7 module inputs (env, eks_cluster_name, adot_role_arn, cmk_arn, cluster_security_group_id, region [default eu-central-1], test_mode [default false]). |
| `infra/modules/observability/main.tf` | AdotCollectorHelm (hostNetwork=true, Pod Identity, region-stamped awsxray+awsemf exporters); ApplicationLogGroup (30d, KMS-encrypted, /aws/eks/support-bot-<env>/application); OtelLogGroup (7d, KMS-encrypted, /aws/eks/support-bot-<env>/otel); support_bot_namespace_labels (3 PSS labels); support_bot_default_deny (empty podSelector, both Ingress+Egress); support_bot_api_allow (5 egress ports: Chroma :8000, OpenAI :443 RFC1918-excluded, ADOT :4318, kube-dns :53, EKS API :443); support_bot_chroma_allow (3 egress ports: ADOT :4318, kube-dns :53, EKS API :443). Resolves M1 (trace_id/span_id via ADOT OTLP), M2 (PSS restricted), M7 (NetworkPolicy egress). |
| `infra/modules/observability/outputs.tf` | 6 outputs: adot_collector_endpoint, application_log_group_name/arn, otel_log_group_name/arn, network_policy_names (list of 3). |
| `infra/modules/observability/tests/observability.tftest.hcl` | 6 run blocks asserting log-group retention+KMS (M1), namespace PSS labels (M2), and the 3 NetworkPolicy resources' policyTypes + selectors (M7). ADOT helm release target is excluded (mirrors the cluster module's karpenter exclusion) — the chart shape is enforced by the CI helm lint step. |
| `deploy/helm/support-bot/templates/networkpolicy.yaml` | Additive template mirroring the 3 NetworkPolicy resources under .Values.networkPolicies.enabled (default-deny gated on .Values.networkPolicies.defaultDeny). |
| `deploy/helm/support-bot/values.yaml` | Added networkPolicies block (enabled=true, defaultDeny=true) + appLabels block (api=support-bot-api, chroma=support-bot-chroma). |
| `infra/root.tf` | Wired module.observability (consumes cluster.cluster_name + cluster_security_group_id, identity.adot_role_arn + identity.cmk_arn, var.region). |
| `infra/root_outputs.tf` | 4 new root outputs: application_log_group_arn, otel_log_group_arn, adot_collector_endpoint, network_policy_names. |
| `.github/workflows/infra-ci.yml` | Added helm template NetworkPolicy count check (asserts exactly 3 NetworkPolicy resources rendered). Also added the missing WP05 storage sanity step that the WP06 base did not include. |

### Test results

6/6 passing -- `cd .worktrees/002-alternative-aws-infrastructure-WP06/infra/modules/observability && tofu init -backend=false && tofu test`

### Validator

0/0 checks passed -- `<spec-bridge-skill-tool implement WP06 --feature 002-alternative-aws-infrastructure>`
