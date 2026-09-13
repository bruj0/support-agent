# Infrastructure

OpenTofu-managed AWS infrastructure for the support-agent. Two independent
EKS clusters (`support-bot-dev`, `support-bot-prod`) in `eu-central-1`.

## Important constraint

**This infrastructure does not install the Helm chart.** The chart at
`deploy/helm/support-bot/` is rendered and validated locally (`helm lint`,
`helm template --validate`, secret scan) by CI; actual `helm install` is a
downstream CI/CD feature.

## Layout

```
infra/
├── bootstrap/          # one-shot: S3 state backend + DynamoDB lock + KMS CMK
├── modules/
│   ├── foundation/     # VPC, subnets, NAT, VPC endpoints
│   ├── cluster/        # EKS, baseline MNG, Karpenter v1
│   ├── identity/       # KMS CMK, Secrets Manager, IAM roles, Pod Identity
│   ├── edge/           # ACM, Route53, WAFv2, ALB controller, Ingress
│   ├── storage/        # StorageClass, ECR, DLM snapshots
│   └── observability/  # ADOT, NetworkPolicy, PSS
├── envs/
│   ├── dev.tfvars
│   └── prod.tfvars
└── root.tf, root_variables.tf, root_outputs.tf, versions.tf
```

## Bootstrap (one-time)

```bash
cd infra/bootstrap
tofu init
tofu apply  # creates S3 bucket, DynamoDB lock, KMS CMK — never destroy
```

Outputs are exported: `tfstate_bucket_name`, `tfstate_lock_table_name`,
`tfstate_kms_key_arn`.

## Main workspace

```bash
cd infra
tofu init \
  -backend-config="bucket=<bucket-from-bootstrap>" \
  -backend-config="key=support-bot/dev/terraform.tfstate" \
  -backend-config="region=eu-central-1" \
  -backend-config="dynamodb_table=support-bot-tfstate-lock" \
  -backend-config="encrypt=true"
```

For prod, change the `key` to `support-bot/prod/terraform.tfstate`.

## Apply per environment

```bash
# dev
tofu apply -var-file=envs/dev.tfvars
# prod
tofu apply -var-file=envs/prod.tfvars
```

The `TF_VAR_openai_api_key=sk-...` env var must be set at apply time. The
`chroma_auth_token` is optional and supplied via `TF_VAR_chroma_auth_token=...`.

## Destroy

```bash
# ONLY for dev — never run this on prod without explicit approval
tofu destroy -var-file=envs/dev.tfvars
```

Resources with `lifecycle.prevent_destroy = true` will refuse to delete,
which is the desired behaviour for production data.

## CI

`.github/workflows/infra-ci.yml` runs on every PR:

- `tofu fmt -check -recursive infra/`
- `tofu validate` on bootstrap and every module
- `tflint -f compact infra/`
- `tofu test` on every module
- `helm lint deploy/helm/support-bot`
- `helm template deploy/helm/support-bot` + secret-scan grep

## Troubleshooting

### "AWS quota exceeded" on `tofu apply`

The plan step surfaces the AWS error. Increase the relevant quota in
AWS Service Quotas console and retry. Common quotas: EKS cluster limit
(default 100), VPC limit (default 5), ALB limit (default 50), EBS volume
IOPS limit (default 320 000), NAT gateway limit (default 5 per AZ).

### "Resource not found" on Pod Identity association

The EKS Pod Identity Agent addon (enabled in WP02) takes 1–2 minutes to
reconcile after creation. Wait and retry the apply.

### "State lock contention" on `tofu apply`

Another `tofu apply` is in progress. Check the DynamoDB lock table:
`aws dynamodb scan --table-name support-bot-tfstate-lock`. If the lock
is stale (no process is running), force-unlock with `tofu force-unlock <id>`.

### OpenAI key rotation

Update the secret in AWS Secrets Manager; ESO picks up the new value
within `refreshInterval` (default 1m, configured in WP03). No pod restart
required.

### ECR image pull failures from EKS

Verify the GitHub Actions OIDC role has been used to push at least one
image (otherwise the ECR policy's role reference is correct but no image
exists). Run `aws ecr describe-images --repository-name support-bot-api-prod`.
