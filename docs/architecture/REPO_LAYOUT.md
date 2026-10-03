# QualLoop — Repository Layout (Phase 0)

The devops engineer scaffolds exactly this tree in P00. Markers: **[P00]** = created now (may be a stub),
**[Pnn]** = created in that phase, **(exists)** = already in the repo. Anything not listed is not created.
Monorepo, one git repository, no workspace tooling beyond `uv` (Python) and `pnpm` (web).

## 1. Tool choices (ADR-002, ADR-013, ADR-016)

| Concern | Tool | Version pin | Notes |
| --- | --- | --- | --- |
| Python | CPython 3.12 | `api/.python-version` = `3.12` | CLAUDE.md §6 |
| Python package/env manager | `uv` | `uv.lock` committed | `uv sync --frozen` in CI and Docker |
| Python lint + format | `ruff` (`ruff check`, `ruff format`) | in `pyproject.toml` dev group | `ruff format` is black-compatible; it replaces `black --check` named in `.claude/agents/backend-engineer.md` (see open question Q-T1) |
| Python types | `mypy --strict` | dev group | plugin `pydantic.mypy` |
| Module boundaries | `import-linter` | dev group | contracts in `pyproject.toml` `[tool.importlinter]` (ARCHITECTURE.md §3.1) |
| Python tests | `pytest`, `pytest-cov`, `hypothesis`, `httpx` (TestClient), `time-machine` (frozen time) | dev group | real Postgres/Redis from compose or CI services; no SQLite |
| Node | Node.js 24 LTS | `web/.nvmrc` = `24` | |
| JS package manager | `pnpm` | `packageManager` field in `web/package.json`; `pnpm-lock.yaml` committed | via corepack |
| TS | `typescript` strict (`"strict": true`, `"noUncheckedIndexedAccess": true`) | | `tsc --noEmit` |
| JS lint/format | `eslint` (flat config, `eslint-config-next`), `prettier` | | |
| JS unit tests | `vitest` | | |
| E2E | `@playwright/test` (+ `@axe-core/playwright` from P08) | | 360 px phone project + desktop project |
| Git hooks | `pre-commit` | `.pre-commit-config.yaml` | |
| Containers | Docker, Docker Compose v2 | `infra/compose.yaml` | |
| CI | GitHub Actions | `.github/workflows/ci.yml` | repo host to be confirmed (Q-T2) |
| IaC | Terraform ≥ 1.9 (AWS provider) | `infra/terraform/` | [P09] |

## 2. Tree

