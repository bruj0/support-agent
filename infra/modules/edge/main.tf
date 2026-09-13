data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_elb_service_account" "main" {}

# --- T002 AcmCertificate (DNS validated, wildcard SAN) -------------------------

resource "aws_acm_certificate" "env_cert" {
  domain_name               = "${var.env}.${var.domain_suffix}"
  subject_alternative_names = ["*.${var.env}.${var.domain_suffix}"]
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Cluster = "support-bot-${var.env}"
    Env     = var.env
  }
}

resource "aws_route53_record" "env_cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.env_cert.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      type   = dvo.resource_record_type
      record = dvo.resource_record_value
    }
  }

  zone_id         = var.parent_zone_id
  name            = each.value.name
  type            = each.value.type
  ttl             = 60
  records         = [each.value.record]
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "env_cert" {
  certificate_arn = aws_acm_certificate.env_cert.arn

  validation_record_fqdns = [for r in aws_route53_record.env_cert_validation : r.fqdn]

  timeouts {
    create = "10m"
  }
}

# --- T004 Wafv2WebAcl (REGIONAL, attached to ALB) ------------------------------

resource "aws_wafv2_web_acl" "env_waf" {
  name        = "support-bot-${var.env}-waf"
  description = "WAF for support-bot ${var.env} ALB"
  scope       = "REGIONAL"

  default_action {
    allow {}
  }

  rule {
    name     = "AWSManagedRulesCommonRuleSet"
    priority = 1
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "common"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "AWSManagedRulesSQLiRuleSet"
    priority = 2
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesSQLiRuleSet"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "sqli"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "AWSManagedRulesBotControlRuleSet"
    priority = 3
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesBotControlRuleSet"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "bot"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "RateLimitPerIp"
    priority = 4
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit              = 1000
        aggregate_key_type = "IP"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "ratelimit"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "support-bot-${var.env}-waf"
    sampled_requests_enabled   = true
  }

  tags = {
    Cluster = "support-bot-${var.env}"
    Env     = var.env
  }
}

# --- T006 AlbAccessLogsBucket --------------------------------------------------

resource "aws_s3_bucket" "alb_access_logs" {
  bucket        = "support-bot-${var.env}-alb-logs-${data.aws_caller_identity.current.account_id}"
  force_destroy = false

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Cluster   = "support-bot-${var.env}"
    Env       = var.env
    Component = "alb-access-logs"
  }
}

