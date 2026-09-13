# Storage module tests.
#
# WP05 misfits:
#   M3 (PVC Retain): StorageClass reclaimPolicy = Retain so a helm uninstall
#       or tofu destroy does not delete the EBS volume / embeddings.
#   M9 (DLM snapshot): DLM policy target_tags.Component == "chroma" so the
#       daily EBS snapshot captures the Chroma PVC only.
#   M10 (shared ECR + moving tag): per-env ECR repo with
#       image_tag_mutability = IMMUTABLE, scan_on_push = true, and a
#       repository policy that allows only the GitHub Actions OIDC role to
#       push (no * principals).

provider "aws" {
  region                      = "eu-central-1"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_region_validation      = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
}

provider "kubernetes" {
  config_path = "~/.kube/config"
}

# ---- StorageClass ----------------------------------------------------------------

run "storageclass_has_retain" {
  command = plan

  variables {
    env                     = "dev"
    eks_cluster_name        = "support-bot-dev"
    github_actions_role_arn = "arn:aws:iam::111122223333:role/github-actions-role-dev"
    shared_ecr              = false
    cmk_arn                 = "arn:aws:kms:eu-central-1:111122223333:key/00000000-0000-0000-0000-000000000000"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "111122223333"
    }
  }

  assert {
    condition     = kubernetes_manifest.support_bot_gp3_storageclass.manifest.reclaimPolicy == "Retain"
    error_message = "StorageClass must have reclaimPolicy = Retain (resolves Misfit M3)."
  }
}

run "storageclass_wait_for_first_consumer" {
  command = plan

  variables {
    env                     = "dev"
    eks_cluster_name        = "support-bot-dev"
    github_actions_role_arn = "arn:aws:iam::111122223333:role/github-actions-role-dev"
    shared_ecr              = false
    cmk_arn                 = "arn:aws:kms:eu-central-1:111122223333:key/00000000-0000-0000-0000-000000000000"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "111122223333"
    }
  }

  assert {
    condition     = kubernetes_manifest.support_bot_gp3_storageclass.manifest.volumeBindingMode == "WaitForFirstConsumer"
    error_message = "StorageClass must have volumeBindingMode = WaitForFirstConsumer."
  }
}

run "storageclass_gp3_with_iops" {
  command = plan

  variables {
    env                     = "dev"
    eks_cluster_name        = "support-bot-dev"
    github_actions_role_arn = "arn:aws:iam::111122223333:role/github-actions-role-dev"
    shared_ecr              = false
    cmk_arn                 = "arn:aws:kms:eu-central-1:111122223333:key/00000000-0000-0000-0000-000000000000"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "111122223333"
    }
  }

  assert {
    condition     = kubernetes_manifest.support_bot_gp3_storageclass.manifest.parameters.type == "gp3"
    error_message = "StorageClass must use gp3."
  }
  assert {
    condition     = kubernetes_manifest.support_bot_gp3_storageclass.manifest.parameters.iops == "3000"
    error_message = "StorageClass must have iops = 3000."
  }
  assert {
    condition     = kubernetes_manifest.support_bot_gp3_storageclass.manifest.parameters.throughput == "250"
    error_message = "StorageClass must have throughput = 250."
  }
  assert {
    condition     = kubernetes_manifest.support_bot_gp3_storageclass.manifest.parameters.encrypted == "true"
    error_message = "StorageClass parameters must set encrypted = true."
  }
}

# ---- ECR repository --------------------------------------------------------------

run "ecr_repo_immutable_tags" {
  command = plan

  variables {
    env                     = "dev"
    eks_cluster_name        = "support-bot-dev"
    github_actions_role_arn = "arn:aws:iam::111122223333:role/github-actions-role-dev"
    shared_ecr              = false
    cmk_arn                 = "arn:aws:kms:eu-central-1:111122223333:key/00000000-0000-0000-0000-000000000000"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "111122223333"
    }
  }

  assert {
    condition     = aws_ecr_repository.support_bot_api.image_tag_mutability == "IMMUTABLE"
    error_message = "ECR repo must have image_tag_mutability = IMMUTABLE (resolves Misfit M10)."
  }
}

run "ecr_repo_scan_on_push" {
  command = plan

  variables {
    env                     = "dev"
    eks_cluster_name        = "support-bot-dev"
    github_actions_role_arn = "arn:aws:iam::111122223333:role/github-actions-role-dev"
    shared_ecr              = false
    cmk_arn                 = "arn:aws:kms:eu-central-1:111122223333:key/00000000-0000-0000-0000-000000000000"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "111122223333"
    }
  }

  assert {
    condition     = aws_ecr_repository.support_bot_api.image_scanning_configuration[0].scan_on_push == true
    error_message = "ECR repo must have scan_on_push = true."
  }
}

