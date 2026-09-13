output "cluster_name" {
  value = aws_eks_cluster.main.name
}

output "cluster_endpoint" {
  value = aws_eks_cluster.main.endpoint
}

output "cluster_ca_certificate" {
  value     = aws_eks_cluster.main.certificate_authority[0].data
  sensitive = true
}

output "cluster_security_group_id" {
  value = aws_security_group.cluster.id
}

output "oidc_provider_arn" {
  value = aws_iam_openid_connect_provider.oidc.arn
}

output "node_iam_role_arn" {
  value = aws_iam_role.node.arn
}

output "baseline_node_group_name" {
  value = aws_eks_node_group.baseline.node_group_name
}

output "karpenter_iam_role_arn" {
  # The Karpenter controller pod assumes a dedicated IAM role via EKS Pod
  # Identity. WP02 creates the role + the Pod Identity association; WP03
  # does not need to provision one (the plan places the Karpenter role in
  # S2 cluster, not S3 identity -- the WP02 review noted this). For now,
  # expose the node role ARN which the Karpenter controller can also assume
  # (its instance profile) -- the dedicated Karpenter controller role is
  # added in a follow-up that creates the PodIdentityAssociation explicitly.
  value = aws_iam_role.node.arn
}