```text
qualloop/
├── CLAUDE.md                                  (exists)
├── README.md                                  (exists) — [P00] append "Local development" section
├── Makefile                                   [P00]
├── .gitignore                                 (exists) — [P00] extend (see §5)
├── .editorconfig                              [P00]
├── .env.example                               [P00]
├── .pre-commit-config.yaml                    [P00]
├── .github/
│   └── workflows/
│       ├── ci.yml                             [P00] third-party actions pinned by full commit SHA; minimal `permissions:`
│       ├── security-audit.yml                 [P01] weekly scheduled pip-audit, pnpm audit, Trivy, gitleaks (S-1)
│       └── deploy.yml                         [P09]
├── .claude/                                   (exists)
├── api/
│   ├── .python-version                        [P00]
│   ├── pyproject.toml                         [P00] deps, ruff, mypy, pytest, coverage, importlinter config
│   ├── uv.lock                                [P00]
│   ├── Dockerfile                             [P00] multi-stage; one image for api/worker/dispatcher/scheduler
│   ├── .dockerignore                          [P00]
│   ├── alembic.ini                            [P00]
│   ├── alembic/
│   │   ├── env.py                             [P00] uses QL_DATABASE_URL_OWNER
│   │   ├── script.py.mako                     [P00]
│   │   ├── helpers.py                         [P00] enable_tenant_rls() (p_tenant + p_supplier_deny), enable_supplier_scoped_rls(), std_columns(), append_only(), data_migration_per_tenant()
│   │   └── versions/
│   │       └── 0001_baseline.py               [P00] extensions (btree_gist), app_current_tenant_id(), app_current_actor_type(),
│   │                                                 app_uuid_v7(), trg_set_updated_at(), trg_append_only(); default privileges
│   │                                                 for qualloop_app; reversible downgrade
│   ├── app/
│   │   ├── __init__.py                        [P00]
│   │   ├── main.py                            [P00] create_app() factory; mounts /healthz, /readyz, /api/v1 router
│   │   ├── worker.py                          [P01] Dramatiq broker + middleware (tenant, retries, DLQ, Prometheus)
│   │   ├── dispatcher.py                      [P01] outbox dispatcher entrypoint
│   │   ├── scheduler.py                       [P01] APScheduler entrypoint + leader lock
│   │   ├── core/
│   │   │   ├── __init__.py                    [P00]
│   │   │   ├── config.py                      [P00] pydantic-settings `Settings` (env prefix QL_)
│   │   │   ├── logging.py                     [P00] structlog JSON; request_id/tenant_id contextvars
│   │   │   ├── db.py                          [P00] engine + session factory; [P01] tenant_tx(), read_tx()
│   │   │   ├── health.py                      [P00] healthz/readyz handlers
│   │   │   ├── errors.py                      [P01] problem+json, DB error mapping
│   │   │   ├── ids.py · money.py · timeutils.py · numbering.py   [P01]
│   │   │   ├── tenancy.py · permissions.py · hooks.py · idempotency.py · ratelimit.py · telemetry.py   [P01]
│   │   │   ├── auth/ (passwords.py, sessions.py, router.py)       [P01]
│   │   │   ├── commands/ (base.py, state_machine.py)              [P01]
│   │   │   ├── audit/ (models.py, writer.py)                      [P01]
│   │   │   ├── outbox/ (models.py, writer.py, registry.py, dispatcher.py, sweeper.py)   [P01]
│   │   │   ├── files/ (storage.py, scanner.py, router.py)         [P01]
│   │   │   └── models.py (tenants, plants, users)                 [P01]
│   │   ├── masters/          [P02] models · schemas · commands · queries · service · router · events · hooks · policies · jobs
│   │   ├── imports/          [P02] + parsers/ · validators/ · report.py
│   │   ├── documents/        [P03] + validity.py · compliance.py · scan_daily.py
│   │   ├── ai/               [P03] providers/ (base.py, fake.py, <vendor>.py) · extraction/ · review_8d/ [P05] · prompts/ · schemas/ · benchmarks/
│   │   ├── receipts/         [P04] + attribution.py · rejections.py (canonical/unreconciled)
│   │   ├── ncr/              [P04] + signature.py · state_machine.py
│   │   ├── supplier_access/  [P05] + otp.py · router_public.py · router_supplier.py
│   │   ├── notifications/    [P05] + channels/ (whatsapp.py, email.py, in_app.py, fake.py) · templates/ (en/, hi/) · consent.py · webhooks.py
│   │   ├── scar/             [P05] + gate.py · severity_policy.py · state_machine.py · reminders.py
│   │   ├── effectiveness/    [P06] + watcher.py
│   │   ├── finance/          [P06] + allocator.py (pro-rata) · views.py (cohort/cash)
│   │   ├── scoring/          [P07] + metrics/ · score.py · snapshot.py · explain.py
│   │   ├── risk/             [P07] + rules/ (one file per rule_code) · recompute.py · reasons.py
│   │   ├── reports/          [P08] + my_work.py · supplier_360.py · case.py · pdf/ (templates/) · exports.py
│   │   └── api/
│   │       ├── __init__.py                    [P00]
│   │       ├── router.py                      [P00] composes module routers under /api/v1 (empty at P00)
│   │       ├── middleware.py                  [P00] request id + access log; [P01] auth, CSRF, rate limit
│   │       └── webhooks.py                    [P05]
│   ├── seeds/
│   │   └── demo.py                            [P01] minimal tenant/plant/user; grows each phase to §24.1.6 by P09
│   └── tests/
│       ├── conftest.py                        [P00] DB/Redis fixtures (compose services), app client
│       ├── factories/                         [P01]
│       ├── unit/
│       │   └── test_placeholder.py            [P00]
│       │   └── <module>/                      [Pnn]
│       ├── integration/
│       │   ├── test_health.py                 [P00] /healthz 200, /readyz 200 with deps up
│       │   ├── test_migrations.py             [P00] upgrade → downgrade → upgrade
│       │   └── <module>/                      [Pnn]
│       ├── security/                          [P01] tenant isolation, supplier scope (§21.2)
│       └── benchmarks/                        [P03] AI benchmark sets (§20.5), not in default test run
├── web/
│   ├── .nvmrc                                 [P00]
│   ├── package.json · pnpm-lock.yaml          [P00]
│   ├── tsconfig.json                          [P00] strict
│   ├── next.config.ts                         [P00] next-intl plugin, output 'standalone', security headers
│   ├── tailwind.config.ts                     [P00] theme built from src/design/tokens.ts
│   ├── postcss.config.mjs                     [P00]
│   ├── eslint.config.mjs · .prettierrc · .prettierignore   [P00]
│   ├── vitest.config.ts                       [P00]
│   ├── playwright.config.ts                   [P00] projects: desktop-1440, phone-360
│   ├── Dockerfile · .dockerignore             [P00]
│   ├── public/
│   │   └── icons/                             [P04] PWA icons
│   ├── messages/
│   │   ├── en.json                            [P00] app shell strings
│   │   └── hi.json                            [P00] same keys
│   ├── src/
│   │   ├── design/
│   │   │   ├── tokens.ts                      [P00] every value in DESIGN_SPEC.md (type scale, colours, status colours, space, radius, layout)
│   │   │   └── fonts.ts                       [P00] next/font: IBM Plex Sans, IBM Plex Sans Devanagari, IBM Plex Mono (self-hosted at build)
│   │   ├── i18n/
│   │   │   ├── config.ts                      [P00] locales ['en','hi'], default 'en'
│   │   │   └── request.ts                     [P00] next-intl request config
│   │   ├── app/
│   │   │   ├── layout.tsx                     [P00] html lang, fonts, NextIntlClientProvider
│   │   │   ├── page.tsx                       [P00] app shell home (nav 232 px + "QualLoop"), returns 200
│   │   │   ├── globals.css                    [P00] Tailwind import + token CSS variables
│   │   │   ├── manifest.ts                    [P04] PWA manifest
│   │   │   ├── (auth)/login/                  [P01]
│   │   │   ├── (app)/…                        [P02+] my-work, suppliers, imports, ncrs, scars, documents, reports
│   │   │   ├── capture/                       [P04] inspector NCR PWA flow
│   │   │   ├── s/[token]/route.ts             [P05] server route handler: exchange token → ql_pre cookie → 303 /s (no HTML, no logging)
│   │   │   └── s/                             [P05] supplier pages (no login) under /s
│   │   ├── components/                        [P01+] Button, Field, StatusChip, KpiTile, QueueRow, ReasonDialog, Tabs, Table
│   │   ├── lib/
│   │   │   ├── api/                           [P01] schema.d.ts (openapi-typescript, generated), client.ts (openapi-fetch)
│   │   │   └── format.ts                      [P01] ₹ Indian grouping, dates "3 Oct 2026" in plant tz
│   │   └── sw/                                [P04] minimal service worker (app-shell cache only; no offline mode, §5.3)
│   ├── src/design/tokens.test.ts              [P00] vitest: tokens match DESIGN_SPEC values
│   └── e2e/
│       └── smoke.spec.ts                      [P00] home returns 200 and renders shell
├── infra/
│   ├── compose.yaml                           [P00] services below
│   ├── postgres/
│   │   └── init/01-roles.sql                  [P00] roles qualloop_owner, qualloop_app, qualloop_sysfn; DBs qualloop, qualloop_test
│   ├── minio/
│   │   └── init.sh                            [P00] create buckets qualloop-files, qualloop-quarantine (private)
│   ├── terraform/                             [P09] modules/{network,rds,redis,s3,ecs,alb_waf,secrets,observability}, envs/{staging,prod}
│   └── scripts/
│       └── restore_drill.sh                   [P09]
├── design/
│   └── README.md                              [P00] where design-canvas exports and screenshots live; source of truth stays docs/design/DESIGN_SPEC.md
└── docs/                                      (exists)
    ├── blueprint/                             (exists, frozen)
    ├── design/DESIGN_SPEC.md                  (exists)
    ├── architecture/                          [P00] this set
    ├── adr/                                   [P00] ADR-001…ADR-019
    ├── build/                                 (exists) STATUS.md, OPEN_QUESTIONS.md, PHASES.md, phases/
    ├── runbooks/                              [P09] deploy, rollback, restore, incident, rotate-secrets
    ├── understanding.md                       (exists)
    └── CHANGELOG.md                           (exists)
```

