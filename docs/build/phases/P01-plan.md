# P01 — Platform foundation — Plan

- Date: 2026-10-03
- Phase source: `docs/build/PHASES.md` §P01
- Blueprint: §2.2, §6 (preamble), §6.1, §7.5, §21.1–§21.2, §22, §22.2, §24.1, §24.2
- Contracts: DATA_MODEL.md §0 (all), §1 (5 platform tables), §8 (definer functions), §9 (technical tables);
  API.md §1 (conventions), §3.1 (platform commands), §5 (`/me`, `/files/upload-url`), §6 (rate limits);
  INVARIANTS.md INV-PLT-01..22 (P01 rows), INV-SEC-01/02/04/08
- ADRs: 001, 002, 003, 004, 005, 006, 008, 011, 015, 019, 020
- Human decisions in force: A-46 (no Google login), A-47 (ClamAV approved), A-73 (`idempotency_keys`),
  A-74 (`users.password_hash`), A-89 (`job_dead_letters`), A-91 (no paid services; local stand-ins)

## 1. Goal

The secure multi-tenant core every later module uses. P01 has no business feature: no suppliers, NCRs or SCARs.
The only "real" commands are the platform ones (auth, users, plants, tenant settings). They exercise the framework end to end.

## 2. Scope

### 2.1 Tables (migration `0002_platform`)

| Table | Source | Notes |
| --- | --- | --- |
| `tenants` | §6.1, DM §1.1 | `CHECK (tenant_id = id)`; T + SS(select `true`); `tenants_sysfn` policy |
| `plants` | §6.1, DM §1.2 | code regex (A-90); timezone validated in command against `pg_timezone_names` |
| `users` | §6.1, DM §1.3 | `users_email_uq` on `lower(email)` (global, A-03); `password_hash` (A-74); `trg_users_plant_ids_valid` |
| `activity_log` | §6.1, DM §1.4 | CR + `trg_append_only`; actor CHECKs; SS insert-only for suppliers |
| `outbox_events` | §6.1, DM §1.5 | CR+u(processed_at, attempts, last_error, updated_*); pending/dead partial indexes; sysfn policies |
| `idempotency_keys` | DM §9 (A-73) | DELETE granted (expiry cleanup only); SS by `actor_id` |
| `job_dead_letters` | DM §9 (A-89) | CR+u(resolved_at, resolved_by) |

All tables: STD columns, `UNIQUE (tenant_id, id)`, composite FKs, tenant-first indexes (DM §0.4 exceptions only),
`enable_tenant_rls`, `trg_set_updated_at`, no DELETE grant except `idempotency_keys`.

Definer functions (owner `qualloop_sysfn`, `SET search_path = pg_catalog, public, pg_temp`, EXECUTE to `qualloop_app` only, ids only):
`app_resolve_login(email)`, `app_active_tenant_ids()`, `app_claim_outbox_batch(limit)`.
The other §8 definer functions belong to P05 (`magic_links`, `messages`, `supplier_contacts`) and are not created here.

DB hardening (D-3): `REVOKE CREATE ON SCHEMA public FROM PUBLIC`, `REVOKE TEMP ON DATABASE … FROM PUBLIC` (verify P00 baseline; add if missing).

### 2.2 Commands and endpoints (API.md §3.1, §5)

| Endpoint | Perm | Reason | Idem. | Event (derived) |
| --- | --- | --- | --- | --- |
| `POST /auth/login` | public, rate-limited | — | — | — (session start logged in `activity_log`) |
| `POST /auth/logout` | any user | — | — | — |
| `POST /auth/password-reset/request` | public, 3/h per email | — | — | — (email OTP via worker job, mailpit locally) |
| `POST /auth/password-reset/confirm` | public (OTP) | — | — | `USER_PASSWORD_RESET` |
| `POST /users` | A | — | opt | `USER_CREATED` |
| `POST /users/{id}/update` | A | yes if role/can_approve change | opt | `USER_UPDATED` |
| `POST /users/{id}/deactivate` | A | yes | opt | `USER_DEACTIVATED` (kills Redis sessions) |
| `POST /plants` · `POST /plants/{id}/update` | A | — | opt | `PLANT_CREATED` / `PLANT_UPDATED` |
| `POST /tenant/settings/update` | A | yes | opt | `TENANT_SETTINGS_UPDATED` |
| `GET /me` | any | | | |
| `GET /users`, `GET /plants`, `GET /tenant/settings` | A (users); A,Q,V (plants, settings) | | | |
| `POST /files/upload-url` | Q | — | — | — |

