output "adot_collector_endpoint" {
  description = "In-cluster DNS name + OTLP gRPC port for the ADOT collector."
  value       = "${var.eks_cluster_name}-adot:4317"
}

output "application_log_group_name" {
  description = "Name of the application CloudWatch Logs group."
  value       = aws_cloudwatch_log_group.application.name
}

output "application_log_group_arn" {
  description = "ARN of the application CloudWatch Logs group."
  value       = aws_cloudwatch_log_group.application.arn
}

output "otel_log_group_name" {
  description = "Name of the OTEL collector CloudWatch Logs group."
  value       = aws_cloudwatch_log_group.otel.name
}

output "otel_log_group_arn" {
  description = "ARN of the OTEL collector CloudWatch Logs group."
  value       = aws_cloudwatch_log_group.otel.arn
}

output "network_policy_names" {
  description = "Names of the 3 NetworkPolicy resources applied to support-bot."
  value = [
    kubernetes_manifest.support_bot_default_deny.manifest.metadata.name,
    kubernetes_manifest.support_bot_api_allow.manifest.metadata.name,
    kubernetes_manifest.support_bot_chroma_allow.manifest.metadata.name,
  ]
}