## 3. `infra/compose.yaml` services [P00]

| Service | Image | Ports (host) | Notes |
| --- | --- | --- | --- |
| `postgres` | `postgres:16` | 5432 | init scripts from `infra/postgres/init`; healthcheck `pg_isready` |
| `redis` | `redis:7` | 6379 | healthcheck `redis-cli ping` |
| `minio` | `minio/minio` (+ `minio/mc` one-shot init) | 9000, 9001 | buckets from `infra/minio/init.sh` |
| `mailpit` | `axllent/mailpit` | 1025 (SMTP), 8025 (UI) | |
| `migrate` | api image, `alembic upgrade head` | — | one-shot; `depends_on: postgres healthy` |
| `api` | api image, `uvicorn app.main:create_app --factory --reload` | 8000 | `depends_on: migrate completed` |
| `web` | web image (dev: `pnpm dev`) | 3000 | `NEXT_PUBLIC_*` none secret; proxies `/api` → api:8000 in dev |
| `worker` · `dispatcher` · `scheduler` | api image | — | **[P01]** (added when the code exists) |
| `clamav` | `clamav/clamav` | 3310 | **[P01], only after human approval (A-47)** |

## 4. Makefile targets [P00]

| Target | Does |
| --- | --- |
| `make up` | `docker compose -f infra/compose.yaml up -d --build --wait` (all services healthy) |
| `make down` | `docker compose -f infra/compose.yaml down` (volumes kept; `make down V=1` removes volumes) |
| `make migrate` | `docker compose run --rm migrate` |
| `make seed` | `docker compose run --rm api uv run python -m seeds.demo` (P00: no-op that exits 0; P01+: real seed) |
| `make test` | `api`: `uv run pytest --cov=app` (unit + integration + security) against compose Postgres/Redis; `web`: `pnpm vitest run` |
| `make lint` | `uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run lint-imports`; `pnpm eslint . && pnpm prettier --check . && pnpm tsc --noEmit` |
| `make fmt` | `uv run ruff format . && uv run ruff check --fix .`; `pnpm prettier --write .` |
| `make e2e` | `pnpm playwright test` against `make up` stack |

