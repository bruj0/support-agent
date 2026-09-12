---
context_name: "AWS Identity & Secrets (per-env KMS, Secrets Manager, IAM, Pod Identity)"
version: "1"
subsystem: "infra/modules/identity"
created: "2026-09-12T15:00:00+00:00"
updated: "2026-09-12T15:00:00+00:00"
---

# AWS Identity & Secrets

The per-env security substrate: KMS CMK + Secrets Manager entries + scoped
IAM roles + EKS Pod Identity associations + GitHub Actions OIDC provider.
One set per environment; consumed by every other subsystem that needs to
authenticate to AWS APIs from in-cluster Pods or external CI.

## Language

**EnvCmk**:
The single per-environment KMS customer-managed key. `description =
"support-bot ${var.env} encryption"`, `deletion_window_in_days = 30`
(7–30 is the AWS-supported range; 30 is the strictest), `enable_key_rotation = true`.
Key policy restricts usage to the per-env IAM roles (External Secrets, ADOT,
ALB Controller) + the cluster envelope encryption role + the root account.
Aliased as `alias/support-bot-${var.env}-cmk`. Encrypts both Secrets Manager
entries and (via WP02's EKS `encryption_config`) Kubernetes secrets.
_Avoid_: kms_key, master_key, data_key
_Subsystems_: S3 Identity & Secrets
_Files_: infra/modules/identity/main.tf
_Relates to_: OpenAiSecret (encrypts), ChromaAuthSecret (encrypts),
ExternalSecretsRole (uses-via-Decrypt), EksCluster (envelope-encrypts-via, WP02)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP03.

**OpenAiSecret**:
The Secrets Manager entry holding the OpenAI API key.
`name = "support-bot/${var.env}/openai-api-key"`, `kms_key_id = aws_kms_key.env_cmk.arn`,
`recovery_window_in_days = 30`, `lifecycle { prevent_destroy = true }`.
The version (`aws_secretsmanager_secret_version.openai_v1`) is created from
`var.openai_api_key` which is `sensitive = true` so the value never appears
in plan output or logs.
_Avoid_: openai_key, llm_secret, api_token
_Subsystems_: S3 Identity & Secrets
_Files_: infra/modules/identity/main.tf
_Relates to_: EnvCmk (encrypted-by), ExternalSecretsRole (read-by),
HelmChart.ExternalSecret (consumed-by, additive)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP03.

**ChromaAuthSecret**:
The Secrets Manager entry holding the ChromaDB auth token. Same shape as
OpenAiSecret. Conditional on `var.chroma_auth_token != null` (ChromaDB is
optional in the dev environment where local Chroma can be used).
_Avoid_: chroma_token, chroma_creds, vector_db_token
_Subsystems_: S3 Identity & Secrets
_Files_: infra/modules/identity/main.tf
_Relates to_: EnvCmk (encrypted-by), ExternalSecretsRole (read-by),
HelmChart.ExternalSecret (consumed-by, additive)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP03.

**ExternalSecretsRole**:
The IAM role for the External Secrets Operator service account. Trust policy:
`pods.eks.amazonaws.com` (EKS Pod Identity) + `sts:TagSession` + tag condition
`aws:RequestTag/cluster = support-bot-${var.env}`. Inline policy: scoped to
the two secret ARNs + the CMK ARN with `secretsmanager:GetSecretValue`,
`secretsmanager:DescribeSecret`, `kms:Decrypt` — never `Resource = "*"`.
_Avoid_: eso_role, secrets_role, irsa_external_secrets
_Subsystems_: S3 Identity & Secrets, S2 Cluster & Compute
_Files_: infra/modules/identity/main.tf
_Relates to_: OpenAiSecret (reads), ChromaAuthSecret (reads),
EnvCmk (decrypts), ExternalSecretsPodIdentityAssociation (assumed-by)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP03.

**AdotRole**:
The IAM role for the AWS Distro for OpenTelemetry collector service account.
Scoped policy: `xray:PutTraceSegments`, `xray:PutTelemetryRecords`,
`logs:CreateLogGroup/Stream`, `logs:PutLogEvents` on the log group ARN prefix
`/aws/eks/support-bot-${var.env}/*`. Never `Resource = "*"`.
_Avoid_: adot_collector_role, observability_role, telemetry_role
_Subsystems_: S3 Identity & Secrets, S6 Observability & Policy
_Files_: infra/modules/identity/main.tf
_Relates to_: AdotPodIdentityAssociation (assumed-by)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP03.

**AlbControllerRole**:
The IAM role for the AWS Load Balancer Controller. Uses the AWS-published
policy verbatim with all `Resource` lists scoped to per-env ALB SG / WAFv2 /
ACM ARN patterns — never `"*"`. Trust policy: EKS Pod Identity.
_Avoid_: aws_lb_controller_role, ingress_role, alb_role
_Subsystems_: S3 Identity & Secrets, S4 Edge & Traffic
_Files_: infra/modules/identity/main.tf
_Relates to_: AlbControllerPodIdentityAssociation (assumed-by)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP03.

**GithubActionsRole**:
The IAM role for GitHub Actions CI/CD pipelines to push images to ECR.
Trust policy: `aws:TokenIssue` condition for the GitHub OIDC provider
(`token.actions.githubusercontent.com`), scoped to the project's
`org/repo:ref:refs/heads/main`. Inline policy: scoped `ecr:PutImage`,
`ecr:InitiateLayerUpload`, `ecr:UploadLayerPart`, `ecr:CompleteLayerUpload`,
`ecr:BatchCheckLayerAvailability` on the ECR repo ARN from WP05.
_Avoid_: gha_role, ci_role, ecr_push_role
_Subsystems_: S3 Identity & Secrets
_Files_: infra/modules/identity/main.tf
_Relates to_: GithubOidcProvider (assumed-via), EcrRepository (pushes-to, WP05)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP03.

**GithubOidcProvider**:
The `aws_iam_openid_connect_provider` for GitHub Actions. URL =
`https://token.actions.githubusercontent.com`, `client_id_list = ["sts.amazonaws.com"]`,
thumbprint fetched via `data.tls_certificate.github`.
_Avoid_: github_oidc, gha_provider, gh_oidc
_Subsystems_: S3 Identity & Secrets
_Files_: infra/modules/identity/main.tf
_Relates to_: GithubActionsRole (assumed-via)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP03.

**PodIdentityAssociation**:
The `aws_eks_pod_identity_association` linking a service account in the
cluster to an IAM role. Three of them: `external-secrets` (support-bot ns),
`adot-collector` (opentelemetry ns), `aws-load-balancer-controller` (kube-system ns).
_Avoid_: pod_identity, irsa_association, eks_pia
_Subsystems_: S3 Identity & Secrets
_Files_: infra/modules/identity/main.tf
_Relates to_: ExternalSecretsRole, AdotRole, AlbControllerRole (links)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP03.

**IdentityModule**:
The `modules/identity` module itself — accepts `env`, `eks_cluster_name`,
`eks_oidc_provider_arn`, `openai_api_key`, `chroma_auth_token`, `domain_suffix`
and produces an EnvCmk + 2 secrets + 4 roles + 1 OIDC provider + 3 Pod
Identity associations.
_Avoid_: identity_module, secrets_module, iam_module
_Subsystems_: S3 Identity & Secrets
_Files_: infra/modules/identity/{main,outputs,variables,versions}.tf
_Relates to_: ClusterModule (consumes-oidc-and-name-from, WP02)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP03.

## Relationships

- An **EnvCmk** encrypts **OpenAiSecret** + **ChromaAuthSecret**
- An **ExternalSecretsRole** reads both secrets via `kms:Decrypt`
- An **AdotRole** writes to CloudWatch Logs + X-Ray (per-env log group prefix)
- An **AlbControllerRole** manages per-env ALB SG / WAFv2 / ACM
- A **GithubActionsRole** pushes images to the per-env ECR repo
- A **GithubOidcProvider** is the trust anchor for **GithubActionsRole**
- Three **PodIdentityAssociation**s link in-cluster service accounts to
  ExternalSecretsRole / AdotRole / AlbControllerRole
- An **IdentityModule** produces all of the above

## Flagged Ambiguities

- "secret" has been used informally to mean both a **Secret** value (the
  literal key/token) and a **SecretEntry** (the Secrets Manager record).
  Resolved: use "secret value" for the literal; use "secret entry" or
  just **OpenAiSecret** / **ChromaAuthSecret** for the record.
- "IRSA" has been used to mean both IAM Roles for Service Accounts (the
  legacy OIDC-based mechanism) and EKS Pod Identity (the modern replacement
  this project uses). Resolved: this project uses EKS Pod Identity throughout;
  "IRSA" appears only in historical comments. Always prefer
  **PodIdentityAssociation** when referring to the new mechanism.
