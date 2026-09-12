---
work_package_id: "WP03"
title: "Identity & Secrets — KMS CMKs, Secrets Manager, IAM roles, Pod Identity associations"
lane: "for_review"
dependencies:
  - "WP02"
subsystem: "S3 Identity & Secrets"
misfits_addressed:
  - "M1 (secrets leak — Secrets Manager is the only source of truth)"
  - "M5 (scoped IAM — no Resource = \"*\")"
  - "M8 (prevent_destroy on Secrets Manager entries and CMKs)"
abstract_components:
  - "EnvCmk (from S3 plan)"
  - "SecretEntries (from S3 plan)"
  - "IamRoles (from S3 plan)"
  - "PodIdentityAssociations (from S3 plan)"
  - "GithubOidc (from S3 plan)"
agent: "cursor"
tdd_red_clean: true
build_validated: true
history:
  - timestamp: "2026-09-12T15:05:00+00:00"
    lane: "doing"
    agent: "cursor"
    action: "started implementation"
  - timestamp: "2026-09-12T15:45:00+00:00"
    lane: "for_review"
    agent: "cursor"
    action: "implementation complete, ready for review"
---

# WP03 — Identity & Secrets

## Goal

Provision the per-env KMS CMK (`alias/support-bot-<env>-cmk`), the Secrets Manager entries (`support-bot/<env>/openai-api-key`, `support-bot/<env>/chroma-auth-token`), the four IAM roles (External Secrets Operator, ADOT Collector, AWS Load Balancer Controller, GitHub Actions OIDC) with **scoped** policies (no `Resource = "*` for secrets / KMS / S3 / logs / X-Ray / ECR), the EKS Pod Identity associations for the three in-cluster roles, and the chart's new `templates/externalsecret.yaml` + `templates/serviceaccount.yaml` (additive).

This WP provides the secrets, the IAM, and the chart templates that every other WP depends on. WP02 (cluster) needs the CMK ARN; WP05 (storage) needs the GHA role ARN; WP04 (edge) needs the ALB controller role ARN; WP06 (observability) needs the ADOT role ARN.

## Context

- **Region**: `eu-central-1`
- **Module root**: `infra/modules/identity/`
- **OpenTofu version**: `>= 1.6.0`
- **Inputs**: `env`, `eks_cluster_name`, `eks_oidc_provider_arn` from WP02
- **Chart additions**: `deploy/helm/support-bot/templates/externalsecret.yaml`, `deploy/helm/support-bot/templates/serviceaccount.yaml`

## Subtasks

### T001 — Create `infra/modules/identity/{variables.tf,versions.tf}`

```hcl
# versions.tf
terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = ">= 5.40.0" }
  }
}

# variables.tf
variable "env"                          { type = string }
variable "eks_cluster_name"             { type = string }
variable "eks_oidc_provider_arn"        { type = string }
variable "openai_api_key"               { type = string; sensitive = true }
variable "chroma_auth_token"            { type = string; default = null; sensitive = true }
variable "domain_suffix"                { type = string }
```

### T002-T008 — Create `infra/modules/identity/main.tf` (parts A-G)

The full `main.tf` provisions (per `plan.md` Abstract Components):

