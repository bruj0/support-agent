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
