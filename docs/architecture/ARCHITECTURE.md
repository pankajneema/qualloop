# QualLoop — Architecture (Phase 0)

Blueprint `§` = `docs/blueprint/Supplier_Quality_OS_Blueprint_FINAL.md`. Scope: Part A only (R1 Core, R1.1).
Companion docs: DATA_MODEL.md, INVARIANTS.md, API.md, SCALING.md, REPO_LAYOUT.md, `docs/adr/`.

---

## 1. System context (C4 level 1)

```text
                 Internal users (browser / phone PWA)
   Head of Quality · SQE · IQC inspector · Purchase/Stores · Plant Head
                               │ HTTPS
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                           QualLoop                                │
│   supplier-quality workflow; ERP stays system of record (§1.1)    │
└──────────────────────────────────────────────────────────────────┘
   ▲ HTTPS (link + OTP, no account)   │ outbound only                │ files in (Excel/CSV), PDFs/Excel out
   │                                   ▼                               ▼
 Supplier quality contact    WhatsApp Business Platform · Email provider · (SMS, A-65)    Customer ERP exports (manual upload, §8 C3)
                                   AI provider (LLM + OCR) — called from workers only
```

| External actor / system | Interaction | Direction | Spec |
| --- | --- | --- | --- |
| Internal users | Web app + PWA | in | §2.2 |
| Supplier contact | Magic link + OTP + scoped session | in | §9 C7 |
| WhatsApp Business Platform (Cloud API or BSP) | templates out; delivery status + STOP in (webhook) | both | §17 |
| Email provider | transactional mail out; bounce/delivery in | both | §17 |
| SMS provider | optional fallback — not built until decided | out | §17.1, A-65 |
| AI provider | OCR + JSON-schema extraction, 8D review assist | out (workers only) | §20 |
| ERP | none live; Excel/CSV exports uploaded by users | in | §1.1, §5.3 |

## 2. Containers (C4 level 2)

| Container | Tech | Responsibility | Scales by | Stage-1 count |
| --- | --- | --- | --- | --- |
| `web` | Next.js (App Router), TypeScript strict, Tailwind | internal UI, inspector PWA, supplier pages (`/s/{token}`) | stateless replicas | 2 |
| `api` | Python 3.12, FastAPI, SQLAlchemy 2 (sync), Pydantic v2, gunicorn + uvicorn workers | commands, queries, auth, webhooks, signed URLs | stateless replicas | 2 |
| `worker` | same image, `dramatiq` entrypoint | outbox handlers, notifications, imports, AI extraction, PDFs, risk/scores, scans | processes × threads, per-queue | 1 (all queues) |
| `dispatcher` | same image, `python -m app.core.outbox.dispatcher` | polls `outbox_events` (`SKIP LOCKED`), enqueues handler jobs | 1–2 replicas (safe concurrent) | 1 |
| `scheduler` | same image, APScheduler | enqueues cron jobs per tenant (daily scan, nightly risk, monthly snapshot, reminders, sweepers) | **exactly 1** (Redis lock as guard) | 1 |
| `postgres` | PostgreSQL 16 managed | system of record, RLS | vertical, then replica | 1 |
| `redis` | Redis 7 managed | job broker, internal sessions, OTPs, rate limits, idempotency fast-path, cache | vertical | 1 |
| `object storage` | S3-compatible, Indian region, private | photos, documents, evidence, import files, PDFs, exports | — | 1 bucket + quarantine bucket |
| `virus scanner` | ClamAV `clamd` sidecar to worker (**requires human approval, A-47**) | scans uploads before use | with worker | 1 |
| `mail` (local) | Mailpit | local email sink | — | local only |

All Python containers share one image (`api/Dockerfile`), different commands — one build, one dependency set.

## 3. Components per module (C4 level 3)

