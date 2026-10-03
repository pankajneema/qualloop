# P00 — Architecture & scaffold — Independent Verification (re-run after `fix(p00)`)

- Date: 2026-10-03
- Verifier: independent verifier, fresh context. No code was edited; the only file written is this report.
- HEAD: `899c2ce fix(p00): env example, settings rule, decisions recorded`. Tag `p00-verified` points at `dd5306c` (one commit behind HEAD).
- Environment: macOS, Docker. Host port 5432 is used by another local Postgres, so `QL_PG_HOST_PORT=55432` was exported. pnpm via `npx pnpm@10.34.6`.
- Clean state: `make down V=1` removed the `pgdata` and `s3data` volumes and the network, then `make up` rebuilt the stack.

## Verdict: PASS

All five gate items have evidence and pass, with two caveats:
- **Gate 2** is proven by running every CI step locally and by emulating the CI `api-test` job on a fresh Postgres. GitHub Actions has never run this workflow.
- **Gate 5** is proven from documents only.

The one failure in the previous report, D-1 (`.env.example` missing), is fixed. No new gate failure was found. The observations below are for the human gate; none of them fails a gate item.

## Gate table

| # | Gate item | Evidence | Result |
|---|---|---|---|
| 1 | `make up` starts all services; `/healthz` and web home return 200 | After `make down V=1` and `make up` (30.5 s): postgres, redis, s3 (SeaweedFS), mailpit, api and web are `healthy`, and migrate and s3-init `exited 0`. `curl :8000/healthz` returns 200 `{"status":"ok","version":"dev"}`. `/readyz` returns 200 with db, redis and migrations ok. `curl :3000/` returns 200 with `<title>QualLoop</title>`. Tests: `tests/integration/test_health.py::test_healthz_200` (asserts 200 and `status=="ok"`), `::test_readyz_200_when_deps_up` (asserts the exact body), `::test_readyz_503_when_redis_down`, and Playwright `e2e/smoke.spec.ts` "home returns 200 and renders the app shell" (asserts status 200, CSP `frame-ancestors 'none'` with a nonce, `permissions-policy` camera=(), nav and h1 "QualLoop", no console errors). Playwright passed on desktop-1440 and phone-360. | PASS |
| 2 | CI runs lint, types, tests (placeholder), migration up/down/up — all green | `.github/workflows/ci.yml` has 7 jobs: api-lint, api-test, web-lint, web-test, secrets, build, e2e. Every step was run locally and exited 0: `make lint-api` (ruff, ruff format, mypy, lint-imports), `make lint-web` (eslint, prettier, tsc), `make test-api` (31 passed, 97.08 %), `make test-web` (8 passed), `make migrations-roundtrip`, `make e2e`, `make secrets`, gitleaks exactly as CI runs it, `make audit`, and `make scan-images` (which builds both images, then Trivy). **CI api-test emulation:** fresh `postgres:16` with the same digest; `psql -f infra/postgres/init/01-roles.sql` as postgres; SeaweedFS started with the CI command and buckets created (`init EXIT=0`); then `alembic upgrade head`, `downgrade base`, `upgrade head` and `pytest` all green. Test `test_migrations.py::test_upgrade_downgrade_upgrade` asserts that the baseline functions are present after upgrade, absent after downgrade, and present after re-upgrade. **Caveat:** `gh run list` is empty, so the workflow has never run on GitHub. ADR-016 still lists the CI host as "human to confirm". | PASS (local and emulated; not yet run on GitHub) |
| 3a | Every §6 table appears in DATA_MODEL.md | My script parsed §6 (blueprint lines 177–266): 48 tables, 0 missing headings in DATA_MODEL.md. Every snake_case key column is present in its table section, with two exceptions: `amount_inr` in 5 money tables (stored as `amount_paise`, documented at DATA_MODEL line 19, A-01) and `expiring_30`, which is an enum value, not a column. | PASS |
| 3b | Every invariant from §7, §10, §11, §12, §14, §15 appears in INVARIANTS.md | INVARIANTS.md has 181 INV rows. I read §7.1–7.5, §10, §11.1–11.4, §12/12.1, §14.1–14.5 and §15.1–15.6 against INVARIANTS §3, §4, §5, §8, §9, §10, §11 and §12. Each rule has an INV id with §, enforcement and a test name. Examples: §10 rules map to INV-MON-01…15; §11.3 decisions map to INV-QTY-07 and INV-QTY-10; §12.1 minimum sample maps to INV-MET-11; §14.2 maps to INV-SCO-04/05; the 11 §15.2 rules map to INV-RSK-02. The weak §7.4 traceability noted last time (O-3) is fixed: INV-DOC-03 now names `test_requested_requirement_stays_requested_when_overdue` and `test_sqe_replacement_request_sets_renewal_fields`. | PASS |
| 4 | Every §24.2 command appears in API.md | All 24 `POST` paths from §24.2 were extracted and grepped as `POST <path>` in API.md: 24 of 24 found (e.g. API.md:128 `POST /ncrs/{id}/decide-scar`). | PASS |
| 5 | Human has approved the architecture | Documentary evidence only. All 20 ADRs are `Accepted (2026-10-03)`, including the new ADR-020 "Accepted (2026-10-03, human decision)". STATUS.md shows P00 approved on 2026-10-03. OPEN_QUESTIONS has 91 entries, of which A-01, A-46, A-47, A-48, A-63, A-73, A-74, A-86, A-87, A-89 and A-91 are marked "decided by human 2026-10-03". The verifier cannot see the human's messages. ADR-016 (CI host) is still marked "human to confirm". | PASS (documentary) |

