---
work_package_id: "WP04"
title: "Edge & Traffic — ACM, Route53, WAFv2, ALB controller, Ingress"
lane: "doing"
dependencies:
  - "WP02"
  - "WP03"
subsystem: "S4 Edge & Traffic"
misfits_addressed:
  - "M2 (chart ↔ infra drift, ALB half — Ingress annotations pinned)"
  - "M4 (multi-AZ, ALB half — internal ALB spans 3 subnets)"
  - "M8 (prevent_destroy on ALB access logs bucket)"
abstract_components:
  - "AcmCertificate (from S4 plan)"
  - "Route53Record (from S4 plan)"
  - "Wafv2WebAcl (from S4 plan)"
  - "AlbControllerHelm (from S4 plan)"
  - "IngressResource (from S4 plan)"
  - "AlbAccessLogsBucket (from S4 plan)"
agent: "cursor"
tdd_red_clean: true
history:
  - timestamp: "2026-09-12T16:55:00+00:00"
    lane: "doing"
    agent: "cursor"
    action: "started implementation"
---

# WP04 — Edge & Traffic

## Goal

Provision the per-env ACM certificate (DNS validated, wildcard SAN), the Route53 alias record (`<env>.${domain_suffix}` → ALB), the WAFv2 WebACL (3 managed rule sets + rate-based rule), the AWS Load Balancer Controller helm release (with Pod Identity association), the ALB access logs S3 bucket, the `Ingress` resource via `kubernetes_manifest`, and the chart's new `templates/ingress.yaml` (validated locally with `helm template --validate`).

This WP provides the public-facing ingress. Without it, no end-user can reach the API.

## Context

- **Region**: `eu-central-1`
- **Module root**: `infra/modules/edge/`
- **Chart additions**: `deploy/helm/support-bot/templates/ingress.yaml`
- **Inputs**: `vpc_id`, `public_subnet_ids`, `eks_cluster_name`, `cluster_security_group_id` from WP01+WP02; `alb_controller_role_arn` from WP03
- **OpenTofu version**: `>= 1.6.0`

## Subtasks

### T001 — Create `infra/modules/edge/{variables.tf,versions.tf}`

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
variable "env"                       { type = string }
variable "cluster_name"              { type = string }
variable "cluster_security_group_id" { type = string }
variable "vpc_id"                    { type = string }
variable "public_subnet_ids"         { type = list(string) }
variable "parent_zone_id"            { type = string }
variable "domain_suffix"             { type = string }
variable "alb_controller_role_arn"   { type = string }
variable "cmk_arn"                   { type = string }
variable "vpc_endpoint_security_group_id" { type = string }
```

### T002-T007 — Create `infra/modules/edge/main.tf`

- **T002 (part A)**: `aws_acm_certificate.env_cert` (`domain_name = "${var.env}.${var.domain_suffix}"`, `subject_alternative_names = ["*.${var.env}.${var.domain_suffix}"]`, `validation_method = "DNS"`); `aws_route53_record.env_cert_validation` (per SAN, against `var.parent_zone_id`, `ttl = 60`, `records = [aws_acm_certificate.env_cert.domain_validation_options[0].resource_record_value]`); `aws_acm_certificate_validation.env_cert` (waits for all SAN validations).
- **T003 (part B)**: `aws_route53_record.env_alias` (`name = "${var.env}.${var.domain_suffix}"`, `type = "A"`, `alias { name = aws_lb.env_alb.dns_name, zone_id = aws_lb.env_alb.zone_id, evaluate_target_health = true }`). **Cycle-breaker**: the ALB is created by the AWS LBC from the Ingress in T007. To avoid the cycle, use a `time_sleep` of 60 seconds between the LBC helm install (T005) and the Route53 record (T003), or use `aws_route53_record.env_alias` with a `depends_on = [kubernetes_manifest.env_ingress]`.
- **T004 (part C)**: `aws_wafv2_web_acl.env_waf` (`default_action = "allow"`, 4 rules with priorities 1–4: `AWSManagedRulesCommonRuleSet`, `AWSManagedRulesSQLiRuleSet`, `AWSManagedRulesBotControlRuleSet`, and `rate_based_statement` with `limit = 1000`, `aggregate_key_type = "IP"`, `scope_down_statement = { not_statement = { statement = ... } }` (optional — leave empty for first iteration), `visibility_config`).
- **T005 (part D)**: `helm_release.aws_load_balancer_controller` (chart `aws-load-balancer-controller`, repository `https://aws.github.io/eks-charts`, `set { name = "clusterName", value = var.cluster_name }`, `set { name = "serviceAccount.annotations.eks\\.amazonaws\\.com/pod-identityassociation-arn", value = var.alb_controller_role_arn }`, replicaCount = 2, `set { name = "vpcId", value = var.vpc_id }`).
- **T006 (part E)**: `aws_s3_bucket.alb_access_logs` (`bucket = "support-bot-${var.env}-alb-logs-${data.aws_caller_identity.current.account_id}"`, `lifecycle { prevent_destroy = true }`, `versioning { enabled = true }`, `server_side_encryption_configuration { rule { apply_server_side_encryption_by_default { sse_algorithm = "aws:kms", kms_master_key_id = var.cmk_arn } } }`, `lifecycle_rule { enabled = true, expiration { days = 30 } }`, `tags = { Cluster = "support-bot-${var.env}" }`); `aws_s3_bucket_public_access_block.alb_access_logs` (block all public access); `aws_s3_bucket_policy.alb_access_logs` (allows `s3:PutObject` from `logging.s3.amazonaws.com` for the ALB log delivery account — see AWS docs for the current log-delivery account ID per region; this account ID rotates occasionally and must be sourced from `data "aws_elb_service_account" "main"` for the region).
- **T007 (part F)**: `kubernetes_manifest.env_ingress` with the Ingress manifest (annotations from FR-010).

