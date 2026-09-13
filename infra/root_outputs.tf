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

output "application_log_group_arn" { value = module.observability.application_log_group_arn }
output "otel_log_group_arn" { value = module.observability.otel_log_group_arn }
output "adot_collector_endpoint" { value = module.observability.adot_collector_endpoint }
output "network_policy_names" { value = module.observability.network_policy_names }
