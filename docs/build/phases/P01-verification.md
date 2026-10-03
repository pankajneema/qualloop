# P01 — Platform foundation — Independent Verification

- Date: 2026-10-03
- Verifier: independent verifier, fresh context. No code was edited; the only file written is this report.
- HEAD: `8de9d23 fix(p01): address review findings` (P01 commits: `18c750c test(p01)`, `94b8616 feat(p01)`, `8de9d23 fix(p01)`).
- Environment: macOS, Docker. Host port 5432 is taken by another local Postgres, so `QL_PG_HOST_PORT=55432` was used for every `make` call.
- Clean state: `make down V=1` (removed `pgdata`, `clamdata`, `s3data` volumes and the network), then `make up`.

## Verdict: FAIL

Every technical gate item has a named, passing test that I read and ran, and the coverage gate passes.
**One gate item has no evidence:** "security-reviewer has no Critical/High". The repository has no security-review
report for P01. There is only indirect evidence: the commit `fix(p01): address review findings`,
`P01-tests.md` "Review regressions (items 1 to 19 of the review fix list)", and OPEN_QUESTIONS entries that cite
"security review L-1 / L-6". None of these states the final severity count after the fixes. Under the verification rules,
a gate item without evidence cannot pass.

## Gate table

| # | Gate item (PHASES.md P01) | Evidence (test name / command) | Result |
|---|---|---|---|
| 1 | All tests green | `make test-api`: **865 passed, 19 xfailed, 0 failed, 0 skipped** (109 s). The 19 xfails are all `test_event_catalogue_every_22_3_event_has_emitter[<EVENT>]`, each with reason "emitter … is built in P0N, not in P01" (expected by plan §5). `make test-web`: 8 passed. `make e2e`: 2 passed (desktop-1440, phone-360). | PASS |
| 2a | Tenant A cannot read/write Tenant B — **API** | `tests/security/test_tenant_isolation_api.py` (11 tests), e.g. `test_tenant_a_cannot_read_tenant_b_users_api` (asserts no B ids/emails in A's list), `test_tenant_a_cannot_update_tenant_b_user_api` (404 `not_found`, B row unchanged), `test_tenant_a_cannot_deactivate_tenant_b_user_api`, `test_foreign_and_nonexistent_ids_are_indistinguishable` (identical 404 bodies), `test_cross_tenant_actions_leave_no_audit_or_outbox_trace_in_either_tenant`, `test_sessions_do_not_cross_tenants_on_a_shared_connection_pool`. | PASS |
| 2b | — **raw ORM session** | `tests/security/test_tenant_isolation_orm.py` (6 tests): select returns only own tenant, `session.get` of a foreign PK is `None`, adding a B row raises "row-level security", foreign UPDATE rowcount 0, no GUC sees nothing, DELETE "permission denied". Plus `tests/integration/db/test_rls_platform_tables.py::test_tenant_a_cannot_read_tenant_b_rows_raw_session`, `::test_tenant_a_cannot_insert_row_for_tenant_b`, `::test_composite_fk_rejects_cross_tenant_reference`, `::test_no_tenant_context_returns_zero_rows`, `::test_no_tenant_context_insert_rejected`. Guard: `tests/conftest.py:128-159` fails any test connection that is superuser/BYPASSRLS or not `qualloop_app`. | PASS |
| 2c | — **worker** | `tests/integration/worker/test_worker_jobs.py::test_worker_job_runs_with_job_tenant_context` (GUC = job tenant, actor_type `system`), `::test_worker_job_cannot_read_other_tenant` (counts of B plants/users/tenant row all 0), `::test_worker_job_cannot_write_for_another_tenant` ("row-level security"), `::test_consecutive_jobs_for_different_tenants_on_one_pooled_connection_do_not_leak_context`, `::test_job_without_a_valid_tenant_id_is_rejected_and_never_runs[5 variants]`. Real Dramatiq worker on Redis. | PASS |
| 3a | Command writes activity_log + outbox in the same transaction | `tests/integration/commands/test_command_audit_and_outbox.py::test_command_writes_activity_log_and_outbox_in_same_transaction[6 commands]`: exactly one audit row and one outbox row, and **`xmin` of business row = audit row = outbox row** (same transaction id). Also `::test_idempotency_row_is_written_in_the_same_transaction_as_the_business_change`. | PASS |
| 3b | Failure rolls back both | `::test_command_failure_rolls_back_activity_log_and_outbox[outbox-write-fails, activity-log-write-fails, idempotent-response-store-fails]`: a NOT VALID CHECK makes the later write fail; asserts no plant, no audit, no outbox, no idempotency row; retry with the same key succeeds and is not a replay. Also `tests/integration/commands/test_hook_bus.py::test_a_raising_hook_rolls_back_business_audit_outbox_and_idempotency_rows`. | PASS |
| 4a | Outbox: processed exactly once under two concurrent workers | `tests/integration/outbox/test_dispatcher.py::test_outbox_event_processed_once_with_two_concurrent_dispatchers`: two threads, a `Barrier(2)` holds both inside their claimed batches; asserts the 10 events are enqueued exactly once (sorted equality) and all `processed_at` set. `::test_app_claim_outbox_batch_skip_locked_returns_disjoint_batches_to_open_transactions` (two open transactions get disjoint 5+5 batches without blocking). Code: `app/core/outbox/dispatcher.py` claims via `app_claim_outbox_batch` (SKIP LOCKED) in one transaction with per-row SAVEPOINT. | PASS |
| 4b | Retries then dead-letter | `::test_outbox_retry_backoff_increases_exponentially` (not claimable at window−2 s, claimable at window+2 s for 10/20/40/80 s), `::test_outbox_event_dead_lettered_after_5_attempts_and_alert_emitted` (attempts = 5, never claimed again, exactly one `outbox_event_dead_lettered` error log line), `::test_last_error_is_truncated_to_four_kilobytes`; jobs: `test_worker_jobs.py::test_job_dead_lettered_after_5_attempts` (5 executions), `::test_dead_lettered_job_recorded_in_job_dead_letters` (durable row + `job_dead_lettered` alert). | PASS |
| 5a | Viewer cannot call any command | `tests/integration/commands/test_permissions_api.py::test_viewer_cannot_call_any_command[7 paths]` parametrised over hard-coded admin commands, `/files/upload-url`, and every POST route of the real app; asserts 403 `forbidden` and no new activity_log row. Live check: viewer `POST /api/v1/plants` → 403 (log below). | PASS |
| 5b | `can_approve` required where flagged | P01 registers no +CA command, so `tests/unit/test_permissions.py::test_can_approve_commands_reject_without_flag` is vacuous (its docstring says so). The gate is proven by `tests/integration/commands/test_can_approve_pipeline.py` (6 tests), which runs a throwaway +CA command through the real `run_command`: quality and admin without the flag → 403 and no rows written; with the flag → runs and is audited; viewer with the flag → still 403. | PASS |
| 6a | Signed URL expires (≤ 15 min) | `tests/integration/files/test_upload_url_api.py::test_signed_url_expires_within_15_minutes` (`expires_at` and `X-Amz-Expires` ≤ 900 s), `tests/integration/files/test_presigned_download.py::test_signed_url_expires_within_15_minutes`, `::test_a_longer_expiry_than_15_minutes_cannot_be_requested[3600, 86400, 901]`, `::test_the_signed_url_downloads_the_object_and_then_actually_expires` (a real SeaweedFS GET works, then returns 400/403 after 2.5 s). | PASS |
| 6b | Unauthorised user cannot download | `test_presigned_download.py::test_unauthorised_user_cannot_get_signed_url` (no caller → Unauthenticated; supplier_session/ai → Forbidden), `::test_unauthorised_user_cannot_get_signed_url_viewer_matrix[6]` (A-70), `::test_tenant_a_cannot_get_signed_url_for_tenant_b_file` (404), `::test_unscanned_file_not_downloadable`; upload side `test_upload_url_api.py::test_unauthorised_user_cannot_get_signed_url`. Note: download is tested at the service level (`core.files.presign_download`) because no download endpoint exists in P01 (SPEC-GAP A-92). | PASS |
| 7 | Migrations up/down/up | `make migrations-roundtrip` (exit 0; log below); `tests/integration/migrations/test_platform_migration.py::test_migrations_up_down_up` (tables/functions present → absent after `downgrade base` → present again; definers have the safe search_path), `::test_after_a_round_trip_rls_is_forced_and_the_app_role_still_works`, `::test_downgrade_one_step_removes_only_the_platform_objects`; `tests/integration/test_migrations.py::test_upgrade_downgrade_upgrade`. The compose `migrate` container also exited 0 on the clean volume. | PASS |
| 8 | Coverage ≥ 90 % on core | `make coverage-core` (`coverage report --include='app/core/*' --fail-under=90`): **TOTAL 93 %**. Overall: **90.97 %** (gate 75 %). | PASS |
| 9 | Security-reviewer has no Critical/High | **No artifact.** No P01 security-review report exists in `docs/` or anywhere else in the repo. The verifier cannot see the reviewer's output. | **FAIL (no evidence)** |

Lint and types (CLAUDE.md §6), not a separate P01 gate line but part of "build green": `make lint` exit 0. Results: ruff "All checks passed!", ruff format "149 files already formatted",
mypy strict "Success: no issues found in 148 source files", import-linter "1 kept, 0 broken", eslint/prettier/tsc clean.

## Failures

### F-1 Gate 9: no evidence that the security review ended with zero Critical/High findings

Reproduce:
```
ls docs/build/phases/            # P00-verification.md P01-plan.md P01-test-contract.md P01-tests.md
grep -rli "security review\|security-review" docs   # only ADRs, PHASES, plan, test-contract, OPEN_QUESTIONS; no P01 review report
git log --format=%s 9ed6627..HEAD   # fix(p01): address review findings  (no report committed)
```
To fix: commit the security-reviewer's P01 report, with its findings and severities, plus a re-review after `8de9d23`
that shows zero open Critical/High (for example `docs/build/phases/P01-security-review.md`). Then re-run verification.
No code change is implied. The verifier's own probes found no Critical/High issue (see the spot-checks and live probes below),
but they do not replace the gate's named reviewer.

## Command log (trimmed, real output)

```
$ QL_PG_HOST_PORT=55432 make down V=1
 Volume qualloop_pgdata Removed / Volume qualloop_clamdata Removed / Volume qualloop_s3data Removed / Network qualloop_default Removed
$ QL_PG_HOST_PORT=55432 make up            # 29.9 s
 Container qualloop-clamav-1 Healthy  ... api-1 Healthy  postgres-1 Healthy  mailpit-1 Healthy  redis-1 Healthy  worker-1 Healthy
 Container qualloop-s3-init-1 Exited  migrate-1 Exited  s3-1 Healthy  scheduler-1 Healthy  dispatcher-1 Healthy  web-1 Healthy
$ docker logs qualloop-migrate-1 | tail -2 ; exit code
 Running upgrade  -> 0001, baseline ...
 Running upgrade 0001 -> 0002, platform: tenants, plants, users, activity_log, outbox_events, idempotency_keys, job_dead_letters
 0
$ curl -s localhost:8000/healthz ; curl -s localhost:8000/readyz
 {"status":"ok","version":"dev"}
 {"status":"ready","checks":{"db":"ok","redis":"ok","migrations":"ok"}}

$ QL_PG_HOST_PORT=55432 make migrations-roundtrip
 Running upgrade  -> 0001 ... Running upgrade 0001 -> 0002 ...
 Running downgrade 0002 -> 0001 ... Running downgrade 0001 -> , baseline ...
 Running upgrade  -> 0001 ... Running upgrade 0001 -> 0002 ...

$ QL_PG_HOST_PORT=55432 make test-api     # EXIT=0
 TOTAL                                 2557    188    444     61    91%
 Required test coverage of 75.0% reached. Total coverage: 90.97%
 ============ 865 passed, 19 xfailed, 1 warning in 109.27s (0:01:49) ============
 cd api && uv run coverage report --include='app/core/*' --fail-under=90
 app/core/outbox/registry.py             36      7     10      1    74%
 app/core/telemetry.py                   39      7      6      2    80%
 ... (all other app/core files 85-100%)
 TOTAL                                 2276    116    386     51    93%
 (warning: StarletteDeprecationWarning "Using httpx with starlette.testclient is deprecated")

$ pytest --no-cov tests/security/ tests/integration/worker/test_worker_jobs.py <gate tests by name> \
    tests/integration/outbox/test_dispatcher.py tests/integration/commands/test_can_approve_pipeline.py \
    tests/unit/test_permissions.py tests/integration/files/test_presigned_download.py <upload-url gate tests> \
    tests/integration/migrations/test_platform_migration.py tests/integration/test_migrations.py -rA
 150 passed, 1 warning in 35.65s
 test_permissions_api.py::test_viewer_cannot_call_any_command[/files/upload-url|/plants|/plants/{id}/update|
   /tenant/settings/update|/users|/users/{id}/deactivate|/users/{id}/update]  PASSED

$ make lint                                # EXIT=0
 All checks passed! / 149 files already formatted / Success: no issues found in 148 source files
 module layering (ARCHITECTURE 3.1) KEPT   Contracts: 1 kept, 0 broken.
 All matched files use Prettier code style!
$ make test-web    ->  Test Files 3 passed (3)  Tests 8 passed (8)
$ make e2e         ->  2 passed (2.6s)
$ make secrets     ->  10 commits scanned. no leaks found
$ make lint-ci     ->  exit 0 (actionlint)
$ cd api && uv run pip-audit --skip-editable  ->  No known vulnerabilities found
```

Live probes against the running stack after `make seed` (demo users):
```
viewer  POST /auth/login -> 200
  set-cookie: ql_session=…; HttpOnly; Max-Age=604800; Path=/; SameSite=lax; Secure
  set-cookie: ql_csrf=…; Max-Age=604800; Path=/; SameSite=lax; Secure
viewer  POST /api/v1/plants            -> 403 {"code":"forbidden", ..., "request_id":"dc628ecb…"}
admin   POST /api/v1/plants (no CSRF)  -> 403 "The security token is missing or invalid…"
admin   POST /api/v1/plants (Origin evil.example) -> 403 "This request came from an unexpected origin."
admin   POST /api/v1/plants + Idempotency-Key K  -> 201;  same again -> 201, idempotency-replayed: true (same id)
admin   same K, different body -> 422 {"code":"idempotency_mismatch"}
DB: outbox PLANT_CREATED processed=t attempts=0 (live dispatcher);
    activity_log plant.create actor_type=user has_session=t ip=172.29.0.1
OpenAPI paths: exactly the P01 set (/auth/login|logout|password-reset/request|confirm, /users, /users/{id}/update|deactivate,
    /plants, /plants/{id}/update, /tenant/settings[/update], /me, /files/upload-url, /healthz, /readyz)
DB tables: activity_log, alembic_version, idempotency_keys, job_dead_letters, outbox_events, plants, tenants, users
```

## Invariant test-name trace (INVARIANTS.md rows owned by P01)

I confirmed that each test name below exists by grepping for `def <name>`, and that it passed in the full run:
INV-PLT-01 (`test_every_table_has_tenant_id_and_forced_rls`, `test_tenant_a_cannot_read_tenant_b_rows_raw_session`,
`test_tenant_a_cannot_insert_row_for_tenant_b`, `test_composite_fk_rejects_cross_tenant_reference`), PLT-02, 03, 04, 05
(`test_activity_log_update_rejected_db`, `_delete_rejected_db`), 06 (`test_no_route_accepts_status_field_outside_commands`),
07, 09, 10, 11 (`test_api_layer_cannot_import_provider_clients`, `test_external_send_carries_idempotency_key`), 12, 13, 14,
15 (xfail by phase), 16, 18, 19, 20, 21, 22, and INV-SEC-01 (P01 part), 02, 04 (`test_password_stored_as_argon2id`, `test_login_rate_limited`,
`test_session_cookie_flags_secure_httponly_samesite`), 08 (`test_redis_app_user_cannot_run_admin_commands`). None is missing.

## Spec spot-checks (5)

1. **§6.1 `activity_log.actor_type` (user / supplier_session / system / ai).** Code: `alembic/versions/0002_platform.py:196`
   CHECK `actor_type IN ('user','supplier_session','system','ai')`, plus actor_id/session_id CHECKs at lines 199 and 203. Test:
   `tests/integration/db/test_supplier_policies.py::test_supplier_actor_type_value_consistent` (only `supplier_session` makes
   `app_is_supplier()` true; any other value is a CheckViolation). Matches.
2. **§21.1 "argon2/bcrypt passwords".** Code: `app/core/auth/passwords.py` (argon2-cffi `PasswordHasher` defaults; a dummy hash
   equalises timing). Test: `tests/integration/auth/test_password_reset.py::test_password_stored_as_argon2id` asserts the prefix
   `$argon2id$v=19$`, no plaintext, `check_needs_rehash` is False, and verify succeeds. Matches.
3. **§21.1 "login rate limits".** Test: `tests/integration/auth/test_login_rate_limit_and_csrf.py::test_login_rate_limited`
   (5 failures, then 429 `rate_limited` even with the correct password, `Retry-After` within the window, no session cookie), plus
   `test_unknown_emails_are_rate_limited_too…` and `test_limit_is_per_email_across_ip_addresses`. Matches API.md §6 (5 / 15 min).
4. **§22.2 "dead-letter after 5 attempts with an alert".** Code: `app/core/outbox/dispatcher.py` (`MAX_ATTEMPTS = 5`, log
   `outbox_event_dead_lettered` at error level and a counter); worker middleware writes `job_dead_letters`. Tests: gate rows 4b. Matches.
5. **§6.1 `tenants.settings` (SLA hours, default PPM target, minimum sample sizes, score weights).** Code:
   `app/core/platform/schemas.py:151-154`. Test: `test_platform_commands_api.py::test_get_settings_returns_documented_defaults_for_a_new_tenant`
   checks min_sample 5 receipts / 1000 units / 1 SCAR due (blueprint line 625), weights 50/20/15/15 (§14.1), SLA critical 24 h / 7 d,
   major 48 h / 10 d, minor — / 15 d (blueprint lines 439-441), and default PPM target 500 (§14.4 "demo default 500"). Matches.

## Scope check (no Part B / later-phase work)

- `api/app/` contains only `core/`, `api/`, `main.py`, `worker.py`, `dispatcher.py`, `scheduler.py`, `uvicorn_worker.py`. There is no masters/ncr/scar/
  documents/ai module.
- The DB holds only the 7 P01 tables. Routes are exactly the P01 set listed in plan §2.2.
- No Google/OAuth, WhatsApp, or LLM provider code (`grep -i "google|oauth|whatsapp|openai|anthropic" api/app` returns nothing). A-46 is respected.
- `git diff 9ed6627..HEAD -- web` is empty: no screens, consistent with A-93.
- New dependencies match plan §7 (argon2-cffi, dramatiq[redis], apscheduler<4, boto3, filetype, prometheus-client,
  opentelemetry-*). ClamAV is the only new server and was approved under A-47.
- No ADR, blueprint, PHASES or CLAUDE.md change in the P01 commits. Docs touched: REPO_LAYOUT (env/compose tables), OPEN_QUESTIONS, and P01 plan/test docs.

## Git

- P01 commits: `test(p01): failing tests for platform foundation`, `feat(p01): platform foundation`, `fix(p01): address review findings`.
  Each is one line, conventional type, with no body, trailers, co-author or emoji. Author `pankajneema`.
- Working tree was clean before this report was written (`git status --porcelain` printed nothing). Tag `p01-verified` does not exist yet (correct, not yet approved).

## Observations (not gate failures)

- **O-1** `feat(p01)` (94b8616) edited tests written in `test(p01)`. The edits were unique emails in 3 tests, the mailpit query encoding,
  Redis `protocol=2`, and `test_redis_acl.py`, which now also accepts "DEBUG command not allowed" as a denial. None weakens a security assertion,
  but CLAUDE.md §2 requires approval for backend changes to qa tests. The human should confirm.
- **O-2** `tests/unit/test_permissions.py::test_can_approve_commands_reject_without_flag` and `test_all_views_are_security_invoker`
  are vacuous in P01 (no +CA command, no views). Both are backed by other evidence: the probe pipeline tests and a negative-control view test.
- **O-3** Core coverage passes as an aggregate (93 %), but `app/core/outbox/registry.py` is 74 % and `app/core/telemetry.py` is 80 %.
- **O-4** Compose still warns "Found orphan containers ([qualloop-minio-init-1])" (P00 O-6, unchanged).
- **O-5** One deprecation warning: Starlette `TestClient` with httpx.
- **O-6** Signed-URL download is service-level only until P03/P04 (A-92). §21.2 "signed file URLs expire" is proven against real SeaweedFS.
- **O-7** Open P01 SPEC-GAPs to raise at the human gate: A-92 to A-101 and A-103 to A-106 in OPEN_QUESTIONS.md. Among them: A-95 (score weights
  must total 100), A-98 (last-admin guard), A-100 (5 executions vs Dramatiq max_retries), A-101 (`__Host-` cookie prefix), A-103 (global email
  uniqueness reveals that an email exists in another tenant), A-104 (no idempotency-key cleanup job yet), A-105 (password-reset caps), and A-106 (trusted proxies).
  A-102 (supplier INSERT policy) is assigned to P05.
