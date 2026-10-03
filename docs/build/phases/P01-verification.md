# P01 — Platform foundation — Independent Verification (re-run 2)

- Date: 2026-10-03
- Verifier: independent verifier, fresh context. No code edited; the only file written is this report (it replaces the earlier FAIL report).
- HEAD: `02c63e4 fix(p01): reset cap only counts guesses on live codes, column grants, review records`.
  P01 commits: `18c750c test(p01)`, `94b8616 feat(p01)`, `8de9d23 fix(p01)`, `02c63e4 fix(p01)`.
- Environment: macOS + Docker. Host 5432 is used by a local Postgres and host 6379 by an ssh tunnel, so every `make` call ran with
  `QL_PG_HOST_PORT=55432 QL_REDIS_HOST_PORT=56379`.
- Clean state: `make down V=1` (pgdata, clamdata, s3data volumes and network removed), then `make up`.

## Verdict: PASS

Every P01 gate item has a named test (or command) that I located, read and ran, and all passed. The previous run's only
failure (F-1, no security-review evidence) is closed by `docs/build/phases/P01-security-review.md`.

## Gate table

| # | Gate item (PHASES.md P01) | Evidence | Result |
|---|---|---|---|
| 1 | All tests green | `make test-api` EXIT=0: **879 passed, 19 xfailed, 0 failed, 0 skipped** (113.9 s). All 19 xfails are `tests/unit/test_outbox_unit.py::test_event_catalogue_every_22_3_event_has_emitter[<EVENT>]` ("emitter … is built in P0N, not in P01"); no other xfail. `make test-web` 8/8 passed; `make e2e` 2/2 passed (phone-360, desktop-1440). Gate subset re-run: 501 passed. | PASS |
| 2a | Tenant A cannot read/write Tenant B — API | `tests/security/test_tenant_isolation_api.py::test_tenant_a_cannot_read_tenant_b_users_api` (no B ids/emails in A's list), `::test_tenant_a_cannot_read_tenant_b_plants_api`, `::test_tenant_a_cannot_update_tenant_b_user_api` (404 `not_found`, B row unchanged), `::test_tenant_a_cannot_deactivate_tenant_b_user_api` and the rest of the file. | PASS |
| 2b | — raw ORM session | `tests/security/test_tenant_isolation_orm.py` (select only own rows; `session.get` foreign PK → None; add foreign row → "row-level security"; foreign UPDATE rowcount 0; no GUC → nothing; DELETE → "permission denied"). `tests/integration/db/test_rls_platform_tables.py::test_tenant_a_cannot_read_tenant_b_rows_raw_session[7 tables]`, `::test_tenant_a_cannot_insert_row_for_tenant_b[...]`. `tests/conftest.py::_role_guard` fails any connection that is superuser/BYPASSRLS or not `qualloop_app`, so these are not false passes. | PASS |
| 2c | — worker | `tests/integration/worker/test_worker_jobs.py::test_worker_job_runs_with_job_tenant_context` (GUC = job tenant, actor_type `system`), `::test_worker_job_cannot_read_other_tenant` (B plants/users/tenant counts all 0), `::test_worker_job_cannot_write_for_another_tenant` ("row-level security", no row in B), `::test_consecutive_jobs_for_different_tenants_on_one_pooled_connection_do_not_leak_context`. | PASS |
| 3a | Command writes activity_log + outbox in the same transaction | `tests/integration/commands/test_command_audit_and_outbox.py::test_command_writes_activity_log_and_outbox_in_same_transaction[user-create, user-update, user-deactivate, plant-create, plant-update, settings-update]`: exactly 1 audit + 1 outbox row, and `xmin` of business row == audit row == outbox row. | PASS |
| 3b | Failure rolls back both | `::test_command_failure_rolls_back_activity_log_and_outbox[outbox-write-fails, activity-log-write-fails, idempotent-response-store-fails]`: NOT VALID CHECK forces the later write to fail; asserts no plant, no audit, no outbox, no idempotency row; same-key retry then succeeds without replay. | PASS |
| 4a | Outbox processed exactly once under two concurrent workers | `tests/integration/outbox/test_dispatcher.py::test_outbox_event_processed_once_with_two_concurrent_dispatchers`: two threads held together by `Barrier(2)` while both hold claimed batches; `sorted(seen) == sorted(ids)` (no duplicate, none missing), all `processed_at` set, attempts 0. Plus `::test_app_claim_outbox_batch_skip_locked_returns_disjoint_batches_to_open_transactions`. | PASS |
| 4b | Retries then dead-letter | `::test_outbox_retry_backoff_increases_exponentially`, `::test_outbox_event_dead_lettered_after_5_attempts_and_alert_emitted` (attempts 5, 5 enqueue calls, never claimed again, exactly one error-level `outbox_event_dead_lettered` log with event_id/tenant_id/attempts); `test_worker_jobs.py::test_job_dead_lettered_after_5_attempts` (5 executions), `::test_dead_lettered_job_recorded_in_job_dead_letters`. | PASS |
| 5a | Viewer cannot call any command | `tests/integration/commands/test_permissions_api.py::test_viewer_cannot_call_any_command[/files/upload-url, /plants, /plants/{id}/update, /tenant/settings/update, /users, /users/{id}/deactivate, /users/{id}/update]` — the list is hard-coded admin commands ∪ every POST route of the real app; asserts 403 `forbidden` and no new activity_log row. Live: viewer `POST /api/v1/plants` → 403. | PASS |
| 5b | `can_approve` required where flagged | `tests/integration/commands/test_can_approve_pipeline.py` (7 tests): throwaway +CA command through real `run_command`; quality/admin without flag → `Forbidden` 403 and zero plant/audit/outbox/idempotency rows; with flag → runs and audited; viewer with flag → refused. (`tests/unit/test_permissions.py::test_can_approve_commands_reject_without_flag` passes but is vacuous in P01 — no registered +CA command.) | PASS |
| 6a | Signed URL expires (≤ 15 min) | `tests/integration/files/test_presigned_download.py::test_signed_url_expires_within_15_minutes`, `::test_a_longer_expiry_than_15_minutes_cannot_be_requested[3600, 86400, 901]`, `::test_the_signed_url_downloads_the_object_and_then_actually_expires` (real SeaweedFS GET returns PDF, then 400/403 after 2.5 s); `tests/integration/files/test_upload_url_api.py::test_signed_url_expires_within_15_minutes`. | PASS |
| 6b | Unauthorised user cannot download | `test_presigned_download.py::test_unauthorised_user_cannot_get_signed_url` (no caller → Unauthenticated; supplier_session / ai → Forbidden), `::test_unauthorised_user_cannot_get_signed_url_viewer_matrix[6]`, `::test_tenant_a_cannot_get_signed_url_for_tenant_b_file` (404, never 403); upload side `test_upload_url_api.py::test_unauthorised_user_cannot_get_signed_url`. Download is service-level (`presign_download`) because P01 has no download endpoint (A-92). | PASS |
| 7 | Migrations up/down/up | `make migrations-roundtrip` EXIT=0 (log below); `tests/integration/migrations/test_platform_migration.py::test_migrations_up_down_up` (tables/functions present → none after `downgrade base`, roles survive → present again, definers have safe search_path); `tests/integration/test_migrations.py::test_upgrade_downgrade_upgrade`. `migrate` container exit 0 on fresh volume. | PASS |
| 8 | Coverage ≥ 90 % on core | `make coverage-core` (`--include='app/core/*' --fail-under=90`): **TOTAL 93 %**. Overall 90.95 % (gate 75 %). | PASS |
| 9 | security-reviewer has no Critical/High | `docs/build/phases/P01-security-review.md`: pass 2 reviewer gate statement "No open Critical/High at 8de9d236… (1 Medium, 4 Low, 8 Info open)". The only later code change (`8de9d23..02c63e4`: `auth/otp.py`, `auth/router.py`, column-level grants in `0002_platform.py`) fixes that Medium and a Low; I read the diff and it only narrows behaviour (no new endpoint, grant or bypass). Its regression tests pass: `tests/integration/auth/test_password_reset_hardening.py`, `tests/integration/db/test_users_grants_and_error_leaks.py`. | PASS (see O-1) |

Lint/types (CLAUDE.md §6): `make lint` EXIT=0.

## Command log (trimmed, real output)

```
$ make down V=1
 Volume qualloop_pgdata Removed / Volume qualloop_clamdata Removed / Volume qualloop_s3data Removed / Network qualloop_default Removed
$ make up                                   # 30.6 s
 ... api-1 Healthy  postgres-1 Healthy  redis-1 Healthy  worker-1 Healthy  dispatcher-1 Healthy  scheduler-1 Healthy
 ... clamav-1 Healthy  s3-1 Healthy  mailpit-1 Healthy  web-1 Healthy  migrate-1 Exited  s3-init-1 Exited
$ docker inspect qualloop-migrate-1 --format '{{.State.ExitCode}}'  ->  0
 Running upgrade  -> 0001, baseline ...
 Running upgrade 0001 -> 0002, platform: tenants, plants, users, activity_log, outbox_events, idempotency_keys, job_dead_letters
$ curl localhost:8000/healthz  -> {"status":"ok","version":"dev"}
$ curl localhost:8000/readyz   -> {"status":"ready","checks":{"db":"ok","redis":"ok","migrations":"ok"}}

$ make migrations-roundtrip                 # EXIT=0
 Running upgrade  -> 0001 / Running upgrade 0001 -> 0002
 Running downgrade 0002 -> 0001 / Running downgrade 0001 -> , baseline
 Running upgrade  -> 0001 / Running upgrade 0001 -> 0002

$ make test-api                             # EXIT=0
 TOTAL                                 2568    189    450     62    91%
 Required test coverage of 75.0% reached. Total coverage: 90.95%
 ============ 879 passed, 19 xfailed, 1 warning in 113.92s (0:01:53) ============
 uv run coverage report --include='app/core/*' --fail-under=90
 app/core/outbox/registry.py             36      7     10      1    74%
 app/core/telemetry.py                   39      7      6      2    80%
 TOTAL                                 2287    117    392     52    93%
$ grep XFAIL testapi.log | grep -vc test_event_catalogue_every_22_3_event_has_emitter  ->  0

$ pytest --no-cov tests/security tests/integration/worker/test_worker_jobs.py tests/integration/outbox/test_dispatcher.py \
    tests/integration/commands tests/unit/test_permissions.py tests/integration/files tests/integration/migrations \
    tests/integration/test_migrations.py tests/integration/db -rA
 501 passed, 1 warning in 75.50s

$ make lint                                 # EXIT=0
 All checks passed! / 149 files already formatted / Success: no issues found in 148 source files
 Contracts: 1 kept, 0 broken. / All matched files use Prettier code style!
$ make test-web   ->  Test Files 3 passed (3)  Tests 8 passed (8)
$ make e2e        ->  2 passed (2.4s)
$ make secrets    ->  11 commits scanned. no leaks found        (EXIT=0)
$ make lint-ci    ->  EXIT=0
$ uv run pip-audit --skip-editable  ->  No known vulnerabilities found
$ pnpm audit --prod                 ->  No known vulnerabilities found
```

Live probes (after `make seed`, demo users, Origin http://localhost:3000):
```
viewer login 200 / admin login 200
viewer POST /api/v1/plants                -> 403 {"code":"forbidden",...,"request_id":"83a09afc…"}
admin  POST /api/v1/plants + Idem-Key K   -> 201 ; same again -> 201, idempotency-replayed: true
admin  same K, different body             -> 422 {"code":"idempotency_mismatch"}
admin  POST without X-CSRF-Token          -> 403 "The security token is missing or invalid…"
DB (postgres superuser in container): outbox PLANT_CREATED processed=t attempts=0 (live dispatcher);
    activity_log plant.create actor_type=user session=t ip=172.29.0.1
DB tables (dev DB): activity_log, alembic_version, idempotency_keys, job_dead_letters, outbox_events, plants, tenants, users
```

## Failures

None.

## Spec spot-checks (5)

1. **§6.1 `users` (email, name, mobile, role admin/quality/viewer, can_approve, plant_ids, active).** Code:
   `api/alembic/versions/0002_platform.py:117-180` (columns, CHECK `role IN ('admin','quality','viewer')`, trigger
   `trg_users_plant_ids_valid`). Test: `tests/integration/db/test_constraints_platform.py::test_user_plant_ids_must_exist_in_tenant_db`
   (foreign plant, unknown plant, mixed array, and UPDATE all rejected). Matches (INV-PLT-09).
2. **§6.1 `outbox_events` (event_id, aggregate_type, aggregate_id, event_type, payload, created_at, processed_at, attempts, last_error).**
   Code: `0002_platform.py:235-269` (all columns, `UNIQUE (tenant_id, event_id)`, pending/dead partial indexes at `attempts < 5` / `>= 5`).
   Tests: gate 4a/4b. Matches §22.2 "dead-letter after 5 attempts".
3. **§21.1 "audit logging of sensitive actions with before/after, reason, session and IP" + §7.5 append-only.** Test:
   `test_command_audit_and_outbox.py::test_activity_log_records_actor_session_and_ip` (actor_type user, actor_id, session_id stable per
   login and different on new login, ip = client IP), `::test_activity_log_create_has_no_before_and_an_after_snapshot`;
   `test_constraints_platform.py::test_activity_log_update_rejected_db` / `_delete_rejected_db` (InsufficientPrivilege). Code:
   `append_only("activity_log")` at `0002_platform.py:228`. Matches.
4. **§22.2 idempotency for commands (PHASES "Idempotency-key support").** Code: `api/app/core/idempotency.py` (100 % covered). Tests:
   `tests/integration/commands/test_idempotency.py::test_idempotency_key_replays_original_response` (same body → same status/body,
   `idempotency-replayed: true`, one plant, one audit, one outbox row), `::test_idempotency_key_reuse_with_different_body_rejected`
   (422 `idempotency_mismatch`, original still replayable). Confirmed live as above. Matches.
5. **§21.1 "content-type and size validation" / §20.2 "≤ 20 MB".** Code: `api/app/core/files/storage.py:30-31,116-119`
   (`MAX_UPLOAD_BYTES = 20_000_000`, marked `# SPEC-GAP: A-97` MB vs MiB, conservative smaller value). Tests:
   `tests/integration/files/test_upload_url_api.py::test_upload_rejects_over_20_mb` (413 `payload_too_large`),
   `::test_upload_accepts_a_file_just_under_20_mb`, `::test_upload_rejects_wrong_content_type[6 types]` (415). Virus scan:
   `tests/integration/files/test_scan_job.py` (EICAR). Matches.

## Scope check (no Part B / later-phase work)

- `api/app/` = `core/`, `api/`, `main.py`, `worker.py`, `dispatcher.py`, `scheduler.py`, `uvicorn_worker.py`. No masters/NCR/SCAR/documents/AI modules.
- `grep -rniE "google|oauth|whatsapp|openai|anthropic|supplier_contact|magic_link" api/app` → no matches (A-46 respected).
- Only the 7 P01 tables (+ `alembic_version`) exist.
- `git diff 9ed6627..HEAD -- web` empty (no screens; A-93). No change to blueprint, PHASES.md, CLAUDE.md or ADRs; only `docs/architecture/REPO_LAYOUT.md` (env/compose tables).

## Git

- `git status --porcelain` empty before this report was written. Tag `p01-verified` does not exist yet (correct).
- P01 commit subjects are one line, conventional type, no body/trailers/co-author/emoji; author `pankajneema`.

## Observations (not gate failures)

- **O-1** The security review "Addendum: fix loop 1" (covering `02c63e4`) is not attributed to the security-reviewer; the reviewer's own
  gate statement is for `8de9d23`. I reviewed the `8de9d23..02c63e4` code diff myself and found nothing that raises severity. The human may want a reviewer sign-off on HEAD.
- **O-2** `test_can_approve_commands_reject_without_flag` and `test_all_views_are_security_invoker` are vacuous in P01 (no +CA command, no views); 5b is proven by the pipeline tests.
- **O-3** Core coverage passes in aggregate (93 %), but `app/core/outbox/registry.py` is 74 % and `app/core/telemetry.py` 80 %. OpenTelemetry has only two unit tests (enabled/disabled by endpoint).
- **O-4** `test_permissions_api.registered_post_paths()` returns `[]` if `create_app()` raises, silently shrinking the dynamic route list to the hard-coded one.
- **O-5** Compose warns "Found orphan containers ([qualloop-minio-init-1])" (unchanged since P00). One Starlette TestClient deprecation warning.
- **O-6** Local port conflicts: Redis 6379 on this machine is held by an ssh tunnel; `QL_REDIS_HOST_PORT` override was needed.
- **O-7** Open SPEC-GAPs for the human gate are in `docs/build/OPEN_QUESTIONS.md` (A-92 … A-108, incl. A-97 20 MB vs MiB, A-101 `__Host-` cookie prefix, A-106/A-107 production proxy/settings hardening, A-108 unmasked email in audit snapshots).