Every backend module under `api/app/<module>/` has the same internal shape (REPO_LAYOUT.md):
`models.py` (SQLAlchemy tables owned by the module), `schemas.py` (Pydantic I/O), `commands.py` (command handlers),
`queries.py` (read models), `service.py` (**public interface** for other modules), `router.py` (HTTP), `jobs.py`
(Dramatiq actors), `events.py` (event-type constants + payload schemas), `hooks.py` (in-transaction hook
subscriptions), `policies.py` (permission rules).

| Module (§22.1) | Owns tables | Key components | Public service (examples) |
| --- | --- | --- | --- |
| `core` | tenants, plants, users, activity_log, outbox_events, idempotency_keys | config, db session + tenant GUC, auth/session, permissions, command base, audit writer, outbox writer + dispatcher, hooks bus, file service (signed URLs, scan), time/period utils, numbering, money utils, error mapping, logging/OTel | `run_command`, `current_actor`, `record_activity`, `emit_event`, `plant_today`, `month_bounds`, `signed_url` |
| `masters` | suppliers, supplier_contacts, customers, parts, customer_parts, supplier_parts | supplier/contact lifecycle, status command, archive | `get_supplier`, `get_contact`, `active_quality_contact` |
| `imports` | import_batches, import_records | parser (openpyxl/csv), column detection, mapping store, validators per entity, dedupe (file hash, row hash, natural key), reconciliation report writer | `start_batch` |
| `receipts` | grn_receipts, defect_codes, defect_events, defect_event_attributions | receipt create/correct, defect event service, attribution (4 decisions), suggestion engine, canonical/unreconciled calculator (`v_receipt_rejections`) | `rejections_for_receipts(as_of)`, `create_defect_events`, `signature_of` |
| `ncr` | ncrs, ncr_photos, ncr_containment, ncr_costs | capture, contain, dispose, cancel, reopen, close, cost lines, repeat detection | `mark_linked`, `mark_verification`, `mark_closed`, `ncr_signatures` |
| `scar` | scars, ncr_scar_links, scar_responses, scar_evidence, scar_reviews | decision gate + severity policy, SCAR lifecycle, links, reviews, reminders/escalations, **supplier routes `/supplier/scar/*`** (`router_supplier.py`, response drafts/submit/evidence/messages) | `reopen_for_effectiveness`, `enter_effectiveness`, `close_after_effectiveness` |
| `effectiveness` | effectiveness_checks | check creation on accept, watcher (new receipts / defect events), 90-day pending, extend, close-no-data; **drives SCAR close**: when all checks of a SCAR pass (system) or on close-no-data, calls `scar.service.close_after_effectiveness` | `pending_checks_for(supplier, part)` |
| `finance` | ncr_costs (read via ncr), debit_notes, debit_note_allocations, recoveries, recovery_allocations, write_offs | debit note create with allocations, pro-rata recovery allocator, write-off, balances, cohort & cash views | `cost_line_balances`, `exposure_cohort`, `cash_view` |
| `documents` | documents, certificates, document_requirements, supplier_requirements, certificate_exceptions, ai_extractions | upload registration, extraction pipeline orchestration, review, requirement lifecycle, validity/compliance functions, daily scan, **supplier routes `/supplier/requirements`, `/supplier/documents/*`** | `certificate_validity`, `requirement_compliance(as_of)` |
| `supplier_access` | magic_links, supplier_sessions | token issue (32 bytes, hash) called by the notification send job, link exchange → `ql_pre`, OTP (Redis + `otp_failed_count`), session resolver + supplier GUCs, revocation hook handlers; public routes `/supplier-access/*`, `/supplier/session`, `/supplier/logout` only | `issue_link_for_message`, `require_supplier_session(purpose)`, `revoke_for_contact`, `revoke_for_object` |
| `scoring` | supplier_scores_monthly, quality_targets | metrics service (§12) with trust signals, as-of calculators, score (§14), snapshot job, explain payloads | `metrics(scope, period, as_of)`, `score(...)` |
| `risk` | risk_events, supplier_risk_current, risk_overrides | rule evaluators (11), recompute (nightly + on event), reasons, trend, on-watch suggestion | `current_risk(supplier)` |
| `notifications` | messages, contact_consents, tasks | notification-type → channel/template/language resolver, WhatsApp/email/in-app adapters, consent & STOP, delivery webhooks, fallback timer, daily digest | `notify(notification_type, object, recipients, variables)` |
| `ai` | (none; `ai_suggestions` if approved, A-63) | provider interface, OCR, extraction schemas + prompts (versioned), validators, 8D review assist, benchmark harness | `extract_certificate(bytes) -> Extraction`, `review_8d(response) -> Suggestions` |
| `reports` | (none) | My Work aggregator, Supplier 360, **case page payload (`GET /scars/{id}` composite)**, monthly report & supplier card (HTML → PDF), Excel exports | `my_work(user)` |
| `api` | (none) | app factory, router composition, middleware (request id, auth, tenant, CSRF, rate limit), error handlers, `/healthz` `/readyz`, webhooks | — |

