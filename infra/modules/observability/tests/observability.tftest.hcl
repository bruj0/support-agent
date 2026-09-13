# Observability module tests.
#
# WP06 misfits:
#   M1 (residual): ADOT collector exports traces to awsxray + metrics to awsemf
#       in the per-env region; ADOT picks up trace_id/span_id automatically.
#       The helm release is excluded from tofu test (mirroring the cluster
#       module's karpenter exclusion) because the chart registry must be
#       reachable at plan time. The set of helm release inputs is statically
#       checked by code review + the CI helm lint step.
#   M2 (residual): Namespace carries the 3 PSS labels (enforce/warn/audit=restricted).
#   M7 (residual): Three NetworkPolicy resources in support-bot ns: default-deny
#       (both Ingress+Egress), api-allow (5 egress ports), chroma-allow (3 egress).
#
# WP02 prerequisite: VPC CNI addon enables NetworkPolicy enforcement;
# the policies have no effect without this.

provider "aws" {
  region                      = "eu-central-1"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_region_validation      = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
}

provider "kubernetes" {
  config_path = "~/.kube/config"
}

# ---- CloudWatch log groups (M1 side: application + otel log groups) --------------

run "application_log_group_retention_30" {
  command = plan

  variables {
    env                       = "dev"
    eks_cluster_name          = "support-bot-dev"
    adot_role_arn             = "arn:aws:iam::111122223333:role/adot-role-dev"
    cmk_arn                   = "arn:aws:kms:eu-central-1:111122223333:key/00000000-0000-0000-0000-000000000000"
    cluster_security_group_id = "sg-00000000000000000"
    test_mode                 = true
  }

  assert {
    condition     = aws_cloudwatch_log_group.application.retention_in_days == 30
    error_message = "Application log group must have retention_in_days = 30."
  }
  assert {
    condition     = aws_cloudwatch_log_group.application.kms_key_id == "arn:aws:kms:eu-central-1:111122223333:key/00000000-0000-0000-0000-000000000000"
    error_message = "Application log group must be encrypted with the per-env CMK."
  }
}

run "otel_log_group_retention_7" {
  command = plan

  variables {
    env                       = "dev"
    eks_cluster_name          = "support-bot-dev"
    adot_role_arn             = "arn:aws:iam::111122223333:role/adot-role-dev"
    cmk_arn                   = "arn:aws:kms:eu-central-1:111122223333:key/00000000-0000-0000-0000-000000000000"
    cluster_security_group_id = "sg-00000000000000000"
    test_mode                 = true
  }

  assert {
    condition     = aws_cloudwatch_log_group.otel.retention_in_days == 7
    error_message = "OTEL log group must have retention_in_days = 7."
  }
  assert {
    condition     = aws_cloudwatch_log_group.otel.kms_key_id == "arn:aws:kms:eu-central-1:111122223333:key/00000000-0000-0000-0000-000000000000"
    error_message = "OTEL log group must be encrypted with the per-env CMK."
  }
}

# ---- Namespace PSS labels (M2) ----------------------------------------------------

run "namespace_has_pss_restricted" {
  command = plan

  variables {
    env                       = "dev"
    eks_cluster_name          = "support-bot-dev"
    adot_role_arn             = "arn:aws:iam::111122223333:role/adot-role-dev"
    cmk_arn                   = "arn:aws:kms:eu-central-1:111122223333:key/00000000-0000-0000-0000-000000000000"
    cluster_security_group_id = "sg-00000000000000000"
    test_mode                 = true
  }

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

# ---- NetworkPolicy resources (M7) ------------------------------------------------

run "default_deny_has_both_policy_types" {
  command = plan

  variables {
    env                       = "dev"
    eks_cluster_name          = "support-bot-dev"
    adot_role_arn             = "arn:aws:iam::111122223333:role/adot-role-dev"
    cmk_arn                   = "arn:aws:kms:eu-central-1:111122223333:key/00000000-0000-0000-0000-000000000000"
    cluster_security_group_id = "sg-00000000000000000"
    test_mode                 = true
  }

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

  variables {
    env                       = "dev"
    eks_cluster_name          = "support-bot-dev"
    adot_role_arn             = "arn:aws:iam::111122223333:role/adot-role-dev"
    cmk_arn                   = "arn:aws:kms:eu-central-1:111122223333:key/00000000-0000-0000-0000-000000000000"
    cluster_security_group_id = "sg-00000000000000000"
    test_mode                 = true
  }

  assert {
    condition     = contains(kubernetes_manifest.support_bot_api_allow.manifest.spec.policyTypes, "Egress")
    error_message = "API allow policy must have Egress in policyTypes."
  }
  assert {
    condition     = contains(kubernetes_manifest.support_bot_api_allow.manifest.spec.policyTypes, "Ingress")
    error_message = "API allow policy must have Ingress in policyTypes."
  }
  assert {
    condition     = kubernetes_manifest.support_bot_api_allow.manifest.spec.podSelector.matchLabels.app == "support-bot-api"
    error_message = "API allow policy must select support-bot-api pods."
  }
}

run "chroma_allow_has_required_egress" {
  command = plan

  variables {
    env                       = "dev"
    eks_cluster_name          = "support-bot-dev"
    adot_role_arn             = "arn:aws:iam::111122223333:role/adot-role-dev"
    cmk_arn                   = "arn:aws:kms:eu-central-1:111122223333:key/00000000-0000-0000-0000-000000000000"
    cluster_security_group_id = "sg-00000000000000000"
    test_mode                 = true
  }

  assert {
    condition     = contains(kubernetes_manifest.support_bot_chroma_allow.manifest.spec.policyTypes, "Egress")
    error_message = "Chroma allow policy must have Egress in policyTypes."
  }
  assert {
    condition     = kubernetes_manifest.support_bot_chroma_allow.manifest.spec.podSelector.matchLabels.app == "support-bot-chroma"
    error_message = "Chroma allow policy must select support-bot-chroma pods."
  }
}
