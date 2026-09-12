---
work_package_id: "WP02"
title: "Cluster & Compute — EKS, OIDC, baseline MNG, Karpenter v1"
lane: "planned"
dependencies:
  - "WP01"
subsystem: "S2 Cluster & Compute"
misfits_addressed:
  - "M2 (chart ↔ infra drift, partial — by pinning cluster version and node groups)"
  - "M4 (multi-AZ — baseline MNG spans 3 AZs)"
  - "M7 (NetworkPolicy egress, partial — VPC CNI addon enabled in this WP for WP06 to use)"
abstract_components:
  - "EksCluster (from S2 plan)"
  - "OidcProvider (from S2 plan)"
  - "BaselineNodeGroup (from S2 plan)"
  - "KarpenterController (from S2 plan)"
  - "NodePoolOutputs (from S2 plan)"
agent: ""
history: []
---

# WP02 — Cluster & Compute

## Goal

Provision the EKS control plane (Kubernetes 1.30, control plane logging, envelope encryption with the per-env CMK from WP03), the OIDC provider, the EKS Pod Identity Agent addon, the baseline managed node group (2× `m7i.large`, On-Demand), the VPC CNI addon with `enableNetworkPolicy=true` (for WP06), and the Karpenter v1 controller with one `NodePool` (`burst`, Spot-first, `WhenEmptyOrUnderutilized` consolidation) and one `EC2NodeClass`.

This WP provides the cluster that every other WP runs on (or into). Without it, no Pods can be scheduled and no `kubernetes_manifest` resources can be applied.

## Context

- **Region**: `eu-central-1`
- **Module root**: `infra/modules/cluster/`
- **Karpenter version**: `v1.0+` (latest stable; pin in `helm_release.karpenter.version`)
- **EKS version**: `1.30`
- **Inputs**: `vpc_id`, `private_subnet_ids`, `vpc_endpoint_security_group_id` from WP01; `cmk_arn` from WP03 (placeholder for envelope encryption; deferred test until WP03 ships)
- **State backend**: configured at `tofu init` time

## Subtasks

### T001 — Create `infra/modules/cluster/{variables.tf,versions.tf}`

```hcl
# versions.tf
terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws    = { source = "hashicorp/aws",    version = ">= 5.40.0" }
    helm   = { source = "hashicorp/helm",   version = ">= 2.12.0" }
    tls    = { source = "hashicorp/tls",    version = ">= 4.0.0"  }
  }
}

# variables.tf
variable "env"                             { type = string }
variable "vpc_id"                          { type = string }
variable "private_subnet_ids"              { type = list(string) }
variable "vpc_endpoint_security_group_id"  { type = string }
variable "cluster_name"                    { type = string; default = null } # if null, computed as "support-bot-${var.env}"
variable "admin_cidr"                      { type = string }
variable "cmk_arn"                         { type = string }  # from WP03 — placeholder until WP03 ships
variable "baseline_instance_type"          { type = string; default = "m7i.large" }
variable "baseline_desired_size"           { type = number; default = 2 }
variable "karpenter_version"               { type = string; default = "1.0.0" }  # pin
variable "karpenter_iam_role_arn"          { type = string }  # placeholder — created in WP03
```

### T002-T007 — Create `infra/modules/cluster/main.tf` (parts A-F)

The full `main.tf` is too large to inline here; the implementer writes it following the plan's `Abstract Components` for S2:

