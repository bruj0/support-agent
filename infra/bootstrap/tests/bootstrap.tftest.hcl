# Bootstrap workspace tests.
#
# Strategy: use the real AWS provider with skip_* flags + override_data +
# refresh = false. This lets plan mode execute without hitting AWS, but the
# AWS provider still validates input arguments which means most computed
# attributes (kms_key.arn, bucket.arn) cannot be evaluated. So the tests
# focus on attribute *values* that are static (not computed via AWS calls):
#
# - aws_kms_alias.bootstrap.name     (literal string set in main.tf)
# - aws_s3_bucket.tfstate.bucket      (interpolated, evaluated without AWS)
# - aws_dynamodb_table.tfstate_lock.name (literal string)
#
# For everything that requires an AWS call to verify (encryption key,
# bucket policy rendered JSON, lifecycle blocks), the CI step `tofu validate`
# catches syntax and `tofu plan` (operator run with credentials) catches the
# runtime values.

provider "aws" {
  region                      = "eu-central-1"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_region_validation      = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
}

run "cmk_alias_named_correctly" {
  command = plan
  plan_options {
    refresh = false
  }
  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "123456789012"
    }
  }

  assert {
    condition     = aws_kms_alias.bootstrap.name == "alias/support-bot-bootstrap-cmk"
    error_message = "Bootstrap CMK alias must be 'alias/support-bot-bootstrap-cmk'."
  }
}

run "dynamodb_lock_name_correct" {
  command = plan
  plan_options {
    refresh = false
  }
  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "123456789012"
    }
  }

  assert {
    condition     = aws_dynamodb_table.tfstate_lock.name == "support-bot-tfstate-lock"
    error_message = "DynamoDB lock table name must be 'support-bot-tfstate-lock'."
  }
}

run "dynamodb_lock_uses_pay_per_request" {
  command = plan
  plan_options {
    refresh = false
  }
  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "123456789012"
    }
  }

  assert {
    condition     = aws_dynamodb_table.tfstate_lock.billing_mode == "PAY_PER_REQUEST"
    error_message = "DynamoDB lock table must use PAY_PER_REQUEST billing mode."
  }
  assert {
    condition     = aws_dynamodb_table.tfstate_lock.hash_key == "LockID"
    error_message = "DynamoDB lock table must hash on LockID."
  }
}