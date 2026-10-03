# Changelog

One section per verified phase: what users can now do, notable decisions, known limitations.

## P01 — Platform foundation (2026-10-03, tag `p01-verified`)

**Now possible:**
- **Tenants and users:**
  - Seed a demo tenant with plants and users (`make seed`).
  - Sign in with email and password; reset a password by email code (Mailpit locally).
  - Admins manage users, plants and tenant settings through command endpoints. `GET /me` returns the signed-in user, role and plants.
- **Isolation and audit:**
  - Every change is authorised, audited (before/after, reason, actor, session, IP) and emits an outbox event in the same transaction.
  - Tenants are isolated by forced Postgres RLS, in requests and in background jobs.
- **Background work:** an outbox dispatcher, Dramatiq workers and a scheduler run in compose. Failed work dead-letters after 5 attempts with an alert.
- **Files:** signed upload and download URLs (at most 15 min), with ClamAV scanning and content-type checks.

**Decisions:**
- Roles are admin, quality and viewer, plus `can_approve`. Viewers cannot run commands.
- Idempotency-Key is a UUID, kept 24 h.
- Redis requires a password and limits the app to its own key patterns.
- The owner DB credential is given to the migration job only.
- `QL_ENV` is required.
- `QL_TRUSTED_PROXIES` sets which proxies' forwarded client IPs are trusted.
- Accepted as built at the gate:
  - A-99: a UUIDv7 generator replaces the `uuid6` library.
  - A-100: dead-letter after 5 executions in total.

**Reviews:** the code review (3 High) and the security review (1 High, then 1 Medium in the re-review) were all fixed, each with a regression test. Records are in `docs/build/phases/P01-code-review.md` and `P01-security-review.md`.

**Verification:** 879 tests passed and 19 were expected failures (events built in later phases). Coverage is 90.95% overall and 93% for `app/core`. Full report in `docs/build/phases/P01-verification.md`.

**Known limitations / open:**
- No screens yet; login and reset screens come in P02 (A-93).
- No generic file-download endpoint (A-92).
- Production proxy CIDRs and stricter production settings checks are set in P09 (A-106, A-107).
- The cookie `__Host-` prefix is undecided (A-101).
- The ADR-005 and ADR-006 text still needs amending for A-99 and A-100.

## P00 — Architecture & scaffold (2026-10-03, tag `p00-verified`)

**Now possible:** `make up` starts Postgres 16, Redis, MinIO, Mailpit, the API (`/healthz`, `/readyz`) and the
web app shell (QualLoop, en/hi, design tokens). `make lint`, `make test`, `make ci`, `make e2e` run locally.

**Decisions:** modular monolith (§22.1 modules, import-linter); forced Postgres RLS with deny-by-default for
supplier sessions; UUIDv7, money as BIGINT paise, UTC timestamps, plant-timezone periods; single command
pipeline writing activity_log + outbox in one transaction; Dramatiq + APScheduler; SQL as-of metrics engine;
AWS Mumbai + Terraform proposed. 20 ADRs in `docs/adr/`; architecture in `docs/architecture/`.

**Follow-up fixes (2026-10-03):**
- Added `.env.example`. The `.env*` read-deny rule was narrowed to real env files so the template can exist.
- Local and CI object storage moved from the unmaintained `bitnamilegacy/minio` to SeaweedFS (ADR-020).
- Added a commit-msg guard (`infra/scripts/check_commit_msg.sh`) that rejects trailers, sign-offs and multi-line messages.
- `ruff format` replaces black (CLAUDE.md, backend agent, ADR-002).

**Decisions recorded:**
- No paid services for now. Production targets are AWS ap-south-1, SES, the WhatsApp Cloud API, the Sentry free
  tier and Bedrock/Textract; no accounts are opened until needed.
- ClamAV is the virus scanner.
- `amount_paise` is approved.
- The technical tables and columns in DATA_MODEL.md are approved.
- Google login moves to R1.1.
- Billing stays in P09.

**Known limitations / open:**
- No business tables or endpoints yet (P01+).
- GitHub Actions has not run yet; CI is verified locally only.
- The CI host still needs confirmation (ADR-016).
- 80 SPEC-GAPs remain open in `docs/build/OPEN_QUESTIONS.md`.
