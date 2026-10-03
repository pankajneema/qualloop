# ADR-002 — Backend runtime and tooling

- Status: Proposed
- Spec: §22 (FastAPI, SQLAlchemy, Pydantic), CLAUDE.md §6

## Context
CLAUDE.md fixes Python 3.12, FastAPI, SQLAlchemy 2, Pydantic v2, Alembic, PostgreSQL 16. Open choices: sync vs async
DB access, driver, package manager, lint/type tools, settings, logging.

## Options considered
| Concern | Options | Chosen | Why |
| --- | --- | --- | --- |
| DB access style | async SQLAlchemy + asyncpg; **sync SQLAlchemy + psycopg 3** | sync | identical code in API (FastAPI runs `def` endpoints in a threadpool) and in thread-based Dramatiq workers; simpler transactions, `SET LOCAL` GUCs and triggers; workload is DB-bound CRUD, not high fan-out I/O |
| Driver | psycopg2, **psycopg 3** | psycopg 3 | maintained, binary wheels, server-side cursors for exports |
| Package manager | pip-tools, poetry, **uv** | uv | fast, lockfile, single tool for venv + Python pin |
| Lint/format | flake8+black+isort, **ruff (check + format)** | ruff | one tool; black-compatible formatting |
| Types | pyright, **mypy --strict** | mypy | CLAUDE agents specify mypy strict; Pydantic plugin |
| Settings | **pydantic-settings** | — | typed env config, prefix `QL_` |
| Logging | stdlib, **structlog** JSON | structlog | contextvars for request_id/tenant_id |
| App server | **gunicorn + uvicorn workers** | — | process supervision in containers |
| UUIDv7 | **`uuid6` package** | — | Python 3.12 has no `uuid.uuid7` (ADR-005) |
| Test | **pytest, hypothesis, httpx, time-machine** | — | property tests for money/attribution (data-engineer rule) |

## Decision
As "Chosen" above. All dependencies pinned in `uv.lock`. New runtime dependencies are added only in the phase that
needs them (REPO_LAYOUT.md marks the phase).

## Consequences
- No async/await in domain code; long external calls happen in workers, never in requests.
- Throughput per api task is bounded by threadpool size (default 40) × DB pool; sized in SCALING.md.

## Revisit when
- api threadpool saturation (queueing > 50 ms p95) at < 60% CPU, or
- an endpoint must hold many concurrent slow I/O calls (none planned in Part A).
