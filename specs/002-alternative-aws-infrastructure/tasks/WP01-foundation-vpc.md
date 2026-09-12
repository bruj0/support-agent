---
work_package_id: "WP01"
title: "Foundation — VPC, subnets, NAT, VPC endpoints"
lane: "doing"
dependencies:
  - "WP00"
subsystem: "S1 Foundation"
misfits_addressed:
  - "(substrate — provides VPC consumed by S2–S6)"
abstract_components:
  - "VpcModule (from S1 plan)"
agent: "cursor"
history:
  - timestamp: "2026-09-12T11:05:00+00:00"
    lane: "doing"
    agent: "cursor"
    action: "started implementation"
---

# WP01 — Foundation (VPC + subnets + NAT + VPC endpoints)

## Goal

Provision the per-environment VPC in `eu-central-1`: 3 AZs, public subnets (ALB), private subnets (EKS nodes + Pods), 1 NAT gateway, 6 VPC interface endpoints (Secrets Manager, STS, ECR API, ECR DKR, CloudWatch Logs, CloudWatch Monitoring) + 1 S3 gateway endpoint. Also create the top-level OpenTofu configuration (`versions.tf`, `root_variables.tf`, `root_outputs.tf`) and the per-environment `tfvars` skeletons.

This WP provides the VPC that every other WP imports. Without it, WP02 (EKS), WP04 (ALB), WP05 (EBS volumes), and WP06 (logs) cannot start.

## Context

- **Region**: `eu-central-1`
- **Module root**: `infra/modules/foundation/`
- **Root files**: `infra/{versions.tf,root_variables.tf,root_outputs.tf,root.tf}`
- **Env files**: `infra/envs/{dev.tfvars,prod.tfvars}`
- **State backend**: configured at `tofu init` time with the S3 bucket from WP00
- **OpenTofu version**: `>= 1.6.0`

## Subtasks

### T001 — Create `infra/versions.tf`

Pin OpenTofu and providers:

```hcl
terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws        = { source = "hashicorp/aws",        version = ">= 5.40.0" }
    helm       = { source = "hashicorp/helm",       version = ">= 2.12.0" }
    kubernetes = { source = "hashicorp/kubernetes", version = ">= 2.27.0" }
    random     = { source = "hashicorp/random",     version = ">= 3.6.0"  }
    null       = { source = "hashicorp/null",       version = ">= 3.2.0"  }
    kubectl    = { source = "gavinbunney/kubectl",  version = ">= 1.14.0" }
  }
}
```

### T002 — Create `infra/root_variables.tf`

```hcl
variable "region"            { type = string; default = "eu-central-1" }
variable "env"               { type = string }   # "dev" or "prod" — required
variable "parent_zone_id"    { type = string }   # Route53 zone for the parent domain
variable "admin_cidr"        { type = string }   # CIDR allowed to reach the EKS public endpoint
variable "shared_ecr"        { type = bool;   default = false }
variable "chroma_auth_token" { type = string; default = null; sensitive = true }
variable "openai_api_key"    { type = string; sensitive = true }
variable "domain_suffix"     { type = string; default = "support-bot.example.com" }
variable "vpc_cidr"          { type = string; default = "10.0.0.0/16" }
variable "nat_gateway_count" { type = number; default = 1 }
```

### T003 — Create `infra/root_outputs.tf`

```hcl
output "vpc_id"                          { value = module.foundation.vpc_id }
output "private_subnet_ids"              { value = module.foundation.private_subnet_ids }
output "public_subnet_ids"               { value = module.foundation.public_subnet_ids }
output "vpc_endpoint_security_group_id"  { value = module.foundation.vpc_endpoint_security_group_id }
```

The remaining outputs (cluster name, ALB DNS, ECR URL, etc.) are added in their respective WPs.

### T004 — Create `infra/modules/foundation/{variables.tf,versions.tf}`

```hcl
# versions.tf
terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = ">= 5.40.0" }
  }
}

# variables.tf
variable "env"              { type = string }
variable "vpc_cidr"         { type = string }
variable "az_count"         { type = number; default = 3 }
variable "nat_gateway_count" { type = number; default = 1 }
variable "enable_vpc_endpoints" { type = bool; default = true }
```

