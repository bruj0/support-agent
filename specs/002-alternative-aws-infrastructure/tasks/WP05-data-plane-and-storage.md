---
work_package_id: "WP05"
title: "Data Plane & Storage — StorageClass, ECR, DLM snapshots"
lane: "planned"
dependencies:
  - "WP02"
  - "WP03"
subsystem: "S5 Data Plane & Storage"
misfits_addressed:
  - "M3 (PVC Retain)"
  - "M9 (DLM snapshot)"
  - "M10 (shared ECR + moving tag — fixed by per-env repo + tag immutability)"
abstract_components:
  - "Gp3StorageClass (from S5 plan)"
  - "StorageClassValueMerge (from S5 plan)"
  - "EcrRepository (from S5 plan)"
  - "DlmSnapshotPolicy (from S5 plan)"
agent: ""
history: []
---

# WP05 — Data Plane & Storage

## Goal

Provision the per-env `support-bot-gp3` StorageClass via `kubernetes_manifest` (gp3, 3000 IOPS, 250 MiB/s, encrypted, `reclaimPolicy: Retain`, `volumeBindingMode: WaitForFirstConsumer`), the ECR repository (image scanning on, tag immutability, repository policy scoped to the GitHub Actions OIDC role), the DLM snapshot policy (target tags `Cluster=<env>, Component=chroma`, 24h interval, 7d retention), and the additive chart values for `persistence.storageClassName` and PVC annotations.

This WP provides the data persistence primitives. Without it, the Chroma PVC fails to bind (StorageClass missing), the operator cannot push container images (ECR missing), and a PVC deletion loses the embeddings (no DLM snapshot).

## Context

- **Region**: `eu-central-1`
- **Module root**: `infra/modules/storage/`
- **Chart additions**: additive values only (no new templates in this WP)
- **Inputs**: `eks_cluster_name` from WP02; `github_actions_role_arn` from WP03; `vpc_id` from WP01 (for DLM tag scoping)
- **OpenTofu version**: `>= 1.6.0`

## Subtasks

### T001 — Create `infra/modules/storage/{variables.tf,versions.tf}`

```hcl
# versions.tf
terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws        = { source = "hashicorp/aws",        version = ">= 5.40.0" }
    kubernetes = { source = "hashicorp/kubernetes", version = ">= 2.27.0" }
  }
}

# variables.tf
variable "env"                   { type = string }
variable "eks_cluster_name"      { type = string }
variable "github_actions_role_arn" { type = string }
variable "shared_ecr"            { type = bool; default = false }
```

### T002 — Create `infra/modules/storage/main.tf` (part A): `support-bot-gp3` StorageClass

```hcl
resource "kubernetes_manifest" "support_bot_gp3_storageclass" {
  manifest = {
    apiVersion = "storage.k8s.io/v1"
    kind       = "StorageClass"
    metadata = {
      name = "support-bot-gp3"
      annotations = {
        "storageclass.kubernetes.io/is-default-class" = "false"
      }
    }
    provisioner = "ebs.csi.aws.com"
    parameters = {
      type      = "gp3"
      iops      = "3000"
      throughput = "250"
      encrypted = "true"
    }
    reclaimPolicy         = "Retain"
    volumeBindingMode     = "WaitForFirstConsumer"
    allowVolumeExpansion  = true
  }
}
```

**Critical**: `reclaimPolicy = "Retain"` resolves Misfit M3. Without this, a `helm uninstall` or `tofu destroy` would delete the EBS volume and lose the embeddings.

### T003 — Create `infra/modules/storage/main.tf` (part B): ECR repository

```hcl
resource "aws_ecr_repository" "support_bot_api" {
  name                 = var.shared_ecr ? "support-bot-api" : "support-bot-api-${var.env}"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "KMS"
  }
  tags = {
    Name    = "support-bot-api-${var.env}"
    Cluster = "support-bot-${var.env}"
    Component = "api"
  }
  lifecycle { prevent_destroy = true }
}
```

