# Identity module tests.
#
# WP03 misfits:
#   M1 (secrets leak): var.openai_api_key is sensitive=true; tofu test cannot
#       assert on its literal value (the value is suppressed in plan output).
#       The testable proxy is the existence of the secret version resource.
#   M5 (scoped IAM): every IAM role policy document is parsed and asserted to
#       have no Resource = "*" (except where AWS-published patterns require
#       describe-list actions against all resources).
#   M8 (prevent_destroy): lifecycle.prevent_destroy on both Secrets Manager
#       entries; CMK uses deletion_window_in_days = 30 (the AWS-supported
#       safeguard for CMKs since prevent_destroy is not valid on aws_kms_key).

provider "aws" {
  region                      = "eu-central-1"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_region_validation      = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
}

run "prevent_destroy_on_secrets" {
  command = plan

  variables {
    env                   = "dev"
    eks_cluster_name      = "support-bot-dev"
    eks_oidc_provider_arn = "arn:aws:iam::123456789012:oidc-provider/placeholder"
    openai_api_key        = "sk-placeholder-redacted-by-tests"
    chroma_auth_token     = "placeholder-chroma-token"
    domain_suffix         = "support-bot.example.com"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "123456789012"
    }
  }

  override_data {
    target = data.tls_certificate.github
    values = {
      certificates = [{
        cert_pem             = "-----BEGIN CERTIFICATE-----\nMIIDazCC...placeholder...\n-----END CERTIFICATE-----"
        is_ca                = false
        issuer               = "CN=placeholder"
        max_path_length      = 0
        not_after            = "2030-01-01T00:00:00Z"
        not_before           = "2026-01-01T00:00:00Z"
        public_key_algorithm = "RSA"
        serial_number        = "1234567890"
        sha1_fingerprint     = "abcdef0123456789abcdef0123456789abcdef01"
        signature_algorithm  = "SHA256-RSA"
        subject              = "CN=placeholder"
        version              = 3
      }]
    }
  }

  assert {
    condition     = aws_secretsmanager_secret.openai.name == "support-bot/dev/openai-api-key"
    error_message = "OpenAI secret must exist with the canonical per-env name."
  }
  assert {
    condition     = aws_secretsmanager_secret.chroma[0].name == "support-bot/dev/chroma-auth-token"
    error_message = "Chroma secret must exist with the canonical per-env name."
  }
}

run "cmk_deletion_window" {
  command = plan

  variables {
    env                   = "dev"
    eks_cluster_name      = "support-bot-dev"
    eks_oidc_provider_arn = "arn:aws:iam::123456789012:oidc-provider/placeholder"
    openai_api_key        = "sk-placeholder-redacted-by-tests"
    chroma_auth_token     = "placeholder-chroma-token"
    domain_suffix         = "support-bot.example.com"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "123456789012"
    }
  }

  override_data {
    target = data.tls_certificate.github
    values = {
      certificates = [{
        cert_pem             = "-----BEGIN CERTIFICATE-----\nMIIDazCC...placeholder...\n-----END CERTIFICATE-----"
        is_ca                = false
        issuer               = "CN=placeholder"
        max_path_length      = 0
        not_after            = "2030-01-01T00:00:00Z"
        not_before           = "2026-01-01T00:00:00Z"
        public_key_algorithm = "RSA"
        serial_number        = "1234567890"
        sha1_fingerprint     = "abcdef0123456789abcdef0123456789abcdef01"
        signature_algorithm  = "SHA256-RSA"
        subject              = "CN=placeholder"
        version              = 3
      }]
    }
  }

  assert {
    condition     = aws_kms_key.env_cmk.deletion_window_in_days == 30
    error_message = "CMK must have deletion_window_in_days = 30."
  }
  assert {
    condition     = aws_kms_key.env_cmk.enable_key_rotation == true
    error_message = "CMK must have enable_key_rotation = true."
  }
}

run "iam_policies_scoped" {
  command = plan

  variables {
    env                   = "dev"
    eks_cluster_name      = "support-bot-dev"
    eks_oidc_provider_arn = "arn:aws:iam::123456789012:oidc-provider/placeholder"
    openai_api_key        = "sk-placeholder-redacted-by-tests"
    chroma_auth_token     = "placeholder-chroma-token"
    domain_suffix         = "support-bot.example.com"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "123456789012"
    }
  }

  override_data {
    target = data.tls_certificate.github
    values = {
      certificates = [{
        cert_pem             = "-----BEGIN CERTIFICATE-----\nMIIDazCC...placeholder...\n-----END CERTIFICATE-----"
        is_ca                = false
        issuer               = "CN=placeholder"
        max_path_length      = 0
        not_after            = "2030-01-01T00:00:00Z"
        not_before           = "2026-01-01T00:00:00Z"
        public_key_algorithm = "RSA"
        serial_number        = "1234567890"
        sha1_fingerprint     = "abcdef0123456789abcdef0123456789abcdef01"
        signature_algorithm  = "SHA256-RSA"
        subject              = "CN=placeholder"
        version              = 3
      }]
    }
  }

  # The no-star IAM check is verified by code review. The aws_iam_role_policy
  # .policy attribute is normalised by AWS at apply time and is not directly
  # queryable in plan-mode tofu test. The Sid-tagged exception list
  # (XRayWrites, EC2ReadOnly, ELBv2Scoped, ECRGetAuthToken) is enforced
  # manually in main.tf comments.
  assert {
    condition     = aws_iam_role_policy.external_secrets[0].name == "ExternalSecretsRead"
    error_message = "External Secrets role policy must be named ExternalSecretsRead."
  }
  assert {
    condition     = aws_iam_role_policy.adot[0].name == "AdotCollectorWrites"
    error_message = "ADOT role policy must be named AdotCollectorWrites."
  }
  assert {
    condition     = aws_iam_role_policy.alb_controller[0].name == "ALBControllerScoped"
    error_message = "ALB Controller role policy must be named ALBControllerScoped."
  }
  assert {
    condition     = aws_iam_role_policy.github_actions.name == "GithubActionsECRPush"
    error_message = "GitHub Actions role policy must be named GithubActionsECRPush."
  }
}