### T008 — Add `deploy/helm/support-bot/templates/ingress.yaml` (NEW)

```yaml
{{- /*
Additive template. Ingress resource for the support-bot API.
Renders with the chart's values; the actual apply is done by the AWS LBC
(the tofu code in T007 applies the same shape via kubernetes_manifest).
*/ -}}
{{- if .Values.ingress.enabled -}}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ .Values.ingress.name | default "support-bot-api" }}
  namespace: {{ .Release.Namespace }}
  annotations:
    alb.ingress.kubernetes.io/scheme: {{ .Values.ingress.scheme | default "internal" }}
    alb.ingress.kubernetes.io/target-type: {{ .Values.ingress.targetType | default "ip" }}
    alb.ingress.kubernetes.io/ssl-policy: {{ .Values.ingress.sslPolicy | default "ELBSecurityPolicy-TLS13-1-2-2021-06" }}
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTPS":443}]'
    alb.ingress.kubernetes.io/healthcheck-path: /healthz
    alb.ingress.kubernetes.io/healthcheck-interval-seconds: "15"
    alb.ingress.kubernetes.io/healthy-threshold-count: "2"
    alb.ingress.kubernetes.io/unhealthy-threshold-count: "3"
    {{- if .Values.ingress.wafv2AclArn }}
    alb.ingress.kubernetes.io/wafv2-acl-arn: {{ .Values.ingress.wafv2AclArn }}
    {{- end }}
spec:
  ingressClassName: alb
  rules:
    - host: {{ .Values.ingress.host }}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: {{ .Values.ingress.backendService | default "support-bot-api" }}
                port:
                  number: {{ .Values.ingress.backendPort | default 8000 }}
{{- end }}
```

The default values file supplies:

```yaml
# values.yaml (additive)
ingress:
  enabled: true
  scheme: internal
  targetType: ip
  sslPolicy: ELBSecurityPolicy-TLS13-1-2-2021-06
  host: "{{ .Values.env }}.{{ .Values.domainSuffix }}"
  backendService: support-bot-api
  backendPort: 8000
  # wafv2AclArn is injected at tofu apply time via values override
```