### Deliverables (PHASES.md P00)

| Deliverable | Evidence | Result |
|---|---|---|
| `docs/understanding.md` | present | OK |
| `docs/architecture/` ARCHITECTURE, DATA_MODEL, INVARIANTS, API, SCALING, REPO_LAYOUT | all 6 present | OK |
| `docs/adr/` (14 required topics) | 20 ADRs (ADR-001…020) cover all the required topics | OK |
| `/api` app factory, settings, `/healthz`, `/readyz`, structured logging | OpenAPI paths: `['/healthz', '/readyz']`. Logging and settings tests pass | OK |
| `/web` shell, tokens.ts from DESIGN_SPEC, fonts, i18n en/hi | `make test-web`: 3 files, 8 tests pass (includes `tokens.test.ts` and `messages.test.ts`). With cookie `ql_locale=hi` the page renders `<html lang="hi">` | OK |
| `/infra` compose: postgres16, redis, S3-compatible store (SeaweedFS, ADR-020), mailpit | all healthy. Anonymous S3 list and put both return 403 (private) | OK |
| Makefile `up down test lint fmt migrate seed` | all present. `make migrate` exit 0; `make seed` prints "seed: nothing to seed at P00" | OK |
| CI pipeline, pre-commit hooks, `.gitignore` | `pre-commit validate-config` exit 0. The commit-msg hook accepts `feat(p01): x` and rejects a `Co-authored-by` trailer and a non-conventional message. `.env` is ignored and `.env.example` is not | OK |
| **`.env.example`** | tracked (`git ls-files` line 18). Every `QL_*`/`NEXT_PUBLIC_*` variable named in REPO_LAYOUT's `.env.example` section is present. Placeholder values only | **OK (D-1 fixed)** |
| Alembic baseline + RLS helper | `0001_baseline.py` and `alembic/helpers.py::enable_tenant_rls`. RLS tests pass | OK |
| STATUS, OPEN_QUESTIONS, CHANGELOG initialised | present | OK |

## Failures

None.

## Observations (not gate items; for the human gate)

- **O-1 Tag behind HEAD.** `p00-verified` points at `dd5306c`, but the fix that resolves D-1 (`899c2ce`) comes after it. Moving the tag would need `git tag -f`, which CLAUDE.md §4 forbids unless the human asks. The human should decide whether to re-tag.
- **O-2 Configuration and permission changes in `899c2ce`.** This `fix(p00)` commit also changed:
  - `CLAUDE.md`: added the line "Python quality gates: ruff check, ruff format (no black), mypy --strict".
  - `.claude/settings.json`: replaced the deny rule `Read(./.env.*)` with `Read(./.env.local)`, `Read(./.env.*.local)` and `Read(./.env.production)`. This narrows the secret-file read protection: `.env.staging`, for example, is no longer denied.
  - `PHASES.md`: moved Google login out of P01 into R1.1 (A-46).

  The commit records these as human decisions. I cannot see the human's approval, so the human should confirm them at the gate (CLAUDE.md §5: security posture, configuration).