Event names marked "derived" go into the event registry. Their exact names are confirmed against ARCHITECTURE.md §7 during the build; none of them is a §22.3 event.

### 2.3 Framework pieces (`api/app/core/`, REPO_LAYOUT)

- `ids.py` (UUIDv7), `money.py` (Paise, StrictInt), `timeutils.py` (plant_today and period helpers; only what P01 needs).
- `db.py`: `tenant_tx(tenant_id, actor)` and `read_tx()`, which set GUCs with `set_config(…, true)` at READ COMMITTED.
- `tenancy.py`: request dependency that sets `app.tenant_id`, `app.actor_type='user'`, `app.actor_id` from the session.
- `auth/`: argon2id passwords, Redis sessions (`sess:{sha256}`, idle 8 h, absolute 7 d, `user_sessions:{user_id}` index),
  cookie `ql_session` (HttpOnly, Secure, SameSite=Lax), CSRF double-submit `ql_csrf` + `X-CSRF-Token` + Origin check,
  login rate limit 5 failures / 15 min per email and per IP, generic error, password-reset OTP (6 digits, hashed, TTL 15 min, 5 attempts).
- `permissions.py`: role set, `requires_can_approve`, plant scope (A-04), actor ≠ `ai`. Viewer is never allowed on any command.
- `commands/base.py`: `Command[In, Out]` + `run_command`: idempotency reservation → authorise → lock → validate →
  mutate → `activity_log` (before/after read-model, reason, actor_type, actor_id, session_id, ip) → `outbox_events` →
  hooks → store idempotent response → commit. Uses one transaction. `state_machine.py` guard → `409 invalid_transition`.
- `idempotency.py`: `Idempotency-Key`; replay with `Idempotency-Replayed: true`; `422 idempotency_mismatch`; `409 conflict` while the first request is in flight; 24 h expiry.
- `errors.py`: RFC 9457 problem+json with `request_id`; DB error mapping (RLS / check / trigger → 404/422, deadlock → 409).
- `outbox/`: writer, registry, dispatcher (`app_claim_outbox_batch`, SKIP LOCKED, backoff `5 s × 2^attempts`,
  dead-letter at `attempts ≥ 5` plus alert log/metric), sweeper stub (`core.sweep_pending`).
- `worker.py`: Dramatiq Redis broker with these middlewares: tenant (rejects messages without `tenant_id`), Retries (max 5, 10 s → 30 min, jitter),
  dead-letter middleware that writes `job_dead_letters` and logs `job_dead_lettered`, and Prometheus.
- `dispatcher.py`, `scheduler.py` (APScheduler 3.x, Redis leader lock `sched:leader` SET NX TTL 30 s, enqueues only).
- `files/`: presigned PUT to the quarantine bucket (≤ 15 min, Content-Type/Length conditions, ≤ 20 MB, purpose allow-list),
  presigned GET ≤ 15 min from the files bucket with tenant-prefix check, key layout `t/{tenant_id}/{kind}/{object_id}/{uuid7}.{ext}`,
  magic-byte sniff (`filetype`), and the `files.scan` job (clamd INSTREAM → SHA-256 → copy to files bucket → delete from quarantine; infected or mismatched files → quarantined).
- `ratelimit.py` (Redis counters), `telemetry.py` (OTel; disabled unless an endpoint is set, ADR-015), log PII masking.
- `seeds/demo.py`: one demo tenant, two plants, and users (admin, quality with can_approve, quality, viewer) with known dev passwords.

### 2.4 Infra (devops)

- compose: `worker`, `dispatcher`, `scheduler` (api image), and `clamav` (`clamav/clamav`, pinned by digest).
- Redis: `requirepass` + ACL file. App user `qualloop_app` is limited to the key patterns from ADR-008, and `@admin`, `@dangerous`, `FLUSHALL`, `KEYS` and `CONFIG` are denied. The default user is disabled (INV-SEC-08).
- CI: clamav service (or EICAR-capable stand-in decided by devops), Redis with ACL; overall coverage gate 75%, plus a core gate of **90%** on `app/core` (PHASES gate "coverage ≥ 90% on core").
- `.env.example` and REPO_LAYOUT env table updated with new variables (S3 keys, bucket names, ClamAV host, Redis user).
- `security-audit.yml` weekly workflow (REPO_LAYOUT [P01]).

