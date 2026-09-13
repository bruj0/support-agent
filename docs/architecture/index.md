# Architecture documents

- [AWS Infrastructure](aws-flow-v2.md) — **default**. OpenTofu-managed infra (VPC, EKS 1.30, Karpenter, ADOT, WAFv2, EBS gp3, NetworkPolicies).
- [Local Infrastructure](local-flow.md) — docker-compose dev environment
- [Architecture deep dive](architecture.md)
- [Observability](observability.md) — logs, traces, metrics, the `request_id` invariant, secret scrubbing, and a worked-example playbook.
