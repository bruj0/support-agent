---
context_name: "AWS EKS Cluster & Compute"
version: "1"
subsystem: "infra/modules/cluster"
created: "2026-09-12T13:00:00+00:00"
updated: "2026-09-12T13:00:00+00:00"
---

# AWS EKS Cluster & Compute

The EKS control plane + OIDC + baseline compute + Karpenter v1 controller
that hosts every workload in the per-environment AWS account. One cluster
per environment; Kubernetes 1.30; baseline On-Demand MNG carries the cluster
bootstrap (CoreDNS, Karpenter, aws-node); Karpenter handles everything else
via Spot-first NodePools.

## Language

**EksCluster**:
The single per-environment EKS control plane (`Kubernetes 1.30`). Control
plane logging enabled for `api`, `audit`, `authenticator`. Envelope
encryption for Kubernetes secrets uses the per-env CMK from WP03 (the
`cmk_arn` input is a placeholder until WP03 ships). API server endpoint
publicly reachable but restricted to `var.admin_cidr`.
_Avoid_: eks, k8s, control_plane, kubernetes_cluster
_Subsystems_: S2 Cluster & Compute
_Files_: infra/modules/cluster/main.tf, infra/modules/cluster/outputs.tf
_Relates to_: OidcProvider (allows-trust-with), BaselineNodeGroup (runs-on),
VpcCniAddon (extends), PodIdentityAgentAddon (extends), KarpenterController
(runs-on)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP02.

**OidcProvider**:
The `aws_iam_openid_connect_provider` for the cluster. URL =
`EksCluster.identity[0].oidc[0].issuer`, `client_id_list = ["sts.amazonaws.com"]`,
thumbprint fetched via `data.tls_certificate.cluster`. Allows EKS Pod Identity
and IRSA to mint short-lived service-account credentials.
_Avoid_: oidc, iam_openid_provider, irsa_provider
_Subsystems_: S2 Cluster & Compute
_Files_: infra/modules/cluster/main.tf
_Relates to_: EksCluster (issued-by), PodIdentityAgentAddon (depends-on)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP02.

**BaselineNodeGroup**:
The single On-Demand managed node group that carries cluster bootstrap
workloads (`kube-system`, `karpenter`, `aws-node`). 2x `m7i.large`,
`desired_size = min_size = max_size = 2`, spans all 3 private subnets,
tainted with `workload=baseline:NO_SCHEDULE` so only bootstrap Pods land
here.
_Avoid_: baseline_mng, core_node_group, system_node_group
_Subsystems_: S2 Cluster & Compute
_Files_: infra/modules/cluster/main.tf
_Relates to_: EksCluster (belongs-to), PrivateSubnet (spans), NodeIamRole
(used-by, from WP03)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP02.

**VpcCniAddon**:
The `aws_eks_addon` for `vpc-cni`, pinned to `v1.14+`. `configuration_values`
includes `enableNetworkPolicy = "true"` so WP06 can author NetworkPolicy
resources that actually enforce egress restrictions (without this, Calico or
Cilium would be required).
_Avoid_: cni_addon, aws_node, network_policy
_Subsystems_: S2 Cluster & Compute, S6 Observability
_Files_: infra/modules/cluster/main.tf
_Relates to_: EksCluster (extends), NetworkPolicy (enables, from S6)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP02.

**PodIdentityAgentAddon**:
The `aws_eks_addon` for `eks-pod-identity-agent`, latest version. Provides
the in-cluster webhook that mints temporary AWS credentials for service
accounts using EKS Pod Identity (the project's preferred IRSA replacement —
no OIDC trust setup, no `aws-sdk` env var sprawl).
_Avoid_: pod_identity, irsa, pod_identity_webhook
_Subsystems_: S2 Cluster & Compute
_Files_: infra/modules/cluster/main.tf
_Relates to_: OidcProvider (complements), EksCluster (extends)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP02.

