# P00 — Architecture & scaffold — Independent Verification (re-run)

- Date: 2026-10-03
- Verifier: independent verifier. Fresh context, no code edited; the only file written is this report.
- HEAD: `dd5306c docs(p00): close phase 0 status and changelog`. Tag `p00-verified` already points at `dd5306c`.
- Environment: macOS, Docker, `QL_PG_HOST_PORT=55432` (host port 5432 is used by another project), pnpm via `npx pnpm@10.34.6`.
- Clean state: `make down V=1` removed the pgdata and miniodata volumes, then `make up` rebuilt everything.

## Verdict: FAIL

All five gate items have evidence and pass. Gate 2 is checked locally only; Gate 5 is checked from documents only.

The phase still fails on one explicit P00 deliverable:
- **D-1:** `.env.example` does not exist.

This failure is not new. The previous verification report flagged it, and STATUS.md and CHANGELOG.md list it as a known limitation ("blocked by permission rule"). Even so, the phase was tagged `p00-verified` while the committed verification report said FAIL.

To reach PASS, add `.env.example` with the variables listed in REPO_LAYOUT.md §".env.example". Alternatively, the human can explicitly waive the deliverable and record the waiver.

## Gate table

| # | Gate item | Evidence | Result |
|---|---|---|---|
| 1 | `make up` starts all services; `/healthz` and web home return 200 | After `make down V=1` and `make up`, all services are up within 29 s: postgres, redis, minio, mailpit, api and web are healthy, and migrate and minio-init exited 0. `curl :8000/healthz` returned 200. `curl :3000/` returned 200 with `<title>QualLoop</title>`. Passing tests: `tests/integration/test_health.py::test_healthz_200` (asserts 200 and `status == "ok"`), `test_readyz_200_when_deps_up` (asserts the exact body with db, redis and migrations ok), `test_readyz_503_when_redis_down`, and Playwright `e2e/smoke.spec.ts` "home returns 200 and renders the app shell" (asserts status 200, CSP/permissions headers, nav and h1 "QualLoop", no console errors) on desktop-1440 and phone-360. | PASS |
| 2 | CI runs lint, types, tests (placeholder), migration up/down/up — all green | `.github/workflows/ci.yml` has 7 jobs: api-lint, api-test, web-lint, web-test, secrets, build, e2e. `actionlint` 1.7.7 exits 0. Each CI step was run locally and all exit 0: `make lint-api` (ruff, ruff format, mypy strict, lint-imports), `make lint-web` (eslint, prettier, tsc), `make test-api` (31 passed, coverage 97.08%), `make test-web` (8 passed), `make migrations-roundtrip`, `make secrets`, `make audit`, `make scan-images` (which builds the images), and `make e2e`. Test `test_migrations.py::test_upgrade_downgrade_upgrade` asserts that the baseline functions exist after upgrade, are gone after downgrade, and are back after re-upgrade. **GitHub Actions has never run:** `gh run list` is empty, and `origin/main` is at `f579f78`, 4 commits behind. I also ran the CI gitleaks command exactly as CI does (no safe.directory env): no leaks, exit 0. | PASS (local equivalent; never executed on GitHub) |
| 3a | Every §6 table appears in DATA_MODEL.md | My own script parsed the §6 tables: 48 of 48 have a heading in DATA_MODEL.md. It then checked every key column named in §6 against the matching section. The only column misses are `amount_inr` in 5 money tables, which is a documented rename to `amount_paise` (DATA_MODEL line 19, SPEC-GAP A-01). The other miss is the prose word "physical". | PASS |
| 3b | Every invariant from §7, §10, §11, §12, §14, §15 appears in INVARIANTS.md | INVARIANTS.md has 181 INV rows. I read §7, §10, §11, §12, §14 and §15 line by line against INVARIANTS.md §3, §4, §5, §8, §9, §10, §11 and §12. Every rule maps to an INV id with § reference, enforcement and test name. The gap found last time, §7.4 "replacement rejected → renewal_due_at reset, asked again", is now covered by INV-DOC-14 (`test_rejected_renewal_resets_renewal_due_at_and_rerequests`). Traceability for two §7.4 sub-rules is weak; see Observations O-3. | PASS |
| 4 | Every §24.2 command appears in API.md | Each of the 24 `POST` paths from §24.2 was grepped with `grep -cF` against API.md. All 24 are present, count ≥ 1 each, listed in API.md §2 "all 24, verbatim". | PASS |
| 5 | Human has approved the architecture | Documentary evidence only: commit `dd5306c` changed all 19 ADRs from `Proposed` to `Accepted (2026-10-03)`, and STATUS.md shows "Approved on 2026-10-03". The verifier cannot see the human's message. ADR-010, 011, 012, 015, 016 and 017 are "Accepted (design only)" and still need human decisions on paid services, ClamAV and the CI host. | PASS (documentary) |

