locals {
  cluster_name = coalesce(var.cluster_name, "support-bot-${var.env}")
}

# ----------------------------------------------------------------------------
# Providers: helm + kubernetes + kubectl authenticate against the cluster.
# ----------------------------------------------------------------------------
provider "helm" {
  kubernetes = {
    host                   = aws_eks_cluster.main.endpoint
    cluster_ca_certificate = base64decode(aws_eks_cluster.main.certificate_authority[0].data)
    exec = {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", aws_eks_cluster.main.name]
    }
  }
}

provider "kubernetes" {
  host                   = aws_eks_cluster.main.endpoint
  cluster_ca_certificate = base64decode(aws_eks_cluster.main.certificate_authority[0].data)
  exec = {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", aws_eks_cluster.main.name]
  }
}

provider "kubectl" {
  apply_retry_count      = 5
  host                   = aws_eks_cluster.main.endpoint
  cluster_ca_certificate = base64decode(aws_eks_cluster.main.certificate_authority[0].data)
  load_config_file       = false
  exec = {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", aws_eks_cluster.main.name]
  }
}

# ----------------------------------------------------------------------------
# T002 (part A): EKS Cluster
# ----------------------------------------------------------------------------
resource "aws_eks_cluster" "main" {
  name     = local.cluster_name
  version  = "1.30"
  role_arn = aws_iam_role.cluster.arn

  vpc_config {
    subnet_ids              = var.private_subnet_ids
    endpoint_public_access  = true
    public_access_cidrs     = [var.admin_cidr]
    endpoint_private_access = true
    security_group_ids      = [aws_security_group.cluster.id]
  }

  enabled_cluster_log_types = ["api", "audit", "authenticator"]

  encryption_config {
    provider {
      key_arn = var.cmk_arn
    }
    resources = ["secrets"]
  }

  depends_on = [
    aws_iam_role_policy_attachment.cluster_amazon_eks_cluster_policy,
  ]

  tags = {
    Name    = local.cluster_name
    Cluster = local.cluster_name
  }
}

# ----------------------------------------------------------------------------
# T003 (part B): OIDC provider + Pod Identity Agent addon
# ----------------------------------------------------------------------------
data "tls_certificate" "cluster" {
  url = aws_eks_cluster.main.identity[0].oidc[0].issuer
}

resource "aws_iam_openid_connect_provider" "oidc" {
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.cluster.certificates[0].sha1_fingerprint]
  url             = aws_eks_cluster.main.identity[0].oidc[0].issuer

  tags = {
    Name    = "${local.cluster_name}-oidc"
    Cluster = local.cluster_name
  }
}

resource "aws_eks_addon" "pod_identity_agent" {
  cluster_name             = aws_eks_cluster.main.name
  addon_name               = "eks-pod-identity-agent"
  addon_version            = data.aws_eks_addon_version.pod_identity_agent.version
  service_account_role_arn = aws_iam_role.pod_identity_agent.arn

  tags = {
    Name    = "${local.cluster_name}-pod-identity-agent"
    Cluster = local.cluster_name
  }
}

data "aws_eks_addon_version" "pod_identity_agent" {
  addon_name         = "eks-pod-identity-agent"
  kubernetes_version = aws_eks_cluster.main.version
  most_recent        = true
}

# ----------------------------------------------------------------------------
# T004 (part C): Baseline managed node group
# ----------------------------------------------------------------------------
resource "aws_eks_node_group" "baseline" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "${local.cluster_name}-baseline"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = var.private_subnet_ids

  instance_types = [var.baseline_instance_type]
  capacity_type  = "ON_DEMAND"

  scaling_config {
    desired_size = var.baseline_desired_size
    min_size     = var.baseline_desired_size
    max_size     = var.baseline_desired_size
  }

  ami_type  = "AL2023_x86_64_STANDARD"
  disk_size = 50
  update_config {
    max_unavailable = 1
  }

  labels = {
    workload = "baseline"
  }

  taint {
    key    = "workload"
    value  = "baseline"
    effect = "NO_SCHEDULE"
  }

  tags = {
    Name                                = "${local.cluster_name}-baseline"
    Cluster                             = local.cluster_name
    "karpenter.sh/discovery"            = local.cluster_name
    "eks.amazonaws.com/nodegroup-image" = "AL2023"
  }
}

# ----------------------------------------------------------------------------
# T005 (part D): VPC CNI addon with enableNetworkPolicy = true
# ----------------------------------------------------------------------------
resource "aws_eks_addon" "vpc_cni" {
  cluster_name  = aws_eks_cluster.main.name
  addon_name    = "vpc-cni"
  addon_version = data.aws_eks_addon_version.vpc_cni.version

  configuration_values = jsonencode({
    enableNetworkPolicy = "true"
  })

  tags = {
    Name    = "${local.cluster_name}-vpc-cni"
    Cluster = local.cluster_name
  }
}

data "aws_eks_addon_version" "vpc_cni" {
  addon_name         = "vpc-cni"
  kubernetes_version = aws_eks_cluster.main.version
  most_recent        = true
}

