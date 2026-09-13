# ----------------------------------------------------------------------------
# T002 (part A): Per-env KMS CMK + alias
# ----------------------------------------------------------------------------
resource "aws_kms_key" "env_cmk" {
  description             = "support-bot ${var.env} encryption"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "RootAccountFullAccess"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
        }
        Action   = "kms:*"
        Resource = "*"
      },
      {
        Sid    = "AllowEnvelopeEncryptionForCluster"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/aws-service-role/eks.amazonaws.com/AWSServiceRoleForEKS"
        }
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:DescribeKey",
          "kms:CreateGrant",
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:EncryptionContext:cluster" = "support-bot-${var.env}"
          }
        }
      },
    ]
  })

  tags = {
    Name    = "support-bot-${var.env}-cmk"
    Cluster = "support-bot-${var.env}"
  }
}

data "aws_caller_identity" "current" {}

resource "aws_kms_alias" "env_cmk" {
  name          = "alias/support-bot-${var.env}-cmk"
  target_key_id = aws_kms_key.env_cmk.key_id
}

# ----------------------------------------------------------------------------
# T003 (part B): OpenAI secret + version
# ----------------------------------------------------------------------------
resource "aws_secretsmanager_secret" "openai" {
  name                    = "support-bot/${var.env}/openai-api-key"
  kms_key_id              = aws_kms_key.env_cmk.arn
  recovery_window_in_days = 30

  # prevent_destroy enforces M8. The tofu test cannot assert on the
  # lifecycle meta-block directly; code review confirms its presence.
  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name    = "support-bot-${var.env}-openai"
    Cluster = "support-bot-${var.env}"
  }
}

resource "aws_secretsmanager_secret_version" "openai_v1" {
  secret_id     = aws_secretsmanager_secret.openai.id
  secret_string = var.openai_api_key
}

# ----------------------------------------------------------------------------
# T004 (part C): Chroma secret + version (conditional)
# ----------------------------------------------------------------------------
resource "aws_secretsmanager_secret" "chroma" {
  count                   = var.chroma_auth_token != null ? 1 : 0
  name                    = "support-bot/${var.env}/chroma-auth-token"
  kms_key_id              = aws_kms_key.env_cmk.arn
  recovery_window_in_days = 30

  # See note on aws_secretsmanager_secret.openai above (prevent_destroy + code review).
  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name    = "support-bot-${var.env}-chroma"
    Cluster = "support-bot-${var.env}"
  }
}

resource "aws_secretsmanager_secret_version" "chroma_v1" {
  count         = var.chroma_auth_token != null ? 1 : 0
  secret_id     = aws_secretsmanager_secret.chroma[0].id
  secret_string = var.chroma_auth_token
}

# ----------------------------------------------------------------------------
# T005 (part D): External Secrets Operator IAM role
# ----------------------------------------------------------------------------
data "aws_iam_policy_document" "external_secrets_assume_role" {
  count = var.eks_oidc_provider_arn != null ? 1 : 0
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/cluster"
      values   = ["support-bot-${var.env}"]
    }
  }
}

resource "aws_iam_role" "external_secrets" {
  count              = var.eks_oidc_provider_arn != null ? 1 : 0
  name               = "external-secrets-operator-${var.env}"
  assume_role_policy = data.aws_iam_policy_document.external_secrets_assume_role[0].json
  tags = {
    Name    = "external-secrets-operator-${var.env}"
    Cluster = "support-bot-${var.env}"
  }
}

data "aws_iam_policy_document" "external_secrets_policy" {
  count = var.eks_oidc_provider_arn != null ? 1 : 0
  statement {
    sid    = "ReadSecrets"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
    ]
    resources = compact([
      aws_secretsmanager_secret.openai.arn,
      try(aws_secretsmanager_secret.chroma[0].arn, null),
    ])
  }
  statement {
    sid    = "DecryptWithEnvCmk"
    effect = "Allow"
    actions = [
      "kms:Decrypt",
      "kms:DescribeKey",
    ]
    resources = [aws_kms_key.env_cmk.arn]
  }
}

resource "aws_iam_role_policy" "external_secrets" {
  count  = var.eks_oidc_provider_arn != null ? 1 : 0
  name   = "ExternalSecretsRead"
  role   = aws_iam_role.external_secrets[0].id
  policy = data.aws_iam_policy_document.external_secrets_policy[0].json
}

# ----------------------------------------------------------------------------
# T006 (part E): ADOT Collector IAM role
# ----------------------------------------------------------------------------
data "aws_iam_policy_document" "adot_assume_role" {
  count = var.eks_oidc_provider_arn != null ? 1 : 0
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/cluster"
      values   = ["support-bot-${var.env}"]
    }
  }
}

resource "aws_iam_role" "adot" {
  count              = var.eks_oidc_provider_arn != null ? 1 : 0
  name               = "adot-collector-${var.env}"
  assume_role_policy = data.aws_iam_policy_document.adot_assume_role[0].json
  tags = {
    Name    = "adot-collector-${var.env}"
    Cluster = "support-bot-${var.env}"
  }
}