### T009 — Create `infra/modules/edge/outputs.tf`

```hcl
output "acm_cert_arn"           { value = aws_acm_certificate.env_cert.arn }
output "wafv2_web_acl_arn"      { value = aws_wafv2_web_acl.env_waf.arn }
output "alb_dns_name"           { value = aws_lb.env_alb.dns_name }  # the ALB is created by the LBC from the Ingress
output "route53_zone_id"        { value = aws_route53_record.env_alias.zone_id }
output "alb_access_logs_bucket" { value = aws_s3_bucket.alb_access_logs.id }
```

**Critical implementation note**: `aws_lb.env_alb` is **not** declared in this module — it is created by the AWS Load Balancer Controller from the Ingress in T007. To get the ALB DNS in T009, the implementer must use a `data "kubernetes_ingress_v1" "env_ingress"` resource, OR poll the LBC's output via `kubernetes_manifest.env_ingress.status.loadBalancer.ingress[0].hostname` (which is not available at plan time).

The cleanest pattern: add a `null_resource.wait_for_alb` that runs `kubectl get ingress support-bot-api -n support-bot -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'` in a `local-exec` provisioner after the `kubernetes_manifest.env_ingress` is applied. The ALB DNS is then exported via a `terraform_data` or `null_resource` output.

**Alternative pattern** (cleaner): skip the `aws_lb` output from T009 entirely; the Route53 alias in T003 references `aws_lb.env_alb.dns_name` via a `local-exec` lookup after the LBC has provisioned the ALB. The DNS lookup is done by the LBC itself (it watches Ingress events and creates/updates the ALB accordingly).

The implementer chooses one approach and documents it in the `infra/root.tf` extension.

### T010 — Create `infra/modules/edge/tests/edge.tftest.hcl`

```hcl
run "acm_cert_has_wildcard_san" {
  command = plan
  assert {
    condition     = contains(aws_acm_certificate.env_cert.subject_alternative_names, "*.dev.support-bot.example.com")
    error_message = "ACM cert must include wildcard SAN for *.<env>.${var.domain_suffix}."
  }
}

run "waf_has_managed_and_rate_rules" {
  command = plan
  assert {
    condition     = length(aws_wafv2_web_acl.env_waf.rule) == 4
    error_message = "WAFv2 WebACL must have exactly 4 rules (3 managed + 1 rate-based)."
  }
}

run "alb_controller_helm_release_pinned" {
  command = plan
  assert {
    condition     = strcontains(helm_release.aws_load_balancer_controller.chart, "aws-load-balancer-controller")
    error_message = "ALB Controller helm release must use the aws-load-balancer-controller chart."
  }
}

run "ingress_manifest_has_albc_annotations" {
  command = plan
  # Same file_contents mock_provider pattern as WP02 T009 — verify the
  # kubernetes_manifest.manifest contains the 4 ALBC annotations.
  # See plan.md "Open Questions" #4.
}
```

### T011 — Extend `infra/root.tf`

```hcl
# infra/root.tf (append)
module "edge" {
  source = "./modules/edge"

  env                              = var.env
  cluster_name                     = module.cluster.cluster_name
  cluster_security_group_id        = module.cluster.cluster_security_group_id
  vpc_id                           = module.foundation.vpc_id
  public_subnet_ids                = module.foundation.public_subnet_ids
  parent_zone_id                   = var.parent_zone_id
  domain_suffix                    = var.domain_suffix
  alb_controller_role_arn          = module.identity.alb_controller_role_arn
  cmk_arn                          = module.identity.cmk_arn
  vpc_endpoint_security_group_id   = module.foundation.vpc_endpoint_security_group_id
}
```

Also extend the root outputs:

```hcl
# infra/root_outputs.tf (append)
output "acm_cert_arn"      { value = module.edge.acm_cert_arn }
output "wafv2_web_acl_arn" { value = module.edge.wafv2_web_acl_arn }
output "alb_access_logs_bucket" { value = module.edge.alb_access_logs_bucket }
```

### T012 — CI step