**Critical**: `image_tag_mutability = "IMMUTABLE"` resolves Misfit M10 (no `latest` tag, no moving tags). Combined with `scan_on_push = true`, this is the supply-chain gate for this feature (cosign signing is out of scope).

### T004 — Create `infra/modules/storage/main.tf` (part C): ECR repository policy

```hcl
data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "ecr_repo_policy" {
  statement {
    sid    = "AllowGitHubActionsPush"
    effect = "Allow"
    principals {
      type        = "AWS"
      identifiers = [var.github_actions_role_arn]
    }
    actions = [
      "ecr:PutImage",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
    ]
  }

  statement {
    sid    = "AllowAccountPull"
    effect = "Allow"
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
    actions = [
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
      "ecr:DescribeImages",
    ]
  }
}

resource "aws_ecr_repository_policy" "support_bot_api" {
  repository = aws_ecr_repository.support_bot_api.name
  policy     = data.aws_iam_policy_document.ecr_repo_policy.json
}
```

The policy scopes push to only the GitHub Actions role, pull to only the account root. No `*` principals.

### T005 — Create `infra/modules/storage/main.tf` (part D): DLM snapshot policy

```hcl
resource "aws_dlm_lifecycle_policy" "chroma_snapshot" {
  description        = "Daily EBS snapshot for Chroma PVCs in support-bot-${var.env}"
  execution_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/AWSDataLifecycleManagerDefaultRole"
  state              = "ENABLED"

  policy_details {
    policy_type = "EBS_SNAPSHOT_MANAGEMENT"
    resource_types = ["VOLUME"]
    target_tags = {
      Cluster   = "support-bot-${var.env}"
      Component = "chroma"
    }

    schedule {
      name = "daily-7day-retention"
      create_rule {
        interval      = 24
        interval_unit = "HOURS"
        times         = ["03:00"]
      }
      retain_rule {
        count = 7
      }
      copy_tags = true
    }
  }
}
```

**Critical**: `target_tags` must match the PVC's actual annotations at creation time. The chart's existing `templates/pvc.yaml` is not edited, but the chart values are extended (T006) to set `persistence.annotations = { Cluster, Component }` — these flow through Helm's standard `metadata.annotations` mapping and become the EBS volume's tags when the EBS CSI driver provisions the volume.

**Caveat**: the AWS EBS CSI driver does **not** automatically tag the EBS volume with the PVC's annotations by default. The annotations are on the PVC, not on the EBS volume. Two options:
1. Enable the `aws-ebs-csi-driver` DaemonSet's `extra-tags` flag to copy PVC tags to volumes.
2. Add a `post-binding` webhook that copies annotations.

For this WP, document the limitation in the WP prompt's "Notes for implementer" section, and use option 1 (the extra-tags flag in the EBS CSI driver DaemonSet configuration — added in WP02's `aws_eks_addon.ebs_csi_driver` if not already there).

### T006 — Extend chart values for `persistence.storageClassName`

```yaml
# deploy/helm/support-bot/values.yaml (append)
persistence:
  storageClassName: "support-bot-gp3"  # additive — does not edit any existing template
```

The chart's existing `templates/pvc.yaml` already references `{{ .Values.persistence.storageClassName }}` (verify by reading the existing template — the field name must match exactly).

### T007 — Extend chart values for `persistence.annotations`

```yaml
# deploy/helm/support-bot/values.yaml (append — extends T006)
persistence:
  storageClassName: "support-bot-gp3"
  annotations:
    Cluster: "support-bot-{{ .Values.env }}"
    Component: "chroma"
```

