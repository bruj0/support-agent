# Cluster module tests.
#
# Substrate WP02 -- tests cover M2 (drift via pinned version), M4 (multi-AZ MNG),
# and M7 (VPC CNI enableNetworkPolicy). The cluster attributes
# (version, enabled_cluster_log_types, encryption_config) are all set
# statically via literals, so plan-mode evaluation does not require AWS API calls.
#
# Karpenter (helm_release + kubectl_manifest) is excluded from the test scope via
# `var.test_mode = true` because the helm_release OCI registry login and the
# kubectl_manifest CRD schema both require live network/cluster access. The
# operator's first `tofu apply` (with `test_mode = false`) brings up Karpenter;
# WP06 refines the NodePool/EC2NodeClass with NetworkPolicy-aware configuration.

provider "aws" {
  region                      = "eu-central-1"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_region_validation      = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
}

run "eks_version_1_30" {
  command = plan

  variables {
    env                            = "dev"
    vpc_id                         = "vpc-00000000"
    private_subnet_ids             = ["subnet-aaaa", "subnet-bbbb", "subnet-cccc"]
    vpc_endpoint_security_group_id = "sg-00000000"
    admin_cidr                     = "10.0.0.0/8"
    cmk_arn                        = "arn:aws:kms:eu-central-1:123456789012:key/placeholder"
    karpenter_iam_role_arn         = "arn:aws:iam::123456789012:role/placeholder"
    test_mode                      = true
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "123456789012"
    }
  }

  assert {
    condition     = aws_eks_cluster.main.version == "1.30"
    error_message = "EKS cluster must be Kubernetes 1.30."
  }
}

run "control_plane_logging_enabled" {
  command = plan

  variables {
    env                            = "dev"
    vpc_id                         = "vpc-00000000"
    private_subnet_ids             = ["subnet-aaaa", "subnet-bbbb", "subnet-cccc"]
    vpc_endpoint_security_group_id = "sg-00000000"
    admin_cidr                     = "10.0.0.0/8"
    cmk_arn                        = "arn:aws:kms:eu-central-1:123456789012:key/placeholder"
    karpenter_iam_role_arn         = "arn:aws:iam::123456789012:role/placeholder"
    test_mode                      = true
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "123456789012"
    }
  }

  assert {
    condition     = sort(aws_eks_cluster.main.enabled_cluster_log_types) == sort(["api", "audit", "authenticator"])
    error_message = "Control plane logging must be enabled for api, audit, authenticator."
  }
}

run "envelope_encryption" {
  command = plan

  variables {
    env                            = "dev"
    vpc_id                         = "vpc-00000000"
    private_subnet_ids             = ["subnet-aaaa", "subnet-bbbb", "subnet-cccc"]
    vpc_endpoint_security_group_id = "sg-00000000"
    admin_cidr                     = "10.0.0.0/8"
    cmk_arn                        = "arn:aws:kms:eu-central-1:123456789012:key/abc123"
    karpenter_iam_role_arn         = "arn:aws:iam::123456789012:role/placeholder"
    test_mode                      = true
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "123456789012"
    }
  }

  assert {
    condition     = aws_eks_cluster.main.encryption_config[0].provider[0].key_arn == "arn:aws:kms:eu-central-1:123456789012:key/abc123"
    error_message = "EKS must envelope-encrypt secrets with the per-env CMK from WP03."
  }
}

run "baseline_mng_2_m7i_large" {
  command = plan

  variables {
    env                            = "dev"
    vpc_id                         = "vpc-00000000"
    private_subnet_ids             = ["subnet-aaaa", "subnet-bbbb", "subnet-cccc"]
    vpc_endpoint_security_group_id = "sg-00000000"
    admin_cidr                     = "10.0.0.0/8"
    cmk_arn                        = "arn:aws:kms:eu-central-1:123456789012:key/placeholder"
    karpenter_iam_role_arn         = "arn:aws:iam::123456789012:role/placeholder"
    test_mode                      = true
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "123456789012"
    }
  }

  assert {
    condition     = aws_eks_node_group.baseline.instance_types[0] == "m7i.large"
    error_message = "Baseline MNG must use m7i.large."
  }
  assert {
    condition     = aws_eks_node_group.baseline.scaling_config[0].desired_size == 2
    error_message = "Baseline MNG must have desired_size = 2."
  }
}

run "baseline_mng_multi_az" {
  command = plan

  variables {
    env                            = "dev"
    vpc_id                         = "vpc-00000000"
    private_subnet_ids             = ["subnet-aaaa", "subnet-bbbb", "subnet-cccc"]
    vpc_endpoint_security_group_id = "sg-00000000"
    admin_cidr                     = "10.0.0.0/8"
    cmk_arn                        = "arn:aws:kms:eu-central-1:123456789012:key/placeholder"
    karpenter_iam_role_arn         = "arn:aws:iam::123456789012:role/placeholder"
    test_mode                      = true
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "123456789012"
    }
  }

  assert {
    condition     = length(aws_eks_node_group.baseline.subnet_ids) >= 3
    error_message = "Baseline MNG must span at least 3 subnets (one per AZ)."
  }
}

run "vpc_cni_network_policy_enabled" {
  command = plan

  variables {
    env                            = "dev"
    vpc_id                         = "vpc-00000000"
    private_subnet_ids             = ["subnet-aaaa", "subnet-bbbb", "subnet-cccc"]
    vpc_endpoint_security_group_id = "sg-00000000"
    admin_cidr                     = "10.0.0.0/8"
    cmk_arn                        = "arn:aws:kms:eu-central-1:123456789012:key/placeholder"
    karpenter_iam_role_arn         = "arn:aws:iam::123456789012:role/placeholder"
    test_mode                      = true
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "123456789012"
    }
  }

  assert {
    condition     = jsondecode(aws_eks_addon.vpc_cni.configuration_values).enableNetworkPolicy == "true"
    error_message = "VPC CNI addon must have enableNetworkPolicy = true (for WP06 NetworkPolicy enforcement)."
  }
}