### Deliverables (PHASES.md P00)

| Deliverable | Evidence | Result |
|---|---|---|
| `docs/understanding.md` | present (313 lines) | OK |
| `docs/architecture/` ARCHITECTURE, DATA_MODEL, INVARIANTS, API, SCALING, REPO_LAYOUT | all 6 present. API.md has the error format (§1.4), keyset pagination (§1.5) and idempotency (§1.6) | OK |
| `docs/adr/` (14 required topics) | 19 ADRs, which cover all the required topics | OK |
| `/api` app factory, settings, `/healthz`, `/readyz`, structured logging | `app/main.py`, `core/config.py`, `core/health.py`, `core/logging.py`. OpenAPI paths are `['/healthz','/readyz']` | OK |
| `/web` shell, tokens.ts from DESIGN_SPEC, fonts, i18n en/hi | `tokens.test.ts` parses DESIGN_SPEC.md and compares it to `tokens.ts` (passes). With cookie `ql_locale=hi` the page renders `<html lang="hi">`. `messages.test.ts` passes | OK |
| `/infra` compose (pg16, redis, minio, mailpit) | `infra/compose.yaml`; all four services healthy | OK |
| Makefile `up down test lint fmt migrate seed` | all targets present. `make migrate` exits 0. `make seed` prints "seed: nothing to seed at P00" | OK |
| CI pipeline, pre-commit hooks, `.gitignore` | `actionlint` passes. `pre-commit validate-config` prints "valid". `.gitignore` excludes `.env` and `.env.*` but keeps `.env.example` | OK |
| **`.env.example`** | `ls -a` at the repo root shows nothing matching. `git ls-files \| grep -i env.example` is empty | **MISSING (D-1)** |
| Alembic baseline + RLS helper | `0001_baseline.py` has `app_current_tenant_id()` and the GUC accessors. `helpers.enable_tenant_rls` is the policy template. `set_config('app.tenant_id', …)` is in `data_migration_per_tenant` | OK |
| STATUS, OPEN_QUESTIONS, CHANGELOG initialised | present. OPEN_QUESTIONS has A-01…A-90 | OK |

## Failures

### D-1 — `.env.example` missing (P00 deliverable)

Why it matters:
- PHASES.md line 43 lists `.env.example` as a P00 scaffold item.
- REPO_LAYOUT.md line 37 marks it `[P00]`, and lines 214 onward specify its contents.
- README.md line 102 tells users to "Copy `.env.example` to `.env`", but there is nothing to copy.

To reproduce:
```
cd /Users/mac/pnkj/qualloop
ls -a | grep -i 'env.example'            # no output
git ls-files | grep -i 'env.example'     # no output
grep -n "env.example" README.md          # README.md:102: ... Copy `.env.example` to `.env` ...
```

## Observations (not gate items)