### 3.1 Module boundary rules (enforced by `import-linter` in CI)

1. A module may import another module **only** via `<module>.service`, `<module>.events`, `<module>.schemas` (public DTOs). Never `models`, `commands`, `queries` of another module.
2. Allowed dependency direction (a module may depend only on modules listed to its right/below):

| Module | May import |
| --- | --- |
| `core` | nothing in `app` |
| `ai` | core |
| `masters` | core |
| `notifications` | core, masters; calls `supplier_access.issue_link_for_message` through the hook bus `core.hooks` (`message.needs_link`), because supplier_access sits above notifications |
| `supplier_access` | core, masters, notifications |
| `receipts` | core, masters |
| `ncr` | core, masters, receipts |
| `documents` | core, masters, ai, notifications, supplier_access (incl. `require_supplier_session` for its supplier routes) |
| `scar` | core, masters, receipts, ncr, supplier_access (incl. `require_supplier_session` for its supplier routes), notifications, ai |
| `effectiveness` | core, masters, receipts, ncr, scar (drives `close_after_effectiveness`, `reopen_for_effectiveness`), notifications |
| `finance` | core, masters, ncr |
| `imports` | core, masters, receipts, ncr, documents |
| `scoring` | core, masters, receipts, ncr, scar, effectiveness, finance, documents |
| `risk` | core, masters, receipts, ncr, scar, effectiveness, documents, scoring |
| `reports` | all of the above (read services only) |
| `api` | all routers |

3. Reactions in the **same transaction** that would invert this order (e.g. masters → supplier_access revocation on
   contact disable; masters → documents requirement creation on supplier create) use the in-process hook bus
   `core.hooks` (`publish("contact.disabled", ctx, contact_id)`; subscribers registered at startup). Hooks run inside
   the caller's transaction; a failing hook rolls back the command.
4. Reactions that may be **asynchronous** use outbox events (§7 below).
5. Only `notifications/` imports channel clients (WhatsApp/email/SMS) (§17.2). Only `ai/providers/` imports AI SDKs,
   and `ai.providers` may be imported only from `*.jobs` modules (§24.1.3). `ai` may not import `finance`, `masters`
   commands, `scar` commands, `documents` commands (§20.1).
6. `risk` may not import `masters.service.change_status` (§15.6 risk never changes status).

## 4. Request flow (internal user)

```text
Browser ──HTTPS──► ALB ──/api/*──► api (gunicorn/uvicorn)
                     └─other────► web (Next.js)
api middleware order:
 1 RequestId (X-Request-ID in/out, contextvar)        5 RateLimit (Redis)
 2 Logging + OTel span                                 6 CSRF (double-submit + Origin) for POST
 3 Session auth (ql_session → Redis → user, tenant)    7 Router → dependency `db_tx(actor)`:
 4 Plant scope loader (users.plant_ids)                  BEGIN; set_config('app.tenant_id'…, true);
                                                         set_config('app.actor_type'/'app.actor_id'…); handler; COMMIT
```

Queries run in a read-only transaction (`SET TRANSACTION READ ONLY`) with the same GUCs.

## 5. Command flow (ADR-003)

