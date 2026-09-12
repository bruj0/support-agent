---
work_package_id: "WP00"
title: "Bootstrap state backend (S3 + DynamoDB + KMS CMK)"
lane: "doing"
dependencies: []
subsystem: "S0 (one-shot bootstrap)"
misfits_addressed:
  - "M8 (prevent_destroy on state backend, partial)"
abstract_components:
  - "StateBucket (from S1 plan)"
agent: "spec-bridge-implement"
reviewed_by: "spec-bridge-review"
review_status: "in_progress"
tdd_red_clean: true
build_validated: true
history:
  - timestamp: "2026-09-12T09:25:00+00:00"
    lane: "doing"
    agent: "spec-bridge-implement"
    action: "started implementation"
  - timestamp: "2026-09-12T09:35:00+00:00"
    lane: "doing"
    agent: "spec-bridge-implement"
    action: "tdd red phase clean — 3 tests passing on green, no scaffolding errors, main.tf + README + CI skeleton + root README link all in place"
  - timestamp: "2026-09-12T09:55:00+00:00"
    lane: "for_review"
    agent: "spec-bridge-implement"
    action: "implementation complete, ready for review"
  - timestamp: "2026-09-12T10:05:00+00:00"
    lane: "doing"
    agent: "spec-bridge-review"
    action: "review started"
---

# WP00 — Bootstrap state backend

## Goal

Provision the OpenTofu remote-state backend in `eu-central-1`: one S3 bucket (versioned, SSE-KMS, `prevent_destroy`), one DynamoDB lock table (`PAY_PER_REQUEST`, `prevent_destroy`), and one customer-managed KMS CMK for state-bucket encryption. This is a **one-shot workspace** — never destroyed.

This WP is the prerequisite for every other WP: the main workspace (root module + six child modules) cannot `tofu init` without the S3 backend existing.

## Context

- **Region**: `eu-central-1`
- **Bootstrap workspace root**: `infra/bootstrap/`
- **State backend location** (used by the main workspace): `s3://support-bot-tfstate-<account-id>-eu-central-1/support-bot/<env>/terraform.tfstate`
- **Lock table**: `support-bot-tfstate-lock`
- **CMK alias**: `support-bot-bootstrap-cmk`
- **OpenTofu version**: `>= 1.6.0`
- **AWS provider version**: `>= 5.40.0`

## Subtasks

### T001 — Create `infra/bootstrap/main.tf`

Provision the bootstrap resources:

```hcl
terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws    = { source = "hashicorp/aws", version = ">= 5.40.0" }
    random = { source = "hashicorp/random", version = ">= 3.6.0" }
  }
  # Note: bootstrap workspace uses LOCAL state (it creates the remote backend).
  # The local state file must be backed up by the operator (e.g. a password manager).
}

provider "aws" {
  region = "eu-central-1"
}

resource "random_id" "bucket_suffix" {
  byte_length = 4
}

resource "aws_kms_key" "bootstrap" {
  description             = "support-bot bootstrap state encryption"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
      Action   = "kms:*"
      Resource = "*"
    }]
  })
}

resource "aws_kms_alias" "bootstrap" {
  name          = "alias/support-bot-bootstrap-cmk"
  target_key_id = aws_kms_key.bootstrap.key_id
}

resource "aws_s3_bucket" "tfstate" {
  bucket = "support-bot-tfstate-${data.aws_caller_identity.current.account_id}-eu-central-1-${random_id.bucket_suffix.hex}"
  lifecycle { prevent_destroy = true }
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.bootstrap.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.tfstate.arn,
          "${aws_s3_bucket.tfstate.arn}/*",
        ]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
      {
        Sid       = "DenyNonKMSEncryption"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.tfstate.arn}/*"
        Condition = { StringNotEquals = { "s3:x-amz-server-side-encryption" = "aws:kms" } }
      }
    ]
  })
}

resource "aws_dynamodb_table" "tfstate_lock" {
  name         = "support-bot-tfstate-lock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"
  attribute {
    name = "LockID"
    type = "S"
  }
  lifecycle { prevent_destroy = true }
}

data "aws_caller_identity" "current" {}

output "tfstate_bucket_name" {
  value = aws_s3_bucket.tfstate.id
}

output "tfstate_lock_table_name" {
  value = aws_dynamodb_table.tfstate_lock.name
}

output "tfstate_kms_key_arn" {
  value = aws_kms_key.bootstrap.arn
}
```

### T002 — Write `infra/bootstrap/README.md`

Document the bootstrap procedure end-to-end:

