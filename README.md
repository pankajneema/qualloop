# QualLoop — Claude Code Build Kit

A ready-to-use setup that makes Claude Code build QualLoop phase by phase like a senior engineering team:
architecture first, tests first, independent verification in fresh contexts, human approval at every gate,
and clean plain-git commits.

## What's inside

```
CLAUDE.md                         Project constitution: sources of truth, team, phase protocol, git rules, human gates
.claude/settings.json             No co-author trailers; blocks push/remote/rebase/reset/amend; hides .env
.claude/agents/                   10 specialist subagents (each runs in its own fresh context)
  architect.md                    Architecture, ADRs, data model, scaling path (Opus)
  qa-engineer.md                  Writes failing tests from the SPEC before code exists
  backend-engineer.md             FastAPI, migrations + RLS, commands, outbox, workers
  data-engineer.md                Metrics, money invariants, attribution, snapshots (Opus)
  frontend-engineer.md            Next.js screens to DESIGN_SPEC, i18n, PWA
  devops-engineer.md              Docker, CI/CD, IaC, observability, backups
  security-reviewer.md            Tenant isolation, supplier access, OWASP (read-only, Opus)
  code-reviewer.md                Correctness, boundaries, transactions, N+1 (read-only, Opus)
  ux-reviewer.md                  Design + UX rules + accessibility (read-only)
  verifier.md                     Independent phase gate check, evidence only (read-only, Opus)
.claude/commands/
  architecture.md                 /architecture       → Phase 0
  build-phase.md                  /build-phase <N>    → one full phase with gates and commits
  verify-phase.md                 /verify-phase <N>   → fresh independent verification
  fix-bug.md                      /fix-bug <desc>     → test-first bug fix + commit
  status.md                       /status             → where we are, what's next
docs/build/PHASES.md              P00–P10 + scale track: scope, mandatory tests, gates
docs/build/STATUS.md              Phase tracker
docs/build/OPEN_QUESTIONS.md      SPEC-GAP register
docs/design/DESIGN_SPEC.md        Typography, colours, components, screens, 10 UX rules
docs/blueprint/                   Put Supplier_Quality_OS_Blueprint_FINAL.md here
docs/CHANGELOG.md
```

## Setup (once)

```bash
mkdir qualloop && cd qualloop
git init
# copy everything from this kit into the folder (including the hidden .claude folder)
# copy the frozen blueprint:
cp /path/to/Supplier_Quality_OS_Blueprint_FINAL.md docs/blueprint/
git add -A
git commit -m "chore: project kit and frozen blueprint"
claude
```

## Run

| Step | Type in Claude Code | You do |
| --- | --- | --- |
| 1 | `/architecture` | Read the summary, ADRs and ambiguity list. Reply "approved" or give changes. |
| 2 | `/build-phase 1` | Review the gate report. Reply "approved". |
| 3 | `/build-phase 2` … `/build-phase 9` | Same, one phase per session (start a new session with `/clear` between phases). |
| 4 | Pilot plant goes live | — |
| 5 | `/build-phase 10` | R1.1 items |
| any time | `/status`, `/verify-phase N`, `/fix-bug <description>` | — |

Tips:
- Use a fresh session (`/clear`) for each phase; everything important lives in files, not chat memory.
- Answer SPEC-GAP questions at each gate; decisions go into `docs/build/OPEN_QUESTIONS.md`.
- Commits are local only. Push yourself when you choose (`git push` is blocked for the agent).
- If your Claude Code version uses a different setting name for co-author attribution, CLAUDE.md §4 still
  forbids trailers; check `git log` after the first commit.

## What this kit cannot guarantee

No prompt makes software bug-free. This kit makes errors unlikely to survive: tests are written from the spec
by an agent that never saw the code, every phase is verified by a fresh agent that must show command output,
money and tenant rules are enforced in the database, and you approve every phase before the next starts.

## Local development

Prerequisites: Docker (with Compose v2), `make`, [uv](https://docs.astral.sh/uv/) (Python 3.12 is installed by uv),
Node.js 24 (`web/.nvmrc`). pnpm is pinned in `web/package.json` (`packageManager`). pnpm is not required globally:
the Makefile runs it through `npx pnpm@10.34.6` (override with `make PNPM=pnpm ...`; with corepack available,
`corepack enable pnpm` works too).

```
make up        # postgres, redis, minio (+ buckets), mailpit, migrate, api, web; waits until healthy
make down      # stop (V=1 also drops volumes)
make test      # api: pytest + coverage gate against compose Postgres/Redis; web: vitest
make lint      # ruff, ruff format --check, mypy --strict, lint-imports, eslint, prettier --check, tsc
make fmt       # auto-format
make migrate   # alembic upgrade head
make seed      # demo data (no-op until P01)
make e2e       # Playwright smoke against the running stack (first: cd web && npx pnpm@10.34.6 exec playwright install chromium)
make ci        # the same steps as .github/workflows/ci.yml, locally
```

| URL | Service |
| --- | --- |
| http://localhost:3000 | web (Next.js) |
| http://localhost:8000/healthz, /readyz | api liveness / readiness |
| http://localhost:8025 | Mailpit (local email) |
| http://localhost:9001 | MinIO console (dev credentials in `infra/compose.yaml`) |

If 5432 or 6379 is already used on your machine, publish on other host ports: `QL_PG_HOST_PORT=55432 make up`
(and use the same value for `make test`). Dev passwords in `infra/` are placeholders for local use only; real
secrets come from a secrets manager or CI secrets and never from the repo. Copy `.env.example` to `.env` for
host-side tooling; `.env` is gitignored.

Note: the MinIO image is `bitnamilegacy/minio` (pinned by digest) because official MinIO images are no longer
published on Docker Hub. It is unmaintained and used for local development and CI only; staging/prod use the
cloud provider's object storage. Container base images are pinned by digest; `make ci` also runs `pip-audit`,
`pnpm audit --prod` and a Trivy image scan (these need network access).
