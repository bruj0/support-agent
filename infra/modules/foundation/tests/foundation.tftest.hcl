# Foundation module tests.
#
# Substrate WP — no misfit to reproduce. These tests assert the structural
# invariants the plan.md §5.2 contract promises:
#   - VPC has 3 public + 3 private subnets
#   - Exactly 1 NAT gateway by default
#   - 6 interface VPC endpoints + 1 S3 gateway endpoint
#   - Subnets are cluster-tagged
#
# Pattern: provider skip + plan. All AWS resources have static (non-computed)
# shapes (count, for_each sizes, tags-as-literal), so plan-mode evaluates
# without AWS calls. The `tofu apply` acceptance criteria (acceptance #2–#6)
# are deferred to the operator's first `tofu apply` against real AWS.

provider "aws" {
  region                      = "eu-central-1"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_region_validation      = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
}

run "vpc_has_three_azs" {
  command = plan

  variables {
    env      = "dev"
    vpc_cidr = "10.0.0.0/16"
    region   = "eu-central-1"
  }

  override_data {
    target = data.aws_availability_zones.available
    values = {
      names = ["eu-central-1a", "eu-central-1b", "eu-central-1c"]
    }
  }

  assert {
    condition     = length(aws_subnet.public) == 3
    error_message = "VPC must have 3 public subnets (one per AZ)."
  }
  assert {
    condition     = length(aws_subnet.private) == 3
    error_message = "VPC must have 3 private subnets (one per AZ)."
  }
}

run "nat_gateway_count" {
  command = plan

  variables {
    env      = "dev"
    vpc_cidr = "10.0.0.0/16"
    region   = "eu-central-1"
  }

  override_data {
    target = data.aws_availability_zones.available
    values = {
      names = ["eu-central-1a", "eu-central-1b", "eu-central-1c"]
    }
  }

  assert {
    condition     = length(aws_nat_gateway.main) == 1
    error_message = "Exactly 1 NAT gateway expected (overridable to 3 for prod HA)."
  }
}

run "vpc_endpoints_present" {
  command = plan

  variables {
    env      = "dev"
    vpc_cidr = "10.0.0.0/16"
    region   = "eu-central-1"
  }

  override_data {
    target = data.aws_availability_zones.available
    values = {
      names = ["eu-central-1a", "eu-central-1b", "eu-central-1c"]
    }
  }

  assert {
    condition     = length(aws_vpc_endpoint.interface) == 6
    error_message = "Exactly 6 interface VPC endpoints expected."
  }
  assert {
    condition     = aws_vpc_endpoint.s3.vpc_endpoint_type == "Gateway"
    error_message = "S3 VPC endpoint must be of type Gateway."
  }
}

run "subnets_tagged" {
  command = plan

  variables {
    env      = "dev"
    vpc_cidr = "10.0.0.0/16"
    region   = "eu-central-1"
  }

  override_data {
    target = data.aws_availability_zones.available
    values = {
      names = ["eu-central-1a", "eu-central-1b", "eu-central-1c"]
    }
  }

  assert {
    condition     = alltrue([for s in aws_subnet.public : s.tags.Cluster == "support-bot-dev"])
    error_message = "Public subnets must be tagged with the cluster name."
  }
  assert {
    condition     = alltrue([for s in aws_subnet.private : s.tags.Cluster == "support-bot-dev"])
    error_message = "Private subnets must be tagged with the cluster name."
  }
}
