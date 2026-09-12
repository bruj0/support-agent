variable "region" {
  type    = string
  default = "eu-central-1"
}

variable "env" {
  type = string # "dev" or "prod" -- required
}

variable "parent_zone_id" {
  type = string # Route53 zone for the parent domain
}

variable "admin_cidr" {
  type = string # CIDR allowed to reach the EKS public endpoint
}

variable "shared_ecr" {
  type    = bool
  default = false
}

variable "chroma_auth_token" {
  type      = string
  default   = null
  sensitive = true
}

variable "openai_api_key" {
  type      = string
  sensitive = true
}

variable "domain_suffix" {
  type    = string
  default = "support-bot.example.com"
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "nat_gateway_count" {
  type    = number
  default = 1
}