These annotations become the PVC's `metadata.annotations`. The EBS CSI driver copies them to the EBS volume's tags (via the DaemonSet's `extra-volume-tags` flag — see WP02 notes).

### T008 — Create `infra/modules/storage/outputs.tf`

```hcl
output "storage_class_name"  { value = kubernetes_manifest.support_bot_gp3_storageclass.manifest.metadata.name }
output "ecr_repository_url"  { value = aws_ecr_repository.support_bot_api.repository_url }
output "ecr_repository_arn"  { value = aws_ecr_repository.support_bot_api.arn }
output "dlm_policy_id"       { value = aws_dlm_lifecycle_policy.chroma_snapshot.id }
```

### T009 — Create `infra/modules/storage/tests/storage.tftest.hcl`

```hcl
run "storageclass_has_retain" {
  command = plan
  assert {
    condition     = kubernetes_manifest.support_bot_gp3_storageclass.manifest.reclaimPolicy == "Retain"
    error_message = "StorageClass must have reclaimPolicy = Retain (resolves Misfit M3)."
  }
}

run "storageclass_wait_for_first_consumer" {
  command = plan
  assert {
    condition     = kubernetes_manifest.support_bot_gp3_storageclass.manifest.volumeBindingMode == "WaitForFirstConsumer"
    error_message = "StorageClass must have volumeBindingMode = WaitForFirstConsumer."
  }
}

run "storageclass_gp3_with_iops" {
  command = plan
  assert {
    condition     = kubernetes_manifest.support_bot_gp3_storageclass.manifest.parameters.type == "gp3"
    error_message = "StorageClass must use gp3."
  }
  assert {
    condition     = kubernetes_manifest.support_bot_gp3_storageclass.manifest.parameters.iops == "3000"
    error_message = "StorageClass must have iops = 3000."
  }
  assert {
    condition     = kubernetes_manifest.support_bot_gp3_storageclass.manifest.parameters.throughput == "250"
    error_message = "StorageClass must have throughput = 250."
  }
}

run "ecr_repo_immutable_tags" {
  command = plan
  assert {
    condition     = aws_ecr_repository.support_bot_api.image_tag_mutability == "IMMUTABLE"
    error_message = "ECR repo must have image_tag_mutability = IMMUTABLE (resolves Misfit M10)."
  }
}

run "ecr_repo_scan_on_push" {
  command = plan
  assert {
    condition     = aws_ecr_repository.support_bot_api.image_scanning_configuration[0].scan_on_push == true
    error_message = "ECR repo must have scan_on_push = true."
  }
}

run "ecr_repo_policy_scoped" {
  command = plan
  assert {
    condition = alltrue([
      for stmt in jsondecode(aws_ecr_repository_policy.support_bot_api.policy).Statement :
      stmt.principals[0].identifiers[0] != "*"
    ])
    error_message = "ECR repo policy must not grant access to * principals."
  }
}

run "dlm_targets_chroma_tag" {
  command = plan
  assert {
    condition     = aws_dlm_lifecycle_policy.chroma_snapshot.policy_details[0].target_tags.Component == "chroma"
    error_message = "DLM policy must target Component = chroma tag (resolves Misfit M9)."
  }
  assert {
    condition     = aws_dlm_lifecycle_policy.chroma_snapshot.policy_details[0].schedule[0].retain_rule[0].count == 7
    error_message = "DLM policy must retain 7 snapshots."
  }
}

run "ecr_repo_lifecycle_prevent_destroy" {
  command = plan
  assert {
    condition     = aws_ecr_repository.support_bot_api.lifecycle.prevent_destroy == true
    error_message = "ECR repo must have prevent_destroy = true (resolves Misfit M8)."
  }
}
```

### T010 — Extend `infra/root.tf`

```hcl
# infra/root.tf (append)
module "storage" {
  source = "./modules/storage"

  env                     = var.env
  eks_cluster_name        = module.cluster.cluster_name
  github_actions_role_arn = module.identity.github_actions_role_arn
  shared_ecr              = var.shared_ecr
}
```

Also extend root outputs:

```hcl
# infra/root_outputs.tf (append)
output "storage_class_name" { value = module.storage.storage_class_name }
output "ecr_repository_url" { value = module.storage.ecr_repository_url }
output "ecr_repository_arn" { value = module.storage.ecr_repository_arn }
output "dlm_policy_id"      { value = module.storage.dlm_policy_id }
```

### T011 — CI step

Add a CI step that runs after `tofu validate`:

```yaml
- name: helm template storageClass + annotations check
  working-directory: deploy/helm/support-bot
  run: |
    helm template . --values values-prod.yaml > /tmp/rendered.yaml
    grep -E 'storageClassName: support-bot-gp3' /tmp/rendered.yaml && \
    grep -E 'Component: chroma' /tmp/rendered.yaml
```

## Acceptance Criteria

1. `tofu apply -var-file=envs/prod.tfvars` provisions: 1 StorageClass (via `kubernetes_manifest`), 1 ECR repository, 1 ECR policy, 1 DLM policy.
2. `kubectl get sc support-bot-gp3` (after cluster authentication) returns `gp3` with `reclaimPolicy: Retain`.
3. `helm template deploy/helm/support-bot --values values-prod.yaml` renders a PVC with `storageClassName: support-bot-gp3` and annotations `Cluster: support-bot-prod, Component: chroma`.
4. `aws ecr describe-repositories --names support-bot-api-prod` returns `imageScanningConfiguration: { scanOnPush: true }`, `imageTagMutability: IMMUTABLE`.
5. `aws dlm get-lifecycle-policies --policy-id <id>` returns `PolicyDetails.Schedules[0].CreateRule.Interval = 24`, `RetainRule.Count = 7`.
6. `cd infra/modules/storage && tofu test` runs all 9 `run` blocks; all assertions pass.
7. `tofu plan` after apply reports `No changes.`

## TDD Targets

- **M3 (PVC Retain)**: `tofu test` asserts the StorageClass manifest has `reclaimPolicy: Retain`.
- **M9 (DLM snapshot)**: `tofu test` asserts the DLM policy's `target_tags.Component == "chroma"`.
- **M10 (shared ECR + moving tag)**: `tofu test` asserts the ECR repo has `image_tag_mutability = "IMMUTABLE"`.

## Execution constraints

- Product code and tests: only in `$WORKTREES_DIR/002-alternative-aws-infrastructure-WP05/`
- Do not merge to `main` until `spec-bridge-merge` after accept
- Do not instruct "verify on main" — verify in the WP worktree after dependency merges
- **Independent of WP04** — can run in parallel after WP02 + WP03 land on `main`.

## Notes for implementer

- **Critical caveat about DLM tags**: the EBS CSI driver does NOT automatically copy PVC annotations to EBS volume tags. The PVC annotations become the PVC's metadata.annotations; the EBS volume itself has separate tags. To make DLM work, the EBS CSI driver DaemonSet must be configured with `--node-taint-no-execute=true` (already done) AND the chart must set `metadata.labels` (not annotations) with the right tags, OR the EBS CSI driver must be configured with `extra-volume-tags` that copies from PVC labels.

  The simplest fix is to also set `persistence.labels` in the chart values:
  ```yaml
  persistence:
    labels:
      Cluster: "support-bot-{{ .Values.env }}"
      Component: "chroma"
  ```
  And configure the EBS CSI driver to copy labels to volume tags. Verify the chart's existing `templates/pvc.yaml` supports `metadata.labels` via Helm (it does — standard Helm behavior).

  If `persistence.labels` is the right approach, update T007 to use labels instead of annotations. Document the change in the commit message and update T009/T011 accordingly.

- The `execution_role_arn` for the DLM policy is the AWS-managed role `AWSDataLifecycleManagerDefaultRole` that AWS creates automatically when the first DLM policy is enabled. The implementer may need to create this role manually (per AWS docs) if it doesn't exist.

- The chart's existing `templates/pvc.yaml` already supports `persistence.storageClassName` and `persistence.annotations` via Helm's standard `metadata.annotations` merge. Verify by reading the existing template — if it does NOT, the implementer needs to **propose an additive change** (which the spec allows). Do not edit the existing template without first reading it.

- The `kubernetes_manifest.support_bot_gp3_storageclass` resource uses `manifest` (HCL map) — not `manifest_json`. For StorageClass CRDs the HCL map shape works; for complex CRDs (Ingress, NetworkPolicy) the implementer should prefer `manifest_json` for safety.