- **T002 (part A)**: `aws_eks_cluster.main` — `version = "1.30"`, control plane logging `["api", "audit", "authenticator"]`, `encryption_config { provider { key_arn = var.cmk_arn }, resources = ["secrets"] }`, `vpc_config { subnet_ids = var.private_subnet_ids, endpoint_public_access = true, public_access_cidrs = [var.admin_cidr] }`, `enabled_cluster_log_types`.
- **T003 (part B)**: `aws_iam_openid_connect_provider.oidc` (URL = `aws_eks_cluster.main.identity[0].oidc[0].issuer`, `client_id_list = ["sts.amazonaws.com"]`, `thumbprint_list = [data.tls_certificate.cluster.certificates[0].sha1_fingerprint]`); `aws_eks_addon.pod_identity_agent` (`addon_name = "eks-pod-identity-agent"`, latest version).
- **T004 (part C)**: `aws_eks_node_group.baseline` (`instance_types = [var.baseline_instance_type]`, `desired_size = var.baseline_desired_size`, `min_size = 2`, `max_size = 2`, `subnet_ids = var.private_subnet_ids`, `taint { key = "workload", value = "baseline", effect = "NO_SCHEDULE" }`, capacity type `ON_DEMAND`).
- **T005 (part D)**: `aws_eks_addon.vpc_cni` (`addon_name = "vpc-cni"`, `configuration_values = jsonencode({ enableNetworkPolicy = "true" })`, pin to `v1.14+`).
- **T006 (part E)**: `helm_release.karpenter` (chart `oci://public.ecr.aws/karpenter/karpenter`, `version = var.karpenter_version`, `set { name = "settings.clusterName", value = local.cluster_name }`, `set { name = "settings.interruptionQueue", value = local.cluster_name }`, `set { name = "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn", value = var.karpenter_iam_role_arn }`); `kubectl_manifest.node_pool_burst` (apply the `karpenter.sh/v1 NodePool` YAML, with `spec.disruption.consolidationPolicy = WhenEmptyOrUnderutilized`).
- **T007 (part F)**: `kubectl_manifest.ec2_node_class_burst` (`karpenter.k8s.aws/v1 EC2NodeClass`, `spec.subnetSelectorTerms = [{ tags = { "karpenter.sh/discovery" = local.cluster_name } }]`, `spec.securityGroupSelectorTerms = [{ tags = { "karpenter.sh/discovery" = local.cluster_name } }]`, `spec.amiFamily = "AL2023"`, `spec.role = "KarpenterNodeRole-${local.cluster_name}"` (placeholder — actual role is created in WP03; use `depends_on` to enforce order).

**Critical implementation note**: WP02 cannot run `tofu apply` until WP03 has provisioned `cmk_arn` and `karpenter_iam_role_arn`. The implementer must:
1. Write the `cluster` module with placeholder variables that point to WP03 outputs.
2. Commit the WP02 worktree.
3. After WP03 lands on `main`, rebase the WP02 worktree, re-run `tofu init && tofu plan`, and verify the placeholders resolve.
4. Only then run `tofu apply`.

### T008 — Create `infra/modules/cluster/outputs.tf`

```hcl
output "cluster_name"                   { value = aws_eks_cluster.main.name }
output "cluster_endpoint"               { value = aws_eks_cluster.main.endpoint }
output "cluster_ca_certificate"        { value = aws_eks_cluster.main.certificate_authority[0].data }
output "cluster_security_group_id"      { value = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id }
output "oidc_provider_arn"              { value = aws_iam_openid_connect_provider.oidc.arn }
output "node_iam_role_arn"              { value = aws_eks_node_group.baseline.node_role_arn }
output "baseline_node_group_name"       { value = aws_eks_node_group.baseline.node_group_name }
```

### T009 — Create `infra/modules/cluster/tests/cluster.tftest.hcl`

```hcl
run "eks_version_1_30" {
  command = plan
  assert {
    condition     = aws_eks_cluster.main.version == "1.30"
    error_message = "EKS cluster must be Kubernetes 1.30."
  }
}

run "control_plane_logging_enabled" {
  command = plan
  assert {
    condition     = sort(aws_eks_cluster.main.enabled_cluster_log_types) == sort(["api", "audit", "authenticator"])
    error_message = "Control plane logging must be enabled for api, audit, authenticator."
  }
}

run "envelope_encryption" {
  command = plan
  assert {
    condition     = aws_eks_cluster.main.encryption_config[0].provider[0].key_arn == "<placeholder-cmk-arn-from-wp03>"
    error_message = "EKS must envelope-encrypt secrets with the per-env CMK from WP03."
  }
}

run "baseline_mng_2_m7i_large" {
  command = plan
  assert {
    condition     = aws_eks_node_group.baseline.instance_types[0] == "m7i.large"
    error_message = "Baseline MNG must use m7i.large."
  }
  assert {
    condition     = aws_eks_node_group.baseline.desired_size == 2
    error_message = "Baseline MNG must have desired_size = 2."
  }
}

run "baseline_mng_multi_az" {
  command = plan
  assert {
    condition     = length(aws_eks_node_group.baseline.subnet_ids) >= 3
    error_message = "Baseline MNG must span at least 3 subnets (one per AZ)."
  }
}

run "vpc_cni_network_policy_enabled" {
  command = plan
  assert {
    condition     = jsondecode(aws_eks_addon.vpc_cni.configuration_values).enableNetworkPolicy == "true"
    error_message = "VPC CNI addon must have enableNetworkPolicy = true (for WP06 NetworkPolicy enforcement)."
  }
}

run "karpenter_nodepool_consolidation" {
  command = plan
  # The kubectl_manifest resource is opaque to tofu test; use the file_contents mock_provider pattern.
  # See plan.md "Open Questions" #4 for the verification approach.
}
```

For the Karpenter NodePool assertion (the last `run` block), the implementer uses `mock_provider` + `file_contents` to verify the `kubectl_manifest.node_pool_burst` resource contains `consolidationPolicy: WhenEmptyOrUnderutilized`. The exact `file_contents` mock pattern is in the `hashicorp/kubernetes` provider docs under "Testing mocked resources" — verify the shape during implementation.

### T010 — Extend `infra/envs/<env>.tfvars`

Add the per-env cluster config:

```hcl
# envs/dev.tfvars (append)
cluster_name            = "support-bot-dev"
baseline_instance_type  = "m7i.large"
baseline_desired_size   = 2
karpenter_version      = "1.0.0"

# envs/prod.tfvars (append)
cluster_name            = "support-bot-prod"
baseline_instance_type  = "m7i.large"
baseline_desired_size   = 2
karpenter_version      = "1.0.0"
```

Also extend `infra/root.tf` to call the cluster module (after WP03 ships the CMK and Karpenter role ARNs):

```hcl
# infra/root.tf (append)
module "cluster" {
  source = "./modules/cluster"

  env                             = var.env
  vpc_id                          = module.foundation.vpc_id
  private_subnet_ids              = module.foundation.private_subnet_ids
  vpc_endpoint_security_group_id  = module.foundation.vpc_endpoint_security_group_id
  cluster_name                    = local.cluster_name
  admin_cidr                      = var.admin_cidr
  cmk_arn                         = module.identity.cmk_arn      # from WP03
  baseline_instance_type          = var.baseline_instance_type
  baseline_desired_size           = var.baseline_desired_size
  karpenter_version               = var.karpenter_version
  karpenter_iam_role_arn          = module.identity.karpenter_role_arn  # from WP03
}

locals {
  cluster_name = "support-bot-${var.env}"
}
```

## Acceptance Criteria

1. `tofu apply -var-file=envs/prod.tfvars` provisions the EKS cluster (after WP03 has shipped and the `cmk_arn` + `karpenter_iam_role_arn` references resolve).
2. `aws eks describe-cluster --name support-bot-prod` returns `ACTIVE` and `version: "1.30"`.
3. `aws eks list-nodegroups --cluster-name support-bot-prod` returns the baseline node group with `desiredSize: 2`.
4. `kubectl get nodepools.karpenter.sh -n karpenter` returns one `burst` NodePool with `consolidationPolicy: WhenEmptyOrUnderutilized`.
5. `aws eks describe-addon --cluster-name support-bot-prod --addon-name vpc-cni` returns `enableNetworkPolicy: "true"` in `configurationValues`.
6. `aws eks describe-addon --cluster-name support-bot-prod --addon-name eks-pod-identity-agent` returns `AddonStatus: ACTIVE`.
7. `cd infra/modules/cluster && tofu test` runs the 6 `run` blocks above; all assertions pass (the Karpenter one requires the `file_contents` mock — see plan.md "Open Questions" #4).
8. `tofu plan` after apply reports `No changes.`

## TDD Targets

- **M4 (multi-AZ)**: `tofu test` asserts the baseline MNG's `subnet_ids` covers all 3 AZs.
- **M2 (chart ↔ infra drift)**: `tofu test` asserts the `EksCluster.version = "1.30"` and the baseline MNG instance type matches the t-shirt-sized value in `envs/<env>.tfvars`.
- **M7 (NetworkPolicy egress, partial)**: `tofu test` asserts the VPC CNI addon has `enableNetworkPolicy: "true"`.

## Execution constraints

- Product code and tests: only in `$WORKTREES_DIR/002-alternative-aws-infrastructure-WP02/`
- Do not merge to `main` until `spec-bridge-merge` after accept
- Do not instruct "verify on main" — verify in the WP worktree after dependency merges
- **Sequential constraint**: this WP cannot run `tofu apply` until WP03 has merged to `main` (the cluster module depends on the CMK ARN and the Karpenter IAM role ARN from WP03). Plan accordingly in the worktree coordination.

## Notes for implementer

- **Critical**: WP02 depends on WP03 outputs (`cmk_arn`, `karpenter_iam_role_arn`). The implementer writes WP02 with placeholder variable references, then **after WP03 merges to main**, rebases the WP02 worktree, and only then runs `tofu apply`. Do not attempt `tofu apply` before WP03 lands.
- The Karpenter `NodePool` and `EC2NodeClass` are `kubectl_manifest` resources, not native `aws_*` resources. The shape of `kubectl_manifest.manifest` is provider-version-specific — verify against the installed `hashicorp/kubernetes` provider version (`tofu providers` shows the version; then check the provider docs).
- The `subnetSelectorTerms` and `securityGroupSelectorTerms` in the `EC2NodeClass` must match the tags applied to the private subnets (T005 of WP01: `Cluster = "support-bot-${var.env}"`). Add `karpenter.sh/discovery = "support-bot-${var.env}"` to the VPC, private subnets, and cluster security group via a `null_resource` or `aws_ec2_tag` resource in this WP (or wait until WP03 and add the tag there).
- The VPC CNI addon version must be `v1.14.0+eksbuild.3` or later for the `enableNetworkPolicy` flag to be recognized. Pin it.
- The control plane logging retention is the cluster's responsibility; the log groups are created by WP06 (with `retention_in_days = 7` for otel, 30 for application).