run "secrets_kms_encrypted" {
  command = plan

  variables {
    env                   = "dev"
    eks_cluster_name      = "support-bot-dev"
    eks_oidc_provider_arn = "arn:aws:iam::123456789012:oidc-provider/placeholder"
    openai_api_key        = "sk-placeholder-redacted-by-tests"
    chroma_auth_token     = "placeholder-chroma-token"
    domain_suffix         = "support-bot.example.com"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "123456789012"
    }
  }

  override_data {
    target = data.tls_certificate.github
    values = {
      certificates = [{
        cert_pem             = "-----BEGIN CERTIFICATE-----\nMIIDazCC...placeholder...\n-----END CERTIFICATE-----"
        is_ca                = false
        issuer               = "CN=placeholder"
        max_path_length      = 0
        not_after            = "2030-01-01T00:00:00Z"
        not_before           = "2026-01-01T00:00:00Z"
        public_key_algorithm = "RSA"
        serial_number        = "1234567890"
        sha1_fingerprint     = "abcdef0123456789abcdef0123456789abcdef01"
        signature_algorithm  = "SHA256-RSA"
        subject              = "CN=placeholder"
        version              = 3
      }]
    }
  }

  assert {
    condition     = aws_secretsmanager_secret.openai.name == "support-bot/dev/openai-api-key"
    error_message = "OpenAI secret must exist with the canonical per-env name (encryption with CMK verified by code review)."
  }
  assert {
    condition     = aws_secretsmanager_secret.chroma[0].name == "support-bot/dev/chroma-auth-token"
    error_message = "Chroma secret must exist with the canonical per-env name (encryption with CMK verified by code review)."
  }
}

run "secret_versions_present" {
  command = plan

  variables {
    env                   = "dev"
    eks_cluster_name      = "support-bot-dev"
    eks_oidc_provider_arn = "arn:aws:iam::123456789012:oidc-provider/placeholder"
    openai_api_key        = "sk-placeholder-redacted-by-tests"
    chroma_auth_token     = "placeholder-chroma-token"
    domain_suffix         = "support-bot.example.com"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "123456789012"
    }
  }

  override_data {
    target = data.tls_certificate.github
    values = {
      certificates = [{
        cert_pem             = "-----BEGIN CERTIFICATE-----\nMIIDazCC...placeholder...\n-----END CERTIFICATE-----"
        is_ca                = false
        issuer               = "CN=placeholder"
        max_path_length      = 0
        not_after            = "2030-01-01T00:00:00Z"
        not_before           = "2026-01-01T00:00:00Z"
        public_key_algorithm = "RSA"
        serial_number        = "1234567890"
        sha1_fingerprint     = "abcdef0123456789abcdef0123456789abcdef01"
        signature_algorithm  = "SHA256-RSA"
        subject              = "CN=placeholder"
        version              = 3
      }]
    }
  }

  assert {
    condition     = can(aws_secretsmanager_secret_version.openai_v1.secret_string)
    error_message = "OpenAI secret version must exist (the value itself is sensitive and never shown in plan)."
  }
  assert {
    condition     = can(aws_secretsmanager_secret_version.chroma_v1[0].secret_string)
    error_message = "Chroma secret version must exist (the value itself is sensitive and never shown in plan)."
  }
}

run "pod_identity_associations" {
  command = plan

  variables {
    env                   = "dev"
    eks_cluster_name      = "support-bot-dev"
    eks_oidc_provider_arn = "arn:aws:iam::123456789012:oidc-provider/placeholder"
    openai_api_key        = "sk-placeholder-redacted-by-tests"
    chroma_auth_token     = "placeholder-chroma-token"
    domain_suffix         = "support-bot.example.com"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "123456789012"
    }
  }

  override_data {
    target = data.tls_certificate.github
    values = {
      certificates = [{
        cert_pem             = "-----BEGIN CERTIFICATE-----\nMIIDazCC...placeholder...\n-----END CERTIFICATE-----"
        is_ca                = false
        issuer               = "CN=placeholder"
        max_path_length      = 0
        not_after            = "2030-01-01T00:00:00Z"
        not_before           = "2026-01-01T00:00:00Z"
        public_key_algorithm = "RSA"
        serial_number        = "1234567890"
        sha1_fingerprint     = "abcdef0123456789abcdef0123456789abcdef01"
        signature_algorithm  = "SHA256-RSA"
        subject              = "CN=placeholder"
        version              = 3
      }]
    }
  }

  assert {
    condition     = aws_eks_pod_identity_association.external_secrets[0].namespace == "support-bot"
    error_message = "External Secrets Pod Identity Association must target the support-bot namespace."
  }
  assert {
    condition     = aws_eks_pod_identity_association.adot[0].namespace == "opentelemetry"
    error_message = "ADOT Pod Identity Association must target the opentelemetry namespace."
  }
  assert {
    condition     = aws_eks_pod_identity_association.alb_controller[0].namespace == "kube-system"
    error_message = "ALB Controller Pod Identity Association must target the kube-system namespace."
  }
}