**KarpenterController**:
The `helm_release` for Karpenter v1.0.0, installed via OCI chart
`oci://public.ecr.aws/karpenter/karpenter`. Settings: `clusterName =
local.cluster_name`, `interruptionQueue = local.cluster_name`,
`serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn =
var.karpenter_iam_role_arn`. Requires the per-env Karpenter role from WP03.
_Avoid_: karpenter, karpenter_helm, node_provisioner
_Subsystems_: S2 Cluster & Compute
_Files_: infra/modules/cluster/main.tf
_Relates to_: EksCluster (provisions-for), KarpenterNodePool (spawns),
KarpenterEc2NodeClass (selects-subnets-via), KarpenterRole (assumes, from WP03)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP02.

**KarpenterNodePool**:
The `kubectl_manifest` applying a `NodePool` resource named `burst` (Spot-first,
`WhenEmptyOrUnderutilized` consolidation). Defined inline as YAML in `main.tf`.
Holds the project's only workload NodePool until WP06 introduces tiered pools.
_Avoid_: nodepool, burst_pool, karpenter_nodepool
_Subsystems_: S2 Cluster & Compute
_Files_: infra/modules/cluster/main.tf
_Relates to_: KarpenterController (consumed-by), KarpenterEc2NodeClass
(paired-with)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP02.

**KarpenterEc2NodeClass**:
The `kubectl_manifest` applying a `EC2NodeClass` resource. `subnetSelectorTerms`
+ `securityGroupSelectorTerms` match the `karpenter.sh/discovery` tag applied to
the private subnets and the cluster security group. `amiFamily = "AL2023"`,
`role` references the per-env Karpenter node role from WP03.
_Avoid_: ec2nodeclass, node_template, karpenter_nodeclass
_Subsystems_: S2 Cluster & Compute
_Files_: infra/modules/cluster/main.tf
_Relates to_: KarpenterNodePool (paired-with), PrivateSubnet
(selects-via-tag), KarpenterRole (assumed-by, from WP03)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP02.

**ClusterModule**:
The `modules/cluster` module itself — accepts `env`, `vpc_id`,
`private_subnet_ids`, `vpc_endpoint_security_group_id`, `cluster_name`,
`admin_cidr`, `cmk_arn`, `baseline_instance_type`, `baseline_desired_size`,
`karpenter_version`, `karpenter_iam_role_arn` and produces the EksCluster +
addons + node group + Karpenter controller + NodePool + EC2NodeClass.
_Avoid_: cluster_module, eks_module
_Subsystems_: S2 Cluster & Compute
_Files_: infra/modules/cluster/{main,outputs,variables,versions}.tf
_Relates to_: FoundationModule (consumes-vpc-from), IdentityModule
(consumes-cmk-and-role-from, WP03)
_History_:
- 2026-09-12 (002-alternative-aws-infrastructure): initial definition for WP02.

## Relationships

- An **EksCluster** has-one **OidcProvider**, one **BaselineNodeGroup**,
  one **VpcCniAddon**, one **PodIdentityAgentAddon**, and one
  **KarpenterController**
- A **BaselineNodeGroup** runs in **PrivateSubnet**s (the foundation's
  private subnets) using the foundation VPC's cluster security group
- A **KarpenterController** schedules **KarpenterNodePool**s that pair with
  a **KarpenterEc2NodeClass** to select **PrivateSubnet**s and the cluster
  security group by tag
- A **ClusterModule** produces an **EksCluster** + everything above

## Flagged Ambiguities

- "node group" has been used informally to mean both the AWS managed
  node group (**BaselineNodeGroup**) and a Karpenter NodePool
  (**KarpenterNodePool**) — resolved: MNG is the AWS `aws_eks_node_group`
  resource; everything Karpenter-managed is a NodePool.
- "discovery tag" has been used to mean both `karpenter.sh/discovery`
  (used by **KarpenterEc2NodeClass**'s selectors) and the foundation's
  `Cluster` tag — resolved: `karpenter.sh/discovery` is the selector key;
  `Cluster` is a human-readable tag; both must agree on value.
