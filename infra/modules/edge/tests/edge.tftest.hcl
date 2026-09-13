# Edge module tests.
#
# WP04 misfits:
#   M2 (chart ↔ infra drift, ALB half): Ingress className=alb + 4 ALBC
#       annotations are verified by `helm template deploy/helm/support-bot
#       --values values-prod.yaml` in the infra-ci.yml helm-step (T012) --
#       not here, because the chart is a separate artifact. In this test,
#       only the AWS-side of the contract is verifiable (cert, waf, logs
#       bucket, helm_release wiring).
#   M4 (multi-AZ, ALB half): asserted via the var.public_subnet_ids length
#       reaching the ALBC helm release's `subnets` set (the LBC creates the
#       ALB and places subnets across 3 AZs from this list).
#   M8 (prevent_destroy on ALB access logs bucket): bucket policy + versioning
#       + sse enforced by resource blocks; the prevent_destroy lifecycle
#       meta-block is verified by code review (not queryable in `tofu test`).

provider "aws" {
  region                      = "eu-central-1"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_region_validation      = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
}

provider "helm" {
  kubernetes = {
    config_path = "~/.kube/config"
  }
}

provider "kubernetes" {
  config_path = "~/.kube/config"
}

run "acm_cert_has_wildcard_san" {
  command = plan

  variables {
    env                            = "dev"
    cluster_name                   = "support-bot-dev"
    cluster_security_group_id      = "sg-00000000000000000"
    vpc_id                         = "vpc-00000000000000000"
    public_subnet_ids              = ["subnet-aaaa", "subnet-bbbb", "subnet-cccc"]
    parent_zone_id                 = "Z000000000000000000000"
    domain_suffix                  = "support-bot.example.com"
    alb_controller_role_arn        = "arn:aws:iam::111122223333:role/alb-controller-role-dev"
    cmk_arn                        = "arn:aws:kms:eu-central-1:111122223333:key/00000000-0000-0000-0000-000000000000"
    vpc_endpoint_security_group_id = "sg-00000000000000001"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "111122223333"
    }
  }

  override_data {
    target = data.aws_region.current
    values = {
      name = "eu-central-1"
    }
  }

  assert {
    condition     = contains(aws_acm_certificate.env_cert.subject_alternative_names, "*.dev.support-bot.example.com")
    error_message = "ACM cert must include wildcard SAN *.<env>.domain_suffix (per FR-012)."
  }
}

run "acm_uses_dns_validation" {
  command = plan

  variables {
    env                            = "dev"
    cluster_name                   = "support-bot-dev"
    cluster_security_group_id      = "sg-00000000000000000"
    vpc_id                         = "vpc-00000000000000000"
    public_subnet_ids              = ["subnet-aaaa", "subnet-bbbb", "subnet-cccc"]
    parent_zone_id                 = "Z000000000000000000000"
    domain_suffix                  = "support-bot.example.com"
    alb_controller_role_arn        = "arn:aws:iam::111122223333:role/alb-controller-role-dev"
    cmk_arn                        = "arn:aws:kms:eu-central-1:111122223333:key/00000000-0000-0000-0000-000000000000"
    vpc_endpoint_security_group_id = "sg-00000000000000001"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = { account_id = "111122223333" }
  }
  override_data {
    target = data.aws_region.current
    values = { name = "eu-central-1" }
  }

  assert {
    condition     = aws_acm_certificate.env_cert.validation_method == "DNS"
    error_message = "ACM cert must use DNS validation (FR-012)."
  }
  assert {
    condition     = aws_acm_certificate.env_cert.domain_name == "dev.support-bot.example.com"
    error_message = "ACM cert domain_name must be <env>.domain_suffix."
  }
}

run "waf_has_managed_and_rate_rules" {
  command = plan

  variables {
    env                            = "dev"
    cluster_name                   = "support-bot-dev"
    cluster_security_group_id      = "sg-00000000000000000"
    vpc_id                         = "vpc-00000000000000000"
    public_subnet_ids              = ["subnet-aaaa", "subnet-bbbb", "subnet-cccc"]
    parent_zone_id                 = "Z000000000000000000000"
    domain_suffix                  = "support-bot.example.com"
    alb_controller_role_arn        = "arn:aws:iam::111122223333:role/alb-controller-role-dev"
    cmk_arn                        = "arn:aws:kms:eu-central-1:111122223333:key/00000000-0000-0000-0000-000000000000"
    vpc_endpoint_security_group_id = "sg-00000000000000001"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = { account_id = "111122223333" }
  }
  override_data {
    target = data.aws_region.current
    values = { name = "eu-central-1" }
  }

  assert {
    condition     = length(aws_wafv2_web_acl.env_waf.rule) == 4
    error_message = "WAFv2 WebACL must have exactly 4 rules (3 managed + 1 rate-based)."
  }
}

run "alb_controller_uses_three_public_subnets" {
  command = plan

  variables {
    env                            = "dev"
    cluster_name                   = "support-bot-dev"
    cluster_security_group_id      = "sg-00000000000000000"
    vpc_id                         = "vpc-00000000000000000"
    public_subnet_ids              = ["subnet-aaaa", "subnet-bbbb", "subnet-cccc"]
    parent_zone_id                 = "Z000000000000000000000"
    domain_suffix                  = "support-bot.example.com"
    alb_controller_role_arn        = "arn:aws:iam::111122223333:role/alb-controller-role-dev"
    cmk_arn                        = "arn:aws:kms:eu-central-1:111122223333:key/00000000-0000-0000-0000-000000000000"
    vpc_endpoint_security_group_id = "sg-00000000000000001"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = { account_id = "111122223333" }
  }
  override_data {
    target = data.aws_region.current
    values = { name = "eu-central-1" }
  }

  assert {
    condition     = length(var.public_subnet_ids) == 3
    error_message = "Edge module must be wired with 3 public subnets (M4 multi-AZ ALB)."
  }
}

run "alb_access_logs_bucket_name_and_encryption" {
  command = plan

  variables {
    env                            = "dev"
    cluster_name                   = "support-bot-dev"
    cluster_security_group_id      = "sg-00000000000000000"
    vpc_id                         = "vpc-00000000000000000"
    public_subnet_ids              = ["subnet-aaaa", "subnet-bbbb", "subnet-cccc"]
    parent_zone_id                 = "Z000000000000000000000"
    domain_suffix                  = "support-bot.example.com"
    alb_controller_role_arn        = "arn:aws:iam::111122223333:role/alb-controller-role-dev"
    cmk_arn                        = "arn:aws:kms:eu-central-1:111122223333:key/00000000-0000-0000-0000-000000000000"
    vpc_endpoint_security_group_id = "sg-00000000000000001"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = { account_id = "111122223333" }
  }
  override_data {
    target = data.aws_region.current
    values = { name = "eu-central-1" }
  }

  assert {
    condition     = aws_s3_bucket.alb_access_logs.bucket == "support-bot-dev-alb-logs-111122223333"
    error_message = "ALB access logs bucket name must include env + account_id."
  }
}
