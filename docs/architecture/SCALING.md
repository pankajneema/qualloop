# QualLoop — Scaling Path (Phase 0)

Rule (PHASES.md scale track): nothing below is built until its trigger fires. Each change then gets an ADR and human
approval. Triggers are measured from the dashboards defined in ADR-015; numbers are engineering thresholds chosen here,
not product requirements.

## 1. Stages

| Stage | Definition | Expected load (planning numbers) |
| --- | --- | --- |
| Stage 1 — Pilot | ≤ 10 tenants, ≤ 20 plants | ≤ 300 suppliers/plant; ≤ 5k receipts/plant/month; ≤ 500 NCRs/plant/month; ≤ 50 concurrent users |
| Stage 2 — Growth | ≤ 200 tenants | ≤ 250 plants; ≤ 1.5M receipts/month total; ≤ 500 concurrent users |
| Stage 3 — Enterprise | > 200 tenants or any tenant with contractual isolation / SSO / data-residency requirements | per-contract |

## 2. Stage 1 baseline (what we build in P00–P09)

| Component | Stage 1 configuration |
| --- | --- |
| Postgres | 1 × RDS PostgreSQL 16, 2 vCPU / 4–8 GB (db.t4g.medium → db.m7g.large), single-AZ, gp3 100 GB, PITR 7 days |
| Redis | 1 × ElastiCache node (cache.t4g.small), no replica |
| api | 2 Fargate tasks (1 vCPU / 2 GB), gunicorn 2 workers × uvicorn, sync endpoints with threadpool |
| web | 2 Fargate tasks (0.5 vCPU / 1 GB) |
| worker | 1 task, all queues; dispatcher 1; scheduler 1 |
| Tables | no partitioning; all metrics computed live by SQL; no materialised tables |
| Search | Postgres `ILIKE` on indexed `lower(name)` / `part_no` prefix |
| Backups | RDS automated + daily snapshot copy to ap-south-2 (ADR-018) |

Performance budgets (verified in P07/P08/P09 with seed × 10):

| Budget | Value | Source |
| --- | --- | --- |
| My Work server time | < 500 ms p95 | PHASES P08 |
| Command endpoints | < 300 ms p95 | this doc |
| List queries | < 300 ms p95 | this doc |
| Metrics for 300 suppliers × 12 months | < 5 s (job), < 1 s per supplier page | PHASES P07 |
| Outbox lag (event → handler start) | < 10 s p95 | this doc |
| WhatsApp failure → email fallback | ≤ 15 min | §17.4 |
| Import 5,000 rows | < 60 s locally | PHASES P02 |

## 3. Triggers and changes

| # | Change | Trigger (any one, sustained 7 days unless noted) | Stage | Effort / risk |
| --- | --- | --- | --- | --- |
| S-01 | RDS Multi-AZ | first paying (post-pilot) tenant, **or** > 10 tenants | 2 | config change; minutes of failover |
| S-02 | ElastiCache replica + Multi-AZ | > 10 tenants, or Redis outage caused a user-visible incident | 2 | config |
| S-03 | Scale api tasks / autoscaling on CPU 60% | api CPU > 60% p95 or command p95 > 300 ms | 1–2 | config |
| S-04 | Split worker per queue (`notifications`, `ai`, `imports`, `reports` dedicated services) | queue lag p95 > 60 s on any queue, or one queue's backlog delays another | 2 | task definitions only |
| S-05 | Partition `activity_log` by month (declarative range on `created_at`) | table > 50 GB **or** > 100M rows **or** > 10M rows/month | 2 | migration with copy; ADR |
| S-06 | Partition `messages` by month | > 20M rows or > 5M rows/month | 2 | same |
| S-07 | Partition `outbox_events` by month + drop processed partitions > 90 days (after retention decision A-83) | > 20M rows or dispatcher claim query > 50 ms p95 | 2 | same |
| S-08 | Partition `defect_events` by month of `created_at` (or hash by tenant) | > 50M rows or receipt-rejection query > 200 ms p95 | 2–3 | higher (FKs reference it) — ADR required |
| S-09 | Read replica for reports, exports, monthly snapshot job, explain payloads | reporting/metrics queries > 30% of primary DB time, or primary CPU > 60% p95 | 2 | route read-only sessions by role; replica lag alarm > 30 s |
| S-10 | Materialised metric tables (`receipt_rejections_daily`, `supplier_month_facts`) refreshed by workers on events + nightly | metrics endpoint > 1 s p95, or My Work > 500 ms p95 after index tuning | 2 | data-engineer ADR; parity tests vs live SQL |
| S-11 | Trigram indexes (`pg_trgm`) for supplier/part search | search p95 > 300 ms | 1–2 | migration |
| S-12 | Dedicated search (OpenSearch) | Postgres full-text/trigram fails budgets after S-11 | 3 | new server → human approval |
| S-13 | DB vertical scale | CPU > 70% p95 or memory pressure (buffer cache hit < 95%) | any | config, short downtime / failover |
| S-14 | PgBouncer / RDS Proxy | DB connections > 70% of `max_connections` | 2 | RLS GUCs must use `SET LOCAL` (already the design) |
| S-15 | CDN caching of static web assets & fonts | always (Stage 1 via CloudFront) | 1 | — |
| S-16 | Dedicated database per tenant (option) | contract requirement, or one tenant > 20% of total DB load | 3 | tenant routing in `core.db`; same schema; ADR |
| S-17 | SSO/SAML/SCIM, multi-plant consolidation, SOC 2 / ISO 27001 readiness, data-residency guarantees | enterprise contract (Part B §29) | 3 | **out of R1 scope**; new spec section first |
| S-18 | Multi-region | never in Part A (§5.3) | — | — |

## 4. Data growth model (to evaluate triggers early)

| Table | Rows per plant per month (Stage 1 planning) | 200 tenants × 1.25 plants × 12 months |
| --- | --- | --- |
| `grn_receipts` | 5,000 | 15M |
| `defect_events` | 600 | 1.8M |
| `ncrs` | 500 | 1.5M |
| `activity_log` | ~ 20 per command × 2,000 commands = 40,000 | 120M → S-05 fires in Stage 2 |
| `messages` | 3,000 | 9M |
| `outbox_events` | 4,000 | 12M |

These are estimates for planning only; real rows/month per table are measured weekly by a dashboard query
(`pg_stat_user_tables.n_tup_ins` deltas) and compared with the trigger thresholds above.

## 5. What does NOT change between stages

- Modular monolith, one image, same module boundaries (ADR-001) — Stage 3 may extract a module only with an ADR
  showing a trigger (independent scaling or team ownership), never speculatively. No Kafka, no Kubernetes, no
  microservices in Part A (§5.3).
- RLS on `tenant_id`, command/outbox pattern, as-of metrics semantics.
- Single Indian region for primary data (§22).
