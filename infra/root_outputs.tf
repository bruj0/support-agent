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
