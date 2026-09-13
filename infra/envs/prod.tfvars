# prod environment tfvars
# Operator must populate parent_zone_id and admin_cidr before first apply.
# openai_api_key and chroma_auth_token are passed via TF_VAR_* env vars at apply
# time, NOT stored here.

env            = "prod"
parent_zone_id = "<operator-supplied Route53 zone ID for support-bot.example.com>"
admin_cidr     = "<operator-supplied CIDR for EKS admin access, e.g. 203.0.113.0/24>"

# Cluster (S2)
baseline_instance_type = "m7i.large"
baseline_desired_size  = 2
karpenter_version      = "1.0.0"

# Identity (S3) placeholders -- replace after WP03 ships
cmk_arn                = "arn:aws:kms:eu-central-1:000000000000:key/placeholder"
karpenter_iam_role_arn = "arn:aws:iam::000000000000:role/placeholder"
