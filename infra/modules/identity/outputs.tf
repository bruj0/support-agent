output "cmk_arn" {
  value = aws_kms_key.env_cmk.arn
}

output "cmk_alias" {
  value = aws_kms_alias.env_cmk.name
}

output "openai_secret_arn" {
  value = aws_secretsmanager_secret.openai.arn
}

output "chroma_auth_secret_arn" {
  value = try(aws_secretsmanager_secret.chroma[0].arn, null)
}

output "external_secrets_role_arn" {
  value = try(aws_iam_role.external_secrets[0].arn, null)
}

output "adot_role_arn" {
  value = try(aws_iam_role.adot[0].arn, null)
}

output "alb_controller_role_arn" {
  value = try(aws_iam_role.alb_controller[0].arn, null)
}

output "github_actions_role_arn" {
  value = aws_iam_role.github_actions.arn
}

output "github_oidc_provider_arn" {
  value = aws_iam_openid_connect_provider.github.arn
}
