# ADR-015 — Observability

- Status: Accepted (2026-10-03); Sentry free tier selected, no account yet
- Spec: §22 (error tracking, structured logs, uptime checks, queue dashboard), §22.4 (technical + product metrics), §21.5 (personal data)

## Options considered
| Concern | Options | Recommendation |
| --- | --- | --- |
| Logs | **structlog JSON → stdout → CloudWatch Logs** | — |
| Traces/metrics | vendor SDKs; **OpenTelemetry SDK → ADOT collector sidecar → CloudWatch (X-Ray traces, EMF metrics)** | OTel keeps the vendor swappable |
| Error tracking | **Sentry SaaS** (EU/US hosting); self-hosted Sentry/GlitchTip (needs own server); CloudWatch-only | Sentry SaaS with PII scrubbing (`send_default_pii=False`, before_send scrubber for mobile/email/token patterns, no request bodies). This is a **cross-border transfer of personal data under the DPDP Act 2023 (§21.5)**: error payloads may still contain user ids, IPs or names. It needs human/legal approval and an entry in the subprocessor register (§21.6). If declined, use CloudWatch-only alarms (D-8) |
| Uptime | **CloudWatch Synthetics** canaries on `/readyz`, web `/`, supplier `/s/health` | — |
| Queue dashboard | Dramatiq Prometheus middleware + custom gauges → CloudWatch dashboard | — |

## Decision
1. Every log line: `ts, level, msg, request_id, tenant_id, actor_type, user_id|contact_id, route, status, duration_ms, job, event_id`.
   PII rules: mobile/email masked (`+91******3210`), magic-link tokens and OTPs never logged, request bodies not logged.
2. Metrics (§22.4):

| Metric | Source | Alert |
| --- | --- | --- |
| API latency p95 per route group | OTel http server | > 500 ms 15 min |
| DB latency, connections, CPU | RDS | CPU > 70% 15 min; connections > 70% |
| Queue depth per queue, job failures, dead-letters | Dramatiq middleware | any dead-letter; depth > 500 |
| Outbox lag (oldest unprocessed) | dispatcher gauge | > 60 s |
| WhatsApp / email failures | notifications | failure rate > 5% 1 h |
| Extraction failures, import failures, PDF failures | job outcome counters | > 3 consecutive |
| NCR capture time (median, p90) | from `ncrs` (daily job) | product dashboard only |
| Supplier link open → submit conversion | `magic_links.opened_at`, responses | product dashboard |
| SCAR response time, certificate processing time | domain timestamps | product dashboard |

3. Traces: FastAPI, SQLAlchemy, httpx, Redis and Dramatiq instrumentation; trace id = request_id propagated into job
   messages so an outbox event can be traced from command to send.
4. Health: the ALB/ECS target health check uses **`/healthz`** (liveness, no dependencies), so a DB or Redis blip does not drain every task (m7). `/readyz` (DB, Redis, migration head) is used by the deploy step after rollout and by Synthetics canaries.
5. Local: OTel disabled by default; logs pretty-printed when `QL_ENV=local`.

## Consequences
- One dashboard per §22.4 group delivered in P09; alerts route to an email list + on-call WhatsApp group (manual).

## Revisit when
- CloudWatch cost > 15% of infra bill, or trace sampling needs tail-based sampling (→ Grafana/Tempo stack, new ADR).

## Human decision (2026-10-03)

No paid services or accounts now; local stand-ins in dev. Production targets (accounts created only when needed, each still subject to CLAUDE.md §5 before use): Sentry free tier for error tracking (DPDP cross-border note in this ADR still applies). Dev logs to stdout only (A-91).