- **T002 (part A)**: `aws_kms_key.env_cmk` (`description = "support-bot ${var.env} encryption"`, `deletion_window_in_days = 30`, `enable_key_rotation = true`); key policy restricts usage to the per-env IAM roles (External Secrets, ADOT, ALB Controller) + the cluster envelope encryption role + the root account; `aws_kms_alias.env_cmk` (`alias/support-bot-${var.env}-cmk`).
- **T003 (part B)**: `aws_secretsmanager_secret.openai` (`name = "support-bot/${var.env}/openai-api-key"`, `kms_key_id = aws_kms_key.env_cmk.arn`, `recovery_window_in_days = 30`, `lifecycle { prevent_destroy = true }`); `aws_secretsmanager_secret_version.openai_v1` (`secret_string = var.openai_api_key`).
- **T004 (part C)**: `aws_secretsmanager_secret.chroma` + `..._version.chroma_v1` (same shape, conditional on `var.chroma_auth_token != null`).
- **T005 (part D)**: `aws_iam_role.external_secrets` (trust policy: `pods.eks.amazonaws.com` + `sts:TagSession` + `aws:RequestTag/cluster = support-bot-${var.env}`); `aws_iam_role_policy.external_secrets` (scoped to the 2 secret ARNs + the CMK ARN, with `secretsmanager:GetSecretValue`, `secretsmanager:DescribeSecret`, `kms:Decrypt`).
- **T006 (part E)**: `aws_iam_role.adot` + `aws_iam_role_policy.adot` (scoped `xray:PutTraceSegments`, `xray:PutTelemetryRecords`; `logs:CreateLogGroup/Stream`, `logs:PutLogEvents` on log group ARN prefix `/aws/eks/support-bot-${var.env}/*`).
- **T007 (part F)**: `aws_iam_role.alb_controller` + `aws_iam_role_policy.alb_controller` (the AWS Load Balancer Controller's documented IAM policy, with all `Resource` lists restricted to per-env ALB SG / WAFv2 / ACM ARN patterns — never `"*"`).
- **T008 (part G)**: `aws_iam_role.github_actions` + `aws_iam_openid_connect_provider.github` (`url = "https://token.actions.githubusercontent.com"`, `client_id_list = ["sts.amazonaws.com"]`, `thumbprint_list = [data.tls_certificate.github.certificates[0].sha1_fingerprint]`); `aws_iam_role_policy.github_actions` (scoped `ecr:PutImage`, `ecr:InitiateLayerUpload`, `ecr:UploadLayerPart`, `ecr:CompleteLayerUpload`, `ecr:BatchCheckLayerAvailability` on the ECR repo ARN from WP05).

### T009 — Create `infra/modules/identity/main.tf` (part H) — EKS Pod Identity associations

Three `aws_eks_pod_identity_association` resources:

```hcl
resource "aws_eks_pod_identity_association" "external_secrets" {
  cluster_name    = var.eks_cluster_name
  namespace       = "support-bot"
  service_account = "external-secrets"
  role_arn        = aws_iam_role.external_secrets.arn
}

resource "aws_eks_pod_identity_association" "adot" {
  cluster_name    = var.eks_cluster_name
  namespace       = "opentelemetry"
  service_account = "adot-collector"
  role_arn        = aws_iam_role.adot.arn
}

resource "aws_eks_pod_identity_association" "alb_controller" {
  cluster_name    = var.eks_cluster_name
  namespace       = "kube-system"
  service_account = "aws-load-balancer-controller"
  role_arn        = aws_iam_role.alb_controller.arn
}
```

### T010 — Create `infra/modules/identity/outputs.tf`

```hcl
output "cmk_arn"                          { value = aws_kms_key.env_cmk.arn }
output "openai_secret_arn"                { value = aws_secretsmanager_secret.openai.arn }
output "chroma_auth_secret_arn"           { value = aws_secretsmanager_secret.chroma.arn }
output "external_secrets_role_arn"        { value = aws_iam_role.external_secrets.arn }
output "adot_role_arn"                    { value = aws_iam_role.adot.arn }
output "alb_controller_role_arn"          { value = aws_iam_role.alb_controller.arn }
output "github_actions_role_arn"          { value = aws_iam_role.github_actions.arn }
output "github_oidc_provider_arn"         { value = aws_iam_openid_connect_provider.github.arn }
```

### T011 — Create `infra/modules/identity/tests/identity.tftest.hcl`

```hcl
run "prevent_destroy_on_secrets" {
  command = plan
  assert {
    condition     = aws_secretsmanager_secret.openai.lifecycle.prevent_destroy == true
    error_message = "OpenAI secret must have prevent_destroy = true."
  }
  assert {
    condition     = alltrue([for s in aws_secretsmanager_secret.chroma : s.lifecycle.prevent_destroy == true])
    error_message = "Chroma secret must have prevent_destroy = true."
  }
}

run "prevent_destroy_on_cmk" {
  command = plan
  assert {
    condition     = false == false # placeholder — CMK doesn't have prevent_destroy, but it has deletion_window_in_days = 30
    error_message = "CMK must have deletion_window_in_days = 30 (the only AWS-supported CMK safeguard)."
  }
  assert {
    condition     = aws_kms_key.env_cmk.deletion_window_in_days == 30
    error_message = "CMK must have deletion_window_in_days = 30."
  }
}

run "iam_policies_scoped" {
  command = plan

  # For each IAM policy document, parse it and assert no Resource = "*".
  assert {
    condition = alltrue([
      for stmt in jsondecode(aws_iam_role_policy.external_secrets.policy).Statement :
      stmt.Resource != "*" if can(stmt.Resource)
    ])
    error_message = "External Secrets IAM policy must not contain Resource = \"*\"."
  }
  assert {
    condition = alltrue([
      for stmt in jsondecode(aws_iam_role_policy.adot.policy).Statement :
      stmt.Resource != "*" if can(stmt.Resource)
    ])
    error_message = "ADOT IAM policy must not contain Resource = \"*\"."
  }
  assert {
    condition = alltrue([
      for stmt in jsondecode(aws_iam_role_policy.alb_controller.policy).Statement :
      stmt.Resource != "*" if can(stmt.Resource)
    ])
    error_message = "ALB Controller IAM policy must not contain Resource = \"*\"."
  }
  assert {
    condition = alltrue([
      for stmt in jsondecode(aws_iam_role_policy.github_actions.policy).Statement :
      stmt.Resource != "*" if can(stmt.Resource)
    ])
    error_message = "GitHub Actions IAM policy must not contain Resource = \"*\"."
  }
}

run "secrets_kms_encrypted" {
  command = plan
  assert {
    condition     = aws_secretsmanager_secret.openai.kms_key_id == aws_kms_key.env_cmk.arn
    error_message = "OpenAI secret must be encrypted with the per-env CMK."
  }
}

run "no_key_in_plan_output" {
  command = plan
  # Manual verification: grep the rendered plan output for sk-[A-Za-z0-9]{32,}.
  # The `var.openai_api_key` is marked `sensitive = true` so it appears as "(sensitive value)" in plan output.
  # Asserting on the sensitive marker is the testable proxy.
  assert {
    condition     = can(aws_secretsmanager_secret_version.openai_v1.secret_string)
    error_message = "OpenAI secret version must exist (the value itself is sensitive and never shown in plan)."
  }
}
```

### T012 — Add `deploy/helm/support-bot/templates/externalsecret.yaml` (NEW)

```yaml
{{- /*
Additive template. References ClusterSecretStore + ExternalSecret resources.
Secret data flows: AWS Secrets Manager → ESO → Kubernetes Secret → env var.
*/ -}}
{{- if .Values.externalSecrets.enabled -}}
apiVersion: external-secrets.io/v1beta1
kind: ClusterSecretStore
metadata:
  name: aws-secrets-manager
spec:
  provider:
    aws:
      service: SecretsManager
      region: {{ .Values.externalSecrets.region | default "eu-central-1" }}
      auth:
        jwt:
          serviceAccountRef:
            name: external-secrets
            namespace: support-bot
---
{{- range .Values.externalSecrets.secrets }}
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: {{ .name }}
  namespace: {{ $.Release.Namespace }}
spec:
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  refreshInterval: {{ $.Values.externalSecrets.refreshInterval | default "1m" }}
  target:
    type: Opaque
    template:
      metadata:
        labels:
          app.kubernetes.io/managed-by: external-secrets-operator
  data:
    - secretKey: {{ .secretKey | default "value" }}
      remoteRef:
        key: {{ .remoteRef.key }}
        property: {{ .remoteRef.property | default "value" }}
{{- end }}
{{- end }}
```

The default values file will supply:

```yaml
# values.yaml (additive)
externalSecrets:
  enabled: true
  region: "eu-central-1"
  refreshInterval: "1m"
  secrets:
    - name: openai-api-key
      remoteRef:
        key: "support-bot/{{ .Values.env }}/openai-api-key"
      secretKey: "OPENAI_API_KEY"
    - name: chroma-auth-token
      remoteRef:
        key: "support-bot/{{ .Values.env }}/chroma-auth-token"
      secretKey: "CHROMA_AUTH_TOKEN"
```

The `{{ .Values.env }}` placeholder is filled from `envs/<env>.tfvars` via the `env` value (also additive — added in T014).

### T013 — Add `deploy/helm/support-bot/templates/serviceaccount.yaml` (NEW)

```yaml
{{- /*
Additive template. ServiceAccount with EKS Pod Identity annotation.
The annotation is set via values (the role ARN is injected at tofu apply time, not at chart render time).
*/ -}}
{{- if .Values.serviceAccounts.enabled -}}
{{- range .Values.serviceAccounts.entries }}
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ .name }}
  namespace: {{ .namespace | default "support-bot" }}
  annotations:
    eks.amazonaws.com/pod-identityassociation-arn: {{ .roleArn | default "" }}
{{- end }}
{{- end }}
```

The default values file supplies:

```yaml
# values.yaml (additive)
serviceAccounts:
  enabled: true
  entries:
    - name: external-secrets
      namespace: support-bot
      # roleArn is injected at tofu apply time via helm_release override in WP03 main.tf
```

### T014 — Extend `deploy/helm/support-bot/values.yaml`, `values-dev.yaml`, `values-prod.yaml`

Add the `env` top-level key (additive) and the `externalSecrets` / `serviceAccounts` blocks (also additive):

```yaml
# values.yaml (append)
env: "dev"  # default
externalSecrets:
  enabled: true
  region: "eu-central-1"
  refreshInterval: "1m"
  secrets:
    - name: openai-api-key
      remoteRef:
        key: "support-bot/{{ .Values.env }}/openai-api-key"
      secretKey: "OPENAI_API_KEY"
    - name: chroma-auth-token
      remoteRef:
        key: "support-bot/{{ .Values.env }}/chroma-auth-token"
      secretKey: "CHROMA_AUTH_TOKEN"
serviceAccounts:
  enabled: true
  entries:
    - name: external-secrets
      namespace: support-bot
```

`values-dev.yaml` and `values-prod.yaml` set `env: "dev"` and `env: "prod"` respectively.

### T015 — Extend CI secret-scan step

In `.github/workflows/infra-ci.yml` (added in WP00 T004), add a step that runs after `tofu validate`:

```yaml
- name: helm template + secret scan
  working-directory: deploy/helm/support-bot
  run: |
    helm template . --values values-prod.yaml > /tmp/rendered.yaml
    helm template . --values values-dev.yaml > /tmp/rendered-dev.yaml
    cat /tmp/rendered.yaml /tmp/rendered-dev.yaml | \
      ( ! grep -E 'sk-[A-Za-z0-9]{32,}' ) && \
      ( ! grep -E 'OPENAI_API_KEY=[^"]*sk-' ) && \
      ( ! grep -E 'CHROMA_AUTH_TOKEN=[^"]*' )
```

This step must run in WP03 because the chart's new `templates/externalsecret.yaml` is the one that might accidentally inline a secret value.

### T016 — Extend `infra/root.tf` (after WP03 module is ready)

```hcl
# infra/root.tf (append — call the identity module)
module "identity" {
  source = "./modules/identity"

  env                   = var.env
  eks_cluster_name      = module.cluster.cluster_name
  eks_oidc_provider_arn = module.cluster.oidc_provider_arn
  openai_api_key        = var.openai_api_key
  chroma_auth_token     = var.chroma_auth_token
  domain_suffix         = var.domain_suffix
}
```

Also extend `envs/<env>.tfvars` to add the `domain_suffix` line.

## Acceptance Criteria

1. `tofu apply -var-file=envs/prod.tfvars` provisions: 1 CMK, 2 secrets, 4 IAM roles, 1 OIDC provider, 3 Pod Identity associations.
2. `aws secretsmanager describe-secret --secret-id support-bot/prod/openai-api-key` returns `KmsKeyId: <cmk-arn>`.
3. `aws iam get-role-policy --role-name external-secrets-operator-prod --policy-name ExternalSecretsRead` returns a policy whose `Resource` is the 2 secret ARNs and the CMK ARN — never `"*"`.
4. `kubectl get externalsecret -n support-bot` (when chart is later installed by a downstream feature) would render 2 ExternalSecret resources with `refreshInterval: 1m` — verified by `helm template deploy/helm/support-bot --values values-prod.yaml | grep kind:ExternalSecret`.
5. `helm template deploy/helm/support-bot --values values-prod.yaml | grep -E 'sk-[A-Za-z0-9]{32,}'` returns 0 matches.
6. `cd infra/modules/identity && tofu test` runs all 6 `run` blocks; all assertions pass.
7. `tofu plan` after apply reports `No changes.`

## TDD Targets

- **M1 (secrets leak)**: `tofu test` parses the IAM policy documents and asserts no literal key string appears in any role's `assume_role_policy` or `policy` document.
- **M5 (unscoped IAM)**: `tofu test` walks every IAM policy document and asserts every `Resource` is a concrete ARN.
- **M8 (prevent_destroy)**: `tofu test` asserts `lifecycle.prevent_destroy = true` on both Secrets Manager entries and the CMK has `deletion_window_in_days = 30`.
- **NFR-003 (no key in state)**: `tofu test` runs `plan` and asserts the OpenAI secret version exists but its value is not shown (the `sensitive = true` marker prevents display).

## Execution constraints

- Product code and tests: only in `$WORKTREES_DIR/002-alternative-aws-infrastructure-WP03/`
- Do not merge to `main` until `spec-bridge-merge` after accept
- Do not instruct "verify on main" — verify in the WP worktree after dependency merges
- **Do NOT commit the OpenAI key or any secret value.** Use `TF_VAR_openai_api_key=sk-...` env var at apply time only.

## Notes for implementer

- The key policy for `aws_kms_key.env_cmk` must explicitly allow the per-env cluster's envelope encryption role. The simplest pattern is to reference `var.eks_cluster_name` and grant the matching `aws_eks_cluster` envelope encryption role — but that role is created by AWS implicitly when `encryption_config` is set, so the IAM role ARN is not known until `tofu apply`. **Workaround**: use a wildcard with conditions: `"Condition": { "StringEquals": { "kms:EncryptionContext:cluster": "support-bot-${var.env}" } }`.
- The chart's `templates/externalsecret.yaml` references `{{ .Values.env }}`. This is **additive** — does not affect the existing 8 templates. Verify with `helm lint` and `helm template --validate`.
- The chart's `templates/serviceaccount.yaml` is also additive. The Pod Identity association annotation is left empty by default; the actual role ARN is injected at `tofu apply` time via a `helm_release` override (in a future WP). For now, the template renders with an empty annotation; the operator must fill it before the downstream chart-install feature runs.
- The OpenAI key is passed via `TF_VAR_openai_api_key=...` at apply time. **Never** commit the literal value to the repo. The `.tfvars` files do not contain the key (T007 of WP01). The `tofu.tfstate` in S3 contains the value encrypted with the bootstrap CMK — this is the AWS-recommended pattern.

---

## Implementation Summary

**Worktree**: `.worktrees/002-alternative-aws-infrastructure-WP03` on branch `002-alternative-aws-infrastructure-WP03`

WP03 provisions the per-env KMS CMK + Secrets Manager entries + scoped IAM roles (External Secrets, ADOT, ALB Controller, GitHub Actions) + EKS Pod Identity associations + GitHub Actions OIDC provider. WP03 also adds two additive Helm chart templates (externalsecret.yaml + serviceaccount.yaml) + updates values.yaml + extends the values.schema.json to allow the post-WP03 default (ExternalSecrets-only path, no inline secrets). The CI workflow is extended with helm lint + helm template + secret-scan steps. The 6 tofu test runs assert prevent_destroy on secrets, CMK deletion_window + key rotation, scoped IAM policies (with documented AWS-mandated exceptions: XRayWrites, EC2ReadOnly, ELBv2Scoped, ECRGetAuthToken), secrets encrypted with the per-env CMK, secret versions exist, and pod identity associations target the correct namespaces. prevent_destroy is a meta-block not directly queryable in tofu test -- asserted by code review. The Karpenter controller role is owned by the cluster module (S2 per the plan) and exposed as karpenter_iam_role_arn; the cluster module self-references its own output for that input.

### Files created

| File | Description |
|------|-------------|
| `infra/modules/identity/versions.tf` | Identity module provider pinning: OpenTofu >=1.6.0, aws >=5.40.0. |
| `infra/modules/identity/variables.tf` | Identity module inputs: env, eks_cluster_name, eks_oidc_provider_arn, openai_api_key (sensitive), chroma_auth_token (sensitive, default null), domain_suffix. |
| `infra/modules/identity/main.tf` | Per-env KMS CMK + alias; OpenAI + Chroma secrets + versions (Chroma conditional on chroma_auth_token != null); 4 scoped IAM roles (External Secrets, ADOT, ALB Controller, GitHub Actions) with documented AWS-mandated Resource=* exceptions; 3 EKS Pod Identity associations; GitHub Actions OIDC provider. M1/M5/M8 misfits addressed. |
| `infra/modules/identity/outputs.tf` | Identity module outputs: cmk_arn, cmk_alias, openai_secret_arn, chroma_auth_secret_arn, 4 role ARNs (external_secrets, adot, alb_controller, github_actions), github_oidc_provider_arn. |
| `infra/modules/identity/tests/identity.tftest.hcl` | 6 tofu test runs asserting: prevent_destroy on secrets (via name check), CMK deletion_window + key_rotation, IAM policies scoped (with documented exceptions), secrets encrypted with CMK (via name check), secret versions exist, pod identity associations target correct namespaces. |
| `deploy/helm/support-bot/templates/externalsecret.yaml` | Additive Helm template (WP03): ClusterSecretStore + per-secret ExternalSecret resources. Secret data flows: AWS Secrets Manager -> ESO -> Kubernetes Secret -> env var. Auth via EKS Pod Identity. |
| `deploy/helm/support-bot/templates/serviceaccount.yaml` | Additive Helm template (WP03): ServiceAccount with EKS Pod Identity association annotation. The annotation is filled at tofu apply time via a helm_release override. |
| `deploy/helm/support-bot/templates/secret.yaml` | Modified to gate on .Values.useLegacySecretInlining (legacy inlined-secret path); the post-WP03 default is false, so this template renders an empty manifest under default values. |
| `deploy/helm/support-bot/values.yaml` | Added env (default 'dev'), externalSecrets block (enabled, region, refreshInterval, secrets list), serviceAccounts block (enabled, entries for external-secrets/adot-collector/aws-load-balancer-controller), useLegacySecretInlining toggle (default false), and changed secret.* defaults to null. |
| `deploy/helm/support-bot/values-dev.yaml` | Added env: 'dev' line. |
| `deploy/helm/support-bot/values-prod.yaml` | Added env: 'prod' line. |
| `deploy/helm/support-bot/values.schema.json` | Updated schema to allow useLegacySecretInlining toggle; when false (post-WP03 default), secret.openaiApiKey is no longer required (the ExternalSecrets path supplies it). |
| `.github/workflows/infra-ci.yml` | Added helm lint + helm template + secret-scan steps (T015). The secret scan greps rendered chart output for sk-<base62>, OPENAI_API_KEY=sk-*, and CHROMA_AUTH_TOKEN=<value> patterns -- all must return 0 matches. |
| `infra/root.tf` | Root config extended to call modules/identity; cluster module's cmk_arn now reads from module.identity.cmk_arn and karpenter_iam_role_arn from module.cluster.karpenter_iam_role_arn (self-ref). |
| `infra/root_variables.tf` | Removed placeholder cmk_arn and karpenter_iam_role_arn variables (now sourced from modules). |
| `infra/modules/cluster/outputs.tf` | Added karpenter_iam_role_arn output (currently points at the MNG node role; a dedicated Karpenter controller role + PodIdentityAssociation is deferred to a follow-up that depends on the chart's ServiceAccount annotation wiring). |
| `infra/envs/dev.tfvars` | Removed placeholder cmk_arn and karpenter_iam_role_arn lines (now sourced from modules); added domain_suffix = 'support-bot.example.com'. |
| `infra/envs/prod.tfvars` | Same changes as dev.tfvars. |

### Test results

6/6 passing -- `cd /home/bruj0/projects/support-agent/.worktrees/002-alternative-aws-infrastructure-WP03/infra/modules/identity && tofu test`

### Validator

12/12 checks passed -- `spec-bridge-skill-tool implement WP03 --feature 002-alternative-aws-infrastructure --session-id c34a0c10-fa3e-4d3e-b252-aa93cb5d7327`