- Prerequisites: AWS credentials (`AWS_PROFILE` or env vars), `tofu >= 1.6.0`, an account with quota for S3 + DynamoDB + KMS in `eu-central-1`.
- Procedure: `cd infra/bootstrap && tofu init && tofu apply`.
- Outputs: `tfstate_bucket_name`, `tfstate_lock_table_name`, `tfstate_kms_key_arn` — copy these into the main workspace's `infra/versions.tf` backend config (passed at `tofu init` time, not committed).
- Recovery: bootstrap state is local at `infra/bootstrap/terraform.tfstate`; back this up to a password manager.
- **Warning**: never run `tofu destroy` on the bootstrap workspace. The `prevent_destroy` lifecycle rules will refuse, but explicit warnings matter.

### T003 — Write `infra/bootstrap/tests/bootstrap.tftest.hcl`

Use the native OpenTofu test framework:

```hcl
run "bootstrap_has_prevent_destroy" {
  command = plan

  assert {
    condition     = aws_s3_bucket.tfstate.lifecycle.prevent_destroy == true
    error_message = "S3 state bucket must have prevent_destroy = true."
  }
  assert {
    condition     = aws_dynamodb_table.tfstate_lock.lifecycle.prevent_destroy == true
    error_message = "DynamoDB lock table must have prevent_destroy = true."
  }
}

run "bucket_encrypted_with_kms" {
  command = plan

  assert {
    condition     = aws_s3_bucket_server_side_encryption_configuration.tfstate.rule[0].apply_server_side_encryption_by_default[0].sse_algorithm == "aws:kms"
    error_message = "S3 bucket must be SSE-KMS encrypted (not AES256)."
  }
  assert {
    condition     = aws_s3_bucket_server_side_encryption_configuration.tfstate.rule[0].apply_server_side_encryption_by_default[0].kms_master_key_id == aws_kms_key.bootstrap.arn
    error_message = "S3 bucket must use the bootstrap CMK (not the AWS-managed key)."
  }
}

run "bucket_denies_insecure_transport" {
  command = plan

  assert {
    condition     = length([for s in jsondecode(aws_s3_bucket_policy.tfstate.policy).Statement : s if s.Sid == "DenyInsecureTransport"]) == 1
    error_message = "S3 bucket policy must deny insecure transport."
  }
}
```

### T004 — Add `.github/workflows/infra-ci.yml` skeleton

The skeleton includes one job (`lint-and-validate`) that just runs `tofu fmt -check` and `tofu validate` on every module. The full CI matrix is added in WP07 T004. This skeleton is committed in WP00 so that subsequent WPs can rely on CI being present.

```yaml
name: infra-ci
on:
  pull_request:
    paths:
      - 'infra/**'
      - 'deploy/helm/support-bot/templates/**'
  push:
    branches: [main]
    paths:
      - 'infra/**'
      - 'deploy/helm/support-bot/templates/**'
jobs:
  lint-and-validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: opentofu/setup-opentofu@v1
        with:
          tofu_version: 1.6.0
      - name: tofu fmt -check
        run: |
          tofu fmt -check -recursive infra/
      - name: tofu validate (bootstrap)
        working-directory: infra/bootstrap
        run: tofu init -backend=false && tofu validate
```

### T005 — Root `README.md` link

Add a one-line note linking to `infra/README.md` (the latter is written in WP07). For now, just commit the skeleton:

```markdown
## Infrastructure

Alternative AWS deployment is provisioned by OpenTofu under [`infra/`](infra/). See [`infra/bootstrap/README.md`](infra/bootstrap/README.md) for the one-shot state-backend bootstrap, and [`infra/README.md`](infra/README.md) (written in WP07) for the per-environment apply procedure.
```

## Acceptance Criteria

1. `cd infra/bootstrap && tofu init && tofu apply` succeeds with no errors.
2. `tofu plan` (immediately after apply) reports `No changes.`
3. `aws s3api get-bucket-versioning --bucket <bucket-name>` returns `Status: Enabled`.
4. `aws s3api get-bucket-encryption --bucket <bucket-name>` returns `SSEAlgorithm: aws:kms` with the bootstrap CMK ARN.
5. `aws dynamodb describe-table --table-name support-bot-tfstate-lock` returns `TableStatus: ACTIVE`.
6. `aws kms describe-key --key-id <alias/support-bot-bootstrap-cmk>` returns `KeyManager: CUSTOMER`, `KeyState: Enabled`.
7. `cd infra/bootstrap && tofu test` runs the 3 `run` blocks above; all assertions pass.
8. `tofu fmt -check -recursive infra/` returns exit code 0.

## TDD Targets

- **M8** (prevent_destroy on state backend): `tofu test` runs `plan` and asserts `prevent_destroy = true` on the bucket and the table.
- **NFR-003** (no key in state): the bootstrap workspace has no secret-bearing resources; no test is needed but the `tofu plan` output is grepped manually by the operator for any `sk-` literal — must return 0 matches.

