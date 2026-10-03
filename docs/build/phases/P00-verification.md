# P00 — Architecture & scaffold — Independent Verification

- Date: 2026-10-03
- Verifier: independent verifier (fresh context; no code edited)
- Environment: macOS, Docker via colima, `QL_PG_HOST_PORT=55432`, pnpm via `npx pnpm@10.34.6` (Makefile `PNPM`)

## Verdict: FAIL

The gate items that can be checked by machine (1–4) have evidence. The phase still fails for three reasons:
- **D-1:** the `.env.example` deliverable is missing.
- **G3-1:** one §7.4 rule is not in INVARIANTS.md.
- **Gate 5:** human approval is still pending.

GitHub Actions CI was **not executed**, because the repo has no remote. Gate 2 was checked by inspecting `.github/workflows/ci.yml` and running the matching local `make` targets.

## Gate table

| # | Gate item | Evidence | Result |
|---|---|---|---|
| 1 | `make up` starts all services; `/healthz` and web home return 200 | `make down` then `make up`: all 6 services healthy, plus migrate and minio-init exited OK. `curl /healthz` gave 200 `{"status":"ok"}`. `/readyz` gave 200 with db, redis and migrations all ok. `curl :3000/` gave 200 with `<title>QualLoop</title>`. Tests `test_healthz_200` and `test_readyz_200_when_deps_up` pass, and so does the Playwright test `home returns 200 and renders the app shell` (phone-360 and desktop-1440). | PASS |
| 2 | CI runs lint, types, tests (placeholder), migration up/down/up, all green | `ci.yml` parses and has 7 jobs: api-lint, api-test, web-lint, web-test, secrets, build, e2e. Every job was run locally and all are green: `make lint-api`, `make lint-web`, `make test-api` (31 passed, coverage 97.08%), `make test-web` (8 passed), `make migrations-roundtrip`, `make build`, `make secrets`, `make audit`, `make scan-images`, `make e2e`. Test `test_upgrade_downgrade_upgrade` passes. **Not executed on GitHub.** | PASS (local equivalent only) |
| 3 | Every §6 table is in DATA_MODEL.md; every invariant from §7, §10, §11, §12, §14, §15 is in INVARIANTS.md | Tables: all 48 of 48 §6 tables have their own heading. A script checked every column named in §6 against the matching section. The only "misses" are deliberate, documented renames: `amount_inr` became `amount_paise` (A-01), and `user_id` became `recipient_user_id`. Invariants: one §7.4 rule is missing (G3-1). | FAIL (one gap) |
| 4 | Every §24.2 command is in API.md | All 24 of 24 §24.2 paths appear verbatim in API.md §2 (grep count ≥ 1 for each). | PASS |
| 5 | Human has approved the architecture | All 19 ADRs say `Status: Proposed`. | PENDING — human |

### Deliverables checklist

Present:
- `docs/understanding.md`
- `docs/architecture/`: ARCHITECTURE, DATA_MODEL, INVARIANTS, API (error format, keyset pagination, idempotency), SCALING, REPO_LAYOUT
- `docs/adr/`: 19 ADRs, covering every required topic. ADR-017 covers the India region and Terraform; ADR-006 covers the Dramatiq choice.
- `api/`: app factory, settings, `/healthz` and `/readyz`, structlog JSON logging
- `web/`: app shell, `tokens.ts` (tested against DESIGN_SPEC), IBM Plex fonts, next-intl en/hi (cookie `ql_locale=hi` gives `lang="hi"`)
- `infra/compose.yaml`: pg16, redis, minio, mailpit
- `Makefile` targets: up, down, test, lint, fmt, migrate, seed. `make migrate` and `make seed` were both run and both work.
- `ci.yml`, `.pre-commit-config.yaml` (validated with `pre-commit validate-config`), `.gitignore`
- Alembic `0001_baseline`: `app_current_tenant_id()` plus GUC accessors; `helpers.enable_tenant_rls` is the policy template
- STATUS, OPEN_QUESTIONS and CHANGELOG are initialised

**Missing: `.env.example` (D-1).**

## Failures

**D-1. `.env.example` is missing.** PHASES.md P00 requires it. REPO_LAYOUT.md line 37 lists it as a P00 file, and README lines 102–103 tell users to copy it.

To reproduce:
```
docker run --rm -v "$PWD:/r:ro" alpine sh -c 'ls -a /r | grep -ci example'
```
This prints `0`. The same check with `find . -name ".env*"` also finds nothing.

**G3-1. A §7.4 rule is not in INVARIANTS.md.** The rule: "Replacement rejected → current_certificate_id unchanged; renewal_due_at is reset; the supplier is asked again."
- R4-17 covers the "current_certificate_id unchanged / still compliant" part.
- Nothing covers resetting `renewal_due_at` and re-requesting the certificate. `grep -c renewal_due_at docs/architecture/INVARIANTS.md` returns 0.
- `docs/understanding.md` line 87 states the rule, but it has no INV id and no test name.

