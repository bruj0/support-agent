variable "env" { type = string }
variable "eks_cluster_name" { type = string }
variable "github_actions_role_arn" { type = string }
variable "shared_ecr" {
  type    = bool
  default = false
}
variable "cmk_arn" { type = string }