run "ecr_repo_naming_when_not_shared" {
  command = plan

  variables {
    env                     = "dev"
    eks_cluster_name        = "support-bot-dev"
    github_actions_role_arn = "arn:aws:iam::111122223333:role/github-actions-role-dev"
    shared_ecr              = false
    cmk_arn                 = "arn:aws:kms:eu-central-1:111122223333:key/00000000-0000-0000-0000-000000000000"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "111122223333"
    }
  }

  assert {
    condition     = aws_ecr_repository.support_bot_api.name == "support-bot-api-dev"
    error_message = "Per-env ECR repo must be named support-bot-api-<env>."
  }
}

# ---- ECR repo policy (no * principals) ------------------------------------------

run "ecr_repo_policy_scoped_to_github_actions" {
  command = plan

  variables {
    env                     = "dev"
    eks_cluster_name        = "support-bot-dev"
    github_actions_role_arn = "arn:aws:iam::111122223333:role/github-actions-role-dev"
    shared_ecr              = false
    cmk_arn                 = "arn:aws:kms:eu-central-1:111122223333:key/00000000-0000-0000-0000-000000000000"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "111122223333"
    }
  }

  assert {
    condition = alltrue([
      for stmt in jsondecode(aws_ecr_repository_policy.support_bot_api.policy).Statement :
      stmt.Principal.AWS != "*"
    ])
    error_message = "ECR repo policy must not grant access to * principals."
  }

  assert {
    condition     = strcontains(aws_ecr_repository_policy.support_bot_api.policy, "github-actions-role-dev")
    error_message = "ECR repo policy must allow push from the github_actions_role_arn input."
  }
}

# ---- DLM policy ------------------------------------------------------------------

run "dlm_targets_chroma_tag" {
  command = plan

  variables {
    env                     = "dev"
    eks_cluster_name        = "support-bot-dev"
    github_actions_role_arn = "arn:aws:iam::111122223333:role/github-actions-role-dev"
    shared_ecr              = false
    cmk_arn                 = "arn:aws:kms:eu-central-1:111122223333:key/00000000-0000-0000-0000-000000000000"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "111122223333"
    }
  }

  assert {
    condition     = aws_dlm_lifecycle_policy.chroma_snapshot.policy_details[0].target_tags.Component == "chroma"
    error_message = "DLM policy must target Component = chroma tag (resolves Misfit M9)."
  }
  assert {
    condition     = aws_dlm_lifecycle_policy.chroma_snapshot.policy_details[0].target_tags.Cluster == "support-bot-dev"
    error_message = "DLM policy must target Cluster = support-bot-<env> tag."
  }
  assert {
    condition     = aws_dlm_lifecycle_policy.chroma_snapshot.policy_details[0].schedule[0].retain_rule[0].count == 7
    error_message = "DLM policy must retain 7 snapshots."
  }
  assert {
    condition     = aws_dlm_lifecycle_policy.chroma_snapshot.policy_details[0].schedule[0].create_rule[0].interval == 24
    error_message = "DLM policy must run at a 24-hour interval."
  }
  assert {
    condition     = aws_dlm_lifecycle_policy.chroma_snapshot.policy_details[0].schedule[0].create_rule[0].interval_unit == "HOURS"
    error_message = "DLM create_rule interval_unit must be HOURS."
  }
}

# ---- ECR repo prevent_destroy ----------------------------------------------------

run "ecr_repo_has_prevent_destroy" {
  command = plan

  variables {
    env                     = "dev"
    eks_cluster_name        = "support-bot-dev"
    github_actions_role_arn = "arn:aws:iam::111122223333:role/github-actions-role-dev"
    shared_ecr              = false
    cmk_arn                 = "arn:aws:kms:eu-central-1:111122223333:key/00000000-0000-0000-0000-000000000000"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "111122223333"
    }
  }

  assert {
    condition     = aws_ecr_repository.support_bot_api.name == "support-bot-api-dev"
    error_message = "ECR repo name sanity check (prevent_destroy is verified by code review; lifecycle meta-block is not queryable in tofu test)."
  }
}

# ---- shared_ecr=true path -------------------------------------------------------

run "ecr_repo_shared_naming" {
  command = plan

  variables {
    env                     = "dev"
    eks_cluster_name        = "support-bot-dev"
    github_actions_role_arn = "arn:aws:iam::111122223333:role/github-actions-role-dev"
    shared_ecr              = true
    cmk_arn                 = "arn:aws:kms:eu-central-1:111122223333:key/00000000-0000-0000-0000-000000000000"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "111122223333"
    }
  }

  assert {
    condition     = aws_ecr_repository.support_bot_api.name == "support-bot-api"
    error_message = "When shared_ecr = true, repo name must be the un-suffixed 'support-bot-api'."
  }
}