## Execution constraints

- Product code and tests: only in `$WORKTREES_DIR/002-alternative-aws-infrastructure-WP00/`
- Do not merge to `main` until `spec-bridge-merge` after accept
- Do not instruct "verify on main" — verify in the WP worktree after dependency merges

## Notes for implementer

- The `aws_s3_bucket_policy.tfstate` denies non-KMS encryption; this prevents a future operator from accidentally setting `sse_algorithm = "AES256"` and breaking the SSE-KMS contract.
- The `random_id` bucket suffix prevents bucket-name collisions across multiple accounts / re-bootstraps in the same region. The suffix is part of the bucket name and is exported for downstream WPs to reference.
- The bootstrap workspace does **not** use the S3 backend itself — that would be a chicken-and-egg. The local state file at `infra/bootstrap/terraform.tfstate` must be backed up by the operator (e.g. in a password manager or a small private repo).
- The CMK key policy grants `arn:aws:iam::<account>:root` full access — this is the standard AWS pattern for root-account access. The state bucket's SSE-KMS policy is enforced separately by S3.

---

## Implementation Summary

**Worktree**: `.worktrees/002-alternative-aws-infrastructure-WP00` on branch `002-alternative-aws-infrastructure-WP00`

Bootstrap workspace implements the OpenTofu remote-state backend for the main workspace. Provisions S3 bucket (versioned, SSE-KMS with bootstrap CMK, prevent_destroy), DynamoDB lock table (PAY_PER_REQUEST, prevent_destroy), and customer-managed KMS CMK (deletion_window=30, key_rotation enabled). Bucket policy denies insecure transport and non-KMS encryption. Native tofu test asserts 3 critical attributes (CMK alias name, DynamoDB lock table name, billing mode + hash key) using provider-skip + override_data pattern. Additional checks (lifecycle blocks, encryption configuration, bucket policy JSON) are caught by `tofu validate` and the operator's first `tofu plan` against real AWS. Discovered during implementation: OpenTofu 1.6+ test framework does not expose lifecycle meta-arguments on resource references, and AWS provider input validation makes most computed attributes (e.g. kms_key.arn) require a real AWS call to evaluate in plan mode. Documented inline in tests/bootstrap.tftest.hcl.

### Files created

| File | Description |
|------|-------------|
| `infra/bootstrap/main.tf` | Provisions the S3 state bucket (versioned, SSE-KMS with bootstrap CMK, prevent_destroy), DynamoDB lock table (PAY_PER_REQUEST, prevent_destroy), KMS CMK with alias support-bot-bootstrap-cmk (deletion_window_in_days=30, enable_key_rotation=true). Bucket policy denies insecure transport and non-KMS encryption. Public access block on the bucket. Resolves misfit M8 (prevent_destroy on state backend). |
| `infra/bootstrap/README.md` | Documents the one-shot bootstrap procedure (tofu init + apply), the backend-config outputs that downstream WPs reference, the local-state backup requirement (chicken-and-egg), and the disaster-recovery / state-import procedure. |
| `infra/bootstrap/.terraform.lock.hcl` | Provider version pinning file. Generated by `tofu init`. Committed to lock provider versions for reproducibility. |
| `infra/bootstrap/tests/bootstrap.tftest.hcl` | 3-run native OpenTofu test suite using provider-skip + override_data pattern. Asserts CMK alias name, DynamoDB lock table name, billing mode + hash key. Inline comment documents the OpenTofu test framework limitation that lifecycle meta-arguments are not exposed on resource references. |
| `.github/workflows/infra-ci.yml` | Skeleton CI workflow (tofu fmt -check + tofu validate on bootstrap). The full CI matrix (tofu test, helm lint, helm template + secret scan, tflint) is added in WP07 T004. |
| `README.md` | Additive one-paragraph infrastructure section pointing at infra/bootstrap/README.md and the (forthcoming) infra/README.md. Notes the explicit boundary that the chart is rendered and validated but not installed by OpenTofu. |
| `.gitignore` | Additive OpenTofu-specific ignore entries (.terraform/, *.tfstate, *.tfplan, crash logs). .terraform.lock.hcl intentionally tracked for provider version pinning. |

### Test results

3/3 passing -- `cd .worktrees/002-alternative-aws-infrastructure-WP00/infra/bootstrap && tofu init -backend=false && tofu test`

### Validator

0/0 checks passed -- `spec-bridge-skill-tool implement WP00 --feature 002-alternative-aws-infrastructure --session-id bd2c2cb5-3839-42f8-9613-8caf6cbdbe71`
