# ADR-017 — Hosting and deployment

- Status: Proposed — cloud account and spend are paid services → **requires human approval (CLAUDE.md §5)**
- Spec: §21.1 (TLS, encryption at rest, daily encrypted backups), §22 (managed Postgres with RLS, Redis, S3-compatible storage in an Indian region, single Indian region), §5.3 (no Kubernetes, no multi-region), §26.2 (India hosting)

## Options considered
| Option | India regions | Managed PG 16 | Redis | S3-compatible | Containers without K8s | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| **AWS** | ap-south-1 Mumbai, ap-south-2 Hyderabad | RDS PostgreSQL 16 (PITR, KMS) | ElastiCache | S3 | ECS Fargate | broadest managed set; SES email and Bedrock/Textract in-region (verify models at P03); second India region for backup copies |
| Google Cloud | asia-south1 Mumbai, asia-south2 Delhi | Cloud SQL PG 16 | Memorystore | GCS (S3 interop) | Cloud Run | Delhi region close to NCR; Cloud Run simpler; email needs third party |
| Azure | Central India (Pune), South India | Flexible Server PG 16 | Azure Cache for Redis | Blob (not S3 API natively) | Container Apps | S3 compatibility requires a shim |
| Indian VPS (e.g. E2E Networks) + self-managed | Delhi/Mumbai | self-run | self-run | MinIO self-run | Docker | cheapest; we would operate DB backups/HA ourselves — not acceptable for a 2-person team |

## Decision
**AWS ap-south-1 (Mumbai)** as the single primary region; **ap-south-2 (Hyderabad)** only for backup copies (still India).

| Layer | Service (Stage 1) |
| --- | --- |
| DNS/TLS/edge | Route 53, ACM, CloudFront + AWS WAF (managed rules + rate rules for `/supplier-access/*`, `/auth/*`) |
| Load balancer | ALB: `/api/*`, `/healthz`, `/readyz` → api; `/*` → web; target health checks `/healthz` (api) and `/` (web) (m7); access logs disabled, edge logging via CloudFront real-time logs excluding `/s/*` (D-4) |
| Compute | ECS Fargate services: `api` ×2, `web` ×2, `worker` ×1 (+ clamd sidecar if A-47 approved), `dispatcher` ×1, `scheduler` ×1; private subnets; ARM64 images |
| Database | RDS PostgreSQL 16, single-AZ (Multi-AZ at S-01), gp3, KMS, PITR 7 days, `rds.force_ssl=1`, parameter `log_min_duration_statement=500ms` |
| Cache/queue | ElastiCache Redis 7, in-transit + at-rest encryption, RBAC user group with least-privilege user (default user disabled), SG ingress only from ECS task SGs (D-5) |
| Storage | S3 `files` (versioned, SSE-KMS, Block Public Access), `quarantine` (7-day lifecycle) |
| Secrets | Secrets Manager → ECS task secrets; KMS CMKs per environment |
| Registry | ECR with image scanning |
| Email | SES ap-south-1 (ADR-010) |
| Observability | CloudWatch Logs/Metrics/Synthetics, X-Ray via ADOT (ADR-015) |
| Accounts | AWS Organizations: `qualloop-staging`, `qualloop-prod` (separate blast radius); CI deploys via GitHub OIDC roles |
| IaC | **Terraform** (modules in `infra/terraform/modules`, envs in `infra/terraform/envs/{staging,prod}`), remote state in S3 + DynamoDB lock in each account |

Rough Stage-1 monthly cost to be estimated in P09 with the AWS pricing calculator and approved by the human before any
`terraform apply` (no numbers committed here).

## Consequences
- Vendor lock-in limited to managed primitives (Postgres, Redis, S3 API, containers) — portable to GCP with Terraform rewrites.
- Nobody applies IaC to a real account without explicit human approval (devops-engineer rule).

## Revisit when
- Cloud bill > 20% of MRR for 3 consecutive months, or
- a customer contract requires a specific cloud or on-premise deployment (Stage 3), or
- GCP asia-south2 latency advantage is measured as material for NCR plants (> 50 ms p95 difference).
