variable "env" {
  type = string
}

variable "region" {
  type    = string
  default = "eu-central-1"
}

variable "vpc_cidr" {
  type = string
}

variable "az_count" {
  type    = number
  default = 3
}

variable "nat_gateway_count" {
  type    = number
  default = 1
}

variable "enable_vpc_endpoints" {
  type    = bool
  default = true
}