```text
POST /api/v1/scars/{id}/accept   (Idempotency-Key optional)
 └─ run_command(AcceptScar, input, ctx) — one DB transaction:
     1 idempotency: INSERT idempotency_keys … ON CONFLICT → replay / 409 / 422
     2 authorize: role, can_approve, plant scope (policies.py)
     3 load + lock aggregate: SELECT … FOR UPDATE
     4 validate: Pydantic input + state-machine guard (transition table) + business rules
     5 mutate: ORM changes (DB triggers re-check invariants)
     6 activity_log: object, action, before, after, reason, actor_type, actor_id, session_id, ip
     7 outbox_events: event_type, payload (ids), event_id
     8 in-transaction hooks (core.hooks)
     9 store idempotent response; COMMIT
 └─ map DB errors: check/trigger violation → 422 invariant_violation; serialization → 409 conflict
```

Each state machine (§7.1 NCR, §7.2 SCAR, §7.3 certificate, §7.4 requirement, effectiveness result, debit note
status) is a declarative transition table in the owning module (`state_machine.py`): `(from, command) → to`, plus
guard functions. Tests enumerate allowed and forbidden pairs from the table.

## 6. Job / outbox flow (ADR-006)

```text
command txn ──► outbox_events (processed_at NULL)
dispatcher loop (every 1 s, batch 100):
  BEGIN; rows = app_claim_outbox_batch(100)  -- FOR UPDATE SKIP LOCKED, cross-tenant, oldest first,
                                              -- excludes rows still in backoff (updated_at + 2^attempts × 5 s > now)
  for row: for handler in registry[row.event_type]:
              dramatiq.send(handler, tenant_id, event_id, payload, message_id = f"{event_id}:{handler}")
           UPDATE outbox_events SET processed_at = now()    (under row's tenant GUC)
  on enqueue error: attempts += 1, last_error; attempts reaching 5 → dead-letter alert
  COMMIT
worker actor (retries: max 5, exponential backoff 10 s → 30 min, then Dramatiq dead-letter queue + alert):
  with tenant_tx(tenant_id, actor=system): check handler idempotency (domain state or messages.idempotency_key) → act
```

Redis is a transport, not a record. Durable "pending" state lives in Postgres (`messages.status = queued`,
`documents.status = pending_scan`, `ai_extractions` absent, `import_batches.status = importing`); a sweeper job every
5 minutes re-enqueues stale pending work, so losing Redis loses no work (ADR-006).

### 6.1 Queues

| Queue | Actors | Concurrency (Stage 1) |
| --- | --- | --- |
| `default` | outbox handlers, risk recompute on event, hooks for SCAR/NCR follow-ups | 4 threads |
| `notifications` | send WhatsApp/email/in-app, fallback timer, webhooks processing | 4 |
| `imports` | validate, import, report | 1 |
| `ai` | scan, OCR, extraction, 8D review | 2 |
| `reports` | PDF, Excel exports | 1 |
| `scheduled` | daily scan, nightly risk, monthly snapshot, reminders, sweepers | 2 |

### 6.2 Scheduled jobs (scheduler → per-tenant fan-out via `app_active_tenant_ids()`)

| Job | When (plant local, Asia/Kolkata default) | Spec | Idempotency |
| --- | --- | --- | --- |
| `documents.daily_scan` | 06:00 daily | §8 C10, §22.3 | compare computed state with last sent message state (R4-19/20) |
| `scar.reminders` | hourly | §9 C7 | messages idempotency key `(scar, type, due-bucket)` |
| `effectiveness.watch` | hourly + on `RECEIPT_CREATED`/`DEFECT_EVENT_*` | §9 C8 | deterministic re-evaluation |
| `risk.recompute_all` | 02:00 nightly | §15.1 | recompute from conditions (pure) |
| `scoring.monthly_snapshot` | 1st of month 00:30 | §14.5 | unique `(supplier, plant, period_start)`, `ON CONFLICT DO NOTHING` |
| `notifications.daily_digest` | 08:00 | §17.2 `DAILY_DIGEST` | key `(user, date)` |
| `notifications.fallback_check` | every minute | §17.4 (15 min) | message state |
| `core.sweep_pending` | every 5 min | ADR-006 | re-enqueue stale pending |
| `core.idempotency_cleanup` | hourly | ADR-003 | delete expired keys |

