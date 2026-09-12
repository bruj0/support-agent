---
context_name: "Data Plane & Storage"
version: "1"
subsystem: "infra/modules/storage"
created: "2026-09-12T18:30:00+00:00"
updated: "2026-09-12T18:30:00+00:00"
---

# Data Plane & Storage

Data Plane & Storage is the substrate for persistent state in the support-agent deployment. It provisions the StorageClass that backs the Chroma PVC, the ECR repository that holds the API image, and the DLM lifecycle policy that protects the Chroma PVC from accidental deletion. The chart adopts these via additive values only — no template edits in this WP.

## Language

**Gp3StorageClass**:
The per-env Kubernetes StorageClass `support-bot-gp3` provisioned via `kubernetes_manifest` with gp3 EBS volume parameters (3000 IOPS, 250 MiB/s, encrypted) and `reclaimPolicy: Retain` so cluster teardown does not delete the underlying EBS volume.
_Avoid_: storage_class, sc, ebs_storageclass
_Subsystems_: Data Plane & Storage, Cluster & Compute
_Files_: infra/modules/storage/main.tf, infra/modules/storage/outputs.tf
_Relates to_: PersistenceComponent (PVC that consumes this class)

**StorageClassValueMerge**:
The additive chart values (`persistence.storageClassName: support-bot-gp3`, `persistence.annotations/labels` carrying the Cluster+Component tags) that bind the Chroma PVC to the Gp3StorageClass and tag the resulting EBS volume for DLM selection.
_Avoid_: pvc_settings, persistence_config, volume_binding
_Subsystems_: Data Plane & Storage, Support Bot RAG Project
_Files_: deploy/helm/support-bot/values.yaml, deploy/helm/support-bot/values-prod.yaml
_Relates to_: Gp3StorageClass (consumer), DlmSnapshotPolicy (tag selector)

**EcrRepository**:
The per-env ECR repository (named `support-bot-api-<env>` unless `shared_ecr=true`) with `image_tag_mutability: IMMUTABLE` and `scan_on_push: true`; scoped by a repository policy that allows only the GitHub Actions OIDC role from S3 to push, and the AWS account root to pull.
_Avoid_: docker_repo, ecr, image_registry, container_repo
_Subsystems_: Data Plane & Storage, Identity & Secrets
_Files_: infra/modules/storage/main.tf, infra/modules/storage/outputs.tf
_Relates to_: GithubActionsRole (push authority)

**DlmSnapshotPolicy**:
A DLM lifecycle policy in `EBS_SNAPSHOT_MANAGEMENT` mode targeting EBS volumes that carry the tags `Cluster: support-bot-<env>` and `Component: chroma`. Daily schedule at 03:00 UTC, 7-snapshot retention, copy_tags enabled so the snapshot carries the originating tags.
_Avoid_: snapshot_policy, dlm, backup_policy
_Subsystems_: Data Plane & Storage
_Files_: infra/modules/storage/main.tf
_Relates to_: StorageClassValueMerge (PVC tags → EBS volume tags), PersistenceComponent (volume lifecycle)

## Relationships

- A **Gp3StorageClass** is consumed by a `PersistentVolumeClaim` whose `spec.storageClassName` references it (resolved at `helm template` time via StorageClassValueMerge).
- An **EcrRepository** accepts image pushes from a **GithubActionsRole** and image pulls from the in-cluster nodes running the API.
- A **DlmSnapshotPolicy** selects the EBS volume that backs the Chroma PVC by matching tag, runs daily, and creates EBS snapshots retained for 7 days.

## Flagged Ambiguities

- "ECR" vs "ECR Repository" — resolved: prefer **EcrRepository** when referring to the AWS-side resource; "ECR" is acceptable only as the upstream service name.
- "StorageClass" vs "PersistentVolume" — resolved: **Gp3StorageClass** always refers to the Kubernetes StorageClass object; "PV" refers to the bound PersistentVolume that the StorageClass creates (different object, different lifecycle).
- "Tags" on EBS volumes vs "annotations" on PVCs — resolved: PVC annotations flow to PVC metadata only; EBS volume tags are set by the EBS CSI driver's `extra-volume-tags` flag. WP05 chooses labels over annotations on the PVC for the Cluster+Component selectors because the EBS CSI driver reads labels (not annotations) when `extra-volume-tags-from-pvc-labels` is enabled.