## Observations (not gate items)

- **Commit trailer:** commit `f579f78` contains a `Signed-off-by:` trailer, which violates CLAUDE.md §4. History was not rewritten. The human must decide.
- **Duplicate commit:** `f3192d4` and `86287b7` have the same message. Neither commit uses the `(pNN)` scope; both predate P00.
- **No P00 commit or tag yet:** the working tree is dirty, which is expected at this stage.
- **Nothing unsafe would be committed:** `git status --porcelain --untracked-files=all` shows no secrets, `.env`, node_modules, .venv, .next, .coverage or tsbuildinfo, and all of these are confirmed git-ignored. The largest untracked files are `pnpm-lock.yaml` (172 kB) and `uv.lock` (157 kB).
- **No leaks found:** gitleaks over history (`make secrets`) and gitleaks `dir` mode over the working tree both found none.
- **No feature code:** the only DB table is `public.alembic_version`. OpenAPI paths are `['/healthz','/readyz']` only. `api/app` contains only `core` and `api`. No Part B terms (PPAP, PCN, concession) appear in the code.
- **Rule mapping:** `INVARIANTS.md` §18 maps §15.3 `trend` only via DATA_MODEL/API, not as an invariant. This is acceptable, because it is a stored attribute, not a rule.

## Spec spot-checks (§22, §24)

| Rule | Code / doc | Test |
|---|---|---|
| §24.1.1 RLS from the first migration | `alembic/helpers.py:enable_tenant_rls` (ENABLE + FORCE, p_tenant, p_supplier_deny) | `test_rls_is_forced_on_probe_table`, `test_tenant_b_rows_invisible_to_a_even_by_id`, `test_no_tenant_set_sees_nothing_and_cannot_insert`, all passing |
| §22 structured logs | `app/core/logging.py` | `test_log_lines_are_json_with_request_id` (asserts JSON with msg, request_id, tenant_id, level) |
| §22.1 backend layout / boundaries | import-linter `layers` contract in `api/pyproject.toml` | `lint-imports`: 1 contract kept, 0 broken |
| §22.3 events catalogue | All 19 events found in `docs/architecture` + `docs/adr` | grep: 0 missing |
| §22.2 dead-letter after 5 attempts | INV-PLT-13 / INV-PLT-20, ADR-006 | Planned for P01 (`test_outbox_event_dead_lettered_after_5_attempts_and_alert_emitted`). Correctly not built in P00. |

## Command log (trimmed)

```
$ make down && make up
 Container qualloop-postgres-1 Healthy ... qualloop-api-1 Healthy ... qualloop-web-1 Healthy   (29 s)
postgres 127.0.0.1:55432->5432 | redis 6379 | minio 9000-9001 | mailpit 1025/8025 | api 8000 | web 3000

$ curl :8000/healthz -> 200 {"status":"ok","version":"dev"}
$ curl :8000/readyz  -> 200 {"status":"ready","checks":{"db":"ok","redis":"ok","migrations":"ok"}}
$ curl :3000/        -> 200 <title>QualLoop</title>
$ openapi paths      -> ['/healthz', '/readyz']

$ make test-api
collected 31 items
tests/integration/test_health.py ...  test_migrations.py ...  test_rls_helper.py .................
tests/unit/test_placeholder.py ........
TOTAL 159 stmts 3 miss 97%   Required test coverage of 75.0% reached. Total coverage: 97.08%
31 passed, 1 warning in 1.06s

$ make migrations-roundtrip
Running downgrade 0001 -> , baseline ...
Running upgrade  -> 0001, baseline ...        (exit 0)

$ make lint-api   -> All checks passed! / 22 files already formatted / mypy Success: no issues found in 21 source files / Contracts: 1 kept, 0 broken  (exit 0)
$ make lint-web   -> eslint ok / All matched files use Prettier code style! / tsc --noEmit ok  (exit 0)
$ make test-web   -> Test Files 3 passed (3)  Tests 8 passed (8)  (exit 0)
$ make e2e        -> 2 passed (phone-360, desktop-1440)
$ make build      -> exit 0
$ make secrets    -> 3 commits scanned. no leaks found
$ gitleaks dir /repo -> no leaks found
$ make audit      -> pip-audit: No known vulnerabilities found / pnpm audit --prod: No known vulnerabilities found
$ make scan-images -> exit 0 (Trivy HIGH/CRITICAL fixable: 0)
$ make migrate    -> exit 0 ;  make seed -> "seed: nothing to seed at P00"
$ psql qualloop: tables -> public.alembic_version
$ git log         -> f579f78 "chore: project kit and frozen blueprint" + "Signed-off-by: ..." trailer
```

The stack was left running.