Scheduler holds a Redis lock `sched:leader` (TTL 30 s, renewed) so a second replica never double-fires.

## 7. Event catalogue

| Event | Source | Handlers | Spec |
| --- | --- | --- | --- |
| `NCR_CREATED` | ncr.create | notifications (critical → HoQ), risk.recompute(supplier), effectiveness.evaluate | §22.3 |
| `NCR_CONTAINED` | ncr.contain | scar.decision_recommendation (cache), notifications | §22.3 |
| `SCAR_ISSUED` | scar.issue | notifications `SCAR_ISSUED` (send job creates the magic link, M3), risk | §22.3 |
| `SCAR_RESPONSE_RECEIVED` | supplier submit | notifications (SQE), ai.review_8d | §22.3 |
| `SCAR_SENT_BACK` | scar.send_back | notifications `SCAR_SENT_BACK` | §22.3 |
| `SCAR_ACCEPTED` | scar.accept | effectiveness.create_checks, notifications `SCAR_ACCEPTED` | §22.3 |
| `SCAR_OVERDUE` | scar.reminders job | notifications `SCAR_OVERDUE`, risk | §22.3 |
| `EFFECTIVENESS_PASSED` / `_FAILED` / `_EXTENDED` / `_CLOSED_NO_DATA` | effectiveness | SCAR close/reopen is done synchronously by effectiveness via `scar.service` in the same transaction; handlers: notifications `EFFECTIVENESS_FAILED`, risk | §22.3 |
| `DEFECT_EVENT_ATTRIBUTED` | receipts.attribute | effectiveness.evaluate, risk | §22.3 |
| `DEBIT_CREATED` / `DEBIT_RECOVERED` / `DEBIT_WRITTEN_OFF` | finance | (none external in R1; audit/metrics freshness) | §22.3 |
| `CERTIFICATE_VALIDITY_CHANGED` / `REQUIREMENT_OVERDUE` | documents.daily_scan | notifications `DOC_EXPIRY` / `DOC_REQUEST`, tasks, risk | §22.3 |
| `RISK_CHANGED` | risk.recompute | notifications (turned High → HoQ digest) | §22.3 |
| `SUPPLIER_STATUS_CHANGED` | masters.change_status | risk (display), notifications (none required) | §22.3 |
| Derived (each command emits one, §7 "emit an outbox event"): `NCR_SCAR_DECIDED`, `NCR_DISPOSED`, `NCR_CANCELLED`, `NCR_REOPENED`, `NCR_CLOSED`, `SCAR_CREATED`, `SCAR_NCR_LINKED`, `SCAR_CANCELLED`, `SCAR_CLOSED`, `SCAR_REOPENED`, `SCAR_RESPONSE_STARTED`, `CONTACT_DISABLED`, `CONTACT_REPLACED`, `DOCUMENT_UPLOADED`, `DOCUMENTS_REQUESTED`, `CERTIFICATE_APPROVED`, `CERTIFICATE_REJECTED`, `IMPORT_CONFIRMED`, `RECEIPT_CREATED`, `RECEIPT_CORRECTED`, `SUPPLIER_SESSION_STARTED`, `MAGIC_LINK_REVOKED`, `REPORT_REQUESTED` | commands | per module | §7, §22.2 |

## 8. Key flows

### 8.1 Supplier magic link + OTP + scoped session (§9 C7; ADR-009)

