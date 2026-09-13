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
  cmk_arn                        = module.identity.cmk_arn # from WP03
  baseline_instance_type         = var.baseline_instance_type
  baseline_desired_size          = var.baseline_desired_size
  karpenter_version              = var.karpenter_version
  karpenter_iam_role_arn         = module.cluster.karpenter_iam_role_arn # from cluster module (self-ref for WP02-created node role; dedicated controller role deferred)
}

module "identity" {
  source = "./modules/identity"

  env                   = var.env
  eks_cluster_name      = module.cluster.cluster_name
  eks_oidc_provider_arn = module.cluster.oidc_provider_arn
  openai_api_key        = var.openai_api_key
  chroma_auth_token     = var.chroma_auth_token
  domain_suffix         = var.domain_suffix
}

module "edge" {
  source = "./modules/edge"

  env                            = var.env
  cluster_name                   = module.cluster.cluster_name
  cluster_security_group_id      = module.cluster.cluster_security_group_id
  vpc_id                         = module.foundation.vpc_id
  public_subnet_ids              = module.foundation.public_subnet_ids
  parent_zone_id                 = var.parent_zone_id
  domain_suffix                  = var.domain_suffix
  alb_controller_role_arn        = module.identity.alb_controller_role_arn
  cmk_arn                        = module.identity.cmk_arn
  vpc_endpoint_security_group_id = module.foundation.vpc_endpoint_security_group_id
}

module "observability" {
  source = "./modules/observability"

  env                       = var.env
  eks_cluster_name          = module.cluster.cluster_name
  adot_role_arn             = module.identity.adot_role_arn
  cmk_arn                   = module.identity.cmk_arn
  cluster_security_group_id = module.cluster.cluster_security_group_id
  region                    = var.region
}