data "aws_iam_policy_document" "adot_policy" {
  count = var.eks_oidc_provider_arn != null ? 1 : 0
  statement {
    sid    = "XRayWrites"
    effect = "Allow"
    actions = [
      "xray:PutTraceSegments",
      "xray:PutTelemetryRecords",
    ]
    resources = ["*"]
  }
  statement {
    sid    = "CloudWatchLogsWrites"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      "arn:aws:logs:eu-central-1:${data.aws_caller_identity.current.account_id}:log-group:/aws/eks/support-bot-${var.env}/*",
      "arn:aws:logs:eu-central-1:${data.aws_caller_identity.current.account_id}:log-stream:/aws/eks/support-bot-${var.env}/*",
    ]
  }
}

resource "aws_iam_role_policy" "adot" {
  count  = var.eks_oidc_provider_arn != null ? 1 : 0
  name   = "AdotCollectorWrites"
  role   = aws_iam_role.adot[0].id
  policy = data.aws_iam_policy_document.adot_policy[0].json
}

# ----------------------------------------------------------------------------
# T007 (part F): AWS Load Balancer Controller IAM role
# ----------------------------------------------------------------------------
data "aws_iam_policy_document" "alb_controller_assume_role" {
  count = var.eks_oidc_provider_arn != null ? 1 : 0
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/cluster"
      values   = ["support-bot-${var.env}"]
    }
  }
}

resource "aws_iam_role" "alb_controller" {
  count              = var.eks_oidc_provider_arn != null ? 1 : 0
  name               = "aws-load-balancer-controller-${var.env}"
  assume_role_policy = data.aws_iam_policy_document.alb_controller_assume_role[0].json
  tags = {
    Name    = "aws-load-balancer-controller-${var.env}"
    Cluster = "support-bot-${var.env}"
  }
}

# AWS-published ALB Controller policy verbatim with Resource lists scoped
# to per-env ARN patterns. Source: https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/deploy/installation/
data "aws_iam_policy_document" "alb_controller_policy" {
  count = var.eks_oidc_provider_arn != null ? 1 : 0
  statement {
    sid    = "EC2ReadOnly"
    effect = "Allow"
    actions = [
      "ec2:DescribeAccountAttributes",
      "ec2:DescribeAddresses",
      "ec2:DescribeAvailabilityZones",
      "ec2:DescribeInternetGateways",
      "ec2:DescribeVpcs",
      "ec2:DescribeVpcPeeringConnections",
      "ec2:DescribeSubnets",
      "ec2:DescribeSecurityGroups",
      "ec2:DescribeInstances",
      "ec2:DescribeNetworkInterfaces",
      "ec2:DescribeTags",
      "ec2:DescribeRouteTables",
      "ec2:DescribeListeners",
      "ec2:DescribeLoadBalancers",
      "ec2:DescribeLoadBalancerAttributes",
      "ec2:DescribeTargetGroups",
      "ec2:DescribeTargetGroupAttributes",
      "ec2:DescribeTargetHealth",
    ]
    resources = ["*"]
  }
  statement {
    sid    = "ACMCertsScoped"
    effect = "Allow"
    actions = [
      "acm:DescribeCertificate",
      "acm:ListCertificates",
    ]
    resources = [
      "arn:aws:acm:eu-central-1:${data.aws_caller_identity.current.account_id}:certificate/*",
    ]
  }
  statement {
    sid    = "WAFv2Scoped"
    effect = "Allow"
    actions = [
      "wafv2:AssociateWebACL",
      "wafv2:DisassociateWebACL",
      "wafv2:GetWebACL",
      "wafv2:GetWebACLForResource",
      "wafv2:ListWebACLs",
      "wafv2:ListResourcesForWebACL",
    ]
    resources = [
      "arn:aws:wafv2:eu-central-1:${data.aws_caller_identity.current.account_id}:regional/webacl/*/*",
      "arn:aws:wafv2:eu-central-1:${data.aws_caller_identity.current.account_id}:regional/loadbalancer/*/*",
    ]
  }
  statement {
    sid    = "ELBv2Scoped"
    effect = "Allow"
    actions = [
      "elasticloadbalancing:DescribeLoadBalancers",
      "elasticloadbalancing:DescribeTargetGroups",
      "elasticloadbalancing:DescribeTargetGroupAttributes",
      "elasticloadbalancing:DescribeTargetHealth",
      "elasticloadbalancing:DescribeListeners",
      "elasticloadbalancing:DescribeListenerCertificates",
      "elasticloadbalancing:DescribeRules",
      "elasticloadbalancing:DescribeTags",
      "elasticloadbalancing:DescribeTrustStores",
    ]
    resources = ["*"]
  }
  statement {
    sid    = "ELBv2TagScoped"
    effect = "Allow"
    actions = [
      "elasticloadbalancing:AddTags",
      "elasticloadbalancing:RemoveTags",
    ]
    resources = [
      "arn:aws:elasticloadbalancing:eu-central-1:${data.aws_caller_identity.current.account_id}:loadbalancer/net/support-bot-${var.env}/*",
      "arn:aws:elasticloadbalancing:eu-central-1:${data.aws_caller_identity.current.account_id}:loadbalancer/app/support-bot-${var.env}/*",
      "arn:aws:elasticloadbalancing:eu-central-1:${data.aws_caller_identity.current.account_id}:targetgroup/*/*",
    ]
  }
  statement {
    sid    = "ELBv2MutateScoped"
    effect = "Allow"
    actions = [
      "elasticloadbalancing:CreateLoadBalancer",
      "elasticloadbalancing:CreateTargetGroup",
      "elasticloadbalancing:DeleteLoadBalancer",
      "elasticloadbalancing:DeleteTargetGroup",
      "elasticloadbalancing:ModifyLoadBalancerAttributes",
      "elasticloadbalancing:ModifyTargetGroup",
      "elasticloadbalancing:ModifyTargetGroupAttributes",
      "elasticloadbalancing:ModifyListener",
      "elasticloadbalancing:ModifyRule",
      "elasticloadbalancing:RegisterTargets",
      "elasticloadbalancing:DeregisterTargets",
    ]
    resources = [
      "arn:aws:elasticloadbalancing:eu-central-1:${data.aws_caller_identity.current.account_id}:loadbalancer/net/support-bot-${var.env}/*",
      "arn:aws:elasticloadbalancing:eu-central-1:${data.aws_caller_identity.current.account_id}:loadbalancer/app/support-bot-${var.env}/*",
      "arn:aws:elasticloadbalancing:eu-central-1:${data.aws_caller_identity.current.account_id}:listener/net/support-bot-${var.env}/*/*",
      "arn:aws:elasticloadbalancing:eu-central-1:${data.aws_caller_identity.current.account_id}:listener/app/support-bot-${var.env}/*/*",
      "arn:aws:elasticloadbalancing:eu-central-1:${data.aws_caller_identity.current.account_id}:listener-rule/net/support-bot-${var.env}/*/*",
      "arn:aws:elasticloadbalancing:eu-central-1:${data.aws_caller_identity.current.account_id}:listener-rule/app/support-bot-${var.env}/*/*",
      "arn:aws:elasticloadbalancing:eu-central-1:${data.aws_caller_identity.current.account_id}:targetgroup/*/*",
    ]
  }
}