```text
SQE: POST /scars/{id}/issue
  └ checks quality contact: unverified ≥ 180 d → no send, SQE task "re-verify contact" (§8 C2)
  └ outbox SCAR_ISSUED → notifications: WhatsApp template (if opted in) + email (always) with https://app/s/{base64url(token)}
(Link creation happens in the notification send job, not in issue — M3:
  one txn: revoke previous link of this message ('reissued') → insert magic_links → messages.magic_link_id; commit;
  then provider call with the token held in memory only. Lost/retried send ⇒ new link, old revoked.)
Supplier opens https://app/s/{token} → Next.js route handler (no HTML) → POST /api/v1/supplier-access/exchange {token}
  (private network) → app_resolve_magic_link(sha256) → tenant; checks → signed pre-OTP handle (tenant, link, 15 min)
  → Set-Cookie ql_pre (HttpOnly, Secure, SameSite=Lax) → 303 /s  (token gone from URL; /s/* never logged at edge/app)
GET /api/v1/supplier-access/current (ql_pre) → masked destination, customer name
POST …/request-otp (ql_pre; per-link + per-IP limits) → 6-digit OTP, Redis otp:{link_id} (argon2, TTL 10 min)
POST /api/v1/supplier-access/{token}/verify-otp with {token}=current (A-85) → compare; failure → magic_links.otp_failed_count+1
  (10 → revoke); success → supplier_sessions (otp_verified_at, expires_at = +7 d, ip, ua); cookie ql_sup = sign(tenant, session)
Every /supplier/* request: verify signature → GUCs app.tenant_id, app.actor_type='supplier_session', app.actor_id (contact),
  app.supplier_session_id, app.magic_link_id, app.scope_object_type/id, app.supplier_id → load session (not revoked/expired,
  contact active, link not revoked) → object fixed by session → scoped RLS (DATA_MODEL §0.5) → allow-list schema
Revocation: contact disabled/replaced (hook), SCAR closed/cancelled, manual, OTP failures → magic_links.revoked_at + all sessions revoked_at
```

### 8.2 Metrics data flow incl. as-of snapshots (§11.4, §12, §14.5; ADR-007)

```text
grn_receipts ─┐                          ┌─► live metrics API (current period, now)
defect_events ─┼─► receipt_rejections_as_of(cutoff) ─┤
attributions ─┘    (canonical, unreconciled per receipt)  └─► monthly snapshot job (cutoff = period_end+1 00:00 plant tz)
scars ──► scar_due_status(..., as_of)                         → supplier_scores_monthly (immutable, inputs jsonb)
ncr_costs, allocations, recoveries, write_offs ─► v_cost_line_balances ─► cohort view / cash view
certificates, supplier_requirements, certificate_exceptions ─► requirement_compliance(today) ─► document score, risk rules
risk rule evaluators ◄── all of the above ─► risk_events (active/cleared) ─► supplier_risk_current
```

- Metrics are computed by SQL (set-based) in `scoring/queries.py`; every calculator takes `(scope, period, as_of)`.
- Closed periods: `as_of = cutoff`; only rows with event timestamps ≤ cutoff (ADR-007 table) are used.
- Snapshots are written once on the 1st; later reads of a closed month use the snapshot; the "Corrections to earlier
  periods" list is computed from `activity_log` rows after the cutoff that touched inputs of that period.
- Stage 1: no materialised tables. Stage 2 trigger in SCALING.md.

### 8.3 Upload & import flows (§8 C3, §20.2; ADR-011)

```text
client → POST /files/upload-url {purpose, content_type, size ≤ 20 MB} → presigned PUT (quarantine bucket, 15 min, key t/{tenant}/…)
client PUTs file → POST <domain register command> (e.g. /documents, /ncrs/{id}/photos, /imports)
  → row with status pending_scan / outbox DOCUMENT_UPLOADED
worker scan: magic-byte sniff (PDF/JPEG/PNG; XLSX/CSV for imports) + clamd → copy to private bucket → status available
  (infected/mismatch → quarantined, user told what to do)
documents: available → ai.extract (OCR if no text layer) → ai_extractions + certificate(pending_review) → review queue
imports: validate job → preview JSON in object storage → user confirms → import job → import_records + report.xlsx
```

## 9. Deployment topology (Stage 1, ADR-017)