### 2.5 Screens

None. PHASES P01 lists no screens, and P01's main agents do not include frontend (SPEC-GAP A-93 below).

## 3. Invariants proven in P01

INV-PLT-01, 02, 03, 04, 05, 06, 07, 09, 10, 11, 12, 13, 14, 15 (catalogue test only), 16, 18, 19, 20, 21, 22 (DB CHECK part);
INV-SEC-01 (files and platform tables part), INV-SEC-02, INV-SEC-04, INV-SEC-08.

## 4. Edge cases

- No tenant GUC → zero rows and every insert rejected (fail closed). GUC from a previous transaction must not leak (transaction-local).
- Pooled connection reused across tenants → GUC reset per transaction.
- `INSERT … RETURNING` is never used on `activity_log` or `outbox_events` (supplier SELECT is `false`).
- Login: unknown email, wrong password and inactive user all return the same generic 401 error, with timing equalised by a dummy hash. A rate-limited login returns `429 rate_limited` with `Retry-After` (API.md §1.4, §6).
- Deactivated user: existing sessions are rejected immediately.
- Session idle and absolute expiry. CSRF missing, mismatched, or wrong Origin → 403.
- Idempotency: same key + same body → replay; different body → 422; concurrent same key → 409; key scoped per actor.
- A command that raises after the mutation → nothing persisted (business row, activity_log, outbox, idempotency row).
- Outbox: two dispatchers → each event claimed once; enqueue failure → attempts+1 and backoff; 5th failure → dead, alert.
- Worker message without `tenant_id` → rejected. A job's queries see only its tenant.
- `users.plant_ids` with another tenant's plant → rejected by trigger.
- Upload: size > 20 MB → 413; disallowed content type → 415; content type that does not match the magic bytes → quarantined; EICAR → quarantined.
  A download for a key with another tenant's prefix → 404. A signed URL expires within 15 min.
- Viewer: every command → 403. Original-file download → 403 (A-70).
- AI actor → denied on every command.

## 5. Test list (qa-engineer writes these first; names from INVARIANTS.md where they exist)

**DB / RLS** — `test_every_table_has_tenant_id_and_forced_rls`, `test_every_rls_table_has_supplier_policy`,
`test_tenant_a_cannot_read_tenant_b_rows_raw_session`, `test_tenant_a_cannot_insert_row_for_tenant_b`,
`test_composite_fk_rejects_cross_tenant_reference`, `test_no_tenant_context_returns_zero_rows`,
`test_no_tenant_context_insert_rejected`, `test_activity_log_update_rejected_db`, `test_activity_log_delete_rejected_db`,
`test_app_role_has_no_delete_privilege_on_domain_tables`, `test_user_plant_ids_must_exist_in_tenant_db`,
`test_definer_functions_have_safe_search_path`, `test_public_has_no_temp_or_create_privilege`,
`test_all_views_are_security_invoker`, `test_data_migrations_set_tenant_guc_and_assert_counts`,
`test_supplier_actor_type_value_consistent`, `test_migrations_up_down_up`.

**API tenant isolation** — tenant A cannot read or write tenant B users and plants through the API (404, never 403).

**Commands** — `test_command_writes_activity_log_and_outbox_in_same_transaction`,
`test_command_failure_rolls_back_activity_log_and_outbox`, `test_activity_log_records_actor_session_and_ip`,
`test_viewer_cannot_call_any_command` (parametrised over the route table), `test_can_approve_commands_reject_without_flag`,
`test_ai_actor_denied_on_every_command`, `test_no_route_accepts_status_field_outside_commands`,
`test_event_catalogue_every_22_3_event_has_emitter` (catalogue present; emitters tracked per phase, marked xfail-by-phase),
`test_idempotency_key_replays_original_response`, `test_idempotency_key_reuse_with_different_body_rejected`, concurrent same key → 409.

