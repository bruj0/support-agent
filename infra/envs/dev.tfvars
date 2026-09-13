# dev environment tfvars
# Operator must populate parent_zone_id and admin_cidr before first apply.
# openai_api_key and chroma_auth_token are passed via TF_VAR_* env vars at apply
# time, NOT stored here (NFR-003).

env            = "dev"
parent_zone_id = "<operator-supplied Route53 zone ID for support-bot.example.com>"
admin_cidr     = "<operator-supplied CIDR for EKS admin access, e.g. 203.0.113.0/24>"

# Cluster (S2)
baseline_instance_type = "m7i.large"
baseline_desired_size  = 2
karpenter_version      = "1.0.0"

# Identity (S3)
domain_suffix = "support-bot.example.com"
