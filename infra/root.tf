module "foundation" {
  source = "./modules/foundation"

  env               = var.env
  region            = var.region
  vpc_cidr          = var.vpc_cidr
  nat_gateway_count = var.nat_gateway_count
}
