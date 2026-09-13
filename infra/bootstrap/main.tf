terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws    = { source = "hashicorp/aws", version = ">= 5.40.0" }
    random = { source = "hashicorp/random", version = ">= 3.6.0" }
  }
  # Bootstrap workspace uses LOCAL state (it creates the remote backend).
  # The local state file at terraform.tfstate must be backed up by the operator.
}

provider "aws" {
  region = "eu-central-1"
}

resource "random_id" "bucket_suffix" {
  byte_length = 4
}

resource "aws_kms_key" "bootstrap" {
  description             = "support-bot bootstrap state encryption"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
      Action    = "kms:*"
      Resource  = "*"
    }]
  })
}

resource "aws_kms_alias" "bootstrap" {
  name          = "alias/support-bot-bootstrap-cmk"
  target_key_id = aws_kms_key.bootstrap.key_id
}

resource "aws_s3_bucket" "tfstate" {
  bucket = "support-bot-tfstate-${data.aws_caller_identity.current.account_id}-eu-central-1-${random_id.bucket_suffix.hex}"
  lifecycle { prevent_destroy = true }
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.bootstrap.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.tfstate.arn,
          "${aws_s3_bucket.tfstate.arn}/*",
        ]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
      {
        Sid       = "DenyNonKMSEncryption"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.tfstate.arn}/*"
        Condition = { StringNotEquals = { "s3:x-amz-server-side-encryption" = "aws:kms" } }
      }
    ]
  })
}

resource "aws_dynamodb_table" "tfstate_lock" {
  name         = "support-bot-tfstate-lock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"
  attribute {
    name = "LockID"
    type = "S"
  }
  lifecycle { prevent_destroy = true }
}

data "aws_caller_identity" "current" {}

output "tfstate_bucket_name" {
  value = aws_s3_bucket.tfstate.id
}

output "tfstate_lock_table_name" {
  value = aws_dynamodb_table.tfstate_lock.name
}

output "tfstate_kms_key_arn" {
  value = aws_kms_key.bootstrap.arn
}