- **O-1 Process:** tag `p00-verified` was applied to `dd5306c`, but the verification report committed at that point said **FAIL**. CLAUDE.md §3 step 6 requires failures to be fixed and the phase re-verified before closing.
- **O-2 Commit history:**
  - `f579f78` has `Signed-off-by: pankajneema <...>` inside the one-line subject. CLAUDE.md §4 forbids signatures.
  - `f3192d4` and `86287b7` have identical messages and no `(pNN)` scope.
  - All three predate P00. Both P00 commits follow the format exactly: one line, `docs(p00):`, no body or trailers.
  - The working tree was clean before this report was written.
  - Nothing ignored is tracked: `.venv`, `.next`, caches and `.coverage` are all `!!` ignored. The largest tracked files are `pnpm-lock.yaml` (168 kB) and `uv.lock` (156 kB).
- **O-3 Weak §7.4 traceability:** two §7.4 rules have no dedicated test name:
  - "REQUESTED → due_at passes → still REQUESTED, now overdue"
  - "an SQE asks for a replacement → renewal_requested_at / renewal_due_at set"

  Both are covered only by reference, through INV-DOC-03 ("requirement status machine, first-time vs renewal paths") and INV-DOC-09 (60-day auto-request). `renewal_requested_at` does not appear anywhere in INVARIANTS.md. This is acceptable for P00, but QA should add explicit test names in P03.
- **O-4 Minor doc/code inconsistency:** the docstring of `api/alembic/helpers.py::std_columns` says "`id` has no server default: the app generates UUIDv7". The code actually sets `server_default=app_uuid_v7()`. The behaviour matches ADR-005's SQL fallback, but the comment is wrong.
- **O-5:** INV-PLT-01's `test_every_table_has_tenant_id_and_forced_rls` is planned for P01. In P00 it is approximated by `test_every_rls_table_has_supplier_policy` and `test_introspection_detects_table_without_supplier_policy` on probe tables.

## Scope check (nothing outside P00 / no Part B)

- The database `qualloop` contains only `public.alembic_version`. There are no business tables.
- The API exposes only `/healthz` and `/readyz` (from `openapi.json`).
- Tracked app code consists of `api/app/{main.py, api/, core/}` and `web/src/{app, design, i18n, proxy.ts}` only.
- A case-insensitive grep of all tracked non-doc files for `ppap|pcn|concession|4m change|vendor rating|delivery performance` returns no matches (exit 1).

## Spec spot-checks (§22, §24, plus §6 conventions)

| # | Rule | Code | Test (assertion read) | Result |
|---|---|---|---|---|
| 1 | §6 / §24.1.1: RLS on `tenant_id` from the first migration | `api/alembic/helpers.py::enable_tenant_rls`: ENABLE + FORCE, `p_tenant` USING/WITH CHECK `tenant_id = app_current_tenant_id()`, RESTRICTIVE `p_supplier_deny` | `test_rls_is_forced_on_probe_table` (asserts `(relrowsecurity, relforcerowsecurity) == (True, True)`), `test_tenant_b_rows_invisible_to_a_even_by_id` (count == 0), `test_insert_for_other_tenant_fails`, `test_update_cannot_move_row_to_other_tenant`, `test_no_tenant_set_sees_nothing_and_cannot_insert`: all pass | OK |
| 2 | §22 structured logs with request correlation | `api/app/core/logging.py`, `api/app/api/middleware.py` | `test_log_lines_are_json_with_request_id` (parses JSON; asserts msg, request_id, tenant_id, level), `test_request_id_is_echoed_and_hostile_ids_replaced`, `test_error_responses_carry_request_id`: all pass | OK |
| 3 | §22.1 modular monolith boundaries | import-linter `layers` contract in `api/pyproject.toml` | `lint-imports`: "module layering (ARCHITECTURE 3.1) KEPT — Contracts: 1 kept, 0 broken" | OK |
| 4 | §21.2 / ADR-004: app role cannot bypass RLS | `infra/postgres/init/01-roles.sql` (NOSUPERUSER NOBYPASSRLS, TEMP revoked) | `test_app_role_cannot_bypass_rls` (asserts not super and not bypassrls for all 3 roles), `test_app_role_has_no_temp_privilege`, `test_app_role_has_no_delete`: all pass | OK |
| 5 | §24 migrations reversible (up/down/up) | `0001_baseline.py` upgrade/downgrade | `test_upgrade_downgrade_upgrade` (asserts the function set is present, then absent, then present) and `make migrations-roundtrip` exit 0 | OK |
| 6 | DESIGN_SPEC tokens (P00 web) | `web/src/design/tokens.ts` | `tokens.test.ts` reads DESIGN_SPEC.md and asserts 9 colour rows match, the typography table matches, and the status colours match | OK |

