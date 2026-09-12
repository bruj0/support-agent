---
context_name: "AWS Foundation (VPC substrate)"
version: "1"
subsystem: "infra/modules/foundation"
created: "2026-09-12T11:00:00+00:00"
updated: "2026-09-12T11:00:00+00:00"
---

# AWS Foundation (VPC substrate)

Per-environment AWS VPC substrate consumed by every other subsystem module
(S2 cluster, S3 identity, S4 edge, S5 storage, S6 observability). One VPC
per environment; 3 AZs; private subnets host EKS nodes and Pods; public
subnets host the NAT gateway and ALB; VPC endpoints eliminate NAT egress
for AWS APIs and S3.

## Language

**FoundationVpc**:
The single per-environment VPC (`10.0.0.0/16` default) with `enable_dns_support`
and `enable_dns_hostnames` both true so VPC endpoints and EKS service endpoints
resolve via private DNS.
_Avoid_: vpc, support_bot_vpc, env_vpc
_Subsystems_: S1 Foundation
_Files_: infra/modules/foundation/main.tf, infra/modules/foundation/outputs.tf
_Relates to_: PublicSubnet (contains), PrivateSubnet (contains),
NatGateway (egresses-through), VpcEndpoint (hosts)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP01.

**PublicSubnet**:
An `aws_subnet` in a single AZ with `map_public_ip_on_launch = false` (public
routing only via ALB and NAT — Pods and nodes do not get public IPs). Numbered
`count.index` (0, 1, 2); CIDR offset 0 from `var.vpc_cidr /16` via `/24` per AZ.
_Avoid_: dmz_subnet, frontend_subnet, public_subnet_a
_Subsystems_: S1 Foundation
_Files_: infra/modules/foundation/main.tf
_Relates to_: FoundationVpc (belongs-to), NatGateway (hosts-in [0]),
AlbSubnetAssociation (consumed-by S4)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP01.

**PrivateSubnet**:
An `aws_subnet` in a single AZ with route table pointed at the NAT gateway
(when `nat_gateway_count == 1`) or at the AZ-local NAT (when HA enabled).
Numbered `count.index`; CIDR offset +100 from the public CIDR block so
public and private ranges never overlap.
_Avoid_: internal_subnet, backend_subnet, private_subnet_a
_Subsystems_: S1 Foundation
_Files_: infra/modules/foundation/main.tf
_Relates to_: FoundationVpc (belongs-to), EksNodeSubnetAssociation (consumed-by S2),
VpcEndpointInterface (contains)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP01.

**NatGateway**:
Single (default) or per-AZ (HA) NAT gateway placed in `public[count.index]`
to give private subnets egress to the public internet for image pulls,
OpenTelemetry export, and so on. 1 NAT is the dev default; `var.nat_gateway_count`
can be set to 3 for prod HA.
_Avoid_: egress, nat, single_nat
_Subsystems_: S1 Foundation
_Files_: infra/modules/foundation/main.tf
_Relates to_: PublicSubnet (placed-in), PrivateRouteTable (routed-by),
NatEip (allocated-by)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP01.

**VpcEndpoint**:
A VPC endpoint (Interface or Gateway) that removes the need for NAT egress
to reach AWS APIs. Six Interface endpoints (Secrets Manager, STS, ECR API,
ECR DKR, CloudWatch Logs, CloudWatch Monitoring) sit on the private subnets
with `private_dns_enabled = true`. One Gateway endpoint for S3 attaches to
the private route tables.
_Avoid_: vpc_pe, privatelink, aws_endpoint
_Subsystems_: S1 Foundation
_Files_: infra/modules/foundation/main.tf
_Relates to_: PrivateSubnet (Interface-endpoints-placed-in),
PrivateRouteTable (S3-gateway-routes-via), VpcEndpointSecurityGroup (Interface-endpoints-protected-by)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP01.

**VpcEndpointSecurityGroup**:
Security group attached to every Interface VPC endpoint. Allows ingress
TCP/443 from `var.vpc_cidr`; egress is open (AWS-recommended default for
VPC endpoints — the endpoint itself controls what is accepted on the
service side).
_Avoid_: vpce_sg, endpoint_firewall
_Subsystems_: S1 Foundation
_Files_: infra/modules/foundation/main.tf
_Relates to_: VpcEndpoint (protects)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP01.

**FoundationModule**:
The `modules/foundation` module itself — accepts `env`, `vpc_cidr`,
`az_count`, `nat_gateway_count`, `enable_vpc_endpoints` and produces the
FoundationVpc + subnets + NAT + endpoints + their outputs.
_Avoid_: vpc_module, network_module, base_module
_Subsystems_: S1 Foundation
_Files_: infra/modules/foundation/{main,outputs,variables,versions}.tf
_Relates to_: FoundationVpc (produces), RootModule (called-by)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP01.

**RootModule**:
The `infra/` root configuration that wires `modules/foundation` into the
top-level OpenTofu workspace. Accepts `env`, `region`, `vpc_cidr`,
`nat_gateway_count`, plus secrets (`openai_api_key`, `chroma_auth_token`)
that flow through to the cluster / secrets WPs later. Backend is the S3
bucket created by WP00.
_Avoid_: root, main, entrypoint, bootstrap
_Subsystems_: S1 Foundation
_Files_: infra/{versions,root_variables,root_outputs,root}.tf
_Relates to_: FoundationModule (calls), BootstrapStateBucket (uses-backend-from WP00)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP01.

## Relationships

- A **FoundationVpc** contains three **PublicSubnet** + three **PrivateSubnet**
- A **NatGateway** is placed in **PublicSubnet** (one per AZ when HA) and routes
  egress from **PrivateSubnet** via the **PrivateRouteTable**
- A **VpcEndpoint** is anchored to **FoundationVpc** — Interface endpoints on
  **PrivateSubnet**, Gateway endpoint on **PrivateRouteTable**
- A **VpcEndpointSecurityGroup** protects the Interface **VpcEndpoint**s
- A **FoundationModule** produces a **FoundationVpc** + all the above
- A **RootModule** calls a **FoundationModule** and reads its outputs

## Flagged Ambiguities

- "endpoint" has been used informally to mean both an AWS VPC endpoint
  (**VpcEndpoint**) and a FastAPI HTTP endpoint — resolved: AWS resources
  use the `VpcEndpoint` prefix; HTTP endpoints remain unqualified.
- "subnet" has been used to mean both a public subnet (**PublicSubnet**) and
  a private subnet (**PrivateSubnet**) — resolved: always qualify with the
  tier name.
