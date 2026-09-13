output "vpc_id" {
  value = module.foundation.vpc_id
}

output "private_subnet_ids" {
  value = module.foundation.private_subnet_ids
}

output "public_subnet_ids" {
  value = module.foundation.public_subnet_ids
}

output "vpc_endpoint_security_group_id" {
  value = module.foundation.vpc_endpoint_security_group_id
}

output "acm_cert_arn" {
  value = module.edge.acm_cert_arn
}

output "wafv2_web_acl_arn" {
  value = module.edge.wafv2_web_acl_arn
}

output "alb_access_logs_bucket" {
  value = module.edge.alb_access_logs_bucket
}

output "alb_access_logs_bucket_arn" {
  value = module.edge.alb_access_logs_bucket_arn
}

output "application_log_group_arn" { value = module.observability.application_log_group_arn }
output "otel_log_group_arn" { value = module.observability.otel_log_group_arn }
output "adot_collector_endpoint" { value = module.observability.adot_collector_endpoint }
output "network_policy_names" { value = module.observability.network_policy_names }
