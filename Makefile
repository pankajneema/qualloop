SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE := docker compose -f infra/compose.yaml
PNPM    ?= npx --yes pnpm@10.34.6

# Host-side ports published by compose. Override if 5432/6379 are already used on your machine:
#   QL_PG_HOST_PORT=55432 make up
PG_PORT    ?= $(or $(QL_PG_HOST_PORT),5432)
REDIS_PORT ?= $(or $(QL_REDIS_HOST_PORT),6379)
export QL_PG_HOST_PORT    := $(PG_PORT)
export QL_REDIS_HOST_PORT := $(REDIS_PORT)

# Dev-only placeholder (same default as infra/compose.yaml). Redis requires AUTH as ACL user qualloop_app (INV-SEC-08).
REDIS_PASSWORD ?= $(or $(QL_REDIS_PASSWORD),qualloop-redis-dev-only)
export QL_REDIS_PASSWORD := $(REDIS_PASSWORD)
# Core coverage gate (PHASES P01): app/core >= 90% on top of the overall gate in api/pyproject.toml.
CORE_COV_MIN ?= 90

# Tests/migrations run on the host against the compose Postgres/Redis (real services, no SQLite).
TEST_ENV := QL_ENV=local QL_TEST_DATABASE_URL=postgresql+psycopg://qualloop_app:qualloop_app@localhost:$(PG_PORT)/qualloop_test \
            QL_TEST_DATABASE_URL_OWNER=postgresql+psycopg://qualloop_owner:qualloop_owner@localhost:$(PG_PORT)/qualloop_test \
            QL_DATABASE_URL=postgresql+psycopg://qualloop_app:qualloop_app@localhost:$(PG_PORT)/qualloop_test \
            QL_REDIS_URL=redis://qualloop_app:$(REDIS_PASSWORD)@localhost:$(REDIS_PORT)/0 \
            QL_S3_ENDPOINT_URL=http://localhost:8333 \
            QL_SMTP_HOST=localhost QL_SMTP_PORT=1025 \
            QL_CLAMAV_HOST=localhost QL_CLAMAV_PORT=3310
# Owner credential: migrations only (never in TEST_ENV; tests/conftest.py sets it for alembic from the TEST_* URL).
MIGRATE_ENV := QL_DATABASE_URL_OWNER=postgresql+psycopg://qualloop_owner:qualloop_owner@localhost:$(PG_PORT)/qualloop_test
# Note: tests switch to Redis database 15 themselves (tests/conftest.py), so the URL above stays on db 0.

.PHONY: help up down deps migrate seed test test-api coverage-core test-web lint lint-api lint-web fmt e2e \
        migrations-roundtrip build secrets audit scan-images lint-ci ci

help:
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/ -/' | sort
	@echo ""
	@echo "Overrides: QL_PG_HOST_PORT=55432 (Postgres host port) and QL_REDIS_HOST_PORT drive BOTH compose and the test URLs,"
	@echo "  e.g. QL_PG_HOST_PORT=55432 make up && QL_PG_HOST_PORT=55432 make test-api (default 5432 / 6379)." 

up: ## start postgres, redis (ACL), s3 (SeaweedFS), mailpit, clamav, migrate, api, worker, dispatcher, scheduler, web (waits until healthy)
	$(COMPOSE) up -d --build --wait

down: ## stop the stack (V=1 also removes volumes)
	$(COMPOSE) down $(if $(V),-v,)

deps: ## start only what tests need: postgres, redis (ACL), s3 + buckets, mailpit, clamav
	$(COMPOSE) up -d --wait postgres redis s3 s3-init mailpit clamav

migrate: ## run alembic upgrade head in the stack
	$(COMPOSE) run --rm migrate

seed: ## load demo data (P00: no-op)
	$(COMPOSE) run --rm api python -m seeds.demo

test: test-api test-web ## api (pytest+coverage) and web (vitest)

test-api: deps ## pytest (overall gate 75% from pyproject) then the app/core >= 90% gate
	cd api && uv sync --frozen && $(TEST_ENV) uv run pytest
	$(MAKE) coverage-core

coverage-core: ## fail if app/core coverage (from the last pytest run) is below CORE_COV_MIN
	cd api && uv run coverage report --include='app/core/*' --fail-under=$(CORE_COV_MIN)

test-web:
	cd web && $(PNPM) install --frozen-lockfile && $(PNPM) vitest run

lint: lint-api lint-web ## ruff, ruff format, mypy --strict, lint-imports, eslint, prettier, tsc

lint-api:
	cd api && uv sync --frozen && uv run ruff check . && uv run ruff format --check . \
	  && uv run mypy && uv run lint-imports

lint-web:
	cd web && $(PNPM) install --frozen-lockfile && $(PNPM) eslint . && $(PNPM) prettier --check . \
	  && $(PNPM) tsc --noEmit

fmt: ## auto-format
	cd api && uv run ruff format . && uv run ruff check --fix .
	cd web && $(PNPM) prettier --write .

e2e: ## Playwright smoke against the running stack (make up first)
	cd web && $(PNPM) playwright test

migrations-roundtrip: deps ## alembic upgrade -> downgrade base -> upgrade on the test database
	cd api && $(TEST_ENV) $(MIGRATE_ENV) uv run alembic upgrade head \
	  && $(TEST_ENV) $(MIGRATE_ENV) uv run alembic downgrade base \
	  && $(TEST_ENV) $(MIGRATE_ENV) uv run alembic upgrade head

build: ## build production images (no push)
	docker build --target runtime -t qualloop-api:local api
	docker build --target runtime -t qualloop-web:local web

GITLEAKS := zricethezav/gitleaks:v8.21.2@sha256:0e99e8821643ea5b235718642b93bb32486af9c8162c8b8731f7cbdc951a7f46
TRIVY    := aquasec/trivy:0.75.0@sha256:af6acf9a6b85dfe389a1941505c0ce9efef52a4719635e1a962f022a3d855daa

secrets: ## gitleaks over git history (same mode as CI; uncommitted files are covered by the pre-commit hook)
	docker run --rm -v "$(CURDIR):/repo" -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory \
	  -e GIT_CONFIG_VALUE_0=/repo $(GITLEAKS) git /repo --no-banner --redact

audit: ## dependency vulnerability audit (pip-audit, pnpm audit --prod); needs network
	cd api && uv sync --frozen && uv run pip-audit --skip-editable
	cd web && $(PNPM) audit --prod

scan-images: build ## Trivy HIGH/CRITICAL (fixable) scan of the production images; needs network for the vuln DB
	for img in qualloop-api:local qualloop-web:local; do \
	  docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v qualloop-trivy-cache:/root/.cache $(TRIVY) \
	    image --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 --quiet $$img || exit 1; \
	done

ACTIONLINT := rhysd/actionlint:1.7.12@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667

lint-ci: ## actionlint over .github/workflows
	docker run --rm -v "$(CURDIR):/repo" -w /repo $(ACTIONLINT) -color

ci: lint lint-ci test-api migrations-roundtrip test-web build secrets audit scan-images ## same steps as .github/workflows/ci.yml, locally
	@echo "ci: all steps green"
