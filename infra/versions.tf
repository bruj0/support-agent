terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws        = { source = "hashicorp/aws", version = ">= 5.40.0" }
    helm       = { source = "hashicorp/helm", version = ">= 2.12.0" }
    kubernetes = { source = "hashicorp/kubernetes", version = ">= 2.27.0" }
    random     = { source = "hashicorp/random", version = ">= 3.6.0" }
    null       = { source = "hashicorp/null", version = ">= 3.2.0" }
    kubectl    = { source = "gavinbunney/kubectl", version = ">= 1.14.0" }
  }
}