## 5. Root files [P00]

`.gitignore` additions: `.env`, `.env.*` except `.env.example`, `__pycache__/`, `.venv/`, `.mypy_cache/`, `.ruff_cache/`,
`.pytest_cache/`, `.coverage*`, `htmlcov/`, `node_modules/`, `.next/`, `playwright-report/`, `test-results/`,
`*.tfstate*`, `.terraform/`, `.DS_Store`.

`.pre-commit-config.yaml` hooks: `trailing-whitespace`, `end-of-file-fixer`, `check-yaml`, `check-added-large-files`
(`--maxkb=500`), `detect-private-key`, `gitleaks`, `ruff` (check --fix), `ruff-format`, local hook `prettier --check`
on `web/`. (mypy, tsc, tests run in CI and `make lint`/`make test`, not on every commit.)

`.env.example` (no real values):

| Variable | Example | Used by |
| --- | --- | --- |
| `QL_ENV` | `local` | api |
| `QL_DATABASE_URL` | `postgresql+psycopg://qualloop_app:qualloop_app@postgres:5432/qualloop` | api/worker |
| `QL_DATABASE_URL_OWNER` | `postgresql+psycopg://qualloop_owner:qualloop_owner@postgres:5432/qualloop` | migrate |
| `QL_TEST_DATABASE_URL` | `…/qualloop_test` | tests |
| `QL_REDIS_URL` | `redis://redis:6379/0` | api/worker |
| `QL_S3_ENDPOINT_URL` | `http://minio:9000` | api/worker |
| `QL_S3_BUCKET_FILES` / `QL_S3_BUCKET_QUARANTINE` | `qualloop-files` / `qualloop-quarantine` | api/worker |
| `QL_S3_ACCESS_KEY` / `QL_S3_SECRET_KEY` | `minioadmin` / `change-me` | local only |
| `QL_SMTP_HOST` / `QL_SMTP_PORT` | `mailpit` / `1025` | worker |
| `QL_SESSION_SECRET` / `QL_HMAC_SECRET` | `change-me-32-bytes-min` | api |
| `QL_PUBLIC_BASE_URL` | `http://localhost:3000` | links in messages |
| `QL_WHATSAPP_PROVIDER` / `QL_AI_PROVIDER` | `fake` / `fake` | worker |
| `QL_LOG_LEVEL` | `INFO` | all |
| `QL_OTEL_EXPORTER_OTLP_ENDPOINT` | empty (disabled locally) | all |
| `NEXT_PUBLIC_DEFAULT_LOCALE` | `en` | web |