## Command log (trimmed, real output)

```
$ export QL_PG_HOST_PORT=55432
$ make down V=1
 Volume qualloop_pgdata Removed / Volume qualloop_miniodata Removed / Network qualloop_default Removed
$ make up        (29.3 s)
 minio Healthy / minio-init Exited / redis Healthy / postgres Healthy / mailpit Healthy / api Healthy / migrate Exited / web Healthy
$ docker compose ps -a
 api running 0 | mailpit running 0 | migrate exited 0 | minio running 0 | minio-init exited 0 | postgres running 0 (postgres:16@sha256:1a6a...) | redis running 0 | web running 0
$ curl :8000/healthz -> 200 {"status":"ok","version":"dev"}
$ curl :8000/readyz  -> 200 {"status":"ready","checks":{"db":"ok","redis":"ok","migrations":"ok"}}
$ curl :3000/        -> 200 <title>QualLoop</title>
$ curl -b ql_locale=hi :3000/ -> <html lang="hi" ...>
$ openapi paths      -> ['/healthz', '/readyz']

$ make test-api     EXIT 0
collected 31 items
tests/integration/test_health.py ...  tests/integration/test_migrations.py ...
tests/integration/test_rls_helper.py .................  tests/unit/test_placeholder.py ........
TOTAL 159 3 12 2 97%   Required test coverage of 75.0% reached. Total coverage: 97.08%
31 passed, 1 warning in 1.07s     (warning: Starlette httpx TestClient deprecation)

$ make migrations-roundtrip   EXIT 0
Running downgrade 0001 -> , baseline ...
Running upgrade  -> 0001, baseline ...

$ make lint-api     EXIT 0
All checks passed! / 22 files already formatted / Success: no issues found in 21 source files / Contracts: 1 kept, 0 broken.
$ make lint-web     EXIT 0   (eslint, "All matched files use Prettier code style!", tsc --noEmit)
$ make test-web     EXIT 0   Test Files 3 passed (3)  Tests 8 passed (8)
$ make e2e          EXIT 0   [desktop-1440] ✓  [phone-360] ✓  2 passed (2.7s)
$ make secrets      EXIT 0   5 commits scanned. no leaks found
$ gitleaks (exact CI invocation, no safe.directory)  EXIT 0  no leaks found
$ make audit        EXIT 0   pip-audit: No known vulnerabilities found / pnpm audit: No known vulnerabilities found
$ make scan-images  EXIT 0   (builds api+web runtime images; Trivy HIGH/CRITICAL fixable: clean)
$ actionlint 1.7.7 .github/workflows/ci.yml   EXIT 0
$ pre-commit validate-config .pre-commit-config.yaml  -> valid
$ make migrate      EXIT 0
$ make seed         -> seed: nothing to seed at P00
$ psql qualloop: tables -> public.alembic_version
$ gh run list       -> (empty; CI never ran on GitHub)
$ git log origin/main -1 -> f579f78 (local main is 4 commits ahead)
$ §6 table/column script -> tables in §6: 48; missing tables: []; only column misses amount_inr (x5, A-01) and "physical" (prose)
$ §24.2 grep -> 24/24 paths present in API.md (count >= 1 each)
$ ls -a | grep -i env.example -> (no output)    <- D-1
```

The stack was left running.
