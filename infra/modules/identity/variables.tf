variable "env" {
  type = string
}

variable "eks_cluster_name" {
  type = string
}

variable "eks_oidc_provider_arn" {
  type = string
}

variable "openai_api_key" {
  type      = string
  sensitive = true
}

variable "chroma_auth_token" {
  type      = string
  default   = null
  sensitive = true
}

variable "domain_suffix" {
  type = string
}