### T005 — Create `infra/modules/foundation/main.tf`

The VPC, subnets, NAT, and endpoints:

```hcl
data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags = {
    Name    = "support-bot-${var.env}-vpc"
    Cluster = "support-bot-${var.env}"
  }
}

resource "aws_subnet" "public" {
  count                   = var.az_count
  vpc_id                  = aws_vpc.main.id
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  map_public_ip_on_launch = false
  tags = {
    Name    = "support-bot-${var.env}-public-${count.index + 1}"
    Tier    = "public"
    Cluster = "support-bot-${var.env}"
  }
}

resource "aws_subnet" "private" {
  count             = var.az_count
  vpc_id            = aws_vpc.main.id
  availability_zone = data.aws_availability_zones.available.names[count.index]
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 100)
  tags = {
    Name    = "support-bot-${var.env}-private-${count.index + 1}"
    Tier    = "private"
    Cluster = "support-bot-${var.env}"
  }
}

resource "aws_eip" "nat" {
  count  = var.nat_gateway_count
  domain = "vpc"
  tags   = { Name = "support-bot-${var.env}-nat-eip-${count.index + 1}" }
}

resource "aws_nat_gateway" "main" {
  count         = var.nat_gateway_count
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id
  tags          = { Name = "support-bot-${var.env}-nat-${count.index + 1}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
}

resource "aws_route_table_association" "public" {
  count          = var.az_count
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  count  = var.az_count
  vpc_id = aws_vpc.main.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main[count.index % var.nat_gateway_count].id
  }
}

resource "aws_route_table_association" "private" {
  count          = var.az_count
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "support-bot-${var.env}-igw" }
}

# VPC endpoints — interface (6)
resource "aws_security_group" "vpc_endpoints" {
  name        = "support-bot-${var.env}-vpce-sg"
  description = "Allow HTTPS from VPC CIDR to VPC endpoints"
  vpc_id      = aws_vpc.main.id
  ingress {
    description = "HTTPS from VPC"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }
  egress {
    description = "Allow all egress"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

locals {
  interface_endpoints = {
    secretsmanager = "com.amazonaws.${var.region}.secretsmanager"
    sts            = "com.amazonaws.${var.region}.sts"
    ecr_api        = "com.amazonaws.${var.region}.ecr.api"
    ecr_dkr        = "com.amazonaws.${var.region}.ecr.dkr"
    logs           = "com.amazonaws.${var.region}.logs"
    monitoring     = "com.amazonaws.${var.region}.monitoring"
  }
}

resource "aws_vpc_endpoint" "interface" {
  for_each            = local.interface_endpoints
  vpc_id              = aws_vpc.main.id
  service_name        = each.value
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true
  tags                = { Name = "support-bot-${var.env}-${each.key}" }
}

# VPC endpoint — gateway (S3)
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = aws_route_table.private[*].id
  tags              = { Name = "support-bot-${var.env}-s3" }
}
```

### T006 — Create `infra/modules/foundation/outputs.tf`

```hcl
output "vpc_id"                         { value = aws_vpc.main.id }
output "vpc_cidr_block"                 { value = aws_vpc.main.cidr_block }
output "public_subnet_ids"              { value = aws_subnet.public[*].id }
output "private_subnet_ids"             { value = aws_subnet.private[*].id }
output "nat_gateway_ids"                { value = aws_nat_gateway.main[*].id }
output "vpc_endpoint_security_group_id" { value = aws_security_group.vpc_endpoints.id }
output "internet_gateway_id"            { value = aws_internet_gateway.main.id }
```

### T007 — Create `infra/envs/{dev.tfvars,prod.tfvars}` skeleton

```hcl
# infra/envs/dev.tfvars
env           = "dev"
parent_zone_id = "<operator-supplied Route53 zone ID for support-bot.example.com>"
admin_cidr    = "<operator-supplied CIDR for EKS admin access, e.g. 203.0.113.0/24>"

# infra/envs/prod.tfvars
env           = "prod"
parent_zone_id = "<operator-supplied Route53 zone ID for support-bot.example.com>"
admin_cidr    = "<operator-supplied CIDR for EKS admin access, e.g. 203.0.113.0/24>"
```

