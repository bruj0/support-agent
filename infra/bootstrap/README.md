# Bootstrap workspace — `infra/bootstrap/`

One-shot OpenTofu workspace that provisions the remote-state backend used by the
main workspace (`../`). Provisions:

- **S3 bucket** `support-bot-tfstate-<account-id>-eu-central-1-<random-suffix>` — versioned, SSE-KMS, `prevent_destroy`.
- **DynamoDB lock table** `support-bot-tfstate-lock` — `PAY_PER_REQUEST`, `prevent_destroy`.
- **KMS CMK** with alias `support-bot-bootstrap-cmk` — encrypts the S3 bucket.

**This workspace is never destroyed.** The `prevent_destroy` lifecycle rules
refuse to delete the bucket and the table; explicit operator confirmation is
required for the CMK (which has `deletion_window_in_days = 30`).

## Prerequisites

- AWS credentials (`AWS_PROFILE` or env vars), `tofu >= 1.6.0`, an account with
  quota for S3 + DynamoDB + KMS in `eu-central-1`.
- `aws_caller_identity` data source will resolve the account ID automatically.

## Procedure

```bash
cd infra/bootstrap
tofu init
tofu apply
```

Outputs are exported and must be copied into the main workspace's
`tofu init -backend-config=...` invocation (passed at init time, **not**
committed):

| Output | Used as |
|---|---|
| `tfstate_bucket_name` | `-backend-config="bucket=<value>"` |
| `tfstate_lock_table_name` | `-backend-config="dynamodb_table=<value>"` |
| `tfstate_kms_key_arn` | (not used by `tofu init`; available for downstream encryption) |

Example main-workspace `tofu init`:

```bash
cd ../         # back to infra/
tofu init \
  -backend-config="bucket=$(tofu -chdir=../bootstrap output -raw tfstate_bucket_name)" \
  -backend-config="key=support-bot/dev/terraform.tfstate" \
  -backend-config="region=eu-central-1" \
  -backend-config="dynamodb_table=$(tofu -chdir=../bootstrap output -raw tfstate_lock_table_name)" \
  -backend-config="encrypt=true"
```

## State

The bootstrap workspace uses **local state** at
`infra/bootstrap/terraform.tfstate`. There is no remote backend for the bootstrap
itself (chicken-and-egg). **Back this file up to a password manager or a small
private repository** — losing it requires re-bootstrapping with a new bucket
suffix and migrating any downstream state files.

## Disaster recovery

If the local bootstrap state is lost:

1. Re-run `tofu init && tofu apply` with the **same bucket name** (the
   `random_id` re-rolls; the original bucket will be left orphaned unless the
   suffix matches). Pinning the bucket name requires a state import.
2. If the original bucket still exists, import it: `tofu import aws_s3_bucket.tfstate <bucket-name>`.
3. If the original bucket was destroyed, accept a new suffix and update the
   downstream `envs/<env>.tfvars` or main-workspace `tofu init` command to use
   the new bucket.

## Warning

`tofu destroy` on the bootstrap workspace **will fail** because of
`prevent_destroy = true` on the bucket and the DynamoDB table. The CMK has
`deletion_window_in_days = 30` so even force-delete requires waiting 30 days.
This is intentional.