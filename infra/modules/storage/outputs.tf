output "storage_class_name" {
  description = "Name of the support-bot-gp3 StorageClass."
  value       = kubernetes_manifest.support_bot_gp3_storageclass.manifest.metadata.name
}

output "ecr_repository_url" {
  description = "URL of the per-env (or shared) support-bot-api ECR repository."
  value       = aws_ecr_repository.support_bot_api.repository_url
}

output "ecr_repository_arn" {
  description = "ARN of the per-env (or shared) support-bot-api ECR repository."
  value       = aws_ecr_repository.support_bot_api.arn
}

output "ecr_repository_name" {
  description = "Name of the per-env (or shared) support-bot-api ECR repository."
  value       = aws_ecr_repository.support_bot_api.name
}

output "dlm_policy_id" {
  description = "ID of the DLM lifecycle policy targeting the Chroma PVC."
  value       = aws_dlm_lifecycle_policy.chroma_snapshot.id
}
