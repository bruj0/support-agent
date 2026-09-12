locals {
  cluster_name = "support-bot-${var.env}"
}

module "foundation" {
  source = "./modules/foundation"

  env               = var.env
  region            = var.region
  vpc_cidr          = var.vpc_cidr
  nat_gateway_count = var.nat_gateway_count
}

module "cluster" {
  source = "./modules/cluster"

  env                            = var.env
  vpc_id                         = module.foundation.vpc_id
  private_subnet_ids             = module.foundation.private_subnet_ids
  vpc_endpoint_security_group_id = module.foundation.vpc_endpoint_security_group_id
  cluster_name                   = local.cluster_name
  admin_cidr                     = var.admin_cidr
  cmk_arn                        = var.cmk_arn # from WP03
  baseline_instance_type         = var.baseline_instance_type
  baseline_desired_size          = var.baseline_desired_size
  karpenter_version              = var.karpenter_version
  karpenter_iam_role_arn         = var.karpenter_iam_role_arn # from WP03
}
