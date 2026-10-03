# ADR-006 — Outbox, job queue, idempotency, retries, dead-letter, scheduler

- Status: Proposed
- Spec: §22 (Redis + worker queue), §22.2 (outbox, idempotency, retries, dead-letter after 5 with alert), §22.3, §22.4 (queue dashboard)

## Context
Business change and `outbox_events` row are written in the same transaction; workers dispatch notifications, risk
recalculation and reports from the outbox (§22.2). External sends need idempotency keys; retries need exponential
backoff and dead-letter after 5 attempts with an alert. Scheduled jobs: daily document scan, nightly risk, monthly
snapshots, reminders, digests.

## Options considered — job library (Redis broker, CLAUDE.md §6)
| Library | Retries + backoff | Dead-letter | Scheduler | Dashboard/metrics | Fit |
| --- | --- | --- | --- | --- | --- |
| Celery 5 | yes (`autoretry_for`, `retry_backoff`) | no native DLQ (custom) | celery beat | Flower | proven but heavy; Redis visibility-timeout redelivery pitfalls for long jobs (AI, PDF, imports) |
| RQ | `Retry(max, interval=[…])` | failed job registry | rq-scheduler (separate) | rq-dashboard | simple; fork-per-job overhead; fewer middleware hooks for tenant context |
| arq | yes | no | cron built in | none | async-only (ADR-002 chose sync); small maintainer base |
| **Dramatiq** | `Retries` middleware: `max_retries`, exponential `min_backoff`/`max_backoff` | **native dead-letter queue** (messages kept 7 days) | none built in → APScheduler | built-in Prometheus middleware; `dramatiq-dashboard` optional | thread-based workers fit sync SQLAlchemy; middleware hook for tenant context; heartbeat-based Redis broker avoids visibility-timeout redelivery |
| Postgres-based queue (Procrastinate) | yes | yes | yes | — | contradicts CLAUDE.md "Redis job queue" |

## Decision
1. **Dramatiq** (Redis broker) for jobs; **APScheduler 3.x** in a single `scheduler` process for cron triggers, which only
   enqueues Dramatiq messages (no work in the scheduler). Leader lock `sched:leader` in Redis (SET NX, TTL 30 s).
2. **Outbox dispatcher** (separate process): every 1 s, in one transaction, `app_claim_outbox_batch(100)`
   (`FOR UPDATE SKIP LOCKED`, oldest first, skipping rows in backoff: `updated_at + 5 s × 2^attempts > now()`), enqueue
   one Dramatiq message per registered handler with `message_id = "{event_id}:{handler}"`, set `processed_at`. On
   enqueue failure: `attempts += 1`, `last_error`; `attempts ≥ 5` → dead-letter (stays unprocessed, alert fires).
   Two dispatchers are safe (SKIP LOCKED).
3. **Handler idempotency**: every handler is safe to run twice. Mechanisms: unique `messages.idempotency_key`
   (`{event_id}:{notification_type}:{recipient}:{channel}`), deterministic recompute (risk, effectiveness), unique
   snapshot key, `ON CONFLICT DO NOTHING`, state guards.
4. **Retries**: Dramatiq `max_retries=5`, backoff 10 s → 30 min (exponential, jitter) for WhatsApp, email, AI, PDF,
   imports. After the 5th failure, the message goes to the Dramatiq dead-letter queue. Middleware then does three things:
   - writes a durable row to `job_dead_letters` in Postgres, under the job's tenant (technical table, A-89, needs approval), so a Redis loss cannot erase the record;
   - emits `job_dead_lettered` as a log line, a metric and an alert;
   - lists unresolved rows in an Admin view, which a support runbook resolves.

   Outbox dispatch dead letters remain in `outbox_events` (`attempts >= 5`). Non-retryable errors (4xx validation from providers) fail fast and mark
   the domain row (`messages.status = failed`) to trigger fallback (§17.4).
5. **Redis is transport, Postgres is truth**: a `core.sweep_pending` job every 5 min re-enqueues stale pending domain
   work (messages `queued` > 10 min, documents `pending_scan` > 10 min, batches `importing` without heartbeat). Losing
   Redis loses no work.
6. **Tenant context**: Dramatiq middleware requires `tenant_id` in every message (except scheduler fan-out jobs) and
   runs the actor inside `tenant_tx` (ADR-004).
7. **Queue dashboard (§22.4)**: Prometheus metrics from Dramatiq + custom gauges (queue depth per queue, outbox lag =
   now − oldest unprocessed `created_at`, dead-letter counts) → dashboards/alerts (ADR-015).
8. Command idempotency (HTTP `Idempotency-Key`) is separate — ADR-003.

## Consequences
- Three Python entrypoints beyond api (worker, dispatcher, scheduler), one image.
- Event → side effect latency ≈ dispatcher interval + queue wait (budget < 10 s p95).
- `outbox_events` grows; retention decision is A-83 (keep all until decided).

## Revisit when
- Outbox lag p95 > 10 s with dispatcher CPU < 50% (→ LISTEN/NOTIFY wake-up), or
- queue lag p95 > 60 s on any queue (→ SCALING.md S-04), or
- Dramatiq maintenance stalls (no release for 18 months) — migrate to Celery behind the same `core.jobs` facade.
