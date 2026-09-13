variable "env" { type = string }
variable "eks_cluster_name" { type = string }
variable "adot_role_arn" { type = string }
variable "cmk_arn" { type = string }
variable "cluster_security_group_id" { type = string }
variable "region" {
  type    = string
  default = "eu-central-1"
}

variable "test_mode" {
  description = "If true, skips helm_release resources (for tofu test in env without network)."
  type        = bool
  default     = false
}
