---
work_package_id: "WP07"
title: "Docs — infra/README.md + aws-flow-v2.md + CI completion"
lane: "planned"
dependencies:
  - "WP01"
  - "WP02"
  - "WP03"
  - "WP04"
  - "WP05"
  - "WP06"
subsystem: "cross-cutting"
misfits_addressed:
  - "(none — pure docs/CI; the existing WPs already cover the misfits)"
abstract_components:
  - "(documentation + CI)"
agent: ""
history: []
---

# WP07 — Docs + CI completion

## Goal

Write `infra/README.md` (bootstrap, dev/prod apply, destroy, troubleshooting), `docs/architecture/aws-flow-v2.md` (replacement prose for the existing `aws-flow.md`), update `docs/architecture/index.md` to reference v2, and complete the CI workflow at `.github/workflows/infra-ci.yml` with the full matrix of checks (helm lint, helm template --validate, secret scan, tofu fmt -check, tofu validate, tflint, tofu test).

This WP is the last WP. It does not provision any new AWS resources — it documents and validates what the prior WPs built.

## Context

- **Chart additions**: none in this WP
- **Infra additions**: none in this WP (only docs and CI)
- **Inputs**: the prior WPs' modules (read-only references)

## Subtasks

### T001 — Write `infra/README.md`

End-to-end documentation:

```markdown
# Infrastructure

OpenTofu-managed AWS infrastructure for the support-agent. Two independent
EKS clusters (`support-bot-dev`, `support-bot-prod`) in `eu-central-1`.

## Important constraint

**This infrastructure does not install the Helm chart.** The chart at
`deploy/helm/support-bot/` is rendered and validated locally (`helm lint`,
`helm template --validate`, secret scan) by CI; actual `helm install` is a
downstream CI/CD feature.

## Layout

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

## Bootstrap (one-time)

\`\`\`bash
cd infra/bootstrap
tofu init
tofu apply  # creates S3 bucket, DynamoDB lock, KMS CMK — never destroy
\`\`\`

Outputs are exported: `tfstate_bucket_name`, `tfstate_lock_table_name`,
`tfstate_kms_key_arn`.

## Main workspace

\`\`\`bash
cd infra
tofu init \
  -backend-config="bucket=<bucket-from-bootstrap>" \
  -backend-config="key=support-bot/dev/terraform.tfstate" \
  -backend-config="region=eu-central-1" \
  -backend-config="dynamodb_table=support-bot-tfstate-lock" \
  -backend-config="encrypt=true"
\`\`\`

For prod, change the `key` to `support-bot/prod/terraform.tfstate`.

## Apply per environment

\`\`\`bash
# dev
tofu apply -var-file=envs/dev.tfvars
# prod
tofu apply -var-file=envs/prod.tfvars
\`\`\`

The `TF_VAR_openai_api_key=sk-...` env var must be set at apply time. The
`chroma_auth_token` is optional and supplied via `TF_VAR_chroma_auth_token=...`.

## Destroy

\`\`\`bash
# ONLY for dev — never run this on prod without explicit approval
tofu destroy -var-file=envs/dev.tfvars
\`\`\`

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
```

### T002 — Write `docs/architecture/aws-flow-v2.md`

Replacement prose for the existing `aws-flow.md`. Structure:

```markdown
# Alternative AWS View (v2)

This document supersedes `aws-flow.md`. It describes the OpenTofu-managed
infrastructure that this feature (`002-alternative-aws-infrastructure`)
provisions.

## Topology

\`\`\`
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
\`\`\`

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
```

Add a deprecation banner to the existing `docs/architecture/aws-flow.md`:

```markdown
> **DEPRECATED.** This document is superseded by [`aws-flow-v2.md`](aws-flow-v2.md),
> produced by feature `002-alternative-aws-infrastructure`. The text below
> describes the pre-OpenTofu prose design and is kept only for reference.
> Remove this file in a follow-up chore after `aws-flow-v2.md` is verified.
```

### T003 — Update `docs/architecture/index.md`

Add a link to `aws-flow-v2.md` at the top of the architecture section:

```markdown
- [Alternative AWS View (v2)](aws-flow-v2.md) — current OpenTofu-managed deployment
- [Local Flow](local-flow.md) — docker-compose dev environment
- [AWS Flow (deprecated)](aws-flow.md) — pre-OpenTofu prose design
```

### T004 — Complete `.github/workflows/infra-ci.yml`