- **O-3 actionlint regression.** `rhysd/actionlint:1.7.7` now exits 1 on `.github/workflows/ci.yml:65`: shellcheck SC2034 "i appears unused" in the new SeaweedFS wait loop. CI does not run actionlint and the warning is harmless, but the previous report recorded actionlint exit 0. Fix: use `for _ in $(seq 1 30)`. Also, that wait loop does not fail when S3 never answers 403; the next step would fail instead.
- **O-4 GitHub CI never executed.** The `origin/main` ref is `f579f78`, 5 commits behind local `main`, and `gh run list` is empty. Gate 2 rests on local and emulated runs.
- **O-5 Stale docs.** `docs/CHANGELOG.md:7` still says `make up` starts "MinIO". Line 17 of the same file records the move to SeaweedFS.
- **O-6 Orphan container.** `docker compose ps -a` still lists `qualloop-minio-init-1` from the old compose file (exited 0), and compose warns "Found orphan containers". `make down` does not pass `--remove-orphans`. This only affects machines that ran the old stack.
- **O-7 Older commits (before P00):**
  - `f579f78` has `Signed-off-by: …` in a 2-line message. CLAUDE.md §4 forbids signatures.
  - `f3192d4` and `86287b7` have identical messages and no `(pNN)` scope.

  All three P00 commits (`a2a8315`, `dd5306c`, `899c2ce`) follow the format: one line, conventional type, `(p00)` scope, no trailers.
- **O-8** Previous O-4 is fixed: the `std_columns` docstring now matches the server default `app_uuid_v7()`.

## Scope check (nothing outside P00, no Part B)

- Database `qualloop` contains only `public.alembic_version`. There are no business tables.
- The API exposes only `/healthz` and `/readyz`.
- Tracked app code is limited to `api/app/{main.py, api/, core/}`, `api/alembic`, `api/seeds` (a no-op), and `web/src/{app, design, i18n, proxy.ts}`.
- `git grep -iE 'ppap|pcn\b|concession|4m change|vendor rating|delivery performance'` over `api web/src web/e2e infra` returns no matches.

## Spec spot-checks

| # | Rule | Code | Test (assertion read) | Result |
|---|---|---|---|---|
| 1 | §24.1.1 / §6: RLS on `tenant_id` from the first migration | `api/alembic/helpers.py::enable_tenant_rls` | `test_rls_is_forced_on_probe_table` (asserts `(relrowsecurity, relforcerowsecurity) == (True, True)`), `test_tenant_b_rows_invisible_to_a_even_by_id` (count == 0), `test_insert_for_other_tenant_fails` and `test_update_cannot_move_row_to_other_tenant` (both raise "row-level security"), `test_no_tenant_set_sees_nothing_and_cannot_insert`: all pass | OK |
| 2 | §21.2 / ADR-004: runtime role cannot bypass RLS | `infra/postgres/init/01-roles.sql` (NOSUPERUSER NOBYPASSRLS; TEMP revoked) | `test_app_role_cannot_bypass_rls` (all 3 roles have `not rolsuper and not rolbypassrls`), `test_app_role_has_no_temp_privilege`, `test_app_role_has_no_delete`: all pass, and also pass on the freshly emulated CI database | OK |
| 3 | §22.1 modular monolith layout and boundaries | `[tool.importlinter]` layers contract in `api/pyproject.toml` mirrors the §22.1 modules | `lint-imports`: "module layering (ARCHITECTURE 3.1) KEPT — Contracts: 1 kept, 0 broken" | OK |
| 4 | §22.4 observability: structured logs with request correlation, no token leakage | `app/core/logging.py`, `app/api/middleware.py` | `test_log_lines_are_json_with_request_id` (parses JSON; asserts msg, request_id, tenant_id, level), `test_access_log_redacts_magic_link_token` (secret not in output), `test_error_responses_carry_request_id` (404 and 500 echo the id): all pass | OK |
| 5 | §22 "Files: S3-compatible storage; signed URLs only" (local stand-in) | `infra/s3/entrypoint.sh` (identity-only config), `infra/s3/init.sh` | Live: anonymous `GET /qualloop-files/` returns 403 and anonymous `PUT` returns 403. Both buckets are created by s3-init. No automated test yet; signed-URL tests are P01 scope (PHASES P01) | OK for P00 |
| 6 | §24.1.7 / ADR-019: no unsafe defaults outside local | `app/core/config.py` | `test_startup_fails_outside_local_with_default_settings` (raises "unsafe default", rejects a short session_secret, accepts valid values): passes | OK |

## Command log (trimmed, real output)