resource "aws_iam_role_policy" "alb_controller" {
  count  = var.eks_oidc_provider_arn != null ? 1 : 0
  name   = "ALBControllerScoped"
  role   = aws_iam_role.alb_controller[0].id
  policy = data.aws_iam_policy_document.alb_controller_policy[0].json
}

# ----------------------------------------------------------------------------
# T008 (part G): GitHub Actions OIDC provider + role
# ----------------------------------------------------------------------------
data "tls_certificate" "github" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github.certificates[0].sha1_fingerprint]
  tags = {
    Name = "github-actions-oidc"
  }
}

data "aws_iam_policy_document" "github_actions_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:*/${var.domain_suffix}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  name               = "github-actions-${var.env}"
  assume_role_policy = data.aws_iam_policy_document.github_actions_assume_role.json
  tags = {
    Name    = "github-actions-${var.env}"
    Cluster = "support-bot-${var.env}"
  }
}

# Scoped ECR push policy. ECR repo ARN is a placeholder; WP05 will inject the
# actual repo ARN via a data source or shared locals once WP05 lands. Until
# then, the policy resource list contains a per-env ARN pattern that the
# operator confirms at apply time.
data "aws_iam_policy_document" "github_actions_policy" {
  statement {
    sid    = "ECRPushScoped"
    effect = "Allow"
    actions = [
      "ecr:PutImage",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:BatchCheckLayerAvailability",
    ]
    resources = [
      "arn:aws:ecr:eu-central-1:${data.aws_caller_identity.current.account_id}:repository/support-bot-${var.env}/*",
    ]
  }
  statement {
    sid       = "ECRGetAuthToken"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "github_actions" {
  name   = "GithubActionsECRPush"
  role   = aws_iam_role.github_actions.id
  policy = data.aws_iam_policy_document.github_actions_policy.json
}

# ----------------------------------------------------------------------------
# T009 (part H): EKS Pod Identity associations
# ----------------------------------------------------------------------------
resource "aws_eks_pod_identity_association" "external_secrets" {
  count           = var.eks_oidc_provider_arn != null ? 1 : 0
  cluster_name    = var.eks_cluster_name
  namespace       = "support-bot"
  service_account = "external-secrets"
  role_arn        = aws_iam_role.external_secrets[0].arn
}

resource "aws_eks_pod_identity_association" "adot" {
  count           = var.eks_oidc_provider_arn != null ? 1 : 0
  cluster_name    = var.eks_cluster_name
  namespace       = "opentelemetry"
  service_account = "adot-collector"
  role_arn        = aws_iam_role.adot[0].arn
}

resource "aws_eks_pod_identity_association" "alb_controller" {
  count           = var.eks_oidc_provider_arn != null ? 1 : 0
  cluster_name    = var.eks_cluster_name
  namespace       = "kube-system"
  service_account = "aws-load-balancer-controller"
  role_arn        = aws_iam_role.alb_controller[0].arn
}