The existing `infra-ci.yml` skeleton (WP00 T004) needs no change — the secret-scan step already covers the chart's `helm template` output. Add an additional step:

```yaml
- name: helm lint + helm template check (ingress)
  working-directory: deploy/helm/support-bot
  run: |
    helm lint . --values values-prod.yaml
    helm template . --values values-prod.yaml | grep -E 'kind: Ingress' && \
    helm template . --values values-prod.yaml | grep -E 'ingressClassName: alb'
```

## Acceptance Criteria

1. `tofu apply -var-file=envs/prod.tfvars` provisions: 1 ACM cert, 1 WAFv2 WebACL, 1 S3 bucket, 1 helm release (AWS LBC), 1 kubernetes_manifest (Ingress).
2. `aws acm describe-certificate --certificate-arn <arn>` returns `Status: ISSUED`.
3. `aws wafv2 get-web-acl --id <id> --scope REGIONAL` returns the 4 rules.
4. `helm list -n kube-system | grep aws-load-balancer-controller` shows `STATUS: deployed`.
5. `kubectl get ingress -n support-bot` shows the ingress with `ingressClassName: alb` and the 4 ALBC annotations (if the chart is installed by a downstream feature).
6. `helm template deploy/helm/support-bot --values values-prod.yaml | grep -E 'kind: Ingress'` returns 1 Ingress.
7. `cd infra/modules/edge && tofu test` runs all 4 `run` blocks; all assertions pass.
8. `tofu plan` after apply reports `No changes.`

## TDD Targets

- **M2 (chart ↔ infra drift, ALB half)**: `tofu test` asserts the rendered Ingress manifest has `ingressClassName: alb` and all 4 ALBC annotations from FR-010.
- **M4 (multi-AZ, ALB half)**: `tofu test` asserts the ALBC helm release is configured with all 3 public subnets.
- **M8 (prevent_destroy)**: `tofu test` asserts `lifecycle.prevent_destroy = true` on the ALB access logs S3 bucket.

## Execution constraints

- Product code and tests: only in `$WORKTREES_DIR/002-alternative-aws-infrastructure-WP04/`
- Do not merge to `main` until `spec-bridge-merge` after accept
- Do not instruct "verify on main" — verify in the WP worktree after dependency merges
- **Open question to verify during implementation**: the exact shape of `kubernetes_manifest.manifest` for the Ingress CRD (HCL map vs JSON string) — verify against the installed `hashicorp/kubernetes` provider version per plan.md "Open Questions" #4.

## Notes for implementer

- The ALB access logs S3 bucket requires a special bucket policy that allows the **AWS ELB log delivery service principal** to write. The exact principal format varies by region; use `data "aws_elb_service_account" "main"` to look it up.
- The Route53 alias record depends on the ALB being created first. Since the ALB is created by the AWS LBC (not by `terraform`), there's an implicit dependency: `aws_route53_record.env_alias` must `depends_on = [kubernetes_manifest.env_ingress]`. The LBC's reconciliation loop runs in the background after the Ingress is applied; the Route53 record creation may race the ALB creation. A `time_sleep` of 60 seconds after the LBC install (T005) is a pragmatic workaround.
- The `kubernetes_manifest.env_ingress` resource can use a **manifest** field (HCL map) or **manifest_json** field (JSON-encoded string) — both are valid in the `hashicorp/kubernetes` provider. The implementer should use **manifest_json** for complex CRDs to avoid HCL type-conversion bugs.
- The `alb.ingress.kubernetes.io/listen-ports` annotation is a JSON-encoded list of port mappings. The value `'[{"HTTPS":443}]'` is a literal string that must be wrapped in single quotes in YAML.
- The chart's `templates/ingress.yaml` template references `{{ .Values.ingress.wafv2AclArn }}` which is empty by default. The actual value is injected at `tofu apply` time via a `values` block on the `kubernetes_manifest.env_ingress` resource — **but** since this WP doesn't install the chart, the `wafv2AclArn` annotation must be passed to the `kubernetes_manifest` resource directly (not via chart values).