**Outbox / workers** — `test_outbox_event_processed_once_with_two_concurrent_dispatchers`,
`test_outbox_retry_backoff_increases_exponentially`, `test_outbox_event_dead_lettered_after_5_attempts_and_alert_emitted`,
`test_job_dead_lettered_after_5_attempts`, `test_dead_lettered_job_recorded_in_job_dead_letters`,
`test_worker_job_runs_with_job_tenant_context`, `test_worker_job_cannot_read_other_tenant`, job without tenant_id rejected,
`test_api_layer_cannot_import_provider_clients`, `test_external_send_carries_idempotency_key` (password-reset email job).

**Auth / security** — `test_password_stored_as_argon2id`, `test_login_rate_limited`,
`test_session_cookie_flags_secure_httponly_samesite`, generic login error, deactivate kills sessions, idle/absolute expiry,
CSRF rejected, password reset OTP happy path / wrong OTP / expired / 5 attempts, `test_redis_app_user_cannot_run_admin_commands`.

**Files** — `test_signed_url_expires_within_15_minutes`, `test_unauthorised_user_cannot_get_signed_url`,
`test_tenant_a_cannot_get_signed_url_for_tenant_b_file`, size/type rejection, magic-byte mismatch quarantined, EICAR quarantined,
clean file promoted with SHA-256.

**Errors / observability** — problem+json shape with `request_id`, no stack trace on 500, log lines carry request_id/tenant_id, PII masked.

## 6. Who does what

| Step | Agent | Files |
| --- | --- | --- |
| Tests first | qa-engineer | `api/tests/**`, `api/tests/factories/**` |
| Migration, core framework, auth, commands, outbox, worker, files, seed | backend-engineer | `api/alembic/**`, `api/app/**`, `api/seeds/**`, `api/pyproject.toml`, `api/uv.lock` |
| Compose services, Redis ACL, ClamAV, CI, Makefile, `.env.example`, weekly audit workflow | devops-engineer (parallel with backend; no file overlap) | `infra/**`, `.github/**`, `Makefile`, `.env.example`, REPO_LAYOUT env table |
| Review | code-reviewer, security-reviewer (parallel) | read-only |
| Verify | verifier | read-only |

data-engineer: not needed (no metrics or money in P01). frontend-engineer and ux-reviewer: not needed (no screens).

## 7. New dependencies (all named in accepted ADRs; none needs its own server except ClamAV, already approved under A-47)

`argon2-cffi` (ADR-008), `dramatiq[redis]` + `apscheduler<4` (ADR-006), `boto3` (ADR-011/020), `filetype` (ADR-011),
`uuid6` (ADR-005), `opentelemetry-*` (ADR-015), `prometheus-client` (ADR-006/015). The clamd client is a small INSTREAM socket client, not a new library unless devops finds one is needed.

## 8. SPEC-GAPs raised by this plan (none changes scope)

| ID | Question | Conservative default |
| --- | --- | --- |
| A-92 | P01 asks for a signed-URL download service, but no domain object owns a file until P03 (documents) / P04 (NCR photos). Is there a generic download endpoint? | No generic `GET /files/...` endpoint. `core.files` exposes `presign_download(caller, key)` with the tenant-prefix and role checks; domain endpoints (`/documents/{id}/download-url` in P03, etc.) call it. Tested at the service level in P01. |
| A-93 | PHASES P01 lists auth but no screens. Where are the login and password-reset screens built? | API only in P01. The login and reset screens are built in P02, the first phase with UI, as the entry to the masters screens. |
| A-94 | Event names for platform commands (user/plant/settings) are not in §22.3 | Derived names (`USER_CREATED`, …) in the registry, marked derived; no consumers in R1 |

## 9. Risks

- Concurrency tests (two dispatchers, same idempotency key) can be flaky. They use real Postgres with explicit barriers, never sleeps.
- ClamAV image is ~1 GB and takes about 1 min to load signatures, which slows `make up` and CI. CI can use the official image with a health wait. If CI time becomes a problem, raise it at the gate rather than silently mocking.
- Running tests as superuser would bypass RLS silently. Every test DB session uses `qualloop_app`, and a guard fixture asserts `current_user`.
- Redis ACL in compose could break existing P00 health/readyz checks; devops updates URLs in one change.
- Coverage ≥ 90% on `app/core` requires the worker/dispatcher/scheduler entrypoints to be tested, not just imported.
