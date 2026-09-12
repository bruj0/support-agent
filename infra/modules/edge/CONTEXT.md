---
context_name: "Edge & Traffic"
version: "1"
subsystem: "infra/modules/edge"
created: "2026-09-12T16:50:00+00:00"
updated: "2026-09-12T16:50:00+00:00"
---

# Edge & Traffic

Edge & Traffic is the public-facing ingress layer for the support-agent deployment.
It terminates TLS, protects with managed WAF rules, and routes user traffic to the
in-cluster API service via the AWS Load Balancer Controller.

## Language

**AcmCertificate**:
The per-env TLS certificate that fronts the public ingress — DNS-validated against the parent Route53 zone, with a wildcard SAN covering all subdomain hosts in the env.
_Avoid_: cert, ssl_cert, tls_cert
_Subsystems_: Edge & Traffic, Identity & Secrets
_Files_: infra/modules/edge/main.tf, infra/modules/edge/outputs.tf
_Relates to_: Route53Record (alias target), IngressResource (TLS termination)

**Route53Record**:
The DNS alias record that resolves `<env>.${domain_suffix}` to the ALB DNS name; created only after the AWS Load Balancer Controller has provisioned the underlying ALB from the Ingress.
_Avoid_: dns_record, alias, r53_record
_Subsystems_: Edge & Traffic
_Files_: infra/modules/edge/main.tf
_Relates to_: AcmCertificate (DNS validation), IngressResource (ALB discovery)

**Wafv2WebAcl**:
A WAFv2 regional Web ACL attached to the ALB, providing AWS managed rule sets (Common, SQLi, Bot Control) plus a rate-based rule (1000 req/5min/IP).
_Avoid_: waf, web_acl, firewall
_Subsystems_: Edge & Traffic
_Files_: infra/modules/edge/main.tf
_Relates to_: IngressResource (annotation reference)

**AlbControllerHelm**:
The AWS Load Balancer Controller installed via Helm into the cluster, given a Pod Identity association that lets it reconcile Ingress resources into ALBs in the account.
_Avoid_: aws_lb_controller, lbc, ingress_controller
_Subsystems_: Edge & Traffic, Cluster & Compute
_Files_: infra/modules/edge/main.tf, deploy/helm/support-bot/values.yaml
_Relates to_: IngressResource (reconciles into ALB), Identity & Secrets (role assumption)

**IngressResource**:
The Kubernetes `networking.k8s.io/v1` Ingress that targets the in-cluster `support-bot-api` Service on port 8000, annotated for the AWS Load Balancer Controller with the FR-010 contract annotations.
_Avoid_: ingress_object, k8s_ingress, alb_ingress
_Subsystems_: Edge & Traffic
_Files_: infra/modules/edge/main.tf, deploy/helm/support-bot/templates/ingress.yaml
_Relates to_: Wafv2WebAcl (annotation), AlbControllerHelm (reconciler)

**AlbAccessLogsBucket**:
A versioned, KMS-encrypted, non-public S3 bucket that receives ALB access logs with a 30-day lifecycle expiration; bucket policy grants `s3:PutObject` to the regional ELB log-delivery service principal.
_Avoid_: logs_bucket, alb_bucket, access_logs
_Subsystems_: Edge & Traffic
_Files_: infra/modules/edge/main.tf
_Relates to_: Identity & Secrets (KMS CMK)

## Relationships

- An **AlbControllerHelm** reconciles an **IngressResource** into an AWS ALB.
- An **AcmCertificate** fronts an **IngressResource** with TLS.
- A **Route53Record** aliases to the ALB DNS that the **AlbControllerHelm** produces from an **IngressResource**.
- A **Wafv2WebAcl** attaches to the ALB produced by an **IngressResource**.
- An **AlbAccessLogsBucket** receives log writes from the ALB produced by an **IngressResource**.

## Flagged Ambiguities

- "Ingress" was used to mean both the Kubernetes `Ingress` resource and the AWS ALB resource — resolved: **IngressResource** always refers to the Kubernetes object; the AWS resource is "ALB" or "aws_lb".
- "ALB Controller" vs "AWS Load Balancer Controller" — resolved: prefer **AlbControllerHelm** for the helm-managed subsystem component; "AWS Load Balancer Controller" is acceptable only as the upstream helm chart's marketing name.