## 6. Health endpoints [P00]

| Endpoint | Auth | Checks | 200 body | Failure |
| --- | --- | --- | --- | --- |
| `GET /healthz` | none | process alive only (no I/O) | `{"status":"ok","version":"<git sha>"}` | — |
| `GET /readyz` | none | `SELECT 1` on Postgres (as app role), Redis `PING`, Alembic revision == head | `{"status":"ready","checks":{"db":"ok","redis":"ok","migrations":"ok"}}` | 503 with failing check names (no connection strings) |

Web: `GET /` returns 200 (app shell). Load-balancer target health checks: api → **`/healthz`**, web → `/` (m7). `/readyz` is used by the post-deploy gate and uptime canaries.

## 7. CI pipeline `.github/workflows/ci.yml` [P00]

| Job | Steps | Runs |
| --- | --- | --- |
| `api-lint` | uv sync --frozen; ruff check; ruff format --check; mypy --strict app; lint-imports | every push/PR |
| `api-test` | services postgres:16 (+ init roles SQL), redis:7, minio; alembic upgrade head → downgrade base → upgrade head; pytest with coverage (gate 75% overall from P01; per-module 90% gates added in the phases that create those modules) | every push/PR |
| `web-lint` | pnpm install --frozen-lockfile; eslint; prettier --check; tsc --noEmit | every push/PR |
| `web-test` | vitest run | every push/PR |
| `e2e` | compose up; playwright (desktop + phone-360) | push to main [P00 smoke], PRs from P04 |
| `security` | gitleaks; pip-audit; pnpm audit --prod; trivy image scan | [P01] every PR; plus weekly `security-audit.yml` (S-1) |
| `build` | docker build api + web (no push until P09) | every push/PR |
| `ai-bench` | benchmark gates (§20.5) | [P03] on changes under `api/app/ai/prompts/**` or provider config |

## 8. Scaffold acceptance (P00 gate items 1–2)

| Check | Command | Expected |
| --- | --- | --- |
| Stack starts | `make up` | all services healthy |
| API health | `curl -s -o /dev/null -w '%{http_code}' localhost:8000/healthz` | `200` |
| API ready | `curl -s localhost:8000/readyz` | `"ready"` |
| Web home | `curl -s -o /dev/null -w '%{http_code}' localhost:3000/` | `200` |
| Lint/types | `make lint` | exit 0 |
| Tests | `make test` | placeholder + health + migrations up/down/up pass |
| CI | `ci.yml` run | all P00 jobs green |