The `openai_api_key` and `chroma_auth_token` are passed via `TF_VAR_openai_api_key=...` env vars at apply time, **not** in the `.tfvars` files (to avoid committing secrets).

### T008 — Write `infra/modules/foundation/tests/foundation.tftest.hcl`

```hcl
run "vpc_has_three_azs" {
  command = plan
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
  assert {
    condition     = length(aws_nat_gateway.main) == 1
    error_message = "Exactly 1 NAT gateway expected (overridable to 3 for prod HA)."
  }
}

run "vpc_endpoints_present" {
  command = plan
  assert {
    condition     = length(aws_vpc_endpoint.interface) == 6
    error_message = "Exactly 6 interface VPC endpoints expected."
  }
  assert {
    condition     = length(aws_vpc_endpoint.s3) == 1
    error_message = "Exactly 1 S3 gateway VPC endpoint expected."
  }
}

run "subnets_tagged" {
  command = plan
  assert {
    condition     = alltrue([for s in aws_subnet.public : s.tags.Cluster == "support-bot-dev"])
    error_message = "Public subnets must be tagged with the cluster name."
  }
}
```

### T009 — Create `infra/root.tf` (calls the foundation module only)

```hcl
module "foundation" {
  source = "./modules/foundation"

  env               = var.env
  vpc_cidr          = var.vpc_cidr
  nat_gateway_count = var.nat_gateway_count
}
```

The other modules (cluster, identity, edge, storage, observability) are added in their respective WPs.

## Acceptance Criteria

1. `cd infra && tofu init -backend-config="bucket=<bucket>" -backend-config="key=support-bot/dev/terraform.tfstate" -backend-config="region=eu-central-1" -backend-config="dynamodb_table=support-bot-tfstate-lock"` succeeds.
2. `tofu apply -var-file=envs/dev.tfvars` provisions 1 VPC, 3 public + 3 private subnets, 1 NAT gateway, 6 interface endpoints, 1 S3 gateway endpoint.
3. `tofu plan` immediately after reports `No changes.`
4. `aws ec2 describe-vpcs --filters Name=tag:Name,Values=support-bot-dev-vpc` returns one VPC.
5. `aws ec2 describe-nat-gateways --filter Name=tag:Cluster,Values=support-bot-dev` returns 1 NAT gateway.
6. `aws ec2 describe-vpc-endpoints --filters Name=vpc-id,Values=<id>` returns 7 endpoints.
7. `cd infra/modules/foundation && tofu test` runs the 4 `run` blocks above; all assertions pass.
8. `tofu fmt -check -recursive infra/` returns exit code 0.

## TDD Targets

- **Substrate (no misfit)**: `tofu test` for `foundation.tftest.hcl` asserts the VPC has 3 public + 3 private subnets, 1 NAT, 6 interface endpoints, 1 gateway endpoint. Sub-tests T008 covers this.

## Execution constraints

- Product code and tests: only in `$WORKTREES_DIR/002-alternative-aws-infrastructure-WP01/`
- Do not merge to `main` until `spec-bridge-merge` after accept
- Do not instruct "verify on main" — verify in the WP worktree after dependency merges

## Notes for implementer

- The VPC CIDR `10.0.0.0/16` leaves 65 536 IPs — sufficient for ~250 pods per AZ on VPC CNI (the project never exceeds ~20 pods).
- `cidrsubnet(var.vpc_cidr, 8, count.index)` for public subnets and `cidrsubnet(var.vpc_cidr, 8, count.index + 100)` for private subnets ensures public and private subnets never overlap.
- The NAT gateway is placed in `subnet.public[0]` only (1 NAT). When `var.nat_gateway_count = 3`, the NAT gateways are placed in each AZ's public subnet.
- The `aws_security_group.vpc_endpoints` allows ingress from the VPC CIDR; egress is open. This is the AWS-recommended default for VPC endpoints.
- The `private_dns_enabled = true` on each interface endpoint ensures the AWS service private DNS resolves correctly within the VPC (no `PrivateDnsEnabled` mismatch with AWS expectations).
- The S3 gateway endpoint is free (no hourly charge, no per-GB charge) and routes all S3 traffic from the VPC directly to S3 without going through the NAT gateway — saves ~$0.005/GB on egress.