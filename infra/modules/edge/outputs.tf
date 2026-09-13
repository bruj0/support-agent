output "acm_cert_arn" {
  description = "ARN of the per-env ACM certificate."
  value       = aws_acm_certificate.env_cert.arn
}

output "wafv2_web_acl_arn" {
  description = "ARN of the WAFv2 WebACL attached to the ALB."
  value       = aws_wafv2_web_acl.env_waf.arn
}

output "alb_access_logs_bucket" {
  description = "Name of the ALB access logs bucket."
  value       = aws_s3_bucket.alb_access_logs.id
}

output "alb_access_logs_bucket_arn" {
  description = "ARN of the ALB access logs bucket."
  value       = aws_s3_bucket.alb_access_logs.arn
}

output "ingress_name" {
  description = "Name of the kubernetes Ingress resource that drives ALB creation."
  value       = kubernetes_manifest.env_ingress.manifest.metadata.name
}

# alb_dns_name and route53_zone_id are intentionally omitted: the ALB is
# created by the AWS Load Balancer Controller from the Ingress, and its
# DNS name is only knowable at runtime via:
#   kubectl get ingress support-bot-api -n support-bot \
#     -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
# The upstream spec (FR-012) requires the alias to point at this DNS; the
# operator records it manually on the first `tofu apply`, then a follow-up
# apply creates aws_route53_record.env_alias referencing the resolved DNS
# via a data "external" helper. See WP04 prompt T003 / T009 for the
# chosen resolution pattern and the documented comment in main.tf.