```text
AWS ap-south-1 (Mumbai)  — account: qualloop-prod (staging in separate account, same shape, smaller)
 Route 53 → CloudFront (+ AWS WAF; no logging of /s/*) → ALB (TLS, ACM; access logs off)
   ├─ /api/*, /healthz, /readyz → ECS Fargate service `api` (2 tasks, private subnets; target health check `/healthz`)
   └─ /*                        → ECS Fargate service `web` (2 tasks)
 ECS Fargate services: `worker` (1 task, + clamd sidecar if approved), `dispatcher` (1), `scheduler` (1)
 RDS PostgreSQL 16 (single-AZ Stage 1, PITR 7 d, KMS) — private subnets
 ElastiCache Redis 7 (single node Stage 1) — private subnets
 S3: qualloop-prod-files (private, versioned, KMS, Block Public Access), qualloop-prod-quarantine (lifecycle 7 d)
 Secrets Manager (DB creds, session/HMAC keys, provider keys) → ECS task env
 ECR (images), CloudWatch Logs + metrics, OTel collector (ADOT sidecar), alarms → email/WhatsApp to on-call
 Egress: NAT gateway → WhatsApp/email/AI provider endpoints
 DR copies: RDS snapshots + S3 replication to ap-south-2 (Hyderabad) — ADR-018
```

Migrations run as a one-off ECS task (`alembic upgrade head`, role `qualloop_owner`) before the new task definition
rolls out; the app uses `qualloop_app`. Expand/contract migration policy (ADR-016).

## 10. Environments (ADR-016)

| Env | Where | Data | Providers | Deploy trigger | Access |
| --- | --- | --- | --- | --- | --- |
| local | Docker Compose (`infra/compose.yaml`): postgres:16, redis:7, s3 (SeaweedFS, ADR-020), mailpit, (clamav if approved), api, worker, dispatcher, scheduler, web | seed (`make seed`) | email → Mailpit; WhatsApp → console/fake adapter; AI → fake provider (fixtures) | `make up` | developer |
| CI | GitHub Actions (repo host to be confirmed by human, ADR-016) with service containers postgres:16, redis:7, SeaweedFS S3 (started as steps, ADR-020) | fixtures/factories | fakes only | every push / PR | — |
| staging | AWS ap-south-1, staging account | synthetic seed + anonymised samples only (never real customer data) | provider sandboxes (WhatsApp test number, email sandbox, AI provider with test key) | merge to `main` (auto) | team |
| prod | AWS ap-south-1, prod account | customer data | live | tag `vX.Y.Z` + manual approval in CI (CLAUDE.md §5) | restricted, break-glass |

## 11. Cross-cutting decisions index

| Topic | ADR |
| --- | --- |
| Modular monolith & boundaries | ADR-001 |
| Backend runtime & tooling | ADR-002 |
| Command framework, state machines, audit log | ADR-003 |
| Tenancy & RLS | ADR-004 |
| IDs, money, time | ADR-005 |
| Outbox, jobs, idempotency, retries, scheduler | ADR-006 |
| Metrics engine | ADR-007 |
| Internal authentication & authorisation | ADR-008 |
| Supplier access & threat model | ADR-009 |
| Notifications & messaging providers | ADR-010 |
| File storage, signed URLs, virus scanning | ADR-011 |
| AI provider abstraction & governance | ADR-012 |
| Frontend, tokens, i18n, PWA | ADR-013 |
| PDF & Excel generation | ADR-014 |
| Observability | ADR-015 |
| CI/CD & environments | ADR-016 |
| Hosting & deployment | ADR-017 |
| Backup & restore | ADR-018 |
| Security baseline & secrets | ADR-019 |

## 12. Open questions

All ambiguities are tracked in `docs/build/OPEN_QUESTIONS.md` (A-01 … A-90). Items needing human approval before
build: A-47 (ClamAV), A-63 (`ai_suggestions` table), A-73 (`idempotency_keys` table), A-89 (`job_dead_letters` table), A-74/A-86/A-87 (technical columns),
cloud and paid providers (ADR-010, ADR-012, ADR-015, ADR-017).