# ----------------------------------------------------------------------------
# Cluster security group — open between cluster and nodes
# ----------------------------------------------------------------------------
resource "aws_security_group" "cluster" {
  name        = "${local.cluster_name}-cluster-sg"
  description = "Cluster security group for ${local.cluster_name}"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name                     = "${local.cluster_name}-cluster-sg"
    Cluster                  = local.cluster_name
    "karpenter.sh/discovery" = local.cluster_name
  }
}

resource "aws_security_group_rule" "cluster_ingress_nodes" {
  type                     = "ingress"
  from_port                = 0
  to_port                  = 0
  protocol                 = "-1"
  source_security_group_id = aws_security_group.nodes.id
  security_group_id        = aws_security_group.cluster.id
  description              = "Allow all from nodes"
}

resource "aws_security_group" "nodes" {
  name        = "${local.cluster_name}-nodes-sg"
  description = "Security group for EKS nodes"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "${local.cluster_name}-nodes-sg"
    Cluster = local.cluster_name
  }
}

resource "aws_security_group_rule" "nodes_ingress_cluster" {
  type                     = "ingress"
  from_port                = 0
  to_port                  = 0
  protocol                 = "-1"
  source_security_group_id = aws_security_group.cluster.id
  security_group_id        = aws_security_group.nodes.id
  description              = "Allow all from cluster"
}

# ----------------------------------------------------------------------------
# IAM roles: cluster, node, pod-identity-agent
# ----------------------------------------------------------------------------
data "aws_iam_policy_document" "cluster_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cluster" {
  name               = "${local.cluster_name}-cluster-role"
  assume_role_policy = data.aws_iam_policy_document.cluster_assume_role.json
  tags = {
    Name    = "${local.cluster_name}-cluster-role"
    Cluster = local.cluster_name
  }
}

resource "aws_iam_role_policy_attachment" "cluster_amazon_eks_cluster_policy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
  role       = aws_iam_role.cluster.name
}

data "aws_iam_policy_document" "node_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "node" {
  name               = "${local.cluster_name}-node-role"
  assume_role_policy = data.aws_iam_policy_document.node_assume_role.json
  tags = {
    Name    = "${local.cluster_name}-node-role"
    Cluster = local.cluster_name
  }
}

resource "aws_iam_role_policy_attachment" "node_amazon_eks_worker_node_policy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
  role       = aws_iam_role.node.name
}

resource "aws_iam_role_policy_attachment" "node_amazon_eks_cni_policy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
  role       = aws_iam_role.node.name
}

resource "aws_iam_role_policy_attachment" "node_amazon_ec2_container_registry_read_only" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
  role       = aws_iam_role.node.name
}

resource "aws_iam_role_policy_attachment" "node_amazon_ssm_managed_instance_core" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
  role       = aws_iam_role.node.name
}

data "aws_iam_policy_document" "pod_identity_agent_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.oidc.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${replace(aws_iam_openid_connect_provider.oidc.url, "https://", "")}:sub"
      values   = ["system:serviceaccount:eks-pod-identity-agent:eks-pod-identity-agent"]
    }
  }
}

resource "aws_iam_role" "pod_identity_agent" {
  name               = "${local.cluster_name}-pod-identity-agent-role"
  assume_role_policy = data.aws_iam_policy_document.pod_identity_agent_assume_role.json
  tags = {
    Name    = "${local.cluster_name}-pod-identity-agent-role"
    Cluster = local.cluster_name
  }
}

resource "aws_iam_role_policy_attachment" "pod_identity_agent_policy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSPodIdentityAgentPolicy"
  role       = aws_iam_role.pod_identity_agent.name
}

# ----------------------------------------------------------------------------
# T006 (part E): Karpenter v1 helm_release.
# Note: requires `var.karpenter_iam_role_arn` from WP03 (placeholder today).
# The NodePool and EC2NodeClass (T007) are applied with `kubectl apply -f`
# against the live cluster after WP03 lands; the `tofu test` for this module
# does not cover Karpenter resources (mock_provider pattern is fragile for
# helm_release + kubectl_manifest and is deferred to the operator's first
# `tofu apply`).
# ----------------------------------------------------------------------------
resource "helm_release" "karpenter" {
  count = var.test_mode ? 0 : 1

  name                = "karpenter"
  namespace           = "karpenter"
  create_namespace    = true
  chart               = "oci://public.ecr.aws/karpenter/karpenter"
  version             = var.karpenter_version
  repository_username = "AWS"
  repository_password = data.aws_ecr_authorization_token.karpenter[0].password

  set = [
    {
      name  = "settings.clusterName"
      value = aws_eks_cluster.main.name
    },
    {
      name  = "settings.interruptionQueue"
      value = aws_eks_cluster.main.name
    },
    {
      name  = "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn"
      value = var.karpenter_iam_role_arn
    },
  ]
}

data "aws_ecr_authorization_token" "karpenter" {
  count       = var.test_mode ? 0 : 1
  registry_id = data.aws_caller_identity.current.account_id
}

data "aws_caller_identity" "current" {}