```yaml
name: infra-ci
on:
  pull_request:
    paths:
      - 'infra/**'
      - 'deploy/helm/support-bot/templates/**'
      - 'deploy/helm/support-bot/values*.yaml'
      - 'docs/architecture/aws-flow-v2.md'
  push:
    branches: [main]
    paths:
      - 'infra/**'
      - 'deploy/helm/support-bot/templates/**'
      - 'deploy/helm/support-bot/values*.yaml'
jobs:
  tofu-fmt:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: opentofu/setup-opentofu@v1
        with:
          tofu_version: 1.6.0
      - run: tofu fmt -check -recursive infra/
  tofu-validate:
    runs-on: ubuntu-latest
    needs: tofu-fmt
    steps:
      - uses: actions/checkout@v4
      - uses: opentofu/setup-opentofu@v1
        with:
          tofu_version: 1.6.0
      - name: tofu validate (bootstrap)
        working-directory: infra/bootstrap
        run: tofu init -backend=false && tofu validate
      - name: tofu validate (main)
        working-directory: infra
        run: tofu init -backend=false && tofu validate
  tofu-test:
    runs-on: ubuntu-latest
    needs: tofu-validate
    steps:
      - uses: actions/checkout@v4
      - uses: opentofu/setup-opentofu@v1
        with:
          tofu_version: 1.6.0
      - name: install helm
        uses: azure/setup-helm@v4
        with:
          version: v3.14.0
      - name: tofu test (bootstrap)
        working-directory: infra/bootstrap
        run: tofu init -backend=false && tofu test
      - name: tofu test (foundation)
        working-directory: infra/modules/foundation
        run: tofu init -backend=false && tofu test
      - name: tofu test (cluster)
        working-directory: infra/modules/cluster
        run: tofu init -backend=false && tofu test
      - name: tofu test (identity)
        working-directory: infra/modules/identity
        run: tofu init -backend=false && tofu test
      - name: tofu test (edge)
        working-directory: infra/modules/edge
        run: tofu init -backend=false && tofu test
      - name: tofu test (storage)
        working-directory: infra/modules/storage
        run: tofu init -backend=false && tofu test
      - name: tofu test (observability)
        working-directory: infra/modules/observability
        run: tofu init -backend=false && tofu test
  helm-lint:
    runs-on: ubuntu-latest
    needs: tofu-validate
    steps:
      - uses: actions/checkout@v4
      - uses: azure/setup-helm@v4
        with:
          version: v3.14.0
      - working-directory: deploy/helm/support-bot
        run: |
          helm lint . --values values.yaml
          helm lint . --values values-dev.yaml
          helm lint . --values values-prod.yaml
  helm-template-and-secret-scan:
    runs-on: ubuntu-latest
    needs: helm-lint
    steps:
      - uses: actions/checkout@v4
      - uses: azure/setup-helm@v4
        with:
          version: v3.14.0
      - name: helm template + secret scan
        working-directory: deploy/helm/support-bot
        run: |
          set -e
          helm template . --values values-prod.yaml > /tmp/rendered-prod.yaml
          helm template . --values values-dev.yaml > /tmp/rendered-dev.yaml
          cat /tmp/rendered-prod.yaml /tmp/rendered-dev.yaml | \
            ( ! grep -E 'sk-[A-Za-z0-9]{32,}' ) && \
            ( ! grep -E 'OPENAI_API_KEY=[^"]*sk-' ) && \
            ( ! grep -E 'CHROMA_AUTH_TOKEN=[^"]*[A-Za-z0-9]{16,}' )
          # Confirm new templates render
          grep -E 'kind: Ingress' /tmp/rendered-prod.yaml
          grep -E 'kind: ExternalSecret' /tmp/rendered-prod.yaml
          grep -E 'kind: NetworkPolicy' /tmp/rendered-prod.yaml | wc -l | grep -E '^[ ]*3$'
  tflint:
    runs-on: ubuntu-latest
    needs: tofu-fmt
    steps:
      - uses: actions/checkout@v4
      - uses: terraform-linters/setup-tflint@v4
        with:
          tflint_version: latest
      - uses: actions/checkout@v4
        with:
          repository: aws-cloudformation/tflint-ruleset-aws
          ref: latest
          path: .tflint/
      - run: |
          cat > infra/.tflint.hcl <<EOF
          plugin "aws" {
            enabled = true
            version = "0.27.0"
            source  = "github.com/terraform-linters/tflint-ruleset-aws"
          }
          EOF
      - working-directory: infra
        run: tflint --init && tflint -f compact --recursive
```

## Acceptance Criteria

1. `cat infra/README.md` documents the bootstrap, apply, destroy, and troubleshooting procedures end-to-end.
2. `cat docs/architecture/aws-flow-v2.md` describes the implemented design accurately and supersedes `aws-flow.md`.
3. `cat docs/architecture/index.md` references `aws-flow-v2.md`.
4. `cat .github/workflows/infra-ci.yml` has all 7 jobs (`tofu-fmt`, `tofu-validate`, `tofu-test`, `helm-lint`, `helm-template-and-secret-scan`, `tflint`, plus the WP00 skeleton).
5. The CI workflow runs successfully on a sample PR (verified locally by pushing a test commit or with `act`).

## TDD Targets

- (none — pure docs/CI; the prior WPs already cover all 10 misfits)

## Execution constraints

- Docs and CI: only in `$WORKTREES_DIR/002-alternative-aws-infrastructure-WP07/`
- Do not merge to `main` until `spec-bridge-merge` after accept
- Do not instruct "verify on main" — verify in the WP worktree after dependency merges

## Notes for implementer

- The CI workflow depends on the `opentofu/setup-opentofu@v1` action; verify it exists and supports `tofu_version: 1.6.0` before relying on it.
- The `tflint` job installs the AWS ruleset plugin dynamically. The plugin version (`0.27.0`) should be pinned; check https://github.com/terraform-linters/tflint-ruleset-aws/releases for the current version.
- The `helm-template-and-secret-scan` job has 4 grep checks; each must pass. The 4th check (`grep -E 'kind: NetworkPolicy' | wc -l | grep -E '^[ ]*3$'`) verifies that exactly 3 NetworkPolicy resources render.
- The `aws-flow-v2.md` document should be **factually accurate** against the implemented WPs. If any WP's design differs from the plan, update the doc accordingly.