# ADR-018 — Backup and restore

- Status: Proposed
- Spec: §21.1 (daily encrypted backups), §21.4 (RPO 24 h, RTO 8 h; quarterly restore test with measured restore time)

## Options considered
| Option | RPO | RTO | Notes |
| --- | --- | --- | --- |
| Nightly `pg_dump` to S3 | 24 h | hours (size-dependent) | logical; slow restore at scale |
| **RDS automated backups + PITR (7 days) + daily snapshot copy to ap-south-2** | ~5 min (PITR) | < 1 h for Stage-1 size | managed, encrypted with KMS |
| Continuous WAL archiving self-managed | minutes | varies | ops burden |

## Decision
| Asset | Mechanism | RPO | RTO target |
| --- | --- | --- | --- |
| Postgres | RDS automated backups, PITR 7 days (35 at Stage 2); daily snapshot copied to ap-south-2, retained 35 days; plus weekly `pg_dump` (custom format) to a separate encrypted S3 bucket in ap-south-2, retained 90 days (protects against account-level loss) | ≤ 5 min (PITR), ≤ 24 h (cross-region) | ≤ 8 h |
| Object storage | S3 versioning; noncurrent versions kept 30 days; Cross-Region Replication of `files` bucket to ap-south-2 | ≤ 15 min (CRR) | ≤ 8 h |
| Redis | not backed up (transport/session/OTP only; ADR-006) | n/a | rebuild from empty |
| Secrets/config | Terraform + Secrets Manager replication to ap-south-2 | n/a | IaC apply |

Restore drill (quarterly; first one is a P09 gate item):
1. `infra/scripts/restore_drill.sh` restores the latest snapshot (or PITR timestamp) into a new instance in staging.
2. Runs verification SQL: row counts per table vs source at backup time, invariant checks (money sums, unique keys, RLS
   enabled + forced on every table), Alembic revision == expected.
3. Starts an api task against it; `/readyz` 200; sample queries per tenant.
4. Records start/end timestamps → measured RTO in `docs/runbooks/restore.md` drill log.

Backups are encrypted with KMS keys distinct from the primary data keys; deletion protection on RDS and backup vaults.

## Consequences
- PITR makes effective RPO far better than the 24 h requirement at negligible cost.
- Cross-region copies stay inside India (data residency).

## Revisit when
- Measured restore time > 4 h (half the RTO budget), or
- database size > 500 GB.