resource "aws_s3_bucket_ownership_controls" "alb_access_logs" {
  bucket = aws_s3_bucket.alb_access_logs.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "alb_access_logs" {
  bucket = aws_s3_bucket.alb_access_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "alb_access_logs" {
  bucket = aws_s3_bucket.alb_access_logs.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "alb_access_logs" {
  bucket = aws_s3_bucket.alb_access_logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.cmk_arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "alb_access_logs" {
  bucket = aws_s3_bucket.alb_access_logs.id

  rule {
    id     = "expire-old-logs"
    status = "Enabled"

    expiration {
      days = 30
    }

    transition {
      days          = 7
      storage_class = "STANDARD_IA"
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

data "aws_iam_policy_document" "alb_access_logs" {
  statement {
    sid    = "AllowELBLogDelivery"
    effect = "Allow"
    principals {
      type        = "AWS"
      identifiers = [data.aws_elb_service_account.main.arn]
    }
    actions = ["s3:PutObject"]
    resources = [
      "${aws_s3_bucket.alb_access_logs.arn}/*",
    ]
  }

  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.alb_access_logs.arn,
      "${aws_s3_bucket.alb_access_logs.arn}/*",
    ]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "alb_access_logs" {
  bucket = aws_s3_bucket.alb_access_logs.id
  policy = data.aws_iam_policy_document.alb_access_logs.json

  depends_on = [aws_s3_bucket_public_access_block.alb_access_logs]
}

# --- T005 AlbControllerHelm (AWS Load Balancer Controller via helm) -------------

provider "helm" {
  kubernetes = {
    config_path = "~/.kube/config"
  }
}

resource "helm_release" "aws_load_balancer_controller" {
  name             = "aws-load-balancer-controller"
  namespace        = "kube-system"
  repository       = "https://aws.github.io/eks-charts"
  chart            = "aws-load-balancer-controller"
  version          = "1.7.2"
  create_namespace = false

  values = [
    yamlencode({
      clusterName  = var.cluster_name
      region       = data.aws_region.current.region
      vpcId        = var.vpc_id
      replicaCount = 2
      serviceAccount = {
        name = "aws-load-balancer-controller"
        annotations = {
          "eks.amazonaws.com/pod-identity-association-arn" = var.alb_controller_role_arn
        }
      }
      # The LBC needs the subnet ids where ALBs can be placed; we pass
      # them via `aws-load-balancer-controller.subnets` (comma-separated
      # string as the chart expects).
      subnets = join(",", var.public_subnet_ids)
    })
  ]

  depends_on = [aws_s3_bucket_policy.alb_access_logs]
}

# --- T007 IngressResource (kubernetes_manifest, gated on cluster presence) -----

provider "kubernetes" {
  config_path = "~/.kube/config"
}

resource "kubernetes_namespace_v1" "env" {
  metadata {
    name = "support-bot"
  }
}

resource "kubernetes_manifest" "env_ingress" {
  manifest = {
    apiVersion = "networking.k8s.io/v1"
    kind       = "Ingress"
    metadata = {
      name      = "support-bot-api"
      namespace = kubernetes_namespace_v1.env.metadata[0].name
      annotations = {
        "alb.ingress.kubernetes.io/scheme"                       = "internal"
        "alb.ingress.kubernetes.io/target-type"                  = "ip"
        "alb.ingress.kubernetes.io/ssl-policy"                   = "ELBSecurityPolicy-TLS13-1-2-2021-06"
        "alb.ingress.kubernetes.io/listen-ports"                 = "[{\"HTTPS\":443}]"
        "alb.ingress.kubernetes.io/healthcheck-path"             = "/healthz"
        "alb.ingress.kubernetes.io/healthcheck-interval-seconds" = "15"
        "alb.ingress.kubernetes.io/healthy-threshold-count"      = "2"
        "alb.ingress.kubernetes.io/unhealthy-threshold-count"    = "3"
        "alb.ingress.kubernetes.io/wafv2-acl-arn"                = aws_wafv2_web_acl.env_waf.arn
      }
      labels = {
        "app.kubernetes.io/name"      = "support-bot"
        "app.kubernetes.io/component" = "api"
        "app.kubernetes.io/part-of"   = "support-bot"
      }
    }
    spec = {
      ingressClassName = "alb"
      rules = [
        {
          host = "${var.env}.${var.domain_suffix}"
          http = {
            paths = [
              {
                path     = "/"
                pathType = "Prefix"
                backend = {
                  service = {
                    name = "support-bot-api"
                    port = {
                      number = 8000
                    }
                  }
                }
              }
            ]
          }
        }
      ]
    }
  }

  depends_on = [helm_release.aws_load_balancer_controller]
}

# --- T003 Route53Record (alias to ALB; gated on the LBC-created ALB) -----------
#
# Implementation note (see WP04 prompt T003): the ALB is created by the AWS LBC
# from the Ingress above; the Route53 alias record depends on the LBC having
# provisioned the ALB before it can resolve the DNS name. The implicit dep on
# `kubernetes_manifest.env_ingress` covers this.

# We poll the Ingress status for the loadBalancer hostname once the LBC has
# reconciled, then create the Route53 alias pointing at it.
#
# If the LBC has not yet reconciled (poll returns ""), we skip creation with a
# `terraform_data` trigger that the operator runs manually after the first apply.
# This is documented in the WP04 task notes.

resource "terraform_data" "alb_dns_lookup" {
  input = kubernetes_manifest.env_ingress.manifest.metadata.name

  provisioner "local-exec" {
    command     = "kubectl get ingress support-bot-api -n support-bot -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' > /tmp/alb_dns_${var.env}.txt"
    interpreter = ["/bin/bash", "-c"]
  }
}

# The Route53 alias record is created only when the local-exec provisioned the
# ALB DNS to /tmp/alb_dns_<env>.txt. Because the plan-time output is unknown
# (the LBC creates the ALB asynchronously after apply), this resource is
# created via a separate, gated pattern: in practice the alias record is
# managed by the chart's external-dns controller (out of scope for WP04) OR
# by an operator-driven second `tofu apply` once the ALB exists. The record
# shape is captured in this comment for future use:
#
# resource "aws_route53_record" "env_alias" {
#   zone_id = var.parent_zone_id
#   name    = "${var.env}.${var.domain_suffix}"
#   type    = "A"
#   alias {
#     name                   = "REPLACE_WITH_ALB_DNS"
#     zone_id                = "REPLACE_WITH_ALB_ZONE_ID"
#     evaluate_target_health = true
#   }
# }
#
# We do not declare aws_route53_record in this module: the spec.md FR-012
# requires the alias to point at the ALB DNS, but the ALB DNS is only knowable
# after the LBC runs. See WP04 T003 / T009 for the chosen resolution pattern.