```
$ export QL_PG_HOST_PORT=55432
$ make down V=1
 Volume qualloop_s3data Removed / Volume qualloop_pgdata Removed / Network qualloop_default Removed
$ time make up
 redis Healthy / s3-init Exited / migrate Exited / postgres Healthy / mailpit Healthy / s3 Healthy / api Healthy / web Healthy
 make up  30.506 total
$ docker compose ps -a
 api running healthy | mailpit running healthy | migrate exited 0 | minio-init exited 0 (orphan, O-6)
 postgres running healthy | redis running healthy | s3 running healthy | s3-init exited 0 | web running healthy
$ curl :8000/healthz  -> {"status":"ok","version":"dev"}  HTTP 200
$ curl :8000/readyz   -> {"status":"ready","checks":{"db":"ok","redis":"ok","migrations":"ok"}}  HTTP 200
$ curl :3000/         -> web HTTP 200  <title>QualLoop</title>  <html lang="en" ...>
$ curl -b ql_locale=hi :3000/ -> <html lang="hi" ...>
$ openapi paths       -> ['/healthz', '/readyz']
$ s3-init logs        -> bucket ready: qualloop-files / bucket ready: qualloop-quarantine
$ anon S3 list / put  -> 403 / 403

$ make test-api            EXIT=0
 collected 31 items
 tests/integration/test_health.py ...  tests/integration/test_migrations.py ...
 tests/integration/test_rls_helper.py .................  tests/unit/test_placeholder.py ........
 TOTAL 159 3 12 2 97%   Required test coverage of 75.0% reached. Total coverage: 97.08%
 31 passed, 1 warning in 1.02s   (StarletteDeprecationWarning: httpx TestClient)
$ make migrations-roundtrip  EXIT=0
 Running upgrade  -> 0001 ... / Running downgrade 0001 -> ... / Running upgrade  -> 0001 ...
$ make lint-api            EXIT=0   module layering (ARCHITECTURE 3.1) KEPT  Contracts: 1 kept, 0 broken.
$ make lint-web            EXIT=0   All matched files use Prettier code style!  (eslint, tsc --noEmit clean)
$ make test-web            EXIT=0   Test Files 3 passed (3)  Tests 8 passed (8)
$ make e2e                 EXIT=0   [phone-360] ✓  [desktop-1440] ✓  2 passed (2.3s)
$ make secrets             EXIT=0   6 commits scanned. no leaks found
$ gitleaks (exact CI invocation)  EXIT=0   6 commits scanned. no leaks found
$ make migrate             EXIT=0
$ make seed                EXIT=0   seed: nothing to seed at P00
$ make audit               EXIT=0   No known vulnerabilities found (pip-audit) / No known vulnerabilities found (pnpm)
$ make scan-images         EXIT=0   qualloop-api:local (debian 13.7) 0 ... all targets 0 HIGH/CRITICAL fixable

# CI api-test job emulation (fresh containers, CI image digests)
$ docker run postgres:16@sha256:1a6a... ; psql -U postgres -v ON_ERROR_STOP=1 -f 01-roles.sql
 CREATE ROLE x3 / CREATE DATABASE x2 / REVOKE x2 / GRANT ROLE   roles EXIT=0
$ SeaweedFS (CI command) -> s3 code=403 after 3 tries ; aws-cli init.sh -> init EXIT=0
$ alembic upgrade head / downgrade base / upgrade head   mig EXIT=0
$ pytest -> Total coverage: 97.08%  31 passed

$ docker run rhysd/actionlint:1.7.7 -no-color .github/workflows/ci.yml   EXIT=1
 .github/workflows/ci.yml:65:9: shellcheck reported issue in this script: SC2034:warning:4:1: i appears unused   (O-3)
$ uvx pre-commit validate-config .pre-commit-config.yaml   EXIT=0
$ check_commit_msg.sh: "feat(p01): x" EXIT=0 | "fix(p00): y\nCo-authored-by: a" EXIT=1 | "random words" EXIT=1
$ gh run list   -> (empty)
$ git log origin/main -1 -> f579f78
$ §6 table/column script -> tables 48; missing []; col misses: amount_inr x5 (A-01), expiring_30 (enum value)
$ §24.2 grep "POST <path>" in API.md -> 24 ok
$ grep -c '^| INV-' INVARIANTS.md -> 181
$ psql qualloop tables -> public.alembic_version
$ git status --porcelain (before writing this report) -> (empty)
```

The stack was left running. The temporary CI-emulation containers (`civ-pg`, `civ-redis`, `civ-s3`) and the `civerify` network were removed.
