variable "env" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "vpc_endpoint_security_group_id" {
  type = string
}

variable "cluster_name" {
  type    = string
  default = null # if null, computed as "support-bot-${var.env}"
}

variable "admin_cidr" {
  type = string
}

variable "cmk_arn" {
  type        = string
  description = "Per-env CMK ARN from WP03; placeholder until WP03 ships"
}

variable "baseline_instance_type" {
  type    = string
  default = "m7i.large"
}

variable "baseline_desired_size" {
  type    = number
  default = 2
}

variable "karpenter_version" {
  type    = string
  default = "1.0.0"
}

variable "karpenter_iam_role_arn" {
  type        = string
  description = "Per-env Karpenter role ARN from WP03; placeholder until WP03 ships"
}

variable "test_mode" {
  type        = bool
  default     = false
  description = "Disable helm_release + ECR data source for `tofu test`. Operator-credentialed applies set this to false."
}
