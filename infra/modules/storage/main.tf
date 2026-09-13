data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

provider "kubernetes" {
  config_path = "~/.kube/config"
}

# --- T002 Gp3StorageClass (gp3, Retain, WaitForFirstConsumer) ---------------------

resource "kubernetes_manifest" "support_bot_gp3_storageclass" {
  manifest = {
    apiVersion = "storage.k8s.io/v1"
    kind       = "StorageClass"
    metadata = {
      name = "support-bot-gp3"
      annotations = {
        "storageclass.kubernetes.io/is-default-class" = "false"
      }
    }
    provisioner          = "ebs.csi.aws.com"
    reclaimPolicy        = "Retain"
    volumeBindingMode    = "WaitForFirstConsumer"
    allowVolumeExpansion = true
    parameters = {
      type       = "gp3"
      iops       = "3000"
      throughput = "250"
      encrypted  = "true"
    }
  }
}

# --- T003 EcrRepository (per-env, IMMUTABLE tags, scan on push) -------------------

resource "aws_ecr_repository" "support_bot_api" {
  name                 = var.shared_ecr ? "support-bot-api" : "support-bot-api-${var.env}"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = var.cmk_arn
  }

  force_delete = false

  tags = {
    Name      = "support-bot-api-${var.env}"
    Cluster   = "support-bot-${var.env}"
    Component = "api"
  }

  lifecycle {
    prevent_destroy = true
  }
}

# --- T004 EcrRepositoryPolicy (scoped push to GitHub Actions role) ---------------

data "aws_iam_policy_document" "ecr_repo_policy" {
  statement {
    sid    = "AllowGitHubActionsPush"
    effect = "Allow"
    principals {
      type        = "AWS"
      identifiers = [var.github_actions_role_arn]
    }
    actions = [
      "ecr:PutImage",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
    ]
  }

  statement {
    sid    = "AllowAccountPull"
    effect = "Allow"
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
    actions = [
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
      "ecr:DescribeImages",
    ]
  }
}

resource "aws_ecr_repository_policy" "support_bot_api" {
  repository = aws_ecr_repository.support_bot_api.name
  policy     = data.aws_iam_policy_document.ecr_repo_policy.json
}

# --- T005 DlmSnapshotPolicy (daily EBS snapshots for the Chroma PVC) --------------

resource "aws_dlm_lifecycle_policy" "chroma_snapshot" {
  description        = "Daily EBS snapshot for Chroma PVC in support-bot-${var.env}"
  execution_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/AWSDataLifecycleManagerDefaultRole"
  state              = "ENABLED"

  policy_details {
    policy_type    = "EBS_SNAPSHOT_MANAGEMENT"
    resource_types = ["VOLUME"]

    target_tags = {
      Cluster   = "support-bot-${var.env}"
      Component = "chroma"
    }

    schedule {
      name = "daily-7day-retention"

      create_rule {
        interval      = 24
        interval_unit = "HOURS"
        times         = ["03:00"]
      }

      retain_rule {
        count = 7
      }

      copy_tags = true
    }
  